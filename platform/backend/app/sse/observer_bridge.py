"""Sync→async observer bridge + per-run fan-out hub (INV-12 / PRD §8.3).

The engine drives a run on a host coroutine and calls
``EventObserver.on_event(event)`` **synchronously, inline** — and the thread it
runs on is **not guaranteed to be the event-loop thread** (the agent stream is
parsed off a worker). A naive ``queue.put_nowait(event)`` from that callback is a
classic asyncio heisenbug: ``asyncio.Queue`` is *not* thread-safe and touching it
off the loop thread corrupts its internal state / wakeups.

The binding fix (INV-12, ADR-P003): capture the loop at startup and hand off with
``loop.call_soon_threadsafe(queue.put_nowait, event)``. ``call_soon_threadsafe``
is the *only* thread-safe scheduling primitive here; it enqueues the
``put_nowait`` call onto the loop thread, so the queue is only ever touched there.
This module therefore **never** calls bare ``put_nowait`` off-thread, **never**
schedules a coroutine from the observer, and **never** uses a coroutine-scheduling
primitive in the hand-off (each would either be thread-unsafe or spawn an unbounded
coroutine per event). The INV-12 grep over this file for the forbidden
coroutine-scheduling calls is asserted **empty** by AC-8.

The pieces:

* :class:`PlatformEventObserver` — the engine-facing sync observer. Its
  ``on_event`` is the thread-agnostic hand-off into one inbound :class:`asyncio.Queue`
  per run. The single per-run **pump** (see :mod:`app.sse.pump`) drains that queue.
* :class:`Subscriber` — one SSE connection's **bounded** outbound queue with the
  slow-consumer policy: on overflow, *coalesce/drop* meter frames (keep-latest,
  ≤4 Hz) but **never** lifecycle / decision / ``task_completed`` / ``task_failed``
  events; a persistently-slow consumer is *disconnected* (it reconnects and
  replays from the durable ``events`` table — §8.3).
* :class:`RunStreamHub` — the per-run inbound queue + subscriber set; the pump
  publishes each persisted frame to every subscriber through it.
* :class:`StreamRegistry` — the process-wide ``{run_id: RunStreamHub}`` map the
  app composes once on ``app.state`` (one loop, one registry).

Nothing here reaches into ``dkmv/`` beyond importing the engine's
``RuntimeEvent`` / ``EventObserver`` types (INV-13: consume, never edit).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from dkmv.runtime import EventObserver, RuntimeEvent

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.sse.pump import StreamFrame

#: Inbound (observer→pump) queue depth per run. Bounds memory if the pump falls
#: behind the engine's emit rate; the pump batch-drains so this rarely fills.
INBOUND_QUEUE_MAXSIZE = 2000

#: Outbound (pump→subscriber) queue depth per SSE connection. A slow browser /
#: proxy that can't keep up overflows this; the coalescing policy below keeps the
#: meter frames fresh while the lifecycle/decision spine is never dropped.
SUBSCRIBER_QUEUE_MAXSIZE = 512

#: ``event_type`` values that are **meter-only** and may be coalesced/dropped
#: under back-pressure (keep-latest). They carry a cumulative-per-task snapshot,
#: so dropping an intermediate one only loses a frame the next one supersedes.
#: Everything NOT in this set is spine and is never dropped (lifecycle, decision,
#: and the meter-critical ``task_completed`` / ``task_failed`` — §8.3 / INV-7).
COALESCIBLE_EVENT_TYPES: frozenset[str] = frozenset(
    {"stream", "assistant", "user", "result", "meter", "progress"}
)

#: Spine events that MUST survive back-pressure (never coalesced/dropped). Listed
#: explicitly so a future ``event_type`` defaults to spine (kept) rather than
#: silently becoming droppable. ``task_completed`` / ``task_failed`` are
#: meter-critical (they carry a completed segment's final cost — INV-7).
CRITICAL_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "task_completed",
        "task_failed",
        "task_started",
        "run_started",
        "run_completed",
        "run_failed",
        "pause_requested",
        "decision",
        "lifecycle",
        "error",
    }
)


def is_coalescible(event_type: str) -> bool:
    """True iff a frame of ``event_type`` may be dropped under back-pressure.

    A frame is droppable only when it is **explicitly** a meter/stream frame
    (:data:`COALESCIBLE_EVENT_TYPES`) **and not** in the never-drop spine
    (:data:`CRITICAL_EVENT_TYPES`). The default for an unknown type is *kept* —
    we never silently drop a spine event we failed to anticipate (INV-7 / §8.3).
    """
    if event_type in CRITICAL_EVENT_TYPES:
        return False
    return event_type in COALESCIBLE_EVENT_TYPES


class PlatformEventObserver(EventObserver):
    """The engine-facing sync observer that bridges into the run's inbound queue.

    Constructed with the **captured event loop** and the run's inbound
    :class:`asyncio.Queue`. ``on_event`` is invoked by the engine synchronously,
    possibly off the loop thread, so it hands off with
    ``loop.call_soon_threadsafe(queue.put_nowait, event)`` — the thread-safe
    schedule that touches the (non-thread-safe) queue only on the loop thread
    (INV-12). It never schedules a coroutine and never blocks the engine thread.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[RuntimeEvent]) -> None:
        self._loop = loop
        self._queue = queue

    def on_event(self, event: RuntimeEvent) -> None:
        """Hand a ``RuntimeEvent`` to the loop thread (INV-12; thread-agnostic).

        The ONLY safe primitive across the worker→loop thread boundary is
        ``call_soon_threadsafe``; it schedules ``queue.put_nowait(event)`` to run
        on the loop thread. If the loop is already closed (shutdown race) the
        call raises ``RuntimeError`` — swallowed so a late engine event can never
        crash the engine's emit path.
        """
        try:
            self._loop.call_soon_threadsafe(self._put, event)
        except RuntimeError:  # pragma: no cover - loop closed during shutdown
            # Loop is gone (process draining); drop the late event rather than
            # propagate into the engine's synchronous emit loop.
            pass

    def _put(self, event: RuntimeEvent) -> None:
        """Enqueue on the loop thread; drop oldest if the inbound queue is full.

        Runs on the loop thread (scheduled by ``call_soon_threadsafe``), so the
        queue is touched safely. The inbound queue is generously sized; if it is
        nonetheless full (pump wedged), discard the *oldest* frame to keep the
        newest — losing backlog is recoverable via replay, blocking the loop is
        not.
        """
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - racey full→empty
                pass
        self._queue.put_nowait(event)


