"""Full loop self-observability: gauges + heartbeat (PRD §8.2 — AC-5).

A single event loop drives the whole orchestrator; if it wedges (a blocking call,
a deadlock, a never-returning GitHub read) the tick silently stops — runs stop
being dispatched/reconciled with **no** outward sign. Phase 3 shipped the *minimal*
liveness subset (:class:`app.orchestrator.gauges.TickGauges` — tick duration +
time-since-last-successful-tick + heartbeat). Phase 5 / T114 **completes** the suite
(it extends, never forks, that surface) so a wedged *or degrading* loop is fully
observable:

* **tick duration** — last tick's wall-clock (a creeping value warns of a slow
  blocking call before it fully wedges); inherited from :class:`TickGauges`.
* **time-since-last-successful-tick** — the liveness signal that climbs unbounded
  exactly when the loop stopped ticking (a watchdog alarms on ``age > k·interval``);
  inherited from :class:`TickGauges`.
* **slots-in-use** — how many concurrency slots the dispatch semaphore currently
  holds (it tracks :attr:`app.hitl.slots.ConcurrencySlots.held`), so saturation is
  visible (AC-5: a test asserts this gauge tracks the semaphore).
* **queue depth** — how many dispatch candidates the last tick saw (the backlog the
  semaphore is draining).
* **reconcile actions** — how many reconcile actions the last tick took (orphan
  kills, label refreshes, retries fired) so a thrashing reconcile is visible.
* **dispatch latency** — the wall-clock the last tick spent in the dispatch phase
  (admission + launch), distinct from the whole-tick duration.
* **a loop heartbeat** — the monotonic tick counter + last-success UTC timestamp.

These are in-memory process gauges (one orchestrator per process), read by the tick
loop (to log a heartbeat) and exposed for a future health endpoint. The clock is
injectable so tests assert them deterministically. Nothing here touches ``dkmv/`` or
the network.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.orchestrator.deadlines import Clock, utc_now
from app.orchestrator.gauges import TickGauges, TickSnapshot

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LoopSnapshot:
    """An immutable read-only view of the FULL loop gauge set (AC-5).

    Composes the inherited liveness :class:`TickSnapshot` (heartbeat + duration +
    age) with the Phase-5 additions (slots-in-use, queue depth, reconcile actions,
    dispatch latency) so a single capture answers "is the loop alive, saturated, or
    thrashing?".
    """

    tick: TickSnapshot
    slots_in_use: int
    slots_capacity: int
    queue_depth: int
    reconcile_actions: int
    dispatch_latency_s: float | None

    @property
    def tick_count(self) -> int:
        """Heartbeat tick counter (advances each successful tick — AC-5)."""
        return self.tick.tick_count

    @property
    def last_success_age_s(self) -> float | None:
        """Seconds since the last successful tick (the wedge detector)."""
        return self.tick.last_success_age_s


@dataclass(slots=True)
class LoopMetrics(TickGauges):
    """The complete loop gauge set + heartbeat (AC-5; extends :class:`TickGauges`).

    Subclasses the Phase-3 liveness gauges (so ``record_tick`` / the heartbeat
    timestamp / the wedge-detector age are inherited unchanged) and adds the Phase-5
    gauges the tick records each pass: ``slots_in_use`` (tracking the dispatch
    semaphore), ``queue_depth``, ``reconcile_actions``, and ``dispatch_latency_s``.
    One instance per orchestrator; the tick calls :meth:`record_loop` at the end of
    each pass with the just-observed values, then :meth:`heartbeat` logs them.
    """

    #: How many concurrency slots are held right now (tracks the semaphore — AC-5).
    slots_in_use: int = 0
    #: The dispatch semaphore's capacity (``max_concurrent_runs``).
    slots_capacity: int = 0
    #: Dispatch candidates the last tick saw (the backlog being drained).
    queue_depth: int = 0
    #: Reconcile actions the last tick took (orphan kills, label refreshes, retries).
    reconcile_actions: int = 0
    #: Wall-clock the last tick spent in the dispatch phase (admission + launch).
    dispatch_latency_s: float | None = None
    _loop_clock: Clock = field(default=utc_now, repr=False)

    def record_loop(
        self,
        *,
        slots_in_use: int,
        slots_capacity: int,
        queue_depth: int,
        reconcile_actions: int,
        dispatch_latency_s: float | None,
    ) -> None:
        """Record one tick's full gauge set (called at the end of each pass — AC-5).

        Stores the just-observed slots-in-use (which must equal the semaphore's held
        count so the gauge *tracks* the semaphore), queue depth, reconcile-action
        count, and dispatch latency. Does **not** touch the heartbeat — the tick
        calls the inherited :meth:`record_tick` separately so the liveness signal and
        the workload gauges stay independently testable.
        """
        self.slots_in_use = slots_in_use
        self.slots_capacity = slots_capacity
        self.queue_depth = queue_depth
        self.reconcile_actions = reconcile_actions
        self.dispatch_latency_s = dispatch_latency_s

    def loop_snapshot(self) -> LoopSnapshot:
        """Capture the FULL :class:`LoopSnapshot` (liveness + workload gauges)."""
        return LoopSnapshot(
            tick=self.snapshot(),
            slots_in_use=self.slots_in_use,
            slots_capacity=self.slots_capacity,
            queue_depth=self.queue_depth,
            reconcile_actions=self.reconcile_actions,
            dispatch_latency_s=self.dispatch_latency_s,
        )

    def heartbeat(self) -> None:
        """Emit a structured heartbeat carrying the full gauge set (AC-5).

        Overrides :class:`TickGauges.heartbeat` to log the workload gauges alongside
        the liveness ones, so a single ``INFO`` line answers "alive? saturated?
        thrashing?" without a health endpoint (NFR-OBS-1). Raised from ``DEBUG`` to
        ``INFO`` (G10) so the heartbeat is visible at the default log level — a wedged
        loop is then detectable just by tailing the logs (the line stops). Cheap +
        side-effect-free beyond the log.
        """
        snap = self.loop_snapshot()
        _log.info(
            "orchestrator.loop heartbeat tick=%d duration_s=%s age_s=%s "
            "slots=%d/%d queue_depth=%d reconcile_actions=%d dispatch_latency_s=%s",
            snap.tick_count,
            snap.tick.last_tick_duration_s,
            snap.last_success_age_s,
            snap.slots_in_use,
            snap.slots_capacity,
            snap.queue_depth,
            snap.reconcile_actions,
            snap.dispatch_latency_s,
        )


__all__ = ["LoopMetrics", "LoopSnapshot"]
