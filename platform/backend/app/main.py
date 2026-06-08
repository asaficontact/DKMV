"""FastAPI application factory + ASGI entrypoint.

Slice 0.2 wires the working control-plane skeleton:

* the :class:`~app.security.AccessControlMiddleware` access-control stack
  (loopback ``Host`` + local token + ``Origin``/``Referer`` validation + CSRF on
  state-changing POSTs — INV-1 / NFR-SEC-2);
* the §8.9 error-envelope exception handlers;
* the liveness probe (token-exempt) + the engine-backed
  ``GET /api/v1/preflight`` (``get_capabilities()`` → ``{ready,checks,blockers}``);
* a single configured :class:`~app.runtime.RunService` on ``app.state`` — the
  only seam to the in-process DKMV engine (INV-13).

Run locally::

    uvicorn app.main:app --host 127.0.0.1 --port 8787

The container entrypoint reads ``Settings.DKMV_PLATFORM_BIND`` (default
``127.0.0.1:8787``) for the loopback bind address.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api import api_router
from app.api.errors import install_error_handlers
from app.config import Settings, get_settings
from app.runtime import RunService
from app.security import AccessControlMiddleware


def create_app(
    settings: Settings | None = None,
    run_service: RunService | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    Args:
        settings: Optional settings override (tests inject a throwaway one);
            defaults to the process-wide cached settings.
        run_service: Optional pre-built run service (tests inject one whose
            engine is a fast in-process fake so they don't require Docker);
            defaults to one constructed from ``settings`` with the
            platform-owned ``output_dir`` bound to ``settings.OUTPUT_DIR``.
    """
    settings = settings or get_settings()
    app = FastAPI(
        title="DKMV Platform",
        version="0.1.0",
        description="Self-hostable control plane wrapping the DKMV engine.",
    )
    app.state.settings = settings
    app.state.run_service = run_service or RunService(settings)

    # INV-1: the access-control stack wraps the whole app. Added last so it is
    # the outermost middleware (it runs before routing on every request).
    app.add_middleware(AccessControlMiddleware, settings=settings)

    install_error_handlers(app)
    # Single versioned parent router (owns the /api/v1 prefix); feature routers
    # attach to it in app.api, not here.
    app.include_router(api_router)
    return app


app = create_app()
