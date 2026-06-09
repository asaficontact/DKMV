"""HTTP API layer (FastAPI routers).

A single ``/api/v1`` parent router (:data:`api_router`) owns the version prefix
so individual feature routers (health, preflight, …) attach to it *without*
re-declaring ``prefix="/api/v1"`` each time. ``app.main`` includes this one
router; new endpoints register on it via :func:`include_routers`.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.agent_state import router as agent_state_router
from app.api.board import router as board_router
from app.api.connect import router as connect_router
from app.api.health import router as health_router
from app.api.issues import router as issues_router
from app.api.preflight import router as preflight_router
from app.api.repos import router as repos_router

# The single versioned parent router. Feature routers below attach to it, so the
# ``/api/v1`` prefix is declared in exactly one place (no per-router repetition).
api_router = APIRouter(prefix="/api/v1")

# Feature routers attached to the versioned parent. One ``include_router`` per
# line so concurrent slices adding a router union-merge cleanly (add a new line;
# do not edit an existing one).
api_router.include_router(health_router)
api_router.include_router(preflight_router)
api_router.include_router(repos_router)
api_router.include_router(connect_router)
api_router.include_router(issues_router)
api_router.include_router(agent_state_router)
api_router.include_router(board_router)

__all__ = ["api_router"]
