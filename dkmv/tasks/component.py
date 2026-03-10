from __future__ import annotations

import json
import logging
import os
import shlex
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from rich.console import Console

from dkmv.adapters.base import AgentAdapter
from dkmv.config import DKMVConfig, _fetch_oauth_credentials  # noqa: F401  (tests patch this)
from dkmv.core.models import BaseComponentConfig, BaseResult, SandboxConfig
from dkmv.core.runner import RunManager
from dkmv.core.sandbox import SandboxManager, SandboxSession
from dkmv.tasks.loader import TaskLoader
from dkmv.tasks.manifest import ComponentManifest, ManifestTaskRef
from dkmv.tasks.models import CLIOverrides, ComponentResult, TaskDefinition, TaskResult
from dkmv.tasks.pause import PauseQuestion, PauseRequest, PauseResponse
from dkmv.tasks.runner import TaskRunner

logger = logging.getLogger(__name__)

WORKSPACE_DIR = "/home/dkmv/workspace"
AGENT_EMAIL = "dkmv-agent@noreply.dkmv.dev"


def _agent_git_name(component_name: str) -> str:
    """Build a deterministic git author name for the component."""
    if len(component_name) <= 2:
        return f"DKMV/{component_name.upper()}"
    return f"DKMV/{component_name.title()}"


