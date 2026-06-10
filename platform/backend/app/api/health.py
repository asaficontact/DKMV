"""Liveness probe + orchestrator loop health (G10).

``GET /api/v1/healthz`` is the unauthenticated liveness check used by the
container health check and ``docker compose`` (AC-0.1-5). It is intentionally
*exempt* from the access-control middleware (no token required) so an operator
can confirm the process is up before configuring the token.

``GET /api/v1/health/orchestrator`` is the AUTHENTICATED loop-health probe (G10):
it returns the live :class:`~app.orchestrator.loop_metrics.LoopMetrics` snapshot
the orchestrator tick updates every pass (the heartbeat ``tick_count``, the
``last_success_age_s`` wedge detector, ``last_tick_duration_s``, ``slots_in_use``,
``queue_depth``). A wedged loop is detectable by a climbing ``last_success_age_s``.
It inherits the INV-1 access-control stack (token + Host/Origin) — only ``/healthz``
is token-exempt — so it is NOT reachable without the local token.

The real preflight contract — ``EmbeddedRuntime.get_capabilities()`` rendered as
the §8.9 ``{ ready, checks:[{id,label,sub,ok}], blockers }`` envelope — lives in
:mod:`app.api.preflight` (slice 0.2) and *is* gated by the token.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.deps import get_loop_metrics

# No prefix here: the ``/api/v1`` version prefix is owned by the single parent
# router in :mod:`app.api`, which this router attaches to.
router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe — always ``ok`` once the app is up (token-exempt)."""
    return {"status": "ok"}


@router.get("/health/orchestrator")
def orchestrator_health(request: Request) -> dict[str, Any]:
    """Return the live orchestrator loop-health snapshot (G10 — authenticated).

    Resolves the SINGLE :class:`LoopMetrics` gauges the tick updates each pass off
    the running orchestrator handle (``app.state.orchestrator.deps.gauges`` — the
    :func:`app.api.deps.get_loop_metrics` seam) and renders its snapshot so an
    operator can tell a wedged loop (a climbing ``last_success_age_s`` — the tick
    stopped recording successes) from a healthy one. A strict in-memory **read** — no
    DB, no engine call (INV-13). Behind INV-1 access control (token + Host/Origin) —
    only ``/healthz`` is token-exempt.

    When no orchestrator is running (no project connected yet, or a bare test client
    without the lifespan) it degrades gracefully to ``{"running": false}`` with null
    gauges rather than 500-ing — "idle/not started" is distinct from "wedged".
    """
    gauges = get_loop_metrics(request)
    if gauges is None:
        return {
            "running": False,
            "tick_count": 0,
            "last_success_at": None,
            "last_success_age_s": None,
            "last_tick_duration_s": None,
            "slots_in_use": 0,
            "slots_capacity": 0,
            "queue_depth": 0,
            "reconcile_actions": 0,
            "dispatch_latency_s": None,
            "heartbeat": None,
        }
    snap = gauges.loop_snapshot()
    return {
        "running": True,
        "tick_count": snap.tick_count,
        "last_success_at": snap.tick.last_success_at,
        # The wedge detector: re-computed against a fresh ``now()`` at read time, so a
        # loop that stopped ticking shows an ever-climbing age.
        "last_success_age_s": snap.last_success_age_s,
        "last_tick_duration_s": snap.tick.last_tick_duration_s,
        "slots_in_use": snap.slots_in_use,
        "slots_capacity": snap.slots_capacity,
        "queue_depth": snap.queue_depth,
        "reconcile_actions": snap.reconcile_actions,
        "dispatch_latency_s": snap.dispatch_latency_s,
        # The monotonic heartbeat alias (same as ``tick_count``) so a watchdog polling
        # this endpoint can alarm on a STALLED counter even without diffing ages.
        "heartbeat": snap.tick_count,
    }
