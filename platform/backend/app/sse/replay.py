"""Resumable SSE replay — ``Last-Event-ID`` subscribe-before-read + dedup (INV-2 / §8.3).

The binding reconnect contract (§8.3), in the order that closes the gap/dup window
most implementations botch:

1. **Subscribe to the live per-run queue FIRST.** Attaching the :class:`Subscriber`
   to the run's :class:`~app.sse.observer_bridge.RunStreamHub` *before* reading the
   backlog means any event the pump persists during the backlog read is *also*
   captured live — so nothing falls into the gap between "what the DB had" and
   "what goes live."
2. **Read the durable backlog** ``WHERE run_id=? AND id > :last ORDER BY id`` from
   the append-only ``events`` table (through the repository — the **primary**
   replay log; the engine's ``replay_events`` is a fallback only), and flush it in
   ``id`` order.
3. **Tail live**, **de-duplicating by ``id``**: because step 1 overlaps step 2, a
   handful of events appear in *both* the backlog and the live queue. We track the
   highest id already sent and skip any live frame at or below it (and any backlog
   row at or below the client's ``Last-Event-ID``).

The result: **no gaps and no duplicates** across the replay→live handoff (AC-11).
A fresh connection (no ``Last-Event-ID``) starts with ``last_id=0`` — the backlog
read returns the whole run-so-far, then tails live.

This module yields :class:`~app.sse.pump.StreamFrame`-shaped items the endpoint
turns into SSE messages (each ``id`` = ``events.id``). It writes no SQL directly —
it reads through :meth:`Repository.read_events_after` — and never touches ``dkmv/``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from app.db.repository import Repository
from app.sse.observer_bridge import RunStreamHub, Subscriber
from app.sse.pump import StreamFrame


def parse_last_event_id(raw: str | None) -> int:
    """Parse a ``Last-Event-ID`` header / ``?Last-Event-ID`` into a cursor int.

    The SSE cursor is the monotonic ``events.id``. A missing/blank/garbage value
    means "from the start" → ``0`` (the backlog read then returns the whole run).
    Never raises — a malformed reconnect header degrades to a full replay, not a
    500.
    """
    if not raw:
        return 0
    try:
        return max(0, int(raw.strip()))
    except (TypeError, ValueError):
        return 0


def row_to_frame(row: dict[str, Any]) -> StreamFrame:
    """Project an ``events`` backlog row into the SSE :class:`StreamFrame` shape.

    Reconstructs the §6.4 outer body from the persisted columns + the redacted
    inner ``payload_json`` (``data``). ``id`` is the durable cursor; the body
    mirrors what the live pump emits so a replayed frame is indistinguishable from
    a live one on the wire. The payload is already redacted at persist time
    (INV-4) — this read never un-redacts.
    """
    event_id = int(row["id"])
    payload_raw = row.get("payload_json")
    data: dict[str, Any]
    try:
        data = json.loads(payload_raw) if payload_raw else {}
    except (TypeError, ValueError):  # pragma: no cover - defensive; persisted JSON is well-formed
        data = {}
    body: dict[str, Any] = {
        "sequence": int(row.get("sequence") or 0),
        "timestamp": row.get("ts"),
        "run_id": row.get("run_id"),
        "task_name": data.get("_task_name") or data.get("task_name") or "",
        "task_index": row.get("task_index"),
        "step_instance": data.get("_step_instance") or "",
        "event_type": row.get("event_type"),
        "data": data,
        "content": data.get("content_text") or data.get("content") or "",
        "cost_usd": row.get("cost_usd") or 0.0,
        "turns": data.get("num_turns") or 0,
    }
    return StreamFrame(
        event_id=event_id,
        event_type=str(row.get("event_type") or ""),
        body=body,
    )


async def replay_then_tail(
    *,
    repository: Repository,
    hub: RunStreamHub,
    subscriber: Subscriber,
    last_id: int,
) -> AsyncIterator[StreamFrame]:
    """Yield the backlog (id-ordered) then tail live, dedup-by-id (§8.3 contract).

    Precondition (binding): ``subscriber`` is **already attached** to ``hub``
    before this is called — the caller subscribes first so the live capture
    overlaps the backlog read (step 1). This generator then:

    * reads + flushes the durable backlog ``id > last_id`` in order (step 2),
      tracking the highest id sent;
    * drains any frames the subscriber buffered *during* the backlog read and
      tails new ones, **skipping any id ≤ the highest already sent** (step 3 —
      the dedup that removes the overlap).

    It terminates when the run is closed (``hub.closed``) and no buffered frames
    remain. The endpoint wraps each yielded frame as one SSE message (``id`` =
    ``event_id``).
    """
    sent_max = last_id

    # Step 2: durable backlog, id-ordered, strictly after the client's cursor.
    backlog = await repository.read_events_after(hub.run_id, last_id)
    for row in backlog:
        frame = row_to_frame(row)
        if frame.event_id <= sent_max:
            continue
        sent_max = frame.event_id
        yield frame

    # Step 3: tail live, de-duplicating against the backlog overlap by id. Frames
    # captured by the subscriber during the backlog read whose id is ≤ what we
    # already flushed are duplicates and are skipped; the rest stream through.
    while True:
        if subscriber.disconnected:
            return
        # Flush anything buffered first (the overlap window), then await more.
        buffered = subscriber.drain_nowait()
        if not buffered:
            if hub.closed.is_set():
                # No buffered frames and the run is done → end the stream.
                return
            live = await _next_or_close(hub, subscriber)
            if live is None:
                return
            buffered = [live]
        for frame in buffered:
            if frame.event_id <= sent_max:
                continue  # duplicate of a backlog row already sent
            sent_max = frame.event_id
            yield frame


async def _next_or_close(hub: RunStreamHub, subscriber: Subscriber) -> StreamFrame | None:
    """Await the next live frame, or ``None`` if the run closes while waiting.

    Races the subscriber's next-frame await against the hub's ``closed`` signal so
    a finished run with an idle subscriber doesn't block forever.
    """
    get_task = asyncio.ensure_future(subscriber.get())
    closed_task = asyncio.ensure_future(hub.closed.wait())
    try:
        done, _ = await asyncio.wait({get_task, closed_task}, return_when=asyncio.FIRST_COMPLETED)
        if get_task in done:
            return get_task.result()
        # Closed fired first; return any frame that arrived in the meantime.
        if not get_task.done():
            get_task.cancel()
        return None
    finally:
        for task in (get_task, closed_task):
            if not task.done():
                task.cancel()
