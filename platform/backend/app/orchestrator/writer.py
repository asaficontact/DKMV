"""Off-loop, batched event-append buffer for the orchestrator (AC-4 / INV-6).

The orchestrator's correctness depends on the **single event loop never wedging**
(:mod:`app.orchestrator.loop_metrics`). The Phase-0 :class:`app.db.writer.Writer`
already makes every SQLite write **off-loop** (it owns one ``aiosqlite`` connection
on a dedicated serialized task and runs each unit inside ``BEGIN IMMEDIATE`` — INV-6)
and :meth:`app.db.repository.Repository.append_events` already coalesces a *list* of
events into **one** multi-row ``INSERT … RETURNING`` round-trip. So no synchronous
``sqlite3`` write ever runs on the loop thread.

What this module adds (AC-4) is **cross-call batching**: under a burst of events from
several concurrent runs, the loop would otherwise ``await`` one ``append_events`` per
small flush, each a writer round-trip. This buffer **coalesces** queued events and
flushes them as **one** batch — fewer writer round-trips under load, so a slow write
can't pile up per-event back-pressure on the loop. It is a thin façade over the SAME
single writer (INV-6 preserved — there is still exactly one writer, one
``BEGIN IMMEDIATE`` per flush, the same ``ON CONFLICT`` idempotency on the run-claim
path). It introduces **no** second write connection and none of the row-lock
escape hatches SQLite lacks (INV-5 — the idempotency claim is the UNIQUE-key
``ON CONFLICT`` path, never a row-lock skip).

The flush is **off-loop** (it ``await``\\s the writer's ``aiosqlite`` job, never a
blocking ``sqlite3`` call on the loop). The event-append SQL is append-only — there
is no UPDATE/DELETE on ``events`` — so coalescing is safe (ordering within the batch
is preserved by the multi-row INSERT, and the returned ids stay the per-row replay
cursors). Nothing here touches ``dkmv/`` or shells the CLI.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.db.repository import EventRecord, Repository

_log = logging.getLogger(__name__)

#: Flush when this many events have buffered (a size trigger so a burst flushes
#: promptly without unbounded growth). One multi-row INSERT either way.
DEFAULT_MAX_BATCH = 256


class BatchedEventWriter:
    """Coalesces event appends into one off-loop batched write (AC-4 / INV-6).

    Callers :meth:`enqueue` events (cheap, non-blocking, on the loop) and either let
    them coalesce until :meth:`flush` (size-triggered or explicit) or ``await``
    :meth:`append_now` for a synchronous-to-the-caller flush of a specific batch.
    Every flush funnels through the SAME single-writer
    :meth:`Repository.append_events` (off-loop ``aiosqlite``, ``BEGIN IMMEDIATE`` —
    INV-6 preserved); no second writer, no row-lock escape hatch (INV-5).

    Args:
        repository: The lifespan-owned single-writer :class:`Repository`.
        max_batch: Flush automatically once the buffer reaches this many events.
    """

    def __init__(self, repository: Repository, *, max_batch: int = DEFAULT_MAX_BATCH) -> None:
        self._repository = repository
        self._max_batch = max(1, max_batch)
        self._buffer: list[EventRecord] = []
        #: Serializes concurrent flushes so two coroutines cannot each drain a
        #: partial buffer and interleave their writer submissions out of order.
        self._lock = asyncio.Lock()

    @property
    def pending(self) -> int:
        """How many events are buffered awaiting the next flush."""
        return len(self._buffer)

    def enqueue(self, record: EventRecord) -> None:
        """Buffer one event for the next batched flush (cheap, on the loop).

        Non-blocking: appends to the in-memory buffer only. The caller drives the
        actual write via :meth:`flush` (e.g. once per tick, or when
        :attr:`pending` ≥ ``max_batch``) so a burst of events from several runs
        coalesces into one off-loop multi-row INSERT rather than one round-trip each.
        """
        self._buffer.append(record)

    async def flush(self) -> list[int]:
        """Drain the buffer as ONE off-loop batched append (AC-4); return event ids.

        Routes the whole buffered batch through :meth:`Repository.append_events` —
        a single multi-row ``INSERT … RETURNING`` on the single writer's off-loop
        ``aiosqlite`` connection (INV-6: one writer, one ``BEGIN IMMEDIATE``). The
        returned ids are the per-row SSE replay cursors. A no-op (returns ``[]``) when
        the buffer is empty. Flushes are serialized by an :class:`asyncio.Lock` so
        concurrent flushers cannot interleave partial batches.
        """
        async with self._lock:
            if not self._buffer:
                return []
            batch = self._buffer
            self._buffer = []
            return await self._repository.append_events(batch)

    async def append_now(self, records: list[EventRecord]) -> list[int]:
        """Append a specific batch immediately as ONE off-loop write (AC-4).

        Bypasses the coalescing buffer for a caller that already has its batch in
        hand and wants it durable now (e.g. the pause bridge's spine events). Still
        the SAME single writer / one ``BEGIN IMMEDIATE`` per call — never a blocking
        ``sqlite3`` write on the loop thread.
        """
        if not records:
            return []
        return await self._repository.append_events(records)

    async def maybe_flush(self) -> list[int]:
        """Flush iff the buffer has reached ``max_batch`` (the size trigger).

        Called after :meth:`enqueue` so a burst flushes promptly without the buffer
        growing unbounded, while a trickle waits for the explicit per-tick
        :meth:`flush`. Returns the flushed ids (or ``[]`` when below the threshold).
        """
        if len(self._buffer) >= self._max_batch:
            return await self.flush()
        return []


__all__ = ["DEFAULT_MAX_BATCH", "BatchedEventWriter"]
