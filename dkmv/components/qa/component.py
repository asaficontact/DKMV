from __future__ import annotations

import json
import logging
from typing import Any

from dkmv.components import register_component
from dkmv.components.base import WORKSPACE_DIR, BaseComponent
from dkmv.core.models import ComponentName
from dkmv.core.sandbox import SandboxSession

from .models import QAConfig, QAResult

logger = logging.getLogger(__name__)


@register_component("qa")
class QAComponent(BaseComponent[QAConfig, QAResult]):
    @property
    def name(self) -> ComponentName:
        return "qa"

    def build_prompt(self, config: QAConfig) -> str:
        return self._load_prompt_template()

    def parse_result(self, raw_result: dict[str, Any], config: QAConfig) -> QAResult:
        return QAResult(
            run_id="",
            component="qa",
            tests_total=raw_result.get("tests_total", 0),
            tests_passed=raw_result.get("tests_passed", 0),
            tests_failed=raw_result.get("tests_failed", 0),
            warnings=raw_result.get("warnings", []),
        )

    async def collect_artifacts(
        self, session: SandboxSession, config: QAConfig, result_event: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            report_content = await self.sandbox.read_file(
                session, f"{WORKSPACE_DIR}/.dkmv/qa_report.json"
            )
            if report_content:
                data: dict[str, Any] = json.loads(report_content)
                return data
        except Exception:
            logger.debug("No QA report found in container")
        return {}

    async def setup_workspace(self, session: SandboxSession, config: QAConfig) -> None:
        # Write FULL PRD (no stripping) to container
        prd_content = config.prd_path.read_text()
        await self.sandbox.write_file(session, f"{WORKSPACE_DIR}/.dkmv/prd.md", prd_content)

    async def _teardown_git(
        self,
        session: SandboxSession,
        config: QAConfig,
        artifacts_to_commit: list[str] | None = None,
    ) -> None:
        # Force-commit QA report alongside any other artifacts
        artifacts = list(artifacts_to_commit or [])
        if ".dkmv/qa_report.json" not in artifacts:
            artifacts.append(".dkmv/qa_report.json")
        await super()._teardown_git(session, config, artifacts_to_commit=artifacts)