class ComponentRunner:
    def __init__(
        self,
        sandbox: SandboxManager,
        run_manager: RunManager,
        task_loader: TaskLoader,
        task_runner: TaskRunner,
        console: Console,
    ) -> None:
        self._sandbox = sandbox
        self._run_manager = run_manager
        self._task_loader = task_loader
        self._task_runner = task_runner
        self._console = console

    @staticmethod
    def _scan_yaml_files(component_dir: Path) -> list[Path]:
        tasks_subdir = component_dir / "tasks"
        scan_dir = tasks_subdir if tasks_subdir.is_dir() else component_dir
        return sorted(
            p for p in scan_dir.iterdir() if p.suffix in (".yaml", ".yml") and p.is_file()
        )

    def _build_sandbox_config(
        self,
        config: DKMVConfig,
        timeout_minutes: int,
        agents_needed: set[str] | None = None,
        docker_socket: bool = False,
    ) -> tuple[SandboxConfig, Path | None]:
        """Build sandbox config and return (config, temp_credentials_file).

        The caller must delete the temp file (if not None) after the
        container stops.
        """
        from dkmv.adapters import get_adapter

        if agents_needed is None:
            agents_needed = {"claude"}

        env_vars: dict[str, str] = {}
        docker_args: list[str] = ["--shm-size=2g"]
        temp_creds_file: Path | None = None

        # Collect credentials for all needed agents
        for agent_name in agents_needed:
            agent_adapter = get_adapter(agent_name)
            auth_env, extra_args, creds_file = agent_adapter.get_auth_config(config)
            env_vars.update(auth_env)
            docker_args.extend(extra_args)
            if creds_file is not None:
                temp_creds_file = creds_file

        # Mount host Docker socket if requested (DooD)
        if docker_socket or config.docker_socket:
            sock_path = "/var/run/docker.sock"
            if os.path.exists(sock_path):
                docker_args.extend(["-v", f"{sock_path}:{sock_path}"])
                # Match host socket GID so non-root user can access it
                try:
                    sock_gid = os.stat(sock_path).st_gid
                    docker_args.append(f"--group-add={sock_gid}")
                except OSError:
                    logger.warning("Could not stat Docker socket GID")
                logger.info("Docker socket mount enabled (--docker)")
            else:
                logger.warning(
                    "Docker socket not found at %s — --docker flag has no effect", sock_path
                )

        # GitHub token always included (agent-agnostic)
        if config.github_token:
            env_vars["GITHUB_TOKEN"] = config.github_token

        sandbox_config = SandboxConfig(
            image=config.image_name,
            env_vars=env_vars,
            docker_args=docker_args,
            memory_limit=config.memory_limit,
            timeout_minutes=timeout_minutes,
        )
        return sandbox_config, temp_creds_file

    async def _setup_workspace(
        self,
        session: SandboxSession,
        repo: str,
        branch: str | None,
        component_name: str,
        *,
        has_github_token: bool = True,
        adapter: AgentAdapter | None = None,
        agents_needed: set[str] | None = None,
    ) -> None:
        if has_github_token:
            auth_result = await self._sandbox.setup_git_auth(session)
            if auth_result.exit_code != 0:
                raise RuntimeError(f"Git auth setup failed: {auth_result.output[:500]}")
        else:
            logger.info("No GitHub token configured; skipping gh auth setup-git")

        clone_result = await self._sandbox.execute(
            session, f"git clone {shlex.quote(repo)} {WORKSPACE_DIR}", timeout=120
        )
        if clone_result.exit_code != 0:
            raise RuntimeError(f"git clone failed: {clone_result.output[:500]}")

        if branch:
            await self._sandbox.execute(
                session,
                f"cd {WORKSPACE_DIR} && git checkout {shlex.quote(branch)} 2>/dev/null"
                f" || git checkout -b {shlex.quote(branch)}",
            )

        git_name = _agent_git_name(component_name)
        await self._sandbox.execute(
            session,
            f"cd {WORKSPACE_DIR}"
            f" && git config user.name {shlex.quote(git_name)}"
            f" && git config user.email {shlex.quote(AGENT_EMAIL)}",
        )

        # Collect gitignore entries from all needed agents
        if agents_needed:
            from dkmv.adapters import get_adapter as _get_adapter

            seen: set[str] = set()
            gitignore_entries: list[str] = []
            for agent_name in agents_needed:
                for entry in _get_adapter(agent_name).gitignore_entries:
                    if entry not in seen:
                        seen.add(entry)
                        gitignore_entries.append(entry)
        elif adapter is not None:
            gitignore_entries = adapter.gitignore_entries
        else:
            gitignore_entries = [".claude/"]

        gitignore_cmds = [f"cd {WORKSPACE_DIR} && mkdir -p .agent"]
        for entry in gitignore_entries:
            gitignore_cmds.append(
                f"(grep -qxF {shlex.quote(entry)} .gitignore 2>/dev/null"
                f' || {{ [ -s .gitignore ] && [ -n "$(tail -c1 .gitignore)" ]'
                f" && echo >> .gitignore; echo {shlex.quote(entry)} >> .gitignore; }})"
            )
        await self._sandbox.execute(session, " && ".join(gitignore_cmds))

    def _build_variables(
        self,
        cli_vars: dict[str, Any],
        repo: str,
        branch: str,
        feature_name: str,
        component: str,
        run_id: str,
        cli_overrides: CLIOverrides,
        config: DKMVConfig,
        task_results: list[TaskResult],
    ) -> dict[str, Any]:
        variables: dict[str, Any] = {
            "repo": repo,
            "branch": branch,
            "feature_name": feature_name,
            "component": component,
            "model": (
                cli_overrides.model if cli_overrides.model is not None else config.default_model
            ),
            "run_id": run_id,
        }
        variables.update(cli_vars)

        tasks_dict: dict[str, dict[str, Any]] = {}
        for result in task_results:
            outputs_dict: dict[str, Any] = {}
            for path, content in result.outputs.items():
                key = Path(path).stem
                try:
                    outputs_dict[key] = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    outputs_dict[key] = content
            tasks_dict[result.task_name] = {
                "status": result.status,
                "cost": str(result.total_cost_usd),
                "turns": str(result.num_turns),
                "outputs": outputs_dict,
            }
        variables["tasks"] = tasks_dict

        return variables

    async def _inject_shared_inputs(
        self,
        manifest: ComponentManifest,
        session: SandboxSession,
        variables: dict[str, Any],
    ) -> dict[str, str]:
        env_vars: dict[str, str] = {}
        for inp in manifest.inputs:
            if inp.type == "file":
                src_path = Path(str(inp.src)) if inp.src else None
                if src_path is None or not src_path.exists():
                    if inp.optional:
                        logger.debug("Optional shared input '%s' not found, skipping", inp.name)
                        continue
                    raise FileNotFoundError(
                        f"Shared input '{inp.name}': source not found: {inp.src}"
                    )
                if src_path.is_dir():
                    for file_path in src_path.rglob("*"):
                        if file_path.is_file():
                            rel = file_path.relative_to(src_path)
                            dest = f"{inp.dest}/{rel}"
                            await self._sandbox.write_file(session, dest, file_path.read_text())
                else:
                    assert inp.dest is not None
                    await self._sandbox.write_file(session, inp.dest, src_path.read_text())
            elif inp.type == "text":
                assert inp.dest is not None
                await self._sandbox.write_file(session, inp.dest, inp.content or "")
            elif inp.type == "env":
                if inp.key and inp.value is not None:
                    env_vars[inp.key] = inp.value
        return env_vars

    async def _inject_context_files(
        self, session: SandboxSession, context_paths: list[Path]
    ) -> list[str]:
        """Copy ad-hoc context files into .agent/context/ in the container.

        Returns list of container-relative paths for agent instructions.
        """
        if not context_paths:
            return []
        await self._sandbox.execute(session, f"mkdir -p {WORKSPACE_DIR}/.agent/context")
        # Prevent the agent from committing potentially huge context files
        await self._sandbox.execute(
            session,
            f"cd {WORKSPACE_DIR}"
            " && (grep -qxF '.agent/context/' .gitignore 2>/dev/null"
            ' || { [ -s .gitignore ] && [ -n "$(tail -c1 .gitignore)" ]'
            " && echo >> .gitignore; echo '.agent/context/' >> .gitignore; })",
        )
        injected: list[str] = []
        for path in context_paths:
            if path.is_dir():
                for file_path in path.rglob("*"):
                    if not file_path.is_file():
                        continue
                    try:
                        content = file_path.read_text()
                    except (UnicodeDecodeError, ValueError):
                        logger.warning("Skipping non-text file: %s", file_path)
                        continue
                    rel = file_path.relative_to(path)
                    dest = f"{WORKSPACE_DIR}/.agent/context/{path.name}/{rel}"
                    await self._sandbox.write_file(session, dest, content)
                    injected.append(f".agent/context/{path.name}/{rel}")
            elif path.is_file():
                try:
                    content = path.read_text()
                except (UnicodeDecodeError, ValueError):
                    logger.warning("Skipping non-text file: %s", path)
                    continue
                dest = f"{WORKSPACE_DIR}/.agent/context/{path.name}"
                await self._sandbox.write_file(session, dest, content)
                injected.append(f".agent/context/{path.name}")
            else:
                logger.warning("Context path not found: %s", path)
        return injected

    async def _create_workspace_dirs(
        self, manifest: ComponentManifest, session: SandboxSession
    ) -> None:
        for dir_path in manifest.workspace_dirs:
            await self._sandbox.execute(session, f"mkdir -p {WORKSPACE_DIR}/{dir_path}")

    async def _write_state_files(
        self, manifest: ComponentManifest, session: SandboxSession
    ) -> None:
        for sf in manifest.state_files:
            await self._sandbox.write_file(session, sf.dest, sf.content)

    @staticmethod
    def _apply_manifest_defaults(
        task: TaskDefinition,
        manifest: ComponentManifest,
        task_ref: ManifestTaskRef | None,
    ) -> None:
        if task.agent is None:
            if task_ref and task_ref.agent is not None:
                task.agent = task_ref.agent
            elif manifest.agent is not None:
                task.agent = manifest.agent
        if task.model is None:
            if task_ref and task_ref.model is not None:
                task.model = task_ref.model
            elif manifest.model is not None:
                task.model = manifest.model
        if task.max_turns is None:
            if task_ref and task_ref.max_turns is not None:
                task.max_turns = task_ref.max_turns
            elif manifest.max_turns is not None:
                task.max_turns = manifest.max_turns
        if task.timeout_minutes is None:
            if task_ref and task_ref.timeout_minutes is not None:
                task.timeout_minutes = task_ref.timeout_minutes
            elif manifest.timeout_minutes is not None:
                task.timeout_minutes = manifest.timeout_minutes
        if task.max_budget_usd is None:
            if task_ref and task_ref.max_budget_usd is not None:
                task.max_budget_usd = task_ref.max_budget_usd
            elif manifest.max_budget_usd is not None:
                task.max_budget_usd = manifest.max_budget_usd

    @staticmethod
    def _build_pause_request(task_name: str, outputs: dict[str, str]) -> PauseRequest:
        """Extract questions from task outputs to build a pause request."""
        questions: list[PauseQuestion] = []
        context: dict[str, str] = {}

        for path, content in outputs.items():
            context[path] = content[:2000]
            try:
                data = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                continue
            raw_questions = data.get("questions") if isinstance(data, dict) else None
            if not isinstance(raw_questions, list):
                continue
            for raw_q in raw_questions:
                if not isinstance(raw_q, dict):
                    continue
                q_id = raw_q.get("id")
                q_text = raw_q.get("question")
                if not q_id or not q_text:
                    continue
                options = raw_q.get("options", [])
                if not isinstance(options, list):
                    options = []
                clean_options = [
                    o for o in options if isinstance(o, dict) and "value" in o and "label" in o
                ]
                questions.append(
                    PauseQuestion(
                        id=str(q_id),
                        question=str(q_text),
                        options=clean_options,
                        default=raw_q.get("default"),
                    )
                )

        return PauseRequest(task_name=task_name, questions=questions, context=context)

    @staticmethod
    def _resolve_start_task(
        start_task: str,
        expanded_refs: list[tuple[Path, ManifestTaskRef | None, dict[str, Any] | None, int | None]],
    ) -> int:
        """Resolve --start-task value to a 0-based index into expanded_refs."""
        if start_task.isdigit():
            idx = int(start_task)
            if idx < 1 or idx > len(expanded_refs):
                available = ", ".join(str(i + 1) for i in range(len(expanded_refs)))
                raise ValueError(
                    f"Task index {idx} out of range (1-{len(expanded_refs)}). "
                    f"Available: {available}"
                )
            return idx - 1

        for i, (yaml_file, *_) in enumerate(expanded_refs):
            stem = yaml_file.stem
            # Match exact stem ("04-assembly") or suffix after dash ("assembly")
            if stem == start_task or stem.split("-", 1)[-1] == start_task:
                return i

        names = [ref[0].stem for ref in expanded_refs]
        raise ValueError(f"Task '{start_task}' not found. Available: {', '.join(names)}")

    async def _reconstruct_task_from_repo(
        self, task: TaskDefinition, session: SandboxSession
    ) -> TaskResult:
        """Read a skipped task's output files from the cloned repo."""
        outputs: dict[str, str] = {}
        for output in task.outputs:
            if await self._sandbox.file_exists(session, output.path):
                content = await self._sandbox.read_file(session, output.path)
                outputs[output.path] = content
            elif output.required:
                raise FileNotFoundError(
                    f"Cannot skip task '{task.name}': required output "
                    f"'{Path(output.path).name}' not found in repo. "
                    f"Was this task completed and pushed?"
                )
        return TaskResult(task_name=task.name, status="pre-existing", outputs=outputs)

    def _save_prompts_log(
        self,
        run_id: str,
        component_name: str,
        task_results: list[TaskResult],
    ) -> None:
        """Assemble a unified prompts log from per-task instructions and prompt files."""
        run_dir = self._run_manager._run_dir(run_id)
        sections: list[str] = [f"# Component: {component_name} — Prompts & Instructions Log\n"]

        for i, result in enumerate(task_results, 1):
            sections.append(f"## Task {i}: {result.task_name}\n")

            claude_md_file = run_dir / f"claude_md_{result.task_name}.md"
            if claude_md_file.exists():
                sections.append("### Instructions\n")
                sections.append(f"```markdown\n{claude_md_file.read_text()}```\n")

            prompt_file = run_dir / f"prompt_{result.task_name}.md"
            if prompt_file.exists():
                prompt_content = prompt_file.read_text()
                if prompt_content:
                    sections.append("### Prompt\n")
                    sections.append(f"```markdown\n{prompt_content}\n```\n")

            sections.append("---\n")

        self._run_manager.save_artifact(run_id, "prompts_log.md", "\n".join(sections))

    async def run(
        self,
        component_dir: Path,
        repo: str,
        branch: str | None,
        feature_name: str,
        variables: dict[str, Any],
        config: DKMVConfig,
        cli_overrides: CLIOverrides,
        keep_alive: bool = False,
        verbose: bool = False,
        on_pause: Callable[[PauseRequest], Awaitable[PauseResponse]] | None = None,
        context_paths: list[Path] | None = None,
        start_task: str | None = None,
        docker_socket: bool = False,
    ) -> ComponentResult:
        start_time = time.monotonic()
        session: SandboxSession | None = None
        component_status: str = "completed"
        error_message = ""
        task_results: list[TaskResult] = []
        run_id = ""
        temp_creds_file: Path | None = None

        try:
            yaml_files = self._scan_yaml_files(component_dir)

            # IU-5: BaseComponentConfig shim for RunManager compatibility
            base_config = BaseComponentConfig(
                repo=repo,
                branch=branch,
                feature_name=feature_name,
                model=(
                    cli_overrides.model if cli_overrides.model is not None else config.default_model
                ),
                max_turns=(
                    cli_overrides.max_turns
                    if cli_overrides.max_turns is not None
                    else config.default_max_turns
                ),
                timeout_minutes=(
                    cli_overrides.timeout_minutes
                    if cli_overrides.timeout_minutes is not None
                    else config.timeout_minutes
                ),
                max_budget_usd=(
                    cli_overrides.max_budget_usd
                    if cli_overrides.max_budget_usd is not None
                    else config.max_budget_usd
                ),
                keep_alive=keep_alive,
                verbose=verbose,
            )
            run_id = self._run_manager.start_run(component_dir.name, base_config)

            timeout = (
                cli_overrides.timeout_minutes
                if cli_overrides.timeout_minutes is not None
                else config.timeout_minutes
            )
            from dkmv.adapters import get_adapter

            _agent_name = cli_overrides.agent or config.default_agent
            adapter: AgentAdapter = get_adapter(_agent_name)

            # Pre-scan manifest to determine agents_needed before sandbox start
            agents_needed: set[str] = {_agent_name}
            _manifest_path_prescan = component_dir / "component.yaml"
            if _manifest_path_prescan.exists():
                try:
                    import yaml as _yaml

                    _raw = _yaml.safe_load(_manifest_path_prescan.read_text())
                    if isinstance(_raw, dict):
                        if _raw.get("agent"):
                            agents_needed.add(str(_raw["agent"]))
                        for _ref in _raw.get("tasks", []):
                            if isinstance(_ref, dict) and _ref.get("agent"):
                                agents_needed.add(str(_ref["agent"]))
                except Exception:
                    pass  # Pre-scan failures are non-fatal

            sandbox_config, temp_creds_file = self._build_sandbox_config(
                config, timeout, agents_needed, docker_socket=docker_socket
            )
            session = await self._sandbox.start(sandbox_config, component_dir.name)

            container_name = self._sandbox.get_container_name(session)
            if container_name:
                self._run_manager.save_container_name(run_id, container_name)

            await self._setup_workspace(
                session,
                repo,
                branch,
                component_dir.name,
                has_github_token=bool(config.github_token),
                adapter=adapter,
                agents_needed=agents_needed,
            )

            # Inject ad-hoc context files
            context_files = await self._inject_context_files(session, context_paths or [])

            # Load manifest if present
            manifest_path = component_dir / "component.yaml"
            manifest: ComponentManifest | None = None
            shared_env_vars: dict[str, str] | None = None
            component_agent_md: str | None = None
            expanded_refs: list[
                tuple[Path, ManifestTaskRef | None, dict[str, Any] | None, int | None]
            ] = []

            if manifest_path.exists():
                initial_vars = self._build_variables(
                    variables,
                    repo,
                    branch or "",
                    feature_name,
                    component_dir.name,
                    run_id,
                    cli_overrides,
                    config,
                    task_results,
                )
                manifest = self._task_loader.load_manifest(manifest_path, initial_vars)
                await self._create_workspace_dirs(manifest, session)
                await self._write_state_files(manifest, session)
                shared_env_vars = await self._inject_shared_inputs(manifest, session, initial_vars)

                # Resolve agent_md_file if set
                if manifest.agent_md_file:
                    agent_md_path = Path(manifest.agent_md_file)
                    if agent_md_path.exists():
                        manifest.agent_md = agent_md_path.read_text()
                    else:
                        logger.warning("agent_md_file not found: %s", agent_md_path)

                component_agent_md = manifest.agent_md

                # Expand for_each task refs into individual instances
                expanded_refs = []
                for ref in manifest.tasks:
                    if ref.for_each:
                        items = initial_vars.get(ref.for_each, [])
                        if not isinstance(items, list):
                            raise ValueError(
                                f"for_each '{ref.for_each}' must reference a list variable, "
                                f"got {type(items).__name__}"
                            )
                        for idx, item in enumerate(items):
                            expanded_refs.append((component_dir / ref.file, ref, item, idx))
                    else:
                        expanded_refs.append((component_dir / ref.file, ref, None, None))

            else:
                # No manifest: wrap plain yaml_files into expanded_refs format
                expanded_refs = [(yf, None, None, None) for yf in yaml_files]

            # Resolve --start-task to a 0-based index
            start_index = 0
            if start_task is not None:
                start_index = self._resolve_start_task(start_task, expanded_refs)

            # Inject deterministic git identity env vars (highest git precedence)
            git_name = _agent_git_name(component_dir.name)
            git_identity_vars: dict[str, str] = {
                "GIT_AUTHOR_NAME": git_name,
                "GIT_COMMITTER_NAME": git_name,
                "GIT_AUTHOR_EMAIL": AGENT_EMAIL,
                "GIT_COMMITTER_EMAIL": AGENT_EMAIL,
            }
            if shared_env_vars is None:
                shared_env_vars = dict(git_identity_vars)
            else:
                shared_env_vars.update(git_identity_vars)

            # Execute tasks sequentially with per-task loading
            for i, (yaml_file, task_ref, for_each_item, for_each_index) in enumerate(expanded_refs):
                cumulative_vars = self._build_variables(
                    variables,
                    repo,
                    branch or "",
                    feature_name,
                    component_dir.name,
                    run_id,
                    cli_overrides,
                    config,
                    task_results,
                )

                if for_each_item is not None:
                    cumulative_vars["item"] = for_each_item
                    cumulative_vars["item_index"] = for_each_index

                task = self._task_loader.load(yaml_file, cumulative_vars)

                # Apply manifest defaults if present
                if manifest is not None:
                    self._apply_manifest_defaults(task, manifest, task_ref)

                # Reconstruct skipped tasks from repo instead of running them
                if i < start_index:
                    result = await self._reconstruct_task_from_repo(task, session)
                    task_results.append(result)
                    logger.info(
                        "Skipped task '%s' (%d/%d) — outputs recovered from repo",
                        task.name,
                        i + 1,
                        len(expanded_refs),
                    )
                    continue

                self._run_manager.append_stream(
                    run_id,
                    {
                        "type": "task_start",
                        "task_name": task.name,
                        "task_description": task.description,
                        "task_index": i,
                        "total_tasks": len(expanded_refs),
                    },
                )

                result = await self._task_runner.run(
                    task,
                    session,
                    run_id,
                    config,
                    cli_overrides,
                    component_agent_md=component_agent_md,
                    shared_env_vars=shared_env_vars,
                    context_files=context_files,
                )
                task_results.append(result)

                # Pause-after: invoke callback if task succeeded and pause is configured
                if result.status == "completed" and manifest and on_pause:
                    if task_ref and task_ref.pause_after:
                        pause_request = self._build_pause_request(task.name, result.outputs)
                        pause_response = await on_pause(pause_request)
                        await self._sandbox.write_file(
                            session,
                            f"{WORKSPACE_DIR}/.agent/user_decisions.json",
                            json.dumps(pause_response.answers, indent=2),
                        )
                        if pause_response.skip_remaining:
                            for remaining_file, *_ in expanded_refs[i + 1 :]:
                                task_results.append(
                                    TaskResult(
                                        task_name=remaining_file.stem,
                                        status="skipped",
                                    )
                                )
                            break

                if result.status in ("failed", "timed_out"):
                    component_status = result.status
                    error_message = result.error_message
                    for remaining_file, *_ in expanded_refs[i + 1 :]:
                        task_results.append(
                            TaskResult(
                                task_name=remaining_file.stem,
                                status="skipped",
                            )
                        )
                    break

        except TimeoutError:
            component_status = "timed_out"
            error_message = "Component timed out"
        except Exception as e:
            component_status = "failed"
            error_message = str(e)
        finally:
            if session is not None:
                await self._sandbox.stop(session, keep_alive=keep_alive)
            if temp_creds_file is not None:
                temp_creds_file.unlink(missing_ok=True)

        total_cost = sum(r.total_cost_usd for r in task_results)
        duration = time.monotonic() - start_time

        component_result = ComponentResult(
            run_id=run_id,
            component=component_dir.name,
            status=component_status,  # type: ignore[arg-type]
            repo=repo,
            branch=branch or "",
            feature_name=feature_name,
            total_cost_usd=total_cost,
            duration_seconds=duration,
            task_results=task_results,
            error_message=error_message,
        )

        if run_id:
            base_result = BaseResult(
                run_id=run_id,
                component=component_dir.name,
                status=component_status,  # type: ignore[arg-type]
                repo=repo,
                branch=branch or "",
                feature_name=feature_name,
                total_cost_usd=total_cost,
                duration_seconds=duration,
                num_turns=sum(r.num_turns for r in task_results),
            )
            self._run_manager.save_result(run_id, base_result)

            self._run_manager.save_artifact(
                run_id, "tasks_result.json", component_result.model_dump_json(indent=2)
            )

            self._save_prompts_log(run_id, component_dir.name, task_results)

        return component_result
