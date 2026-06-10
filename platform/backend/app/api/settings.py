"""``GET /api/v1/settings`` + ``PUT /api/v1/settings`` — run defaults (FR-SET-1, §5.9).

The Settings screen (§5.9) lets a solo operator edit a small set of **run defaults**
(default agent / model / memory / timeout / budget / turns) and a **daily spend-alert
threshold** ($25.00 / day in the prototype), persisted so they apply to new runs
unless overridden per-launch (the CLI/body > task YAML > config-defaults precedence).

* ``GET /settings`` → the current :class:`~app.runs.settings_store.RunDefaults` view,
  filling any unset field from the process :class:`~app.config.Settings` / engine
  defaults. The view carries **only non-secret** run-shaping values — never a token
  or API key (those live in the encrypted :class:`SecretStore`, never in the KV
  namespace this reads), so a GET can never leak a credential.
* ``PUT /settings`` → validate the body against the §8.10 launch bounds (a bad value
  raises the §8.9 ``validation_error`` envelope) and persist it, returning the new
  view (a read-back round-trip).

Both routes attach to the single ``/api/v1`` parent router (``app.api``), so they
inherit the loopback-bind + local-token + Host/Origin + CSRF access-control
middleware (INV-1) — a state-changing ``PUT`` additionally clears the JSON-only
CSRF gate. Nothing here reaches into ``dkmv/`` or logs a secret value.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api.deps import get_repository
from app.api.errors import validation_error
from app.runs.settings_store import (
    RunDefaults,
    load_run_defaults,
    save_run_defaults,
)

# No prefix here: the ``/api/v1`` version prefix is owned by the single parent
# router in :mod:`app.api`, which this router attaches to.
router = APIRouter(tags=["settings"])


class RunDefaultsUpdate(BaseModel):
    """The ``PUT /settings`` request body (all fields optional → partial update).

    A partial update is allowed: a field omitted from the body keeps its currently
    persisted (or default) value; a field present replaces it. The merged result is
    re-validated through :class:`RunDefaults`, so a bad value (out-of-bounds timeout,
    a non-positive budget, a malformed memory string) is a §8.9 ``validation_error``.
    ``extra='forbid'`` rejects an unknown key (e.g. a smuggled ``github_token``) — a
    secret can never enter this surface.
    """

    model_config = ConfigDict(extra="forbid")

    default_agent: str | None = Field(default=None)
    default_model: str | None = Field(default=None)
    default_memory: str | None = Field(default=None)
    default_timeout_minutes: int | None = Field(default=None)
    default_max_budget_usd: float | None = Field(default=None)
    default_max_turns: int | None = Field(default=None)
    daily_spend_alert_usd: float | None = Field(default=None)


@router.get("/settings")
async def get_settings(request: Request) -> dict[str, Any]:
    """Return the current run defaults (FR-SET-1).

    Reads the persisted ``run_defaults::*`` KV overrides, falling back to the
    process :class:`~app.config.Settings` / engine defaults for any unset field, so
    the view is always fully populated. Carries no secret (INV-1 / §8.6).
    """
    settings = request.app.state.settings
    async with get_repository(request) as repository:
        defaults = await load_run_defaults(repository, settings)
    return defaults.model_dump()


@router.put("/settings")
async def put_settings(request: Request, body: RunDefaultsUpdate) -> dict[str, Any]:
    """Validate + persist the run defaults, returning the new view (FR-SET-1).

    Merges the partial body over the currently persisted view, re-validates the
    merged model against the §8.10 launch bounds (a bad value → §8.9
    ``validation_error``), persists it (one KV upsert per field, INV-6), and returns
    the read-back. ``PUT`` is a state-changing method, so it passes through the CSRF
    gate (JSON-only, INV-1).
    """
    settings = request.app.state.settings
    async with get_repository(request) as repository:
        current = await load_run_defaults(repository, settings)

        # Merge the partial update over the current view: only fields explicitly set
        # in the request body override; everything else keeps its current value. The
        # boolean is "field present in the request payload" (model_fields_set) so an
        # explicit ``null`` (clear an optional) is distinguished from "omitted".
        update = body.model_dump(exclude_unset=True)
        merged = {**current.model_dump(), **update}
        try:
            new_defaults = RunDefaults.model_validate(merged)
        except ValidationError as exc:
            raise validation_error(
                "Invalid settings value",
                details={"fields": _validation_fields(exc)},
            ) from exc

        await save_run_defaults(repository, new_defaults)
    return new_defaults.model_dump()


def _validation_fields(exc: ValidationError) -> list[dict[str, Any]]:
    """Reduce a :class:`ValidationError` to JSON-safe ``loc/msg/type`` entries.

    Mirrors the framework validation-error envelope (``app.api.errors``) so a
    client maps a Settings-form error back to its field the same way it does a
    launch-body error.
    """
    out: list[dict[str, Any]] = []
    for err in exc.errors():
        out.append(
            {
                "loc": list(err.get("loc", [])),
                "msg": str(err.get("msg", "")),
                "type": str(err.get("type", "")),
            }
        )
    return out
