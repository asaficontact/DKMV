"""Scaffold smoke tests: the app boots, liveness answers, preflight is gated.

These assert the app exists, mounts the routers, and that the access-control
middleware (slice 0.2) gates the engine-backed preflight while leaving the
liveness probe token-exempt. Deeper preflight-shape and access-control behavior
live in ``test_preflight.py`` / ``test_access_control.py``.
"""

from __future__ import annotations

from app.config import Settings
from app.main import create_app
from app.runtime import RunService
from fastapi.testclient import TestClient

_TOKEN = "scaffold-token"  # noqa: S105 - test fixture token, not a real secret


class _StubRuntime:
    """Minimal stand-in so create_app does not build a real EmbeddedRuntime."""

    def get_capabilities(self) -> object:
        raise AssertionError("not used by scaffold tests")


def _settings() -> Settings:
    return Settings(_env_file=None, DKMV_PLATFORM_TOKEN=_TOKEN)  # type: ignore[call-arg]  # DKMVP-ESCAPE: pydantic-settings injected kwargs


def _client() -> TestClient:
    settings = _settings()
    run_service = RunService(settings, runtime=_StubRuntime())  # type: ignore[arg-type]  # DKMVP-ESCAPE: stub duck-types get_capabilities
    app = create_app(settings, run_service=run_service)
    # TestClient defaults Host to ``testserver``; pin to loopback so the
    # anti-DNS-rebinding Host check passes.
    return TestClient(app, base_url="http://127.0.0.1")


def test_healthz_ok_without_token() -> None:
    """Liveness is token-exempt so health checks work before auth is set."""
    resp = _client().get("/api/v1/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_preflight_requires_token() -> None:
    """Preflight is gated: no token → 401 envelope."""
    resp = _client().get("/api/v1/preflight")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_engine_importable_in_process() -> None:
    """INV-13: the engine is importable in-process (editable install)."""
    import dkmv.runtime  # noqa: F401
    from dkmv.runtime import EmbeddedRuntime  # noqa: F401
