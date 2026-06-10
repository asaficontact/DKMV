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
    projected to the §6.4 wire shape.

    On redaction (INV-4): the **durable** persisted payload and therefore the
    **replay** view (reconstructed from ``events`` by :func:`app.sse.replay.row_to_frame`)
    are redacted — the repository scrubs every payload before it touches the
    append-only ``events`` table, and the replay path reads those scrubbed rows
    back. The **live** fan-out frame built here carries the engine event body as
    emitted; it is the authenticated *operator's* own real-time view of their run
    (the live SSE stream is gated by the INV-1 middleware + the INV-2 SSE cookie),
    not a third-party sink — and the same event's durable copy in ``events`` (the
    only thing that persists / replays) is redacted.
    """

    event_id: int
    event_type: str
    body: dict[str, Any]


def event_to_record(event: RuntimeEvent, *, run_id: str | None = None) -> EventRecord:
    """Project an engine :class:`RuntimeEvent` into a persistable :class:`EventRecord`.

    ``run_id`` overrides the persisted ``events.run_id`` with the **platform UUID**
    (the hub's id) — binding: the platform addresses every run by its UUID, but the
    engine stamps ``event.run_id`` with its OWN ``YYMMDD-HHMM`` id once it surfaces.
    Persisting under the platform UUID is what makes ``read_events_after`` /
    ``Last-Event-ID`` replay / the segment-sum spend (all keyed by the platform id)
    find the run's events; the engine id is preserved inside the redacted
    ``payload`` (``event.data``) for the ``engine_run_id`` back-fill. When ``run_id``
    is ``None`` the event's own id is used (a direct, pre-wired test).

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
        run_id=run_id or event.run_id,
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
        #: G3 — set once the engine id has been **persisted** to the DB so the
        #: early-persist write fires exactly once (the hub only captures it once,
        #: but guard the write too so a re-drain can never re-issue it).
        self._engine_run_id_persisted = False

    async def run(self) -> None:
        """Drain-persist-fan-out until the run is closed and the queue is empty.

        **Sleeps until an event arrives or the hub closes — no busy-poll.** The
        idle wait is a ``FIRST_COMPLETED`` race of ``queue.get()`` against
        ``hub.closed`` (the same pattern :mod:`app.sse.replay` uses), so an idle
        or paused run (a pause can hold for up to the 60-min HITL timeout) costs
        zero CPU — the pump blocks on the event/close future instead of waking 20×
        a second. When an event arrives it opportunistically batches everything
        currently ready (up to :data:`MAX_BATCH`) into one
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
        """Sleep until ≥1 event arrives (or the hub closes), then drain what's ready.

        No polling: races ``queue.get()`` against ``hub.closed.wait()`` with
        ``FIRST_COMPLETED`` so the pump idles on a future and wakes only on a real
        event or the close signal. If the close fires first (and no event raced in)
        returns an empty batch — the caller's close-and-drained check then exits.
        """
        first = await self._await_next_event(queue)
        if first is None:
            return []
        batch = [first]
        batch.extend(self._drain_ready(queue, limit=MAX_BATCH - 1))
        return batch

    async def _await_next_event(self, queue: asyncio.Queue[RuntimeEvent]) -> RuntimeEvent | None:
        """Await the next inbound event, or ``None`` if the hub closes while waiting.

        The non-polling idle wait (FIX-4): a ``FIRST_COMPLETED`` race between the
        queue ``get`` and the hub's ``closed`` event. If ``get`` wins, return the
        event; if ``closed`` wins (and ``get`` didn't also complete), cancel the
        pending ``get`` and return ``None``. A frame that arrived on the queue in
        the same wakeup as ``closed`` is still returned (``get`` is checked first),
        so the close path never drops a buffered final event.
        """
        get_task = asyncio.ensure_future(queue.get())
        closed_task = asyncio.ensure_future(self._hub.closed.wait())
        try:
            await asyncio.wait({get_task, closed_task}, return_when=asyncio.FIRST_COMPLETED)
            if get_task.done():
                return get_task.result()
            return None
        finally:
            for task in (get_task, closed_task):
                if not task.done():
                    task.cancel()

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

        Every row is persisted under the **platform UUID** (``hub.run_id``), not the
        engine's ``event.run_id`` — the platform addresses each run by its UUID, so
        replay / spend / stage reads (all keyed by it) must find these rows. The
        engine id is captured off the first stamped frame for the completion
        ``engine_run_id`` back-fill.
        """
        platform_run_id = self._hub.run_id
        for event in batch:
            self._hub.note_engine_run_id(event.run_id)
        # G3 (orphan-recovery window): persist ``runs.engine_run_id`` the MOMENT the
        # engine id is first captured off the stream — NOT only at completion. The
        # id is the ONLY handle boot recovery's reaper has to ``docker kill`` an
        # orphaned, money-spending container after a mid-run crash. Writing it at
        # completion left it ``NULL`` for the whole run, so a SIGKILL/OOM/power-loss
        # mid-run left a live container the reaper returned ``False`` on. We now
        # shrink that window to "before the first stamped engine frame" (the residual
        # window documented in ``recovery.py``). Idempotent: fires once per run.
        await self._persist_engine_run_id_early()
        records = [event_to_record(e, run_id=platform_run_id) for e in batch]
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

    async def _persist_engine_run_id_early(self) -> None:
        """Persist ``runs.engine_run_id`` on the FIRST stamped engine frame (G3).

        The hub captures the engine ``YYMMDD-HHMM`` id off the first event whose
        ``run_id`` differs from the platform UUID (:meth:`RunStreamHub.note_engine_run_id`).
        As soon as it is known we write it to the run row through the single writer
        (INV-6), so boot recovery's reaper can ``docker kill`` the orphan after a
        mid-run crash (the id is the only container handle). Fires **exactly once**
        per run (guarded by :attr:`_engine_run_id_persisted`) and is best-effort —
        a write failure here must never wedge the pump (the completion supervisor
        still back-fills the id as a backstop). NOT a re-attach (INV-10): this only
        records the id; it never adopts the container.
        """
        if self._engine_run_id_persisted:
            return
        engine_id = self._hub.engine_run_id
        if not engine_id:
            return
        self._engine_run_id_persisted = True
        with contextlib.suppress(Exception):
            await self._repository.update_run_fields(self._hub.run_id, engine_run_id=engine_id)

    async def _project_stage(self, event: RuntimeEvent) -> None:
        """Update the ``run_stages`` read model from a lifecycle frame.

        A ``task_started`` upserts the stage ``running``; ``task_completed`` marks
        it ``done`` with its final cumulative cost/turns (the segment's final —
        INV-7); ``task_failed`` marks it ``failed``. Non-lifecycle frames (stream/
        assistant/result) don't move the stepper. The stage index is the engine's
        ``task_index``; a frame without a real task context (``-1``) is ignored.
        The stage rows are keyed by the **platform UUID** (``hub.run_id``), matching
        the events persistence, so the §8.9 stage read finds them.
        """
        idx = event.task_index
        if idx is None or idx < 0:
            return
        run_id = self._hub.run_id
        etype = event.event_type
        if etype in _STAGE_START_TYPES:
            name = event.task_name or self._stage_names.get(idx, "")
            self._stage_names[idx] = name
            await self._repository.upsert_stage(run_id, idx, name, status="running")
        elif etype in _STAGE_DONE_TYPES:
            name = event.task_name or self._stage_names.get(idx, "")
            await self._repository.upsert_stage(
                run_id,
                idx,
                name,
                status="done",
                cost_usd=event.cost_usd or None,
                turns=event.turns,
            )
        elif etype in _STAGE_FAILED_TYPES:
            name = event.task_name or self._stage_names.get(idx, "")
            await self._repository.upsert_stage(
                run_id,
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
