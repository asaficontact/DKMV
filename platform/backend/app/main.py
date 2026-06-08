"""FastAPI application factory + ASGI entrypoint.

Slice 0.1 wires the *scaffold* app: it mounts the health/preflight stub router
and exposes ``app`` for ``uvicorn``/``docker compose``. Access-control
middleware (loopback + token + Host/Origin + CSRF, INV-1), the RunService, and
the real preflight wiring arrive in slice 0.2.

Run locally::

    uvicorn app.main:app --host 127.0.0.1 --port 8787

The container entrypoint reads ``Settings.DKMV_PLATFORM_BIND`` (default
``127.0.0.1:8787``) for the bind address.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app.

    Args:
        settings: Optional settings override (tests inject a throwaway one);
            defaults to the process-wide cached settings.
    """
    settings = settings or get_settings()
    app = FastAPI(
        title="DKMV Platform",
        version="0.1.0",
        description="Self-hostable control plane wrapping the DKMV engine.",
    )
    app.state.settings = settings
    app.include_router(health_router)
    return app


app = create_app()
