from __future__ import annotations

import json
import logging
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from rich.console import Console

from dkmv.config import DKMVConfig
from dkmv.core.runner import RunManager
from dkmv.core.sandbox import SandboxManager, SandboxSession
from dkmv.core.stream import StreamParser
from dkmv.tasks.models import CLIOverrides, TaskDefinition, TaskOutput, TaskResult
from dkmv.tasks.system_context import DKMV_SYSTEM_CONTEXT

logger = logging.getLogger(__name__)

T = TypeVar("T")

WORKSPACE_DIR = "/home/dkmv/workspace"


@dataclass
class StreamResult:
    cost: float = 0.0
    turns: int = 0
    session_id: str = ""


class TaskRunner:
    def __init__(
        self,
        sandbox: SandboxManager,
        run_manager: RunManager,
        stream_parser: StreamParser,
        console: Console,
    ) -> None:
        self._sandbox = sandbox
        self._run_manager = run_manager
        self._stream_parser = stream_parser
        self._console = console

    def _resolve_param(self, task_value: T | None, cli_value: T | None, config_value: T) -> T:
        if task_value is not None:
            return task_value
        if cli_value is not None:
            return cli_value
        return config_value

    async def _inject_inputs(self, task: TaskDefinition, session: SandboxSession) -> dict[str, str]:
        env_vars: dict[str, str] = {}
        for inp in task.inputs:
            if inp.type == "file":
                src_path = Path(inp.src) if inp.src else None
                if src_path is None or not src_path.exists():
                    if inp.optional:
                        logger.debug("Optional input '%s' not found, skipping", inp.name)
                        continue
                    raise FileNotFoundError(f"Input '{inp.name}': source not found: {inp.src}")
                if src_path.is_dir():
                    for file_path in src_path.rglob("*"):
                        if file_path.is_file():
                            rel = file_path.relative_to(src_path)
                            dest = f"{inp.dest}/{rel}"
                            await self._sandbox.write_file(session, dest, file_path.read_text())
                else:
                    assert inp.dest is not None  # validated by TaskInput
                    await self._sandbox.write_file(session, inp.dest, src_path.read_text())
            elif inp.type == "text":
                assert inp.dest is not None  # validated by TaskInput
                await self._sandbox.write_file(session, inp.dest, inp.content or "")
            elif inp.type == "env":
                if inp.key and inp.value is not None:
                    env_vars[inp.key] = inp.value
        return env_vars

    async def _write_instructions(
        self,
        task: TaskDefinition,
        session: SandboxSession,
        component_agent_md: str | None = None,
        context_files: list[str] | None = None,
    ) -> str:
        layers: list[str] = [DKMV_SYSTEM_CONTEXT]
        if component_agent_md:
            layers.append(component_agent_md)
        if context_files:
            listing = "\n".join(f"  - `{f}`" for f in context_files)
            layers.append(
                "## Additional Context\n\n"
                "The following reference files have been provided. "
                "Refer to these as needed:\n" + listing
            )
        if task.instructions:
            layers.append(f"## Task-Specific Instructions\n\n{task.instructions}")
        if task.commit:
            layers.append(
                "## Git Commit Rules\n\n"
                "- Commit your work as you go with conventional commit messages "
                "(e.g., `feat(scope): description`, `fix(scope): description`)\n"
                "- Ensure ALL changes are committed before you finish\n"
                "- Do NOT leave uncommitted changes"
            )
        content = "\n\n---\n\n".join(layers) + "\n"
        await self._sandbox.execute(session, f"mkdir -p {WORKSPACE_DIR}/.claude")
        await self._sandbox.write_file(session, f"{WORKSPACE_DIR}/.claude/CLAUDE.md", content)
        return content

    async def _stream_claude(
        self,
        task: TaskDefinition,
        session: SandboxSession,
        run_id: str,
        config: DKMVConfig,
        cli_overrides: CLIOverrides,
        env_vars: dict[str, str],
    ) -> StreamResult:
        model = self._resolve_param(task.model, cli_overrides.model, config.default_model)
        max_turns = self._resolve_param(
            task.max_turns, cli_overrides.max_turns, config.default_max_turns
        )
        timeout = self._resolve_param(
            task.timeout_minutes, cli_overrides.timeout_minutes, config.timeout_minutes
        )
        budget = self._resolve_param(
            task.max_budget_usd, cli_overrides.max_budget_usd, config.max_budget_usd
        )

        stream_result = StreamResult()

        async for event in self._sandbox.stream_claude(
            session=session,
            prompt=task.prompt or "",
            model=model,
            max_turns=max_turns,
            timeout_minutes=timeout,
            max_budget_usd=budget,
            env_vars=env_vars or None,
        ):
            self._run_manager.append_stream(run_id, event)
            parsed = self._stream_parser.parse_line(json.dumps(event))
            if parsed:
                self._stream_parser.render_event(parsed)
            if event.get("type") == "result":
                stream_result.cost = event.get("total_cost_usd", 0.0)
                stream_result.turns = event.get("num_turns", 0)
                stream_result.session_id = event.get("session_id", "")

        return stream_result

    @staticmethod
    def _validate_required_fields(output: TaskOutput, content: str) -> str | None:
        """Return error message if required fields are missing, else None."""
        if not output.required_fields:
            return None
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return f"Output '{output.path}' is not valid JSON but has required_fields"
        if not isinstance(data, dict):
            return f"Output '{output.path}' is not a JSON object but has required_fields"
        missing = [f for f in output.required_fields if f not in data]
        if missing:
            return f"Output '{output.path}' missing required fields: {', '.join(missing)}"
        return None

    async def _collect_outputs(
        self,
        task: TaskDefinition,
        session: SandboxSession,
        run_id: str,
    ) -> tuple[dict[str, str], str | None]:
        outputs: dict[str, str] = {}
        for output in task.outputs:
            if not await self._sandbox.file_exists(session, output.path):
                if output.required:
                    return outputs, f"Required output missing: {output.path}"
                continue
            content = await self._sandbox.read_file(session, output.path)
            field_error = self._validate_required_fields(output, content)
            if field_error:
                return outputs, field_error
            outputs[output.path] = content
            if output.save:
                filename = Path(output.path).name
                self._run_manager.save_artifact(run_id, filename, content)
        return outputs, None

    async def _retry_claude(
        self,
        task: TaskDefinition,
        session: SandboxSession,
        run_id: str,
        config: DKMVConfig,
        cli_overrides: CLIOverrides,
        env_vars: dict[str, str],
        session_id: str,
        error_message: str,
    ) -> StreamResult:
        """Resume Claude Code session with a corrective prompt."""
        corrective_prompt = (
            f"Your previous run did not produce the expected output.\n\n"
            f"Error: {error_message}\n\n"
            f"Please fix this issue and produce the required output files."
        )

        model = self._resolve_param(task.model, cli_overrides.model, config.default_model)
        max_turns = min(
            self._resolve_param(task.max_turns, cli_overrides.max_turns, config.default_max_turns),
            10,
        )
        timeout = self._resolve_param(
            task.timeout_minutes, cli_overrides.timeout_minutes, config.timeout_minutes
        )
        budget = self._resolve_param(
            task.max_budget_usd, cli_overrides.max_budget_usd, config.max_budget_usd
        )

        stream_result = StreamResult()
        async for event in self._sandbox.stream_claude(
            session=session,
            prompt=corrective_prompt,
            model=model,
            max_turns=max_turns,
            timeout_minutes=timeout,
            max_budget_usd=budget,
            env_vars=env_vars or None,
            resume_session_id=session_id,
        ):
            self._run_manager.append_stream(run_id, event)
            parsed = self._stream_parser.parse_line(json.dumps(event))
            if parsed:
                self._stream_parser.render_event(parsed)
            if event.get("type") == "result":
                stream_result.cost = event.get("total_cost_usd", 0.0)
                stream_result.turns = event.get("num_turns", 0)
                stream_result.session_id = event.get("session_id", "")
        return stream_result

    async def _git_teardown(self, task: TaskDefinition, session: SandboxSession) -> None:
        if not task.commit and not task.push:
            return

        if task.commit:
            # Force-add declared outputs (they may be in .gitignore / .agent/)
            for output in task.outputs:
                await self._sandbox.execute(
                    session,
                    f"cd {WORKSPACE_DIR} && git add -f {shlex.quote(output.path)} 2>/dev/null || true",
                )

            # Safety net: catch code changes the agent missed, but exclude
            # workspace dirs (.agent/, .claude/) so they don't pollute commits
            await self._sandbox.execute(
                session,
                f"cd {WORKSPACE_DIR} && git add -A -- . ':!.agent/' ':!.claude/'",
            )
            result = await self._sandbox.execute(
                session, f"cd {WORKSPACE_DIR} && git status --porcelain"
            )
            if result.output.strip():
                msg = f"chore: uncommitted changes from {task.name} [dkmv]"
                commit_result = await self._sandbox.execute(
                    session, f"cd {WORKSPACE_DIR} && git commit -m {shlex.quote(msg)}"
                )
                if commit_result.exit_code != 0:
                    logger.warning("git commit failed: %s", commit_result.output[:500])

        if task.push:
            push_result = await self._sandbox.execute(
                session, f"cd {WORKSPACE_DIR} && git push origin HEAD", timeout=60
            )
            if push_result.exit_code != 0:
                raise RuntimeError(f"git push failed: {push_result.output[:500]}")

    async def run(
        self,
        task: TaskDefinition,
        session: SandboxSession,
        run_id: str,
        config: DKMVConfig,
        cli_overrides: CLIOverrides,
        component_agent_md: str | None = None,
        shared_env_vars: dict[str, str] | None = None,
        context_files: list[str] | None = None,
    ) -> TaskResult:
        start_time = time.monotonic()
        result = TaskResult(task_name=task.name, description=task.description, status="failed")

        try:
            env_vars = {**(shared_env_vars or {})}
            task_env_vars = await self._inject_inputs(task, session)
            env_vars.update(task_env_vars)
            claude_md = await self._write_instructions(
                task, session, component_agent_md, context_files=context_files
            )
            self._run_manager.save_artifact(run_id, f"claude_md_{task.name}.md", claude_md)
            self._run_manager.save_task_prompt(run_id, task.name, task.prompt or "")

            stream_result = await self._stream_claude(
                task, session, run_id, config, cli_overrides, env_vars
            )
            result.total_cost_usd = stream_result.cost
            result.num_turns = stream_result.turns
            result.session_id = stream_result.session_id

            # Push the agent's work BEFORE validating outputs so code is
            # never lost when a metadata file is missing.
            await self._git_teardown(task, session)

            outputs, error = await self._collect_outputs(task, session, run_id)
            if error and stream_result.session_id:
                logger.info("Output collection failed (%s), retrying with --resume", error)
                retry_result = await self._retry_claude(
                    task,
                    session,
                    run_id,
                    config,
                    cli_overrides,
                    env_vars,
                    stream_result.session_id,
                    error,
                )
                result.total_cost_usd += retry_result.cost
                result.num_turns += retry_result.turns
                if retry_result.session_id:
                    result.session_id = retry_result.session_id
                outputs, error = await self._collect_outputs(task, session, run_id)

            if error:
                result.error_message = error
                result.duration_seconds = time.monotonic() - start_time
                return result
            result.outputs = outputs
            result.status = "completed"

        except TimeoutError:
            result.status = "timed_out"
            result.error_message = f"Task '{task.name}' timed out"
        except FileNotFoundError as e:
            result.error_message = str(e)
        except Exception as e:
            result.error_message = f"Unexpected error: {e}"
        finally:
            result.duration_seconds = time.monotonic() - start_time

        return result
