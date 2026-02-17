from __future__ import annotations

import logging
import re
from typing import Any

from dkmv.components import register_component
from dkmv.components.base import WORKSPACE_DIR, BaseComponent
from dkmv.core.models import ComponentName
from dkmv.core.sandbox import SandboxSession

from .models import DevConfig, DevResult

logger = logging.getLogger(__name__)


def _strip_eval_criteria(prd_content: str) -> str:
    """Remove ## Evaluation Criteria section from PRD."""
    pattern = r"(?m)^## Evaluation Criteria\s*\n.*?(?=^## |\Z)"
    return re.sub(pattern, "", prd_content, flags=re.DOTALL).rstrip() + "\n"


@register_component("dev")
class DevComponent(BaseComponent[DevConfig, DevResult]):
    @property
    def name(self) -> ComponentName:
        return "dev"

    def build_prompt(self, config: DevConfig) -> str:
        template = self._load_prompt_template()

        if config.design_docs_path:
            design_docs_section = (
                "## Design Documents\n"
                "Review the design documents in `.dkmv/design_docs/` for architectural context.\n"
            )
        else:
            design_docs_section = ""

        if config.feedback_path:
            feedback_section = (
                "## Previous Feedback\n"
                "Review the feedback from a previous review cycle at `.dkmv/feedback.json` "
                "and address all issues raised.\n"
            )
        else:
            feedback_section = ""

        return template.format(
            design_docs_section=design_docs_section,
            feedback_section=feedback_section,
        )

    def parse_result(self, raw_result: dict[str, Any], config: DevConfig) -> DevResult:
        return DevResult(
            run_id="",
            component="dev",
            files_changed=raw_result.get("files_changed", []),
            tests_passed=raw_result.get("tests_passed"),
            tests_failed=raw_result.get("tests_failed"),
        )

    async def pre_workspace_setup(self, session: SandboxSession, config: DevConfig) -> None:
        if not config.branch:
            feature = config.feature_name or config.prd_path.stem
            config.branch = f"feature/{feature}-dev"

    async def setup_workspace(self, session: SandboxSession, config: DevConfig) -> None:
        # Read PRD from host, strip eval criteria, write to container
        prd_content = config.prd_path.read_text()
        stripped_prd = _strip_eval_criteria(prd_content)
        await self.sandbox.write_file(session, f"{WORKSPACE_DIR}/.dkmv/prd.md", stripped_prd)

        # Copy feedback if provided
        if config.feedback_path:
            feedback_content = config.feedback_path.read_text()
            await self.sandbox.write_file(
                session, f"{WORKSPACE_DIR}/.dkmv/feedback.json", feedback_content
            )

        # Copy design docs if provided
        if config.design_docs_path and config.design_docs_path.is_dir():
            for doc_file in config.design_docs_path.iterdir():
                if doc_file.is_file():
                    content = doc_file.read_text()
                    await self.sandbox.write_file(
                        session,
                        f"{WORKSPACE_DIR}/.dkmv/design_docs/{doc_file.name}",
                        content,
                    )

    async def post_teardown(
        self, session: SandboxSession, config: DevConfig, result: DevResult
    ) -> None:
        try:
            plan_content = await self.sandbox.read_file(session, f"{WORKSPACE_DIR}/.dkmv/plan.md")
            if plan_content:
                run_dir = self.run_manager._run_dir(result.run_id)
                (run_dir / "plan.md").write_text(plan_content)
        except Exception:
            logger.debug("No plan.md found in container")