class Subscriber:
    """One SSE connection's bounded outbound queue + slow-consumer policy (§8.3).

    The pump :meth:`publish`-es each *persisted* frame to every subscriber. A
    healthy consumer drains promptly. A slow one overflows the bounded queue; the
    policy then:

    * **coalesces** meter/stream frames — drop the oldest *coalescible* frame to
      make room (keep-latest, the meter only needs the freshest value); but
    * **never** drops a spine frame (lifecycle / decision / ``task_completed`` /
      ``task_failed`` — INV-7). If the queue is full of spine frames, the
      consumer is **marked slow** (:attr:`disconnected`) so the endpoint closes
      it — it reconnects and replays the durable backlog.
    """

    def __init__(self, *, maxsize: int = SUBSCRIBER_QUEUE_MAXSIZE) -> None:
        self._queue: asyncio.Queue[StreamFrame] = asyncio.Queue(maxsize=maxsize)
        self._disconnected = False

    @property
    def disconnected(self) -> bool:
        """True once the slow-consumer policy gave up on this subscriber."""
        return self._disconnected

    def publish(self, frame: StreamFrame) -> None:
        """Enqueue a frame for this connection, applying the slow-consumer policy.

        Fast path: the queue has room → enqueue. Slow path (full): evict the
        oldest *coalescible* (meter/stream) frame to make room and enqueue —
        regardless of whether ``frame`` itself is meter or spine, since the point
        is to keep the spine flowing by shedding stale meter frames (keep-latest,
        INV-7). Only if there is **no** coalescible frame to evict (the queue is
        full of spine) do we give up: a spine frame can't be dropped, so the
        consumer is persistently slow → mark it disconnected (the endpoint closes
        it; it reconnects + replays the durable backlog — §8.3). A meter frame
        that can't be placed on a spine-full queue is likewise dropped by
        disconnecting. Runs on the loop thread (called from the pump).
        """
        if self._disconnected:
            return
        try:
            self._queue.put_nowait(frame)
            return
        except asyncio.QueueFull:
            pass

        # Queue is full. Evict the oldest coalescible frame (if any) to make room
        # for this frame — shedding a stale meter frame keeps the spine flowing.
        if self._evict_one_coalescible():
            try:
                self._queue.put_nowait(frame)
                return
            except asyncio.QueueFull:  # pragma: no cover - re-filled by another task
                pass

        # No coalescible frame to drop → the queue is full of spine. We cannot
        # drop spine, so the consumer is persistently slow: cut it loose (it
        # reconnects and replays the durable backlog — §8.3).
        self._disconnected = True

    def _evict_one_coalescible(self) -> bool:
        """Drop the oldest *coalescible* frame from the queue; True if one went.

        Scans the queue in FIFO order, skipping (re-enqueueing) spine frames and
        removing the first droppable meter/stream frame. Preserves spine order
        and the relative order of the kept frames. Runs on the loop thread, so
        the drain/refill is atomic w.r.t. other publishes.
        """
        kept: list[StreamFrame] = []
        evicted = False
        while True:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if not evicted and is_coalescible(item.event_type):
                evicted = True  # drop this one
                continue
            kept.append(item)
        for item in kept:
            self._queue.put_nowait(item)
        return evicted

    async def get(self) -> StreamFrame:
        """Await the next frame for this connection (the SSE generator pulls here)."""
        return await self._queue.get()

    def drain_nowait(self) -> list[StreamFrame]:
        """Pop every currently-queued frame (used by the replay dedup handoff)."""
        out: list[StreamFrame] = []
        while True:
            try:
                out.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return out


