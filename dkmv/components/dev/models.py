from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from dkmv.core.models import BaseComponentConfig, BaseResult


class DevConfig(BaseComponentConfig):
    prd_path: Path
    feedback_path: Path | None = None
    design_docs_path: Path | None = None


class DevResult(BaseResult):
    component: Literal["dev"] = "dev"
    files_changed: list[str] = Field(default_factory=list)
    tests_passed: int | None = None
    tests_failed: int | None = None
