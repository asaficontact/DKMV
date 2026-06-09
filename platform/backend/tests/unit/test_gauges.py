"""Basic tick gauges + heartbeat (slice 3.3 — AC-10, minimal observability).

Ship only the minimal subset that makes a wedged loop detectable (the full suite
is Phase 5): tick duration + a monotonic heartbeat + time-since-last-successful-
tick. A frozen clock asserts the success-age climbs exactly when ``record_tick``
stops being called (the wedge signal).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.orchestrator.gauges import TickGauges


def test_heartbeat_counter_and_duration_recorded() -> None:
    gauges = TickGauges()
    assert gauges.tick_count == 0
    assert gauges.snapshot().last_success_age_s is None  # before the first tick

    gauges.record_tick(duration_s=0.5)
    gauges.record_tick(duration_s=0.7)

    snap = gauges.snapshot()
    assert snap.tick_count == 2  # heartbeat advanced
    assert snap.last_tick_duration_s == 0.7
    assert snap.last_success_at is not None


def test_success_age_climbs_when_loop_stops_ticking() -> None:
    base = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
    clock_time = {"t": base}

    def _clock() -> datetime:
        return clock_time["t"]

    gauges = TickGauges(_clock=_clock)
    gauges.record_tick(duration_s=0.1)  # success stamped at base

    # The loop wedges: time advances 120s but record_tick is never called again.
    clock_time["t"] = base + timedelta(seconds=120)
    snap = gauges.snapshot()
    # The detectable signal: success age climbs to the full gap.
    assert snap.last_success_age_s == 120.0
    assert snap.tick_count == 1  # heartbeat did NOT advance — loop is wedged


def test_heartbeat_log_is_side_effect_free(caplog: object) -> None:
    gauges = TickGauges()
    gauges.record_tick(duration_s=0.2)
    # Should not raise; emits a single structured debug line.
    gauges.heartbeat()
    assert gauges.tick_count == 1