class RunStreamHub:
    """Per-run inbound queue + subscriber set (the fan-out point for one run).

    The :class:`PlatformEventObserver` feeds the inbound :attr:`queue`; the single
    per-run pump drains it, persists each event, and :meth:`publish`-es the
    resulting frame to every :class:`Subscriber`. Subscribers come and go as SSE
    connections open/close; the hub outlives any one connection (it lives as long
    as the run streams).
    """

    def __init__(self, run_id: str, loop: asyncio.AbstractEventLoop) -> None:
        self._run_id = run_id
        self._loop = loop
        self.queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue(maxsize=INBOUND_QUEUE_MAXSIZE)
        self._subscribers: set[Subscriber] = set()
        #: Set when the run has fully streamed; the pump signals it so subscriber
        #: generators can terminate the SSE stream after draining.
        self.closed = asyncio.Event()

    @property
    def run_id(self) -> str:
        """The platform UUID this hub streams."""
        return self._run_id

    def observer(self) -> PlatformEventObserver:
        """Build the sync observer the engine ``add_observer``-s for this run.

        Captures the hub's loop + inbound queue so ``on_event`` hands off with
        ``call_soon_threadsafe`` (INV-12). One observer per hub.
        """
        return PlatformEventObserver(self._loop, self.queue)

    def add_subscriber(self, sub: Subscriber) -> None:
        """Register a new SSE connection's subscriber (subscribe-before-read)."""
        self._subscribers.add(sub)

    def remove_subscriber(self, sub: Subscriber) -> None:
        """Drop a closed SSE connection's subscriber."""
        self._subscribers.discard(sub)

    @property
    def subscriber_count(self) -> int:
        """Number of live subscribers (test/observability hook)."""
        return len(self._subscribers)

    def publish(self, frame: StreamFrame) -> None:
        """Fan a persisted frame out to every subscriber (called by the pump).

        Each :class:`Subscriber` applies its own slow-consumer policy; a
        subscriber that the policy disconnects is removed here so it stops
        receiving frames (the endpoint closes its stream separately).
        """
        for sub in list(self._subscribers):
            sub.publish(frame)
            if sub.disconnected:
                self._subscribers.discard(sub)

    def mark_closed(self) -> None:
        """Signal that the run has finished streaming (the pump calls this once)."""
        self.closed.set()


class StreamRegistry:
    """Process-wide ``{run_id: RunStreamHub}`` map (composed once on ``app.state``).

    One registry per process / event loop. The launch path (slice 2.1/2.5)
    :meth:`get_or_create`-s a hub before starting the run and registers the hub's
    observer on the engine ``RunHandle``; the SSE endpoint :meth:`get`-s the same
    hub to attach a subscriber. Lookups are O(1); there is no cross-loop sharing
    (multi-process fan-out is the deferred Redis lane — §8.3).
    """

    def __init__(self) -> None:
        self._hubs: dict[str, RunStreamHub] = {}

    def get_or_create(
        self, run_id: str, loop: asyncio.AbstractEventLoop | None = None
    ) -> RunStreamHub:
        """Return the run's hub, creating it on first use (idempotent).

        ``loop`` defaults to the running loop (the serving loop the SSE generators
        and the pump share). Re-creating is never desired — a second hub would
        split the subscriber set from the pump's publish target.
        """
        hub = self._hubs.get(run_id)
        if hub is None:
            hub = RunStreamHub(run_id, loop or asyncio.get_running_loop())
            self._hubs[run_id] = hub
        return hub

    def get(self, run_id: str) -> RunStreamHub | None:
        """Return the run's hub if one exists, else ``None`` (no implicit create)."""
        return self._hubs.get(run_id)

    def discard(self, run_id: str) -> None:
        """Forget a finished run's hub (called after the pump completes + drains)."""
        self._hubs.pop(run_id, None)
