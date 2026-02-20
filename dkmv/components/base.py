from __future__ import annotations

import importlib.resources
import json
import logging
import shlex
import time
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from pydantic_core import PydanticUndefined

from dkmv.config import DKMVConfig
from dkmv.core.models import BaseComponentConfig, BaseResult, ComponentName, SandboxConfig
from dkmv.core.runner import RunManager
from dkmv.core.sandbox import SandboxManager, SandboxSession
from dkmv.core.stream import StreamParser

logger = logging.getLogger(__name__)

C = TypeVar("C", bound=BaseComponentConfig)
R = TypeVar("R", bound=BaseResult)

WORKSPACE_DIR = "/home/dkmv/workspace"


class BaseComponent(ABC, Generic[C, R]):
    def __init__(
        self,
        global_config: DKMVConfig,
        sandbox: SandboxManager,
        run_manager: RunManager,
        stream_parser: StreamParser,
    ) -> None:
        self.global_config = global_config
        self.sandbox = sandbox
        self.run_manager = run_manager
        self.stream_parser = stream_parser

    @property
    @abstractmethod
    def name(self) -> ComponentName: ...

    @abstractmethod
    def build_prompt(self, config: C) -> str: ...

    @abstractmethod
    def parse_result(self, raw_result: dict[str, Any], config: C) -> R: ...

    async def pre_workspace_setup(self, session: SandboxSession, config: C) -> None:
        """Hook called before branch checkout. Use to derive/modify config.branch."""

    async def setup_workspace(self, session: SandboxSession, config: C) -> None:
        """Hook for component-specific workspace setup. Default is no-op."""

    async def collect_artifacts(
        self, session: SandboxSession, config: C, result_event: dict[str, Any]
    ) -> dict[str, Any]:
        """Hook to read artifacts from container after Claude completes.
        Returns dict passed to parse_result() to populate component-specific fields."""
        return {}

    async def post_teardown(self, session: SandboxSession, config: C, result: R) -> None:
        """Hook called after git teardown. Use for PR creation, artifact capture, etc."""

    def _load_prompt_template(self) -> str:
        package = f"dkmv.components.{self.name}"
        try:
            files = importlib.resources.files(package)
            prompt_file = files / "prompt.md"
            return prompt_file.read_text(encoding="utf-8")  # type: ignore[union-attr]
        except (ModuleNotFoundError, FileNotFoundError, TypeError) as e:
            msg = f"Prompt template not found for component {self.name!r}"
            raise FileNotFoundError(msg) from e

    def _build_sandbox_config(self, config: C) -> SandboxConfig:
        env_vars = {
            "ANTHROPIC_API_KEY": self.global_config.anthropic_api_key,
        }
        if self.global_config.github_token:
            env_vars["GITHUB_TOKEN"] = self.global_config.github_token

        return SandboxConfig(
            image=self.global_config.image_name,
            env_vars={**env_vars, **config.sandbox_config.env_vars},
            docker_args=config.sandbox_config.docker_args,
            startup_timeout=config.sandbox_config.startup_timeout,
            keep_alive=config.keep_alive,
            memory_limit=self.global_config.memory_limit,
            timeout_minutes=config.timeout_minutes,
        )

    async def _setup_base_workspace(self, session: SandboxSession, config: C) -> None:
        # Git auth
        auth_result = await self.sandbox.setup_git_auth(session)
        if auth_result.exit_code != 0:
            msg = (
                f"Git auth setup failed (exit {auth_result.exit_code}): {auth_result.output[:500]}"
            )
            raise RuntimeError(msg)

        # Clone repo
        clone_result = await self.sandbox.execute(
            session,
            f"git clone {shlex.quote(config.repo)} {WORKSPACE_DIR}",
            timeout=120,
        )
        if clone_result.exit_code != 0:
            msg = f"git clone failed (exit {clone_result.exit_code}): {clone_result.output[:500]}"
            raise RuntimeError(msg)

        # Pre-workspace hook (e.g., branch derivation)
        await self.pre_workspace_setup(session, config)

        # Branch: checkout existing or create new
        if config.branch:
            # Try checkout existing, fall back to creating new
            branch = shlex.quote(config.branch)
            result = await self.sandbox.execute(
                session,
                f"cd {WORKSPACE_DIR} && git checkout {branch} 2>/dev/null"
                f" || git checkout -b {branch}",
            )
            logger.debug("Branch setup: %s", result.output)

        # Add .dkmv/ to .gitignore
        await self.sandbox.execute(
            session,
            f"cd {WORKSPACE_DIR} && mkdir -p .dkmv"
            " && (grep -qxF '.dkmv/' .gitignore 2>/dev/null || echo '.dkmv/' >> .gitignore)",
        )

        # Component-specific workspace setup hook
        await self.setup_workspace(session, config)

    async def _write_claude_md(self, session: SandboxSession, config: C) -> None:
        content = (
            "# DKMV Agent Instructions\n\n"
            f"You are the **{self.name}** agent for the DKMV system.\n"
            f"Feature: {config.feature_name}\n"
            f"Branch: {config.branch or 'main'}\n\n"
            "## Rules\n"
            "- Work only on the assigned feature\n"
            "- Commit with conventional commit messages using `[dkmv-"
            f"{self.name}]` suffix\n"
            "- Do not push to main/master directly\n"
        )

        if hasattr(config, "prd_path") and getattr(config, "prd_path", None):
            content += "\n## PRD\nRefer to `.dkmv/prd.md` for requirements.\n"

        await self.sandbox.execute(
            session,
            f"mkdir -p {WORKSPACE_DIR}/.claude",
        )
        await self.sandbox.write_file(session, f"{WORKSPACE_DIR}/.claude/CLAUDE.md", content)

    async def _teardown_git(
        self,
        session: SandboxSession,
        config: C,
        artifacts_to_commit: list[str] | None = None,
    ) -> None:
        # Force-add any artifacts (e.g. QA reports, Judge verdicts)
        if artifacts_to_commit:
            for artifact in artifacts_to_commit:
                await self.sandbox.execute(
                    session, f"cd {WORKSPACE_DIR} && git add -f {shlex.quote(artifact)}"
                )

        await self.sandbox.execute(session, f"cd {WORKSPACE_DIR} && git add -A")

        # Check if there's anything to commit
        porcelain = await self.sandbox.execute(
            session, f"cd {WORKSPACE_DIR} && git status --porcelain"
        )
        if not porcelain.output.strip():
            logger.info("Nothing to commit")
            return

        feature_tag = config.feature_name or "update"
        commit_msg = shlex.quote(f"feat({self.name}): {feature_tag} [dkmv-{self.name}]")
        commit_result = await self.sandbox.execute(
            session,
            f"cd {WORKSPACE_DIR} && git commit -m {commit_msg}",
        )
        if commit_result.exit_code != 0:
            msg = (
                f"git commit failed (exit {commit_result.exit_code}): {commit_result.output[:500]}"
            )
            raise RuntimeError(msg)

        if not config.branch:
            logger.warning("No branch specified — skipping git push to avoid pushing to main")
            return

        push_result = await self.sandbox.execute(
            session,
            f"cd {WORKSPACE_DIR} && git push origin {shlex.quote(config.branch)}",
            timeout=60,
        )
        if push_result.exit_code != 0:
            msg = f"git push failed (exit {push_result.exit_code}): {push_result.output[:500]}"
            raise RuntimeError(msg)

    @staticmethod
    def synthesize_feedback(verdict: dict[str, Any]) -> str:
        """Transform Judge verdict into developer feedback brief."""
        issues = verdict.get("issues", [])
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_issues = sorted(
            issues, key=lambda x: severity_order.get(x.get("severity", "low"), 99)
        )

        lines = ["# Feedback from Judge\n"]
        for issue in sorted_issues:
            severity = issue.get("severity", "unknown").upper()
            description = issue.get("description", "")
            lines.append(f"- **[{severity}]** {description}")

        return "\n".join(lines)

    def _merge_artifact_fields(self, target: R, source: R) -> None:
        """Merge component-specific fields from source into target.
        Skips BaseResult fields (run_id, status, cost, etc.)."""
        base_fields = set(BaseResult.model_fields.keys())
        source_fields = type(source).model_fields
        for field_name in source_fields:
            if field_name not in base_fields:
                value = getattr(source, field_name)
                field_info = source_fields[field_name]
                default = field_info.default
                if default is PydanticUndefined and field_info.default_factory is not None:
                    default = field_info.default_factory()  # type: ignore[call-arg]
                if value != default:
                    setattr(target, field_name, value)

    async def run(self, config: C) -> R:
        # 1. Validate inputs
        if not config.repo:
            msg = "repo is required"
            raise ValueError(msg)
        if config.timeout_minutes <= 0:
            msg = "timeout_minutes must be positive"
            raise ValueError(msg)

        # 2. Create run
        run_id = self.run_manager.start_run(self.name, config)

        session: SandboxSession | None = None
        result_event: dict[str, Any] = {}
        start_time = time.monotonic()

        # Build result shell
        result = self.parse_result({}, config)
        result.run_id = run_id
        result.component = self.name
        result.repo = config.repo
        result.branch = config.branch or ""
        result.feature_name = config.feature_name
        result.model = config.model

        try:
            # 3. Start sandbox
            sandbox_config = self._build_sandbox_config(config)
            session = await self.sandbox.start(sandbox_config, self.name)

            # 3.5 Persist container name for attach/stop commands
            container_name = self.sandbox.get_container_name(session)
            if container_name:
                self.run_manager.save_container_name(run_id, container_name)

            # 4. Setup workspace
            await self._setup_base_workspace(session, config)

            # 5. Write .claude/CLAUDE.md
            await self._write_claude_md(session, config)

            # 6. Build prompt and save
            prompt = self.build_prompt(config)
            self.run_manager.save_prompt(run_id, prompt)

            # 7. Stream Claude Code
            async for event in self.sandbox.stream_claude(
                session=session,
                prompt=prompt,
                model=config.model,
                max_turns=config.max_turns,
                timeout_minutes=config.timeout_minutes,
                max_budget_usd=config.max_budget_usd,
            ):
                self.run_manager.append_stream(run_id, event)
                parsed = self.stream_parser.parse_line(json.dumps(event))
                if parsed:
                    self.stream_parser.render_event(parsed)
                if event.get("type") == "result":
                    result_event = event

            # 8. Collect results
            if not result_event:
                msg = "No result event received from Claude Code"
                raise RuntimeError(msg)

            result.total_cost_usd = result_event.get("total_cost_usd", 0.0)
            result.duration_seconds = result_event.get("duration_ms", 0.0) / 1000
            result.num_turns = result_event.get("num_turns", 0)
            result.session_id = result_event.get("session_id", "")

            # 8.5. Collect container artifacts
            raw_artifacts = await self.collect_artifacts(session, config, result_event)
            if raw_artifacts:
                enriched = self.parse_result(raw_artifacts, config)
                self._merge_artifact_fields(result, enriched)

            # Update branch on result (may have been derived in pre_workspace_setup)
            result.branch = config.branch or ""

            # 9. Git teardown
            await self._teardown_git(session, config)

            # 9.5. Post-teardown hook
            await self.post_teardown(session, config, result)

            # 10. Mark completed
            result.status = "completed"

        except TimeoutError:
            result.status = "timed_out"
            result.error_message = "Component timed out"
            result.duration_seconds = time.monotonic() - start_time

        except Exception as e:
            result.status = "failed"
            result.error_message = str(e)
            result.duration_seconds = time.monotonic() - start_time

        finally:
            # 10. Save result (always)
            self.run_manager.save_result(run_id, result)

            # 11. Stop container (always)
            if session is not None:
                await self.sandbox.stop(session, keep_alive=config.keep_alive)

        # 12. Return typed result
        return result
