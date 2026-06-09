"""Analytics stats API — ``GET /stats`` (slice 3.1 — F10 / §8.9, FR-06-1/1a/2).

The aggregate cards + spend chart + rate-limit health row read this one endpoint
(slice 3.2). It computes::

    { total_runs, success_rate, total_spend_usd, tokens, agent_hours,
      spend_series:[{date, usd}], rate_limits:{github, anthropic, openai} }

from the platform projections (``run_totals`` + active runs via the SQL spend
views, §6.5) — **never** the engine's O(N) directory-scan stats APIs (§6.5: this
file must reference no engine scan helper). The spend math lives in
:mod:`app.db.queries_history`; this module is the thin wire layer.

**Codex exclusion (FR-06-1a / INV-8 — binding).** ``total_spend_usd`` and
``spend_series`` **exclude** $0-cost Codex runs (Codex reports $0 from the engine
and supports no budget cap), while ``tokens`` and ``agent_hours`` count Codex
normally. The exclusion is implemented in the query layer (keyed on the run's
``agent`` column); see :mod:`app.db.queries_history`.

**Rate limits (FR-06-2).** ``rate_limits.github`` surfaces the Phase-1 GitHub
write-queue's :class:`~app.github.write_queue.RateLimitState` (the
``X-RateLimit-*`` primary headroom + the secondary-limit pause state) read-only.
``anthropic`` / ``openai`` carry the per-provider model-API accounting when it is
wired (a future model-call header tap); until then they report ``null`` headroom
so the UI renders "—" rather than a fabricated percentage.

Inherits the app access-control middleware (INV-1). Nothing here touches
``dkmv/``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.deps import get_repository, get_write_queue
from app.db.queries_history import compute_stats
from app.github.write_queue import RateLimitState

router = APIRouter(tags=["stats"])


@router.get("/stats")
async def read_stats(request: Request) -> dict[str, Any]:
    """Return the §8.9 ``GET /stats`` aggregate body (FR-06-1 / FR-06-1a / FR-06-2).

    Spend (``total_spend_usd`` + ``spend_series``) is the **Codex-excluded**
    segment-sum projection over ``run_totals`` + active runs (§6.5); tokens +
    agent-hours count every agent including Codex; success rate is
    ``completed/(completed+failed)``. The rate-limit health row reads the Phase-1
    write-queue accounting read-only.
    """
    async with get_repository(request) as repository:
        stats = await compute_stats(repository)

    write_queue = get_write_queue(request)
    rate_limits = _rate_limits(write_queue.rate_limit_state)

    return {
        "total_runs": stats.total_runs,
        "success_rate": stats.success_rate,
        "total_spend_usd": stats.total_spend_usd,
        "tokens": stats.tokens,
        "agent_hours": stats.agent_hours,
        "spend_series": stats.spend_series,
        "rate_limits": rate_limits,
    }


def _rate_limits(github_state: RateLimitState) -> dict[str, Any]:
    """Shape the FR-06-2 ``rate_limits`` block from the write-queue accounting.

    ``github`` carries the Phase-1 ``X-RateLimit-*`` primary headroom + the
    secondary-limit pause state (read-only). ``anthropic`` / ``openai`` are the
    per-provider model-API slots: until the model-call header tap is wired they
    report ``null`` usage so the UI renders "—" rather than a fabricated number
    (no spend/limit is silently invented).
    """
    return {
        "github": _github_rate_limit(github_state),
        "anthropic": _model_rate_limit(),
        "openai": _model_rate_limit(),
    }


def _github_rate_limit(state: RateLimitState) -> dict[str, Any]:
    """Project the write-queue's :class:`RateLimitState` into the wire shape.

    ``used_pct`` is the consumed fraction of the primary hourly budget
    (``1 - remaining/limit``), ``None`` when no header has been observed yet.
    ``secondary_limited`` / ``secondary_retry_after`` surface the 403-secondary
    pause state so the UI can show "rate limited · retrying in N s".
    """
    remaining = state.primary_remaining
    limit = state.primary_limit
    used_pct: float | None = None
    if remaining is not None and limit:
        used_pct = max(0.0, min(1.0, 1.0 - (remaining / limit)))
    return {
        "remaining": remaining,
        "limit": limit,
        "reset": state.primary_reset,
        "used_pct": used_pct,
        "secondary_limited": state.secondary_limited,
        "secondary_retry_after": state.secondary_retry_after,
    }


def _model_rate_limit() -> dict[str, Any]:
    """Placeholder model-provider rate-limit slot (no header tap wired yet).

    Reports ``null`` usage so the UI renders "—"; the per-provider
    ``X-RateLimit-*`` accounting is a future model-call header tap (FR-06-2).
    """
    return {
        "remaining": None,
        "limit": None,
        "reset": None,
        "used_pct": None,
        "secondary_limited": False,
        "secondary_retry_after": 0.0,
    }
