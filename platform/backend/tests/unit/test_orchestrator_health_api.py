"""G10 — GET /api/v1/health/orchestrator surfaces the live loop-health snapshot.

The orchestrator tick updates a single :class:`LoopMetrics` gauges object each pass;
before G10 that snapshot had no read path, so an operator could not tell a wedged
loop (the tick stopped) from an idle one. These tests lock in:

* the endpoint returns the gauges snapshot (tick_count, last_success_age_s,
  durations, slots, queue_depth, heartbeat);
* a wedged loop (a stale last-success under a frozen clock) shows a climbing
  ``last_success_age_s`` while ``tick_count`` does NOT advance;
* it degrades gracefully to ``running: false`` when no orchestrator is running;
* it is behind INV-1 access control (401 without the local token).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.orchestrator.loop_metrics import LoopMetrics

from tests.conftest import auth_headers, build_client


@dataclass
class _FakeDeps:
    gauges: LoopMetrics


@dataclass
class _FakeHandle:
    deps: _FakeDeps


def _publish_gauges(client: object, gauges: LoopMetrics) -> None:
    client.app.state.orchestrator = _FakeHandle(deps=_FakeDeps(gauges=gauges))  # type: ignore[attr-defined]


def test_returns_snapshot_when_running() -> None:
    client = build_client()
    gauges = LoopMetrics()
    gauges.record_tick(duration_s=0.4)
    gauges.record_loop(
        slots_in_use=2,
        slots_capacity=3,
        queue_depth=5,
        reconcile_actions=1,
        dispatch_latency_s=0.12,
    )
    _publish_gauges(client, gauges)

    resp = client.get("/api/v1/health/orchestrator", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["running"] is True
    assert body["tick_count"] == 1
    assert body["heartbeat"] == 1
    assert body["last_tick_duration_s"] == 0.4
    assert body["slots_in_use"] == 2
    assert body["slots_capacity"] == 3
    assert body["queue_depth"] == 5
    assert body["reconcile_actions"] == 1
    assert body["dispatch_latency_s"] == 0.12
    assert body["last_success_age_s"] is not None


def test_wedged_loop_shows_climbing_age() -> None:
    base = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
    clock = {"t": base}

    def _clock() -> datetime:
        return clock["t"]

    gauges = LoopMetrics(_clock=_clock)
    gauges.record_tick(duration_s=0.1)  # last success stamped at base

    # The loop wedges: 300s pass but no further successful tick is recorded.
    clock["t"] = base + timedelta(seconds=300)

    client = build_client()
    _publish_gauges(client, gauges)
    body = client.get("/api/v1/health/orchestrator", headers=auth_headers()).json()
    assert body["running"] is True
    assert body["tick_count"] == 1  # heartbeat did NOT advance — wedged
    assert body["last_success_age_s"] == 300.0  # the detectable wedge signal


def test_graceful_when_no_orchestrator() -> None:
    client = build_client()
    # No orchestrator published (no project connected); lifespan leaves it None.
    body = client.get("/api/v1/health/orchestrator", headers=auth_headers()).json()
    assert body["running"] is False
    assert body["tick_count"] == 0
    assert body["last_success_age_s"] is None
    assert body["heartbeat"] is None


def test_requires_token_inv1() -> None:
    client = build_client()
    resp = client.get("/api/v1/health/orchestrator")  # no auth header
    assert resp.status_code == 401
