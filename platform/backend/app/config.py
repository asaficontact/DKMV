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

# --- Capability-aware default run timeouts (5.2 / ADR-P009, NFR-COST-1, §7.2) ---
#
# For Codex (``supports_budget``/``supports_max_turns`` both false) the
# ``timeout_minutes`` is the **only** runtime guardrail (ADR-P009) — there is no
# budget or turn cap to stop a runaway run, so the Codex default timeout is
# **strictly tighter** than the Claude default. The Phase-2 prototype's per-
# workflow timeouts (``dev=40``/``docs=20``, §7.2) are the *Claude-style*
# defaults; §7.2 footnote 3 says a Codex workflow defaults to a tighter bound
# because timeout is its sole guardrail. These are the fallbacks applied at
# launch when the operator pins no explicit ``timeout_minutes`` — never an
# override of an explicit value.
#
# INV-8 binding: the gap (``CLAUDE_DEFAULT_TIMEOUT_MINUTES`` >
# ``CODEX_DEFAULT_TIMEOUT_MINUTES``) is asserted by ``test_cost_governance`` —
# Codex MUST be strictly tighter. Keep this invariant if either value changes.

#: Default ``timeout_minutes`` for a Claude (capable) run when none is supplied.
CLAUDE_DEFAULT_TIMEOUT_MINUTES = 40

#: Default ``timeout_minutes`` for a Codex (timeout-only) run when none is
#: supplied — **strictly tighter** than the Claude default (ADR-P009 / §7.2 fn3).
CODEX_DEFAULT_TIMEOUT_MINUTES = 20

