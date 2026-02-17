from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from dkmv.core.models import BaseComponentConfig, BaseResult


class QAConfig(BaseComponentConfig):
    prd_path: Path


class QAResult(BaseResult):
    component: Literal["qa"] = "qa"
    tests_total: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    warnings: list[str] = Field(default_factory=list)
