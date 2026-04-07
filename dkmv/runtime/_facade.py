"""EmbeddedRuntime — the main entry point for embedding DKMV programmatically."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

from rich.console import Console

from dkmv.config import DKMVConfig
from dkmv.core.models import RunDetail, RunStatus, RunSummary
from dkmv.core.runner import RunManager
from dkmv.core.sandbox import SandboxManager
from dkmv.core.stream import StreamParser
from dkmv.runtime._artifacts import ArtifactRef
from dkmv.runtime._artifacts import get_artifact as _get_artifact
from dkmv.runtime._artifacts import list_artifacts as _list_artifacts
from dkmv.runtime._capability import (
    CapabilityReport,
    PreflightResult,
    get_capabilities,
    preflight_check,
)
from dkmv.runtime._handle import RunHandle
from dkmv.runtime._introspection import (
    ComponentInfo,
    ExecutionPlan,
    ValidationResult,
    inspect_component,
    list_components,
    preview_execution_plan as _preview_execution_plan,
    validate_component,
)
from dkmv.runtime._observer import EventBus
from dkmv.runtime._telemetry import RunStats, get_run_stats
from dkmv.runtime._types import (
    ContainerStatus,
    ExecutionSource,
    ExecutionSourceType,
    RetentionPolicy,
    RuntimeConfig,
    SourceProvenance,
)
from dkmv.tasks.component import ComponentRunner
from dkmv.tasks.discovery import resolve_component
from dkmv.tasks.loader import TaskLoader
from dkmv.tasks.models import CLIOverrides, ComponentResult
from dkmv.tasks.pause import PauseRequest, PauseResponse
from dkmv.tasks.runner import TaskRunner

logger = logging.getLogger(__name__)


class EmbeddedRuntime:
    """High-level facade for embedding DKMV in host applications.

    Constructs all internal collaborators so hosts don't have to.
    """

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        output_dir: Path | None = None,
    ) -> None:
        self._runtime_config = config or RuntimeConfig()
        self._dkmv_config: DKMVConfig = self._runtime_config.to_dkmv_config()

        if output_dir is not None:
            self._dkmv_config.output_dir = output_dir

        self._output_dir = self._dkmv_config.output_dir
        self._console = Console(quiet=True)
        self._run_manager = RunManager(self._output_dir)
        self._sandbox_manager = SandboxManager()
        self._task_loader = TaskLoader()

        self._stream_parser = StreamParser(
            console=self._console,
            verbose=False,
        )
        self._task_runner = TaskRunner(
            sandbox=self._sandbox_manager,
            run_manager=self._run_manager,
            stream_parser=self._stream_parser,
            console=self._console,
        )
        self._component_runner = ComponentRunner(
            sandbox=self._sandbox_manager,
            run_manager=self._run_manager,
            task_loader=self._task_loader,
            task_runner=self._task_runner,
            console=self._console,
        )

        self._handles: dict[str, RunHandle] = {}
        self._temp_dirs: list[Path] = []

    # ── Introspection convenience ────────────────────────────────────

    def inspect_component(
        self,
        name_or_path: str,
        project_root: Path | None = None,
        variables: dict[str, str] | None = None,
    ) -> ComponentInfo:
        return inspect_component(name_or_path, project_root, variables)

    def validate_component(
        self,
        name_or_path: str,
        project_root: Path | None = None,
        variables: dict[str, str] | None = None,
    ) -> ValidationResult:
        return validate_component(name_or_path, project_root, variables)

    def list_components(
        self,
        project_root: Path | None = None,
        variables: dict[str, str] | None = None,
    ) -> list[ComponentInfo]:
        return list_components(project_root, variables)

    def preview_execution_plan(
        self,
        name_or_path: str,
        variables: dict[str, str] | None = None,
        project_root: Path | None = None,
        start_task: str | None = None,
    ) -> ExecutionPlan:
        return _preview_execution_plan(name_or_path, variables, project_root, start_task)

    def get_capabilities(self) -> CapabilityReport:
        return get_capabilities(self._runtime_config)

    def preflight_check(
        self,
        component: str,
        source: ExecutionSource,
    ) -> PreflightResult:
        return preflight_check(self._runtime_config, component, source)

    # ── Execution ────────────────────────────────────────────────────

    async def start(
        self,
        component: str,
        source: ExecutionSource,
        feature_name: str = "",
        variables: dict[str, Any] | None = None,
        agent: str | None = None,
        model: str | None = None,
        max_turns: int | None = None,
        timeout_minutes: int | None = None,
        max_budget_usd: float | None = None,
        memory: str | None = None,
        on_pause: Callable[[PauseRequest], Awaitable[PauseResponse]] | None = None,
        context_paths: list[Path] | None = None,
        start_task: str | None = None,
        keep_alive: bool = False,
        docker_socket: bool = False,
    ) -> RunHandle:
        """Start a component run and return a handle for controlling it.

        Args:
            component: Component name or path.
            source: Where source code comes from (remote URL or local snapshot).
            feature_name: Optional feature/branch name.
            variables: Jinja2 template variables for task YAML.
            agent: Agent backend override (e.g. "claude", "codex").
            model: Model override.
            max_turns: Max agent turns override.
            timeout_minutes: Timeout override.
            max_budget_usd: Budget cap override.
            memory: Memory limit override.
            on_pause: Async callback for pause/review flows.
            context_paths: Local paths to copy into the sandbox.
            start_task: Task name to resume from.
            keep_alive: Keep sandbox alive after completion.
            docker_socket: Mount Docker socket (DooD).

        Returns:
            A RunHandle for observing and controlling the run.
        """
        component_dir = resolve_component(component)

        repo, branch, provenance = self._resolve_source(source)

        cli_overrides = CLIOverrides(
            model=model,
            max_turns=max_turns,
            timeout_minutes=timeout_minutes,
            max_budget_usd=max_budget_usd,
            agent=agent,
            memory=memory,
        )

        event_bus = EventBus(run_id="")
        handle = RunHandle(run_id="", event_bus=event_bus)

        def _on_run_id(run_id: str) -> None:
            handle._set_run_id(run_id)
            self._handles[run_id] = handle
            if provenance is not None:
                self._run_manager.save_artifact(
                    run_id,
                    "source_provenance.json",
                    provenance.model_dump_json(indent=2),
                )

        async def _execute() -> ComponentResult:
            try:
                result = await self._component_runner.run(
                    component_dir=component_dir,
                    repo=repo,
                    branch=branch,
                    feature_name=feature_name,
                    variables=variables or {},
                    config=self._dkmv_config,
                    cli_overrides=cli_overrides,
                    keep_alive=keep_alive,
                    verbose=False,
                    on_pause=on_pause,
                    context_paths=context_paths,
                    start_task=start_task,
                    docker_socket=docker_socket,
                    on_event=event_bus.emit,
                    on_run_id=_on_run_id,
                    cancel_event=handle.cancel_event,
                )
                handle._set_result(result)
                return result
            except asyncio.CancelledError:
                # Force cancellation: sandbox cleanup happens in
                # ComponentRunner.run()'s finally block. Mark handle.
                handle._set_result(None)
                raise
            except Exception:
                handle._set_result(None)
                raise

        task = asyncio.create_task(_execute())
        handle._set_task(task)

        return handle

    def _resolve_source(
        self, source: ExecutionSource
    ) -> tuple[str, str | None, SourceProvenance | None]:
        """Convert an ExecutionSource to (repo_url, branch, provenance)."""
        if source.type == ExecutionSourceType.REMOTE:
            provenance = SourceProvenance(
                source_type="remote",
                branch=source.branch or "",
            )
            return source.repo or "", source.branch, provenance

        # LOCAL_SNAPSHOT: create a bare git repo from local workspace
        repo_url, provenance = self._prepare_local_snapshot(source)
        return repo_url, source.branch, provenance

    def _prepare_local_snapshot(self, source: ExecutionSource) -> tuple[str, SourceProvenance]:
        """Create a file:// repo URL from a local workspace.

        Returns:
            (repo_url, provenance) tuple.

        Raises:
            ValueError: If the local path is not a git repository or snapshot fails.
        """
        local_path = source.local_path or Path(".")
        local_path = local_path.resolve()

        if not local_path.exists():
            raise ValueError(f"Local path does not exist: {local_path}")
        if not (local_path / ".git").exists():
            raise ValueError(
                f"Local path is not a git repository: {local_path}. "
                "LOCAL_SNAPSHOT requires a git repository."
            )

        # Capture HEAD SHA
        head_result = subprocess.run(
            ["git", "-C", str(local_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        )
        head_sha = head_result.stdout.strip() if head_result.returncode == 0 else ""

        # Capture branch name
        branch_result = subprocess.run(
            ["git", "-C", str(local_path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
        )
        branch_name = branch_result.stdout.strip() if branch_result.returncode == 0 else ""

        # Capture dirty state
        status_result = subprocess.run(
            ["git", "-C", str(local_path), "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        dirty = bool(status_result.stdout.strip()) if status_result.returncode == 0 else False

        temp_dir = Path(tempfile.mkdtemp(prefix="dkmv-snapshot-"))
        self._temp_dirs.append(temp_dir)
        bare_repo = temp_dir / "repo.git"

        try:
            # Init bare repo
            subprocess.run(
                ["git", "init", "--bare", str(bare_repo)],
                capture_output=True,
                check=True,
            )

            if source.include_uncommitted:
                # For untracked files: git add -A, stash create, git reset
                # in try/finally to protect user's index
                added_untracked = False
                if source.include_untracked:
                    try:
                        subprocess.run(
                            ["git", "-C", str(local_path), "add", "-A"],
                            capture_output=True,
                            check=False,
                        )
                        added_untracked = True
                    except OSError:
                        pass

                try:
                    stash_result = subprocess.run(
                        ["git", "-C", str(local_path), "stash", "create"],
                        capture_output=True,
                        text=True,
                    )
                    ref = stash_result.stdout.strip()
                    if not ref:
                        ref = "HEAD"
                finally:
                    if added_untracked:
                        subprocess.run(
                            ["git", "-C", str(local_path), "reset"],
                            capture_output=True,
                            check=False,
                        )
            else:
                ref = "HEAD"

            # Verify the ref exists (catches empty repos)
            verify = subprocess.run(
                ["git", "-C", str(local_path), "rev-parse", "--verify", ref],
                capture_output=True,
                text=True,
            )
            if verify.returncode != 0:
                raise ValueError(
                    f"Cannot resolve git ref '{ref}' in {local_path}. "
                    "The repository may have no commits."
                )

            # Push the ref to the bare repo
            push_result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(local_path),
                    "push",
                    str(bare_repo),
                    f"{ref}:refs/heads/main",
                ],
                capture_output=True,
                text=True,
            )
            if push_result.returncode != 0:
                raise ValueError(f"Failed to create local snapshot: {push_result.stderr.strip()}")
        except subprocess.CalledProcessError as e:
            raise ValueError(f"Git operation failed during local snapshot: {e.stderr or e}") from e

        provenance = SourceProvenance(
            source_type="local_snapshot",
            local_path=str(local_path),
            head_sha=head_sha,
            branch=branch_name,
            dirty=dirty,
            include_uncommitted=source.include_uncommitted,
            include_untracked=source.include_untracked,
        )

        return f"file://{bare_repo}", provenance

    def get_source_provenance(self, run_id: str) -> SourceProvenance | None:
        """Retrieve source provenance for a run, if recorded."""
        import json

        path = self._output_dir / "runs" / run_id / "source_provenance.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return SourceProvenance(**data)
        except (json.JSONDecodeError, OSError, TypeError):
            return None

    def get_handle(self, run_id: str) -> RunHandle | None:
        """Get a RunHandle by run_id."""
        return self._handles.get(run_id)

    # ── History ──────────────────────────────────────────────────────

    def list_runs(
        self,
        component: str | None = None,
        feature: str | None = None,
        status: RunStatus | None = None,
        limit: int = 20,
    ) -> list[RunSummary]:
        return self._run_manager.list_runs(
            component=component,
            feature=feature,
            status=status,
            limit=limit,
        )

    def get_run(self, run_id: str) -> RunDetail:
        """Get detailed information about a specific run."""
        return self._run_manager.get_run(run_id)

    # ── Artifacts ────────────────────────────────────────────────────

    def list_artifacts(self, run_id: str) -> list[ArtifactRef]:
        return _list_artifacts(run_id, self._output_dir)

    def get_artifact(self, run_id: str, filename: str) -> str:
        return _get_artifact(run_id, filename, self._output_dir)

    # ── Container inspection ────────────────────────────────────────

    def get_container_status(self, run_id: str) -> ContainerStatus:
        """Check the status of a retained container for a run."""
        container_name = self._run_manager.get_container_name(run_id)
        if not container_name:
            return ContainerStatus(
                run_id=run_id,
                state="removed",
                error="No container.txt found for run",
            )

        try:
            proc = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Status}}", container_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode != 0:
                return ContainerStatus(
                    run_id=run_id,
                    container_name=container_name,
                    state="removed",
                )
            state = proc.stdout.strip()
            return ContainerStatus(
                run_id=run_id,
                container_name=container_name,
                alive=state == "running",
                state=state,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            return ContainerStatus(
                run_id=run_id,
                container_name=container_name,
                state="unknown",
                error=str(e),
            )

    def execute_in_container(self, run_id: str, command: str) -> str:
        """Execute a command in a retained container.

        Raises:
            RuntimeError: If container is not running.
        """
        status = self.get_container_status(run_id)
        if not status.alive:
            raise RuntimeError(f"Container for run {run_id} is not running (state={status.state})")

        proc = subprocess.run(
            ["docker", "exec", status.container_name, "bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Command failed (exit {proc.returncode}): {proc.stderr.strip()}")
        return proc.stdout

    def export_workspace(self, run_id: str, output_path: Path) -> Path:
        """Export workspace files from a retained container.

        Raises:
            RuntimeError: If the container does not exist or is removed.
        """
        status = self.get_container_status(run_id)
        if status.state == "removed":
            raise RuntimeError(f"No container available for run {run_id}")

        output_path.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [
                "docker",
                "cp",
                f"{status.container_name}:/home/dkmv/workspace/.",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"docker cp failed: {proc.stderr.strip()}")
        return output_path

    # ── Telemetry ────────────────────────────────────────────────────

    @property
    def active_runs(self) -> list[RunHandle]:
        """Return all currently active (running/stopping) handles."""
        return [h for h in self._handles.values() if h.status in ("running", "stopping", "pending")]

    def get_stats(self, component: str | None = None) -> RunStats:
        return get_run_stats(self._output_dir, component)

    # ── Retention ────────────────────────────────────────────────────

    def cleanup_runs(
        self,
        policy: RetentionPolicy,
        *,
        keep_n: int = 10,
        keep_days: int = 30,
    ) -> list[str]:
        """Clean up old run directories according to policy.

        Returns list of deleted run_ids.
        """
        import json
        import time

        runs_dir = self._output_dir / "runs"
        if not runs_dir.exists():
            return []

        deleted: list[str] = []
        now = time.time()
        cutoff = now - (keep_days * 86400)

        if policy == RetentionPolicy.RETAIN_MANUAL:
            return []

        run_dirs = sorted(runs_dir.iterdir())

        if policy == RetentionPolicy.DESTROY:
            for run_dir in run_dirs:
                if not run_dir.is_dir():
                    continue
                result_path = run_dir / "result.json"
                if not result_path.exists():
                    continue  # still running, skip
                try:
                    data = json.loads(result_path.read_text())
                    if data.get("status") in ("completed", "failed", "timed_out", "cancelled"):
                        shutil.rmtree(run_dir)
                        deleted.append(run_dir.name)
                except (json.JSONDecodeError, OSError):
                    continue
        elif policy == RetentionPolicy.RETAIN_TTL:
            for run_dir in run_dirs:
                if not run_dir.is_dir():
                    continue
                result_path = run_dir / "result.json"
                if not result_path.exists():
                    continue
                if result_path.stat().st_mtime < cutoff:
                    try:
                        shutil.rmtree(run_dir)
                        deleted.append(run_dir.name)
                    except OSError:
                        continue

        return deleted

    # ── Stale run reconciliation ────────────────────────────────────

    def reconcile_stale_runs(self) -> list[str]:
        """Scan for runs with config.json but no result.json, check container
        status, and write result.json with status='cancelled' for dead containers.

        Returns list of reconciled run_ids.
        """
        import json

        from dkmv.core.models import BaseResult

        runs_dir = self._output_dir / "runs"
        if not runs_dir.exists():
            return []

        reconciled: list[str] = []
        for run_dir in runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            config_file = run_dir / "config.json"
            result_file = run_dir / "result.json"
            if not config_file.exists() or result_file.exists():
                continue

            # This run has no result — check if its container is still alive
            container_file = run_dir / "container.txt"
            if not container_file.exists():
                # No container info — assume dead
                alive = False
            else:
                container_name = container_file.read_text().strip()
                if not container_name:
                    alive = False
                else:
                    try:
                        proc = subprocess.run(
                            [
                                "docker",
                                "inspect",
                                "--format",
                                "{{.State.Status}}",
                                container_name,
                            ],
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )
                        alive = proc.returncode == 0 and proc.stdout.strip() == "running"
                    except (subprocess.TimeoutExpired, OSError):
                        alive = False

            if alive:
                continue

            # Write a cancelled result for the dead run
            try:
                config_data = json.loads(config_file.read_text())
            except (json.JSONDecodeError, OSError):
                config_data = {}

            stale_result = BaseResult(
                run_id=run_dir.name,
                component=config_data.get("_component", "unknown"),
                status="cancelled",
                error_message="Reconciled: host died or container exited without result",
            )
            self._run_manager.save_result(run_dir.name, stale_result)
            reconciled.append(run_dir.name)

        return reconciled

    # ── Observer / Replay ────────────────────────────────────────────

    def replay_events(
        self,
        run_id: str,
        offset: int = 0,
    ) -> list[Any]:
        from dkmv.runtime._observer import replay_events as _replay

        return _replay(run_id, self._output_dir, offset)

    # ── Cleanup ──────────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Clean up temporary directories created for local snapshots."""
        for temp_dir in self._temp_dirs:
            shutil.rmtree(temp_dir, ignore_errors=True)
        self._temp_dirs.clear()

    async def __aenter__(self) -> EmbeddedRuntime:
        return self

    async def __aexit__(self, *args: Any) -> None:
        self.cleanup()
