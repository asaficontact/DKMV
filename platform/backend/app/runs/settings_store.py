"""Persisted **run-default settings** over the ``settings`` KV table (FR-SET-1, §5.9).

The Settings screen (§5.9) exposes a small, typed set of *run defaults* and a *daily
spend alert* threshold that an operator can edit once and have applied to new runs
unless overridden per-launch. Those values live in the existing ``settings`` key/value
table (``app.db.schema.settings``) under a stable ``run_defaults::<field>`` namespace,
read/written through the :class:`~app.db.repository.Repository` ``get_setting`` /
``set_setting`` helpers (no new table, no schema migration).

This module owns:

* :class:`RunDefaults` — the typed, validated pydantic model the API round-trips.
  It carries ONLY non-secret run-shaping defaults (agent / model / memory /
  timeout / max_budget / max_turns / the daily spend-alert threshold). It NEVER
  carries a token or API key — secrets live in the encrypted :class:`SecretStore`,
  never in this KV namespace, so ``GET /settings`` can never leak one.
* :func:`load_run_defaults` — read the persisted overrides, falling back to the
  process :class:`~app.config.Settings` / engine defaults for any unset field, so a
  fresh install returns a fully-populated, truthful default view.
* :func:`save_run_defaults` — persist a (already-validated) model, one KV upsert
  per field, through the single writer task (INV-6).
* :func:`persisted_default_memory` — the **launch-path seam**: the persisted
  ``default_memory`` (or the built-in :data:`DEFAULT_MEMORY` when unset), consulted
  by ``POST /runs`` as the "config defaults" layer of the
  CLI/body > task YAML > config-defaults precedence. A clean, low-risk addition —
  it only changes the value used when a launch body omits ``memory`` (the explicit
  body value always still wins), and degrades to the prior constant when unset.

Nothing here reaches into ``dkmv/`` or logs a secret value.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import CLAUDE_DEFAULT_TIMEOUT_MINUTES as _CLAUDE_DEFAULT_TIMEOUT_MINUTES
from app.runs.launch import _DEFAULT_AGENT as _DEFAULT_AGENT
from app.runs.launch import _MEMORY_RE as _MEMORY_RE
from app.runs.launch import _TIMEOUT_MAX as _TIMEOUT_MAX
from app.runs.launch import _TIMEOUT_MIN as _TIMEOUT_MIN
from app.runs.service import DEFAULT_MEMORY

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.config import Settings
    from app.db.repository import Repository

#: KV namespace prefix for the persisted run defaults. Each field is one row under
#: ``run_defaults::<field>`` so a partial save (one field) is a single upsert and a
#: read of an unset field falls through to the config default.
_KEY_PREFIX = "run_defaults::"

#: The persisted, editable field names (the §5.9 "Defaults" + spend-alert form).
#: Secrets are intentionally absent — they are never round-tripped through Settings.
_FIELDS = (
    "default_agent",
    "default_model",
    "default_memory",
    "default_timeout_minutes",
    "default_max_budget_usd",
    "default_max_turns",
    "daily_spend_alert_usd",
)

#: The engine-default model surfaced when no override is persisted (DKMVConfig
#: default — §6.1). Kept as a string constant so the GET view is fully populated.
_DEFAULT_MODEL = "claude-sonnet-4-6"

#: The prototype's default daily spend-alert threshold ($25.00 / day — §5.9).
_DEFAULT_DAILY_SPEND_ALERT_USD = 25.0


def _key(field: str) -> str:
    """The ``settings`` KV key for a run-default field."""
    return f"{_KEY_PREFIX}{field}"


class RunDefaults(BaseModel):
    """Typed, validated run-default settings (the ``GET/PUT /settings`` body).

    Every field is required in the model but the API/loader always supplies a
    value (a persisted override or the config/engine default), so a client never
    sees a half-populated view. Validation mirrors the launch-path §8.10 bounds so
    a value that round-trips through Settings is one a launch would also accept.
    """

    model_config = ConfigDict(extra="forbid")

    default_agent: str = Field(
        description="Default agent for new runs (claude | codex).",
    )
    default_model: str = Field(
        min_length=1,
        description="Default model id for new runs.",
    )
    default_memory: str = Field(
        description="Default container memory limit (e.g. '8g').",
    )
    default_timeout_minutes: int = Field(
        ge=_TIMEOUT_MIN,
        le=_TIMEOUT_MAX,
        description="Default run timeout in minutes (within §8.10 bounds).",
    )
    default_max_budget_usd: float | None = Field(
        default=None,
        gt=0,
        description="Default USD budget cap for budget-capable agents; null = none.",
    )
    default_max_turns: int | None = Field(
        default=None,
        gt=0,
        description="Default turn cap for turn-capable agents; null = none.",
    )
    daily_spend_alert_usd: float = Field(
        gt=0,
        description="Daily spend-alert threshold in USD (the §5.9 '$25.00 / day').",
    )

    @field_validator("default_agent")
    @classmethod
    def _validate_agent(cls, value: str) -> str:
        """Restrict the default agent to a known adapter name (claude | codex)."""
        agent = value.strip().lower()
        if agent not in {"claude", "codex"}:
            raise ValueError("default_agent must be 'claude' or 'codex'")
        return agent

    @field_validator("default_memory")
    @classmethod
    def _validate_memory(cls, value: str) -> str:
        """Match the launch-path memory shape (a positive int + g/m suffix)."""
        mem = value.strip()
        if not _MEMORY_RE.match(mem):
            raise ValueError("default_memory must look like '8g' or '512m'")
        return mem.lower()


def default_run_defaults(settings: Settings) -> RunDefaults:
    """The fully-populated default view (no persisted overrides applied).

    Sources each field from the process :class:`~app.config.Settings` / engine
    defaults so a fresh install returns a truthful, complete default model.
    """
    return RunDefaults(
        default_agent=_DEFAULT_AGENT,
        default_model=_DEFAULT_MODEL,
        default_memory=DEFAULT_MEMORY,
        default_timeout_minutes=_CLAUDE_DEFAULT_TIMEOUT_MINUTES,
        default_max_budget_usd=None,
        default_max_turns=None,
        daily_spend_alert_usd=settings.DAILY_SPEND_CAP or _DEFAULT_DAILY_SPEND_ALERT_USD,
    )


async def load_run_defaults(repository: Repository, settings: Settings) -> RunDefaults:
    """Read the persisted run defaults, filling unset fields from config defaults.

    Each field is read from its ``run_defaults::<field>`` KV row; a missing row
    falls back to the config/engine default (:func:`default_run_defaults`). The
    persisted strings are coerced back to the model's types, so an out-of-range or
    corrupt stored value still validates against the §8.10 bounds on read-back (a
    bad row raises, surfaced as a 500 by the route — it cannot have been written by
    a validating PUT).
    """
    base = default_run_defaults(settings)
    raw: dict[str, str] = {}
    for field in _FIELDS:
        stored = await repository.get_setting(_key(field))
        if stored is not None:
            raw[field] = stored

    return RunDefaults(
        default_agent=raw.get("default_agent", base.default_agent),
        default_model=raw.get("default_model", base.default_model),
        default_memory=raw.get("default_memory", base.default_memory),
        default_timeout_minutes=int(raw["default_timeout_minutes"])
        if "default_timeout_minutes" in raw
        else base.default_timeout_minutes,
        default_max_budget_usd=_opt_float(raw.get("default_max_budget_usd"))
        if "default_max_budget_usd" in raw
        else base.default_max_budget_usd,
        default_max_turns=_opt_int(raw.get("default_max_turns"))
        if "default_max_turns" in raw
        else base.default_max_turns,
        daily_spend_alert_usd=float(raw["daily_spend_alert_usd"])
        if "daily_spend_alert_usd" in raw
        else base.daily_spend_alert_usd,
    )


async def save_run_defaults(repository: Repository, defaults: RunDefaults) -> None:
    """Persist a validated :class:`RunDefaults`, one KV upsert per field (INV-6).

    The model is assumed already validated (the route constructs it from the
    request body, raising the §8.9 ``validation_error`` envelope on a bad value).
    Optional ``None`` fields persist the literal string ``"none"`` so a previously
    set value can be cleared and round-trips back to ``None`` on read.
    """
    await repository.set_setting(_key("default_agent"), defaults.default_agent)
    await repository.set_setting(_key("default_model"), defaults.default_model)
    await repository.set_setting(_key("default_memory"), defaults.default_memory)
    await repository.set_setting(
        _key("default_timeout_minutes"), str(defaults.default_timeout_minutes)
    )
    await repository.set_setting(
        _key("default_max_budget_usd"), _opt_str(defaults.default_max_budget_usd)
    )
    await repository.set_setting(_key("default_max_turns"), _opt_str(defaults.default_max_turns))
    await repository.set_setting(_key("daily_spend_alert_usd"), str(defaults.daily_spend_alert_usd))


async def persisted_default_memory(repository: Repository) -> str | None:
    """The persisted ``default_memory`` override, or ``None`` when unset.

    The launch-path seam: ``POST /runs`` consults this as the "config defaults"
    layer of the precedence (the body's explicit ``memory`` always wins). Returns
    ``None`` when no override is persisted so the caller falls through to the
    built-in :data:`DEFAULT_MEMORY` constant unchanged (a no-op for a fresh
    install — low-risk).
    """
    stored = await repository.get_setting(_key("default_memory"))
    if stored is None:
        return None
    mem = stored.strip()
    # A corrupt/unparsable stored value must not poison the launch path: only
    # return it when it matches the bounds shape, else degrade to the default.
    return mem.lower() if _MEMORY_RE.match(mem) else None


#: The sentinel persisted for a cleared optional field (round-trips back to None).
_NONE_SENTINEL = "none"


def _opt_str(value: float | int | None) -> str:
    """Render an optional numeric as a KV string (``None`` → the sentinel)."""
    return _NONE_SENTINEL if value is None else str(value)


def _opt_float(value: str | None) -> float | None:
    """Parse an optional KV string back to ``float | None`` (sentinel → None)."""
    if value is None or value.strip().lower() == _NONE_SENTINEL:
        return None
    return float(value)


def _opt_int(value: str | None) -> int | None:
    """Parse an optional KV string back to ``int | None`` (sentinel → None)."""
    if value is None or value.strip().lower() == _NONE_SENTINEL:
        return None
    return int(value)
