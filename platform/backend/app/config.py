"""Consolidated, typed platform settings (PRD §8.8 env surface).

A single ``Settings`` object is the *only* place the backend reads
configuration. It exposes every key from the consolidated PRD §8.8 config/env
table and applies the binding defaults:

* ``DKMV_PLATFORM_BIND`` defaults to ``127.0.0.1:8787`` (loopback only — INV-1).
* ``SANDBOX_RUNTIME`` defaults to ``runsc`` (gVisor — INV-3).
* ``DKMV_IMAGE`` defaults to ``dkmv-sandbox:latest``.

Secrets (``GITHUB_TOKEN``, ``ANTHROPIC_API_KEY``, ``CODEX_API_KEY``,
``DKMV_PLATFORM_TOKEN``) are typed as ``SecretStr`` so they never accidentally
print or log their value. In real deployments these live in the encrypted
``SecretStore`` (PRD §8.6), not plain env; the env fields here are the dev-mode
ingress and the typed contract the rest of the app depends on.

Nothing in this module reaches into ``dkmv/`` or shells the CLI.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed view over the consolidated PRD §8.8 config/env surface.

    Field names are the canonical env keys (upper-snake) so the grep-able
    acceptance criteria (AC-0.1-4) match the source verbatim and there is no
    aliasing indirection between the env var and the attribute.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- App access / auth (INV-1) ---
    DKMV_PLATFORM_TOKEN: SecretStr = Field(
        default=SecretStr(""),
        description="Local auth token required on every API/SSE request.",
    )
    DKMV_PLATFORM_BIND: str = Field(
        default="127.0.0.1:8787",
        description="host:port the backend binds to (loopback only by default).",
    )

    # --- Persistence + artifacts ---
    DATABASE_URL: str = Field(
        default="sqlite:///./data/dkmv.db",
        description="SQLite (WAL) connection URL; Postgres later via the repo seam.",
    )
    OUTPUT_DIR: Path = Field(
        default=Path("./data/outputs"),
        description="Platform-owned engine runs/artifacts volume (OQ-4).",
    )

    # --- Provider / engine credentials (secrets) ---
    GITHUB_TOKEN: SecretStr = Field(
        default=SecretStr(""),
        description="Fine-grained GitHub PAT (repo-scoped, short-TTL in prod).",
    )
    ANTHROPIC_API_KEY: SecretStr = Field(
        default=SecretStr(""),
        description="Anthropic API key for Claude runs.",
    )
    CODEX_API_KEY: SecretStr = Field(
        default=SecretStr(""),
        description="Codex API key for Codex runs.",
    )

    # --- Sandbox image / runtime (INV-3) ---
    DKMV_IMAGE: str = Field(
        default="dkmv-sandbox:latest",
        description="Sandbox image name; pin by digest in prod (§8.6).",
    )
    SANDBOX_RUNTIME: str = Field(
        default="runsc",
        description="Container runtime; gVisor 'runsc' by default (NFR-SEC-4).",
    )

    # --- Admission control / governance (Phase 3 consumes these) ---
    MAX_CONCURRENT_RUNS: int = Field(
        default=3,
        ge=1,
        description="Concurrency cap for the dispatch loop.",
    )
    HOST_MEMORY_BUDGET: str | None = Field(
        default=None,
        description="Total host memory budget for sandbox admission (e.g. '32g').",
    )
    DAILY_SPEND_CAP: float | None = Field(
        default=None,
        description="Daily USD spend cap; None disables the cap.",
    )

    # --- Orchestrator timing (Phase 3 consumes these) ---
    TICK_INTERVAL_S: int = Field(
        default=10,
        ge=1,
        description="Reconcile/dispatch loop tick interval in seconds.",
    )
    STALL_TIMEOUT_S: int = Field(
        default=300,
        ge=1,
        description="Seconds without progress before a run is considered stalled.",
    )
    PAUSE_TIMEOUT_S: int = Field(
        default=3600,
        ge=1,
        description="Seconds a HITL pause may wait before auto-timeout.",
    )

    # --- Egress allowlist (INV-3) ---
    EGRESS_ALLOWLIST: str = Field(
        default="api.github.com,github.com,api.anthropic.com,api.openai.com",
        description=(
            "Comma-separated hosts the sandbox may reach (GitHub + model APIs). "
            "Default-on, network-enforced (NFR-SEC-1)."
        ),
    )

    @field_validator("DKMV_PLATFORM_BIND")
    @classmethod
    def _validate_bind(cls, value: str) -> str:
        """Require a ``host:port`` shape with an integer port."""
        if ":" not in value:
            raise ValueError("DKMV_PLATFORM_BIND must be 'host:port'")
        host, _, port = value.rpartition(":")
        if not host:
            raise ValueError("DKMV_PLATFORM_BIND must include a host")
        if not port.isdigit():
            raise ValueError("DKMV_PLATFORM_BIND port must be an integer")
        return value

    @property
    def bind_host(self) -> str:
        """Host portion of ``DKMV_PLATFORM_BIND`` (default ``127.0.0.1``)."""
        return self.DKMV_PLATFORM_BIND.rpartition(":")[0]

    @property
    def bind_port(self) -> int:
        """Port portion of ``DKMV_PLATFORM_BIND`` (default ``8787``)."""
        return int(self.DKMV_PLATFORM_BIND.rpartition(":")[2])

    @property
    def egress_hosts(self) -> list[str]:
        """Parsed egress allowlist as a de-duplicated, stripped host list."""
        seen: dict[str, None] = {}
        for raw in self.EGRESS_ALLOWLIST.split(","):
            host = raw.strip()
            if host:
                seen[host] = None
        return list(seen)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached settings instance.

    Cached so the env surface is parsed once. Tests that need a fresh parse
    call ``get_settings.cache_clear()``.
    """
    return Settings()
