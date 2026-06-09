"""Per-run event pump — persist (events) + project (run_stages) + fan out (§8.3).

Exactly **one** pump task runs per live run. It is the seam between the engine's
event stream and both durable replay and live SSE:

1. **Drain** the run's inbound queue (fed by :class:`~app.sse.observer_bridge.PlatformEventObserver`
   via ``call_soon_threadsafe`` — INV-12), batching whatever is ready.
2. **Persist** the batch to the **append-only** ``events`` table THROUGH the
   slice-2.0 single-writer :class:`~app.db.repository.Repository`
   (:meth:`Repository.append_events`) — never raw SQL, so the redact-before-persist
   guard (INV-4) and the single-writer contract (INV-6) hold. The returned
   ``events.id`` per row is the monotonic **SSE cursor** (``Last-Event-ID``).
3. **Project** ``run_stages`` from lifecycle frames (a task starting/finishing
   updates the mutable stepper read model) — also through the repository.
4. **Fan out** one :class:`StreamFrame` per persisted event to every SSE
   subscriber through the run's :class:`~app.sse.observer_bridge.RunStreamHub`.

The SSE message body carries the **outer** ``RuntimeEvent`` (``sequence,
timestamp, run_id, task_name, task_index, event_type, data{}, content, cost_usd,
turns`` — §6.4); each message ``id`` is the ``events.id`` assigned at persist
time, so a reconnecting client's ``Last-Event-ID`` lines up exactly with the
durable backlog (§8.3 replay). Batch-appending keeps N events at one writer
round-trip (PERF) while preserving per-row cursors.

Nothing here writes raw SQL or reaches ``dkmv/`` beyond the ``RuntimeEvent`` type.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any

from dkmv.runtime import RuntimeEvent

from app.db.repository import EventRecord, Repository
from app.sse.observer_bridge import RunStreamHub

#: Max events appended in one writer round-trip. Bounds the batch so a burst
#: doesn't build an unboundedly large single INSERT while still amortizing the
#: per-event writer hop (PERF).
MAX_BATCH = 256

#: Idle wait when the inbound queue is empty — the pump blocks on the first
#: event (no busy-poll), then opportunistically drains whatever else is ready.
_DRAIN_POLL_S = 0.05

#: Outer-``RuntimeEvent`` field names the SSE body carries verbatim (§6.4). The
#: inner agent line is ``data{}``; the Raw toggle (slice 2.4) reads that dict.
_BODY_FIELDS: tuple[str, ...] = (
    "sequence",
    "timestamp",
    "run_id",
    "task_name",
    "task_index",
    "step_instance",
    "event_type",
    "data",
    "content",
    "cost_usd",
    "turns",
)

#: ``event_type`` values that signal a stage completed (final segment cost). The
#: pump marks the stage ``done`` and records its final cost/turns (INV-7: these
#: are meter-critical). ``task_failed`` marks ``failed``.
_STAGE_DONE_TYPES: frozenset[str] = frozenset({"task_completed"})
_STAGE_FAILED_TYPES: frozenset[str] = frozenset({"task_failed"})
_STAGE_START_TYPES: frozenset[str] = frozenset({"task_started"})


@dataclass(frozen=True, slots=True)
class StreamFrame:
    """One persisted event ready for SSE fan-out: the cursor id + the body.

    ``event_id`` is the monotonic ``events.id`` (the SSE message ``id`` and the
    ``Last-Event-ID`` cursor). ``event_type`` is duplicated out of the body so the
    subscriber slow-consumer policy (coalesce meter, keep spine) can branch
    without re-parsing ``body``. ``body`` is the outer :class:`RuntimeEvent`
    projected to the §6.4 wire shape; it is the **redacted** view (the persisted
    payload went through the repository redactor — INV-4 — and ``data`` mirrors
    it).
    """

    event_id: int
    event_type: str
    body: dict[str, Any]


def event_to_record(event: RuntimeEvent) -> EventRecord:
    """Project an engine :class:`RuntimeEvent` into a persistable :class:`EventRecord`.

    Materializes ``task_index`` / ``cost_usd`` out of the event so the segment-sum
    spend projection (INV-7) can dedup last-cumulative cost per ``(run_id,
    task_index)`` without re-parsing the payload. ``payload`` is the **inner**
    agent line (``event.data``) — the durable raw stream the Raw toggle replays;
    it is redacted by the repository before it touches the ``events`` table
    (INV-4). ``task_index`` of ``-1`` (the engine's "no task context" sentinel)
    is stored as ``NULL`` so it never groups with a real task 0.
    """
    raw_idx = event.task_index
    task_index = raw_idx if raw_idx is not None and raw_idx >= 0 else None
    return EventRecord(
        run_id=event.run_id,
        sequence=event.sequence,
        event_type=event.event_type,
        payload=dict(event.data),
        task_index=task_index,
        cost_usd=event.cost_usd if event.cost_usd else None,
        agent=None,
        ts=event.timestamp.isoformat(),
    )


def event_to_body(event: RuntimeEvent) -> dict[str, Any]:
    """Project the **outer** :class:`RuntimeEvent` to the §6.4 SSE wire shape.

    Carries exactly :data:`_BODY_FIELDS`; ``timestamp`` is ISO-8601. ``data`` is
    the inner agent dict (what the Raw toggle renders). The meters (slice 2.4)
    read the outer ``cost_usd`` / ``turns``; the segment-sum across tasks is
    computed from the persisted ``events``, never from a single body.
    """
    body: dict[str, Any] = {}
    for field in _BODY_FIELDS:
        value = getattr(event, field)
        if field == "timestamp":
            body[field] = value.isoformat()
        else:
            body[field] = value
    return body


class EventPump:
    """The single per-run pump task: drain → persist → project → fan out.

    Owns the run's :class:`RunStreamHub` and a shared :class:`Repository`. Start
    it with :meth:`run` (awaited as an ``asyncio.Task`` by the launch path / a
    test). It exits when the run signals completion (``hub.closed`` set *and* the
    inbound queue drained), persisting any trailing events first so replay is
    complete.
    """

    def __init__(self, *, repository: Repository, hub: RunStreamHub) -> None:
        self._repository = repository
        self._hub = hub
        #: Per-task last-known stage name, so a ``task_completed`` that omits the
        #: name can still address the right ``run_stages`` row.
        self._stage_names: dict[int, str] = {}

    async def run(self) -> None:
        """Drain-persist-fan-out until the run is closed and the queue is empty.

        Blocks on the first event (no busy-poll), then opportunistically batches
        everything currently ready (up to :data:`MAX_BATCH`) into one
        :meth:`Repository.append_events` round-trip. Continues until the hub is
        marked closed AND no events remain. Always flushes a trailing batch so a
        late ``task_completed`` (meter-critical — INV-7) is persisted + replayable.
        """
        queue = self._hub.queue
        try:
            while True:
                batch = await self._next_batch(queue)
                if batch:
                    await self._persist_and_fan_out(batch)
                if self._hub.closed.is_set() and queue.empty():
                    # Final drain: anything that arrived between the close signal
                    # and now is persisted before we exit.
                    tail = self._drain_ready(queue)
                    if tail:
                        await self._persist_and_fan_out(tail)
                    return
        finally:
            self._hub.mark_closed()

    async def _next_batch(self, queue: asyncio.Queue[RuntimeEvent]) -> list[RuntimeEvent]:
        """Await ≥1 event (or a short tick if closed), then drain what's ready."""
        try:
            first = await asyncio.wait_for(queue.get(), timeout=_DRAIN_POLL_S)
        except TimeoutError:
            return []
        batch = [first]
        batch.extend(self._drain_ready(queue, limit=MAX_BATCH - 1))
        return batch

    @staticmethod
    def _drain_ready(
        queue: asyncio.Queue[RuntimeEvent], *, limit: int = MAX_BATCH
    ) -> list[RuntimeEvent]:
        """Pop up to ``limit`` immediately-available events (no awaiting)."""
        out: list[RuntimeEvent] = []
        while len(out) < limit:
            try:
                out.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return out

    async def _persist_and_fan_out(self, batch: list[RuntimeEvent]) -> None:
        """Append the batch (one writer hop), project stages, then fan out frames.

        Persisting **before** publishing is what makes ``Last-Event-ID`` replay
        exact: the SSE message ``id`` IS the assigned ``events.id``, so a client's
        cursor always matches a durable row (no live id the backlog lacks). The
        whole batch is one :meth:`Repository.append_events` round-trip through the
        single writer (INV-6) and the redactor (INV-4).
        """
        records = [event_to_record(e) for e in batch]
        ids = await self._repository.append_events(records)
        # Project run_stages from lifecycle frames (mutable stepper read model).
        for event in batch:
            await self._project_stage(event)
        # Fan out: each persisted event becomes one frame keyed by its events.id.
        for event, event_id in zip(batch, ids, strict=True):
            frame = StreamFrame(
                event_id=event_id,
                event_type=event.event_type,
                body=event_to_body(event),
            )
            self._hub.publish(frame)

    async def _project_stage(self, event: RuntimeEvent) -> None:
        """Update the ``run_stages`` read model from a lifecycle frame.

        A ``task_started`` upserts the stage ``running``; ``task_completed`` marks
        it ``done`` with its final cumulative cost/turns (the segment's final —
        INV-7); ``task_failed`` marks it ``failed``. Non-lifecycle frames (stream/
        assistant/result) don't move the stepper. The stage index is the engine's
        ``task_index``; a frame without a real task context (``-1``) is ignored.
        """
        idx = event.task_index
        if idx is None or idx < 0:
            return
        etype = event.event_type
        if etype in _STAGE_START_TYPES:
            name = event.task_name or self._stage_names.get(idx, "")
            self._stage_names[idx] = name
            await self._repository.upsert_stage(event.run_id, idx, name, status="running")
        elif etype in _STAGE_DONE_TYPES:
            name = event.task_name or self._stage_names.get(idx, "")
            await self._repository.upsert_stage(
                event.run_id,
                idx,
                name,
                status="done",
                cost_usd=event.cost_usd or None,
                turns=event.turns,
            )
        elif etype in _STAGE_FAILED_TYPES:
            name = event.task_name or self._stage_names.get(idx, "")
            await self._repository.upsert_stage(
                event.run_id,
                idx,
                name,
                status="failed",
                cost_usd=event.cost_usd or None,
                turns=event.turns,
            )


async def drain_pump(task: asyncio.Task[None]) -> None:
    """Await a pump task to completion, swallowing cancellation (shutdown helper)."""
    with contextlib.suppress(asyncio.CancelledError):
        await task
