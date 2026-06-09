"""``GET /repos/{repo}/board/aggregate`` — the board aggregate counters (PRD §5.3, FR-02-4).

The board's compact at-a-glance strip and the sidebar live-status chip read this
**poll-driven** endpoint (FR-NAV-2 "last synced", §8.3 "Board/chip use polling")
— there is **no** per-card SSE here (AC-20); only the single open run view holds
an SSE stream (Phase 2). One GET returns:

    {in_progress} in progress · {needs_you} needs you ·
    ${spent_today} spent today · {tokens_today} tokens

The counters come from the Phase-0 **spend projection** (segment-sum per
``(run_id, task_index)`` last-cumulative ``cost_usd`` — INV-7, never a naive SUM)
computed in :meth:`app.db.repository.Repository.board_aggregate`. The **Codex
caveat (FR-06-1a / INV-8)** is encoded in the split the repository applies:
``spent_today`` **excludes** $0-cost Codex runs from the spend figure while
``tokens_today`` still counts their tokens — a Claude + Codex pair yields
``spent = Claude-only``, ``tokens = both`` (AC-17).

Like every Phase-1 route this is behind the app-wide
:class:`~app.security.AccessControlMiddleware` (INV-1 — loopback ``Host`` + local
token + ``Origin``/CSRF); it declares **no** auth opt-out. It is a read-only
``GET`` (no CSRF body needed), so the poller can refresh it freely.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request

from app.db.repository import Repository

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.config import Settings

# No prefix here: the ``/api/v1`` version prefix is owned by the single parent
# router in :mod:`app.api`, which this router attaches to.
router = APIRouter(tags=["github"])

#: ``app.state`` attribute name — same seam as :mod:`app.api.issues` /
#: :mod:`app.api.agent_state` so the read shares one Repository when injected.
_REPO_ATTR = "repository"


def start_of_utc_day(now: datetime | None = None) -> str:
    """The UTC start-of-day ISO boundary for the "today" window (FR-02-4).

    "Spent today" / "tokens today" are bounded to runs ``started_at`` at or after
    **00:00 UTC of the current day**, re-evaluated on every poll (never cached) so
    the strip rolls over at midnight without a restart. UTC is used so the window
    matches the UTC ``started_at`` timestamps the engine bridge writes (and so two
    operators in different zones agree on the figure).
    """
    moment = now or datetime.now(UTC)
    start = moment.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.isoformat()


@asynccontextmanager
async def _repository(request: Request) -> AsyncIterator[Repository]:
    """Yield the platform :class:`Repository` for this request (INV-6 writer).

    Mirrors :func:`app.api.issues._repository`: reuse the lifespan-owned
    ``app.state.repository`` (slice 2.0 — the single per-process writer task) and
    do not close it; **as a test fallback only** (no lifespan) build + ``start()``
    one scoped to this request on the serving loop and ``close()`` it on exit.
    """
    injected = getattr(request.app.state, _REPO_ATTR, None)
    if injected is not None:
        assert isinstance(injected, Repository)
        yield injected
        return
    settings: Settings = request.app.state.settings
    repository = Repository(settings.DATABASE_URL)
    await repository.start()
    try:
        yield repository
    finally:
        await repository.close()


@router.get("/repos/{owner}/{name}/board/aggregate")
async def board_aggregate(owner: str, name: str, request: Request) -> dict[str, Any]:
    """Return the poll-driven board aggregate counters for a repo (FR-02-4, AC-17).

    Reads through the repository seam (NFR-PORT-1). ``spent_today`` excludes $0
    Codex runs (FR-06-1a / INV-8); ``tokens_today`` counts every run's tokens
    including Codex. The today-window is the UTC start-of-day boundary
    (:func:`start_of_utc_day`), re-evaluated each poll.
    """
    repo = f"{owner}/{name}"
    since_iso = start_of_utc_day()
    async with _repository(request) as repository:
        agg = await repository.board_aggregate(repo, since_iso=since_iso)
    return {
        "repo": repo,
        "in_progress": agg.in_progress,
        "needs_you": agg.needs_you,
        "spent_today": agg.spent_today,
        "tokens_today": agg.tokens_today,
    }
