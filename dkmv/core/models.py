from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

RunStatus = Literal["pending", "running", "completed", "failed", "timed_out"]
ComponentName = Literal["dev", "qa", "judge", "docs"]


class SandboxConfig(BaseModel):
    image: str = "dkmv-sandbox:latest"
    env_vars: dict[str, str] = Field(default_factory=dict)
    docker_args: list[str] = Field(default_factory=list)
    startup_timeout: float = 180.0
    keep_alive: bool = False
    memory_limit: str = "8g"
    timeout_minutes: int = 30


class BaseComponentConfig(BaseModel):
    repo: str
    branch: str | None = None
    feature_name: str = ""
    model: str = "claude-sonnet-4-20250514"
    max_turns: int = 100
    keep_alive: bool = False
    verbose: bool = False
    timeout_minutes: int = 30
    sandbox_config: SandboxConfig = Field(default_factory=SandboxConfig)
    max_budget_usd: float | None = None


class BaseResult(BaseModel):
    run_id: str
    component: ComponentName
    status: RunStatus = "pending"
    repo: str = ""
    branch: str = ""
    feature_name: str = ""
    model: str = ""
    total_cost_usd: float = Field(default=0.0, ge=0)
    duration_seconds: float = Field(default=0.0, ge=0)
    num_turns: int = Field(default=0, ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_id: str = ""
    error_message: str = ""


class RunSummary(BaseModel):
    run_id: str
    component: ComponentName
    status: RunStatus
    feature_name: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    total_cost_usd: float = Field(default=0.0, ge=0)
    duration_seconds: float = Field(default=0.0, ge=0)


class RunDetail(BaseResult):
    config: dict[str, Any] = Field(default_factory=dict)
    stream_events_count: int = 0
    prompt: str = ""
    log_path: str = ""
