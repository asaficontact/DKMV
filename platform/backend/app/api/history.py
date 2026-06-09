"""History read API — ``GET /runs`` (filters + cursor) + ``GET /runs/{id}`` (§8.9).

Slice 3.1 **owns** the read half of the run API. Slice 2.1 shipped a baseline
``GET /runs`` / ``GET /runs/{id}`` in :mod:`app.api.runs`; 3.1 relocates those two
read endpoints here and enhances them (``GET /runs``: the FR-06-4 ``workflow`` /
``agent`` / ``status`` filters + cursor pagination; ``GET /runs/{id}``: the full
§8.9 detail). :mod:`app.api.runs` keeps ``POST /runs`` + the launch/stream/answer
wiring — the read routes live here only (no duplicate ``GET /runs`` path).

* ``GET /runs`` → paginated ``RunSummary`` rows (FR-06-4 columns) with filters
  ``?workflow=&agent=&status=`` and cursor pagination (``?limit<=100&cursor=`` →
  ``{ items, next_cursor }``, §8.9). Reads the platform ``runs`` read model via
  :mod:`app.db.queries_history` — **never** the engine ``list_runs`` directory
  scan (§6.5). Codex ``cost_usd`` is ``null`` ("—", FR-06-1a).
* ``GET /runs/{id}`` → the full §8.9 detail (``issue`` / ``stages`` / ``config`` /
  ``sandbox`` / ``artifacts`` / ``pr`` / ``error``); the read-only finished-run
  source for slice 3.2's run view. Unknown id → ``404 run_not_found`` (envelope).

Every endpoint inherits the app access-control middleware (INV-1 — loopback
``Host`` + local token + ``Origin``/CSRF) and the §8.9 error envelope. Nothing
here reaches into ``dkmv/`` — it reads through the :class:`Repository` seam only.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.deps import get_repository
from app.api.errors import run_not_found
from app.db.queries_history import list_runs_filtered
from app.runs.service import DEFAULT_MEMORY, build_run_detail, build_run_summaries

#: No prefix here: the ``/api/v1`` version prefix is owned by the single parent
#: router in :mod:`app.api`.
router = APIRouter(tags=["history"])

#: Cap on a ``GET /runs`` page (cursor pagination contract, §8.9).
_MAX_LIMIT = 100


@router.get("/runs")
async def list_runs(request: Request) -> dict[str, Any]:
    """Return a filtered, cursor-paginated ``GET /runs`` history page (§8.9 / FR-06-4).

    Filters ``?workflow=&agent=&status=`` (each narrows the result set; a blank
    value is a no-op) and ``?repo=`` scope; cursor pagination via
    ``?limit<=100&cursor=`` → ``{ items, next_cursor }`` where ``next_cursor`` is
    an opaque offset string (``null`` on the last page). Reads the ``runs`` read
    model via :mod:`app.db.queries_history` (never the engine ``list_runs``
    scan — §6.5); the page's costs are the segment-sum projection in **one** bulk
    spend query (Codex → ``null``, FR-06-1a / INV-7).
    """
    limit = _parse_limit(request)
    offset = _parse_offset(request)
    repo = request.query_params.get("repo")
    workflow = request.query_params.get("workflow")
    agent = request.query_params.get("agent")
    status = request.query_params.get("status")

    async with get_repository(request) as repository:
        # Over-fetch one row to detect a next page without a second COUNT query.
        rows = await list_runs_filtered(
            repository,
            repo=repo,
            workflow=workflow,
            agent=agent,
            status=status,
            limit=limit + 1,
            offset=offset,
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        # One bulk spend query for the whole page (not N per-row spend queries).
        items = await build_run_summaries(repository, page)

    next_cursor = str(offset + limit) if has_more else None
    return {"items": items, "next_cursor": next_cursor}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> dict[str, Any]:
    """Return the full §8.9 ``GET /runs/{id}`` detail (the read-only finished view).

    Carries ``issue`` / ``stages`` / the FR-04-5 ``config`` snapshot / ``sandbox`` /
    ``artifacts`` / the linked ``pr`` / ``error``, the segment-sum ``cost_usd``
    (``null`` for Codex — INV-8 / FR-06-1a), and token/turn meters. A
    ``404 run_not_found`` for an unknown platform UUID. All run endpoints address
    the platform UUID (§8.4).
    """
    settings = request.app.state.settings
    async with get_repository(request) as repository:
        row = await repository.get_run(run_id)
        if row is None:
            raise run_not_found(run_id)
        return await build_run_detail(
            repository,
            row,
            sandbox_image=settings.DKMV_IMAGE,
            default_memory=DEFAULT_MEMORY,
        )


def _parse_limit(request: Request) -> int:
    """Parse ``?limit`` (1..100; default 100) for the history page (§8.9)."""
    raw = request.query_params.get("limit")
    if raw is None:
        return _MAX_LIMIT
    try:
        value = int(raw)
    except ValueError:
        return _MAX_LIMIT
    return max(1, min(value, _MAX_LIMIT))


def _parse_offset(request: Request) -> int:
    """Parse the opaque ``?cursor`` (an integer offset) for the history page (§8.9)."""
    raw = request.query_params.get("cursor")
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0
