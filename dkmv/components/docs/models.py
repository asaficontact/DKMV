from __future__ import annotations

from typing import Literal

from pydantic import Field

from dkmv.core.models import BaseComponentConfig, BaseResult


class DocsConfig(BaseComponentConfig):
    create_pr: bool = False
    pr_base: str = "main"


class DocsResult(BaseResult):
    component: Literal["docs"] = "docs"
    docs_generated: list[str] = Field(default_factory=list)
    pr_url: str | None = None
