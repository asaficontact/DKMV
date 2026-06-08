"""Liveness probe.

``GET /api/v1/healthz`` is the unauthenticated liveness check used by the
container health check and ``docker compose`` (AC-0.1-5). It is intentionally
*exempt* from the access-control middleware (no token required) so an operator
can confirm the process is up before configuring the token.

The real preflight contract — ``EmbeddedRuntime.get_capabilities()`` rendered as
the §8.9 ``{ ready, checks:[{id,label,sub,ok}], blockers }`` envelope — lives in
:mod:`app.api.preflight` (slice 0.2) and *is* gated by the token.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe — always ``ok`` once the app is up (token-exempt)."""
    return {"status": "ok"}
