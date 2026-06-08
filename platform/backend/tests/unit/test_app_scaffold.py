"""Scaffold smoke tests: the app boots and the preflight stub answers.

The *real* preflight (engine ``get_capabilities()``) and access-control
middleware land in slice 0.2; these tests only assert the scaffold app exists,
mounts the health router, and returns the §8.9 preflight envelope shape so the
M0 boot smoke (AC-0.1-5) has a backing unit equivalent.
"""

from __future__ import annotations

from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def _client() -> TestClient:
    app = create_app(Settings(_env_file=None))  # type: ignore[call-arg]  # DKMVP-ESCAPE: pydantic-settings injected kwarg
    return TestClient(app)


def test_healthz_ok() -> None:
    resp = _client().get("/api/v1/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_preflight_returns_envelope_shape() -> None:
    resp = _client().get("/api/v1/preflight")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"ready", "checks", "blockers"}
    assert isinstance(body["checks"], list)
    assert isinstance(body["blockers"], list)


def test_engine_importable_in_process() -> None:
    """INV-13: the engine is importable in-process (editable install)."""
    import dkmv.runtime  # noqa: F401
    from dkmv.runtime import EmbeddedRuntime  # noqa: F401