assert CODEX_DEFAULT_TIMEOUT_MINUTES < CLAUDE_DEFAULT_TIMEOUT_MINUTES, (
    "INV-8/ADR-P009: the Codex default timeout must be strictly tighter than the "
    "Claude default (timeout is Codex's only runtime guardrail)."
)


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
    DKMV_EXPOSE_DOCS_UNAUTHENTICATED: bool = Field(
        default=False,
        description=(
            "Dev-only opt-in (default OFF): waive the local-token check for the "
            "framework docs paths (/openapi.json, /docs, /redoc). The "
            "Host/Origin anti-DNS-rebinding gate still applies even when on. "
            "Leave OFF in any shared/networked deployment (INV-1)."
        ),
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
    DKMV_PROJECT_ROOT: Path | None = Field(
        default=None,
        description=(
            "Optional local on-disk working copy of the connected project — the "
            "directory holding ``.dkmv/`` (the ``components.json`` registry + any "
            "custom components authored on disk). Published once at lifespan startup "
            "on ``app.state.project_root`` and consumed read-only by BOTH the "
            "Workflows viewer (``GET /workflows`` surfaces registered custom "
            "components via ``list_components(project_root)``) and the launch path "
            "(``POST /runs`` resolves a registry-NAME ``workflow_id`` to a registered "
            "component). UNSET → the viewer shows the five built-ins only (graceful, "
            "no error) and only built-ins / absolute paths are dispatchable. This is "
            "independent of ``orchestrator_repo`` (the connected GitHub repo slug); "
            "it is the LOCAL filesystem root, not a GitHub identity."
        ),
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
    ALLOW_WEAKER_ISOLATION: bool = Field(
        default=False,
        description=(
            "Operator opt-in (OQ-6) to proceed when SANDBOX_RUNTIME=runsc but "
            "gVisor is unavailable on the host. Default False = fail-closed: run "
            "dispatch is blocked rather than silently downgraded to runc (G1)."
        ),
    )
    EGRESS_NETWORK: str = Field(
        default="dkmv-egress",
        description=(
            "Docker network the sandbox joins (engine --network passthrough, "
            "PRD §11.3). Declared 'internal: true' in docker-compose so it has NO "
            "default internet route — the network-level enforcement of the egress "
            "allowlist (INV-3). Empty disables the passthrough (no --network arg)."
        ),
    )
    SANDBOX_DNS: str | None = Field(
        default=None,
        description=(
            "DNS server the sandbox uses (engine --dns passthrough). On a custom "
            "internal network, point this at the egress proxy/resolver to sidestep "
            "gVisor's embedded-DNS (127.0.0.11) breakage. None = no --dns arg."
        ),
    )
    SECRET_FILE_MOUNT: bool = Field(
        default=True,
        description=(
            "Deliver the GitHub PAT to the sandbox as a read-only file mount at "
            "/run/secrets/github_token instead of an env var (INV-4 / G2). Default "
            "True keeps the PAT out of `docker inspect`. False = legacy env var."
        ),
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
    PER_STATE_CAPS: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Optional per-tick dispatch throttle per ``agent:*`` state, e.g. "
            "'agent:queued:2' caps the queued state to two launches per tick. "
            "Empty (the default) means no per-state throttle — the global "
            "concurrency cap + aggregate admission are the only bounds. Parsed "
            "from a 'label:cap,label:cap' env string."
        ),
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

    # --- Events retention (G9 — bound the append-only events table) ---
    EVENTS_RETENTION_DAYS: int = Field(
        default=0,
        ge=0,
        description=(
            "Retention horizon (days) for the append-only ``events`` table (G9). "
            "When > 0, the orchestrator tick prunes events of TERMINAL runs that "
            "have a ``run_totals`` completion snapshot AND finished more than this "
            "many days ago — spend/history survive the prune via the run_totals "
            "fast-path. An active run's events and a snapshot-less run's events are "
            "NEVER pruned. Default 0 = DISABLED (conservative: events grow unbounded "
            "but nothing is ever deleted until an operator opts in, e.g. 90). The "
            "DELETE is routed through the single serialized writer (INV-6)."
        ),
    )

    # --- Egress allowlist (INV-3) ---
    EGRESS_ALLOWLIST: str = Field(
        default="api.github.com,github.com,api.anthropic.com,api.openai.com",
        description=(
            "Comma-separated hosts the sandbox may reach (GitHub + model APIs). "
            "Default-on, network-enforced (NFR-SEC-1)."
        ),
    )

    @field_validator(
        "HOST_MEMORY_BUDGET",
        "DAILY_SPEND_CAP",
        "DKMV_PROJECT_ROOT",
        "SANDBOX_DNS",
        mode="before",
    )
    @classmethod
    def _empty_str_to_none(cls, value: object) -> object:
        """Coerce empty/whitespace-only env values to ``None`` for optional keys.

        ``docker compose`` passes unset optional keys as empty strings via the
        ``"${VAR:-}"`` default pattern (see ``docker-compose.yml``). Without this
        an empty ``DAILY_SPEND_CAP`` fails ``float`` parsing and the container
        crash-loops, so ``docker compose up`` never answers preflight (AC-0.1-5).
        Empty means "unset" for these optional fields.
        """
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("PER_STATE_CAPS", mode="before")
    @classmethod
    def _parse_per_state_caps(cls, value: object) -> object:
        """Parse the ``'label:cap,label:cap'`` env string into a ``{label: cap}`` dict.

        The env surface is a flat string (one var per the PRD §8.8 table), so an
        operator sets e.g. ``PER_STATE_CAPS=agent:queued:2``. The ``agent:`` prefix
        itself contains a colon, so the **last** colon splits the cap off the label
        (``agent:queued`` → ``2``). Empty / unset → an empty dict (no throttle). A
        dict passed directly (a test) is returned as-is; a malformed pair is skipped
        rather than crashing the container at startup.
        """
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return {}
            parsed: dict[str, int] = {}
            for pair in text.split(","):
                label, sep, cap = pair.strip().rpartition(":")
                if not sep or not label.strip() or not cap.strip().isdigit():
                    continue
                parsed[label.strip()] = int(cap.strip())
            return parsed
        return value

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


def default_timeout_minutes(agent: str) -> int:
    """The capability-aware fallback ``timeout_minutes`` for *agent* (ADR-P009).

    Returns the **strictly tighter** :data:`CODEX_DEFAULT_TIMEOUT_MINUTES` for a
    Codex (timeout-only) agent and :data:`CLAUDE_DEFAULT_TIMEOUT_MINUTES` for any
    capable agent (Claude). Applied at launch *only* when the operator pins no
    explicit ``timeout_minutes`` — it never overrides an explicit value (§8.10).
    Codex is the only agent whose ``supports_budget``/``supports_max_turns`` are
    both false, so timeout is its sole runtime guardrail; the tighter default is
    the §7.2-footnote-3 mitigation for a runaway, budget-less Codex run.
    """
    return (
        CODEX_DEFAULT_TIMEOUT_MINUTES
        if agent.strip().lower() == "codex"
        else CLAUDE_DEFAULT_TIMEOUT_MINUTES
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached settings instance.

    Cached so the env surface is parsed once. Tests that need a fresh parse
    call ``get_settings.cache_clear()``.
    """
    return Settings()
