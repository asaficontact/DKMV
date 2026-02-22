from __future__ import annotations

import logging
import shlex
import time
from pathlib import Path
from typing import Any

from rich.console import Console

from dkmv.config import DKMVConfig
from dkmv.core.models import BaseComponentConfig, BaseResult, SandboxConfig
from dkmv.core.runner import RunManager
from dkmv.core.sandbox import SandboxManager, SandboxSession
from dkmv.tasks.loader import TaskLoader
from dkmv.tasks.models import CLIOverrides, ComponentResult, TaskResult
from dkmv.tasks.runner import TaskRunner

logger = logging.getLogger(__name__)

WORKSPACE_DIR = "/home/dkmv/workspace"


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

    def _build_sandbox_config(self, config: DKMVConfig, timeout_minutes: int) -> SandboxConfig:
        env_vars = {"ANTHROPIC_API_KEY": config.anthropic_api_key}
        if config.github_token:
            env_vars["GITHUB_TOKEN"] = config.github_token
        return SandboxConfig(
            image=config.image_name,
            env_vars=env_vars,
            memory_limit=config.memory_limit,
            timeout_minutes=timeout_minutes,
        )

    async def _setup_workspace(
        self, session: SandboxSession, repo: str, branch: str | None
    ) -> None:
        auth_result = await self._sandbox.setup_git_auth(session)
        if auth_result.exit_code != 0:
            raise RuntimeError(f"Git auth setup failed: {auth_result.output[:500]}")

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

        await self._sandbox.execute(
            session,
            f"cd {WORKSPACE_DIR} && mkdir -p .dkmv"
            " && (grep -qxF '.dkmv/' .gitignore 2>/dev/null || echo '.dkmv/' >> .gitignore)",
        )

    def _build_variables(
        self,
        cli_vars: dict[str, str],
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

        tasks_dict: dict[str, dict[str, str]] = {}
        for result in task_results:
            tasks_dict[result.task_name] = {
                "status": result.status,
                "cost": str(result.total_cost_usd),
                "turns": str(result.num_turns),
            }
        variables["tasks"] = tasks_dict

        return variables

    async def run(
        self,
        component_dir: Path,
        repo: str,
        branch: str | None,
        feature_name: str,
        variables: dict[str, str],
        config: DKMVConfig,
        cli_overrides: CLIOverrides,
        keep_alive: bool = False,
        verbose: bool = False,
    ) -> ComponentResult:
        start_time = time.monotonic()
        session: SandboxSession | None = None
        component_status: str = "completed"
        error_message = ""
        task_results: list[TaskResult] = []
        run_id = ""

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
            sandbox_config = self._build_sandbox_config(config, timeout)
            session = await self._sandbox.start(sandbox_config, component_dir.name)

            container_name = self._sandbox.get_container_name(session)
            if container_name:
                self._run_manager.save_container_name(run_id, container_name)

            await self._setup_workspace(session, repo, branch)

            # Execute tasks sequentially with per-task loading
            for i, yaml_file in enumerate(yaml_files):
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

                task = self._task_loader.load(yaml_file, cumulative_vars)

                self._run_manager.append_stream(
                    run_id,
                    {
                        "type": "task_start",
                        "task_name": task.name,
                        "task_description": task.description,
                        "task_index": i,
                        "total_tasks": len(yaml_files),
                    },
                )

                result = await self._task_runner.run(task, session, run_id, config, cli_overrides)
                task_results.append(result)

                if result.status in ("failed", "timed_out"):
                    component_status = result.status
                    for remaining_file in yaml_files[i + 1 :]:
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

        return component_result
