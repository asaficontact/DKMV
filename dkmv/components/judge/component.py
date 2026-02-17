from __future__ import annotations

import json
import logging
from typing import Any

from dkmv.components import register_component
from dkmv.components.base import WORKSPACE_DIR, BaseComponent
from dkmv.core.models import ComponentName
from dkmv.core.sandbox import SandboxSession

from .models import JudgeConfig, JudgeResult

logger = logging.getLogger(__name__)


@register_component("judge")
class JudgeComponent(BaseComponent[JudgeConfig, JudgeResult]):
    @property
    def name(self) -> ComponentName:
        return "judge"

    def build_prompt(self, config: JudgeConfig) -> str:
        return self._load_prompt_template()

    def parse_result(self, raw_result: dict[str, Any], config: JudgeConfig) -> JudgeResult:
        return JudgeResult(
            run_id="",
            component="judge",
            verdict=raw_result.get("verdict", "fail"),
            confidence=raw_result.get("confidence", 0.0),
            reasoning=raw_result.get("reasoning", ""),
            prd_requirements=raw_result.get("prd_requirements", []),
            issues=raw_result.get("issues", []),
            suggestions=raw_result.get("suggestions", []),
            score=raw_result.get("score", 0),
        )

    async def collect_artifacts(
        self, session: SandboxSession, config: JudgeConfig, result_event: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            verdict_content = await self.sandbox.read_file(
                session, f"{WORKSPACE_DIR}/.dkmv/verdict.json"
            )
            if verdict_content:
                data: dict[str, Any] = json.loads(verdict_content)
                return data
        except Exception:
            logger.debug("No verdict found in container")
        return {}

    async def setup_workspace(self, session: SandboxSession, config: JudgeConfig) -> None:
        # Write FULL PRD (no stripping) to container
        prd_content = config.prd_path.read_text()
        await self.sandbox.write_file(session, f"{WORKSPACE_DIR}/.dkmv/prd.md", prd_content)

    async def _teardown_git(
        self,
        session: SandboxSession,
        config: JudgeConfig,
        artifacts_to_commit: list[str] | None = None,
    ) -> None:
        # Force-commit verdict alongside any other artifacts
        artifacts = list(artifacts_to_commit or [])
        if ".dkmv/verdict.json" not in artifacts:
            artifacts.append(".dkmv/verdict.json")
        await super()._teardown_git(session, config, artifacts_to_commit=artifacts)
