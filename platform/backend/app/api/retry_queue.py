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

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(tags=["retry-queue"])


@router.get("/retry-queue")
async def get_retry_queue(request: Request) -> dict[str, Any]:
    """Return the ``RetryEntry`` rows in the retry queue (FR-06-3 / §8.9).

    Each row is ``{ id, issue, attempt, dueIn, lastError }`` (PRD §6.1). The
    retry scheduler that fills the queue is slice 3.4; until then this returns the
    empty cursor envelope ``{ items: [], next_cursor: null }`` (the shape ships
    here so 3.2 renders against the real contract and 3.4 only changes the data).
    """
    # Slice 3.4 replaces this with a read of the retry scheduler's persisted
    # backoff/queue state; the shape (RetryEntry rows + cursor envelope) is fixed
    # here so the 3.2 card and the 3.4 scheduler agree without a contract change.
    items: list[dict[str, Any]] = []
    return {"items": items, "next_cursor": None}
