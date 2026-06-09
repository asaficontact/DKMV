"""Retry-queue API — ``GET /retry-queue`` (slice 3.1 — F10 / §8.9, FR-06-3/6).

The retry-queue card (slice 3.2) reads this endpoint. It returns ``RetryEntry``
rows (PRD §6.1, ``data.jsx RETRY_QUEUE``)::

    { id, issue, attempt, dueIn, lastError }

— the runs that exhausted ≤3 retry attempts and are parked awaiting a manual
"Retry now" (``POST /runs/{id}/retry``). The **retry scheduler** that populates
this queue is slice 3.4; this slice ships the **endpoint + the wire shape** so
3.2 can render the card and 3.4 can fill it without a contract change. Until 3.4
lands, the queue is empty — the endpoint returns ``{ items: [], next_cursor:
null }`` (the cursor-pagination envelope, §8.9), never an error or a stub row.

Inherits the app access-control middleware (INV-1) + the §8.9 envelope. Nothing
here touches ``dkmv/``.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Request

from app.orchestrator.retry_deps import get_retry_scheduler

router = APIRouter(tags=["retry-queue"])


@router.get("/retry-queue")
async def get_retry_queue(request: Request) -> dict[str, Any]:
    """Return the ``RetryEntry`` rows in the retry queue (FR-06-3 / §8.9).

    Each row is ``{ id, issue, attempt, dueIn, lastError }`` (PRD §6.1), sourced
    from the slice-3.4 retry scheduler's **persisted** backoff/queue state (the
    runs in backoff + the runs parked after the ≤3 automatic attempts). ``dueIn`` is
    the seconds until the backoff ``due_at`` (re-evaluated each request, counting
    down). Returned in the §8.9 cursor envelope ``{ items, next_cursor }``; the
    whole queue fits one page on a solo machine so ``next_cursor`` is ``null``.
    """
    scheduler = get_retry_scheduler(request)
    entries = await scheduler.read_retry_queue()
    items: list[dict[str, Any]] = [asdict(entry) for entry in entries]
    return {"items": items, "next_cursor": None}
