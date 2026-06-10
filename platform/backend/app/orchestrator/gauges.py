"""Basic tick gauges + loop heartbeat (PRD §8.2 — AC-10, minimal).

A single event loop drives the whole orchestrator; if it wedges (a blocking call,
a deadlock, a never-returning GitHub read) the tick silently stops and runs stop
being dispatched/reconciled — with **no** outward sign. The *full* loop
self-observability suite (queue depth, dispatch latency, per-action reconcile
counters, OTel) is **Phase 5 / T114**. This module ships only the **minimal**
subset that makes a wedged loop *detectable* (the §3 OUT-of-scope split):

* **tick duration** — how long the last tick took (a creeping duration warns of a
  slow blocking call before it fully wedges);
* **time-since-last-successful-tick** — the liveness signal: it climbs without
  bound exactly when the loop has stopped ticking, so a watchdog / health probe
  can alarm on ``age > k · tick_interval``;
* **a loop heartbeat** — a monotonically-increasing tick counter + the UTC
  timestamp of the last *successful* tick, recorded each tick so "is the loop
  alive?" is answerable.

These are in-memory process gauges (one orchestrator per process). They are read
by the tick loop itself (to log a heartbeat) and are available for a future
health endpoint; Phase 5 extends — never forks — this surface. The clock is
injectable so tests assert the gauges deterministically. Nothing here touches
``dkmv/`` or the network.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.orchestrator.deadlines import Clock, seconds_since, to_iso, utc_now

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TickSnapshot:
    """An immutable read-only view of the loop's liveness gauges (AC-10).

    Captured from :class:`TickGauges` so a caller (a log line, a future health
    probe) sees a consistent set: the heartbeat ``tick_count``, the last
    successful-tick timestamp + its age in seconds (the wedge detector), and the
    last tick's duration. ``last_success_age_s`` is ``None`` only before the first
    successful tick.
    """

    tick_count: int
    last_success_at: str | None
    last_success_age_s: float | None
    last_tick_duration_s: float | None


@dataclass(slots=True)
class TickGauges:
    """Minimal in-memory tick gauges + heartbeat (AC-10; full suite → Phase 5).

    One instance per orchestrator/process. The tick loop calls :meth:`record_tick`
    at the end of each *successful* tick with that tick's wall-clock duration; the
    gauges then expose :meth:`snapshot` (and the convenience
    :meth:`seconds_since_last_success`) so a wedged loop — one that stopped calling
    ``record_tick`` — is detectable by its ever-climbing ``last_success_age_s``.
    The clock is injectable for deterministic tests.
    """

    #: Monotonic heartbeat counter (incremented on every successful tick).
    tick_count: int = 0
    #: UTC ISO-8601 timestamp of the last successful tick (``None`` before the
    #: first), and that tick's duration in seconds.
    last_success_at: str | None = None
    last_tick_duration_s: float | None = None
    _clock: Clock = field(default=utc_now, repr=False)

    def record_tick(self, *, duration_s: float) -> None:
        """Record one successful tick: bump the heartbeat + stamp the success time.

        Called by the tick loop after a tick completes its reconcile→dispatch pass.
        Increments :attr:`tick_count` (the heartbeat), stores the UTC timestamp of
        this success (so :meth:`seconds_since_last_success` measures liveness from
        it), and records the tick's duration. A wedged loop never reaches here, so
        the success age climbs without bound — the detectable signal.
        """
        self.tick_count += 1
        self.last_success_at = to_iso(self._clock())
        self.last_tick_duration_s = duration_s

    def seconds_since_last_success(self) -> float | None:
        """Seconds since the last successful tick, or ``None`` before the first.

        The liveness gauge: a healthy loop keeps this near the tick interval; a
        wedged loop makes it climb unbounded. Computed against a *fresh* ``now()``
        (:func:`app.orchestrator.deadlines.seconds_since`), never a cached value,
        so it reflects real elapsed time even across a suspend gap.
        """
        return seconds_since(self.last_success_at, now=self._clock)

    def snapshot(self) -> TickSnapshot:
        """Capture a consistent :class:`TickSnapshot` of all gauges (AC-10)."""
        return TickSnapshot(
            tick_count=self.tick_count,
            last_success_at=self.last_success_at,
            last_success_age_s=self.seconds_since_last_success(),
            last_tick_duration_s=self.last_tick_duration_s,
        )

    def heartbeat(self) -> None:
        """Emit a structured heartbeat log line for the current gauges (AC-10).

        A single ``INFO`` line carrying the tick count + last duration so a wedged
        loop is visible in the structured logs (NFR-OBS-1) by default even without a
        health endpoint. It was ``DEBUG`` — below the INFO default → invisible (G10);
        at ``INFO`` an operator tailing the logs sees the loop alive (the counter
        climbing) or wedged (it stops) without raising the log level. Cheap and
        side-effect-free beyond the log.
        """
        snap = self.snapshot()
        _log.info(
            "orchestrator.tick heartbeat tick=%d duration_s=%s age_s=%s",
            snap.tick_count,
            snap.last_tick_duration_s,
            snap.last_success_age_s,
        )


__all__ = ["TickGauges", "TickSnapshot"]
