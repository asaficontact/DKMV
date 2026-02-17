from __future__ import annotations

import logging
import shlex
from typing import Any

from dkmv.components import register_component
from dkmv.components.base import WORKSPACE_DIR, BaseComponent
from dkmv.core.models import ComponentName
from dkmv.core.sandbox import SandboxSession

from .models import DocsConfig, DocsResult

logger = logging.getLogger(__name__)


@register_component("docs")
class DocsComponent(BaseComponent[DocsConfig, DocsResult]):
    @property
    def name(self) -> ComponentName:
        return "docs"

    def build_prompt(self, config: DocsConfig) -> str:
        return self._load_prompt_template()

    def parse_result(self, raw_result: dict[str, Any], config: DocsConfig) -> DocsResult:
        return DocsResult(
            run_id="",
            component="docs",
            docs_generated=raw_result.get("docs_generated", []),
            pr_url=raw_result.get("pr_url"),
        )

    async def post_teardown(
        self, session: SandboxSession, config: DocsConfig, result: DocsResult
    ) -> None:
        if config.create_pr and config.branch:
            try:
                pr_result = await self.sandbox.execute(
                    session,
                    f"cd {WORKSPACE_DIR} && gh pr create"
                    f" --base {shlex.quote(config.pr_base)}"
                    f" --head {shlex.quote(config.branch)}"
                    f" --title {shlex.quote('docs: update documentation')}"
                    f" --body {shlex.quote('Auto-generated documentation update by DKMV docs agent.')}",
                    timeout=60,
                )
                if pr_result.exit_code == 0 and pr_result.output.strip():
                    result.pr_url = pr_result.output.strip()
            except Exception:
                logger.warning("PR creation failed", exc_info=True)
