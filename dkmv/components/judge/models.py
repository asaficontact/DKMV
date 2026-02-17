from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from dkmv.core.models import BaseComponentConfig, BaseResult


class JudgeConfig(BaseComponentConfig):
    prd_path: Path


class PrdRequirement(BaseModel):
    requirement: str
    status: Literal["implemented", "missing", "partial"] = "missing"
    notes: str = ""


class JudgeIssue(BaseModel):
    severity: Literal["critical", "high", "medium", "low"] = "medium"
    description: str = ""
    file: str = ""
    line: int | None = None
    suggestion: str = ""


class JudgeResult(BaseResult):
    component: Literal["judge"] = "judge"
    verdict: Literal["pass", "fail"] = "fail"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""
    prd_requirements: list[PrdRequirement] = Field(default_factory=list)
    issues: list[JudgeIssue] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    score: int = Field(default=0, ge=0, le=100)
