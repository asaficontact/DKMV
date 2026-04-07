"""Shared types for the embedded runtime API."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from dkmv.config import DKMVConfig


class ExecutionSourceType(str, Enum):
    """How source code is provided to a run."""

    REMOTE = "remote"
    LOCAL_SNAPSHOT = "local_snapshot"


class ExecutionSource(BaseModel):
    """Describes where source code comes from for a run."""

    type: ExecutionSourceType
    repo: str | None = None
    branch: str | None = None
    local_path: Path | None = None
    include_uncommitted: bool = True
    include_untracked: bool = True


class RuntimeConfig(BaseModel):
    """Host-provided configuration. Converts to internal DKMVConfig without env var loading."""

    anthropic_api_key: str = ""
    claude_oauth_token: str = ""
    github_token: str = ""
    codex_api_key: str = ""
    default_model: str = "claude-sonnet-4-6"
    default_max_turns: int = 100
    image_name: str = "dkmv-sandbox:latest"
    output_dir: Path = Path("./outputs")
    timeout_minutes: int = 30
    memory_limit: str = "8g"
    max_budget_usd: float | None = None
    default_agent: str = "claude"
    docker_socket: bool = False

    def to_dkmv_config(self) -> DKMVConfig:
        """Build a DKMVConfig using model_construct() to bypass env/file loading."""
        return DKMVConfig.model_construct(
            anthropic_api_key=self.anthropic_api_key,
            claude_oauth_token=self.claude_oauth_token,
            github_token=self.github_token,
            codex_api_key=self.codex_api_key,
            default_model=self.default_model,
            default_max_turns=self.default_max_turns,
            image_name=self.image_name,
            output_dir=self.output_dir,
            timeout_minutes=self.timeout_minutes,
            memory_limit=self.memory_limit,
            max_budget_usd=self.max_budget_usd,
            default_agent=self.default_agent,
            auth_method="api_key",
            docker_socket=self.docker_socket,
        )


class SourceProvenance(BaseModel):
    """Records the provenance of source code used for a run."""

    source_type: str  # "remote" or "local_snapshot"
    local_path: str = ""
    head_sha: str = ""
    branch: str = ""
    dirty: bool = False
    include_uncommitted: bool = True
    include_untracked: bool = True


class ContainerStatus(BaseModel):
    """Status of a retained sandbox container."""

    run_id: str
    container_name: str = ""
    alive: bool = False
    state: str = "unknown"  # "running", "exited", "removed", "unknown"
    error: str = ""


class RetentionPolicy(str, Enum):
    """Policy for retaining run output directories."""

    DESTROY = "destroy"
    RETAIN_TTL = "retain_ttl"
    RETAIN_MANUAL = "retain_manual"
