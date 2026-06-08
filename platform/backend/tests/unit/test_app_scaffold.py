"""Scaffold smoke tests: the app boots, liveness answers, preflight is gated.

These assert the app exists, mounts the routers, and that the access-control
middleware (slice 0.2) gates the engine-backed preflight while leaving the
liveness probe token-exempt. Deeper preflight-shape and access-control behavior
live in ``test_preflight.py`` / ``test_access_control.py``. Fixtures come from
``tests/conftest.py``.
"""

from __future__ import annotations

from tests.conftest import build_client


def test_healthz_ok_without_token() -> None:
    """Liveness is token-exempt so health checks work before auth is set."""
    resp = build_client().get("/api/v1/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_preflight_requires_token() -> None:
    """Preflight is gated: no token → 401 envelope."""
    resp = build_client().get("/api/v1/preflight")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_engine_importable_in_process() -> None:
    """INV-13: the engine is importable in-process (editable install)."""
    import dkmv.runtime  # noqa: F401
    from dkmv.runtime import EmbeddedRuntime  # noqa: F401
