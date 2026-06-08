"""Scaffold-level health + preflight stub router.

Phase 0 / slice 0.1 ships only the *scaffold* of the API so the app boots and
``docker compose up`` answers on loopback (AC-0.1-5). The full preflight
contract — ``get_capabilities()`` results in the
``{ ready, checks:[{id,label,sub,ok}], blockers }`` shape — plus the
access-control middleware are owned by slice 0.2 (``0.2-runservice``). The
stub here returns the *shape* so the smoke test passes and later slices fill in
the real engine-backed checks.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe — always ``ok`` once the app is up."""
    return {"status": "ok"}


@router.get("/preflight")
def preflight() -> dict[str, Any]:
    """Scaffold preflight: returns the §8.9 envelope shape with no checks yet.

    Slice 0.2 replaces the body with ``EmbeddedRuntime.get_capabilities()``
    results (FR-01-6). The scaffold returns ``ready: true`` with an empty
    ``checks``/``blockers`` so the M0 smoke (AC-0.1-5) can confirm the app is
    reachable on ``127.0.0.1:8787`` before the real checks land.
    """
    return {"ready": True, "checks": [], "blockers": []}
