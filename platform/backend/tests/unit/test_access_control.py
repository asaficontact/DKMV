"""AC-0.2-4 / INV-1: app access-control middleware.

Covers the NFR-SEC-2 stack: loopback ``Host`` validation (anti-DNS-rebinding),
the local token requirement, ``Origin``/``Referer`` validation, and CSRF
rejection of form-encoded state-changing requests. The liveness probe is
asserted token-exempt.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.main import create_app
from app.runtime import RunService
from fastapi import APIRouter
from fastapi.testclient import TestClient

_TOKEN = "unit-token-xyz"  # noqa: S105 - test fixture, not a real secret


class _StubRuntime:
    def get_capabilities(self) -> Any:  # pragma: no cover - patched per test
        raise AssertionError("preflight not under test here")


def _settings() -> Settings:
    return Settings(_env_file=None, DKMV_PLATFORM_TOKEN=_TOKEN)  # type: ignore[call-arg]  # DKMVP-ESCAPE: pydantic-settings injected kwargs


def _app() -> Any:
    settings = _settings()
    run_service = RunService(settings, runtime=_StubRuntime())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed stub
    app = create_app(settings, run_service=run_service)

    # A state-changing echo route so CSRF behavior is observable without a
    # real POST endpoint (those land in Phase 2).
    router = APIRouter(prefix="/api/v1")

    @router.post("/_echo")
    def _echo() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)
    return app


def _client(host: str = "127.0.0.1") -> TestClient:
    # raise_server_exceptions=False: tests that pass access control reach the
    # preflight stub which raises; the Exception handler maps it to a 500
    # envelope, proving access control let the request through (not 401/403).
    return TestClient(_app(), base_url=f"http://{host}", raise_server_exceptions=False)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {_TOKEN}"}


# ── Host validation (anti-DNS-rebinding) ─────────────────────────────────────


def test_foreign_host_rejected_403() -> None:
    client = TestClient(_app(), base_url="http://attacker.example.com")
    resp = client.get("/api/v1/preflight", headers=_auth())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


def test_loopback_host_allowed_with_token() -> None:
    # Preflight stub raises, but reaching it means access control let us through;
    # an unhandled error is mapped to 500 envelope, not 401/403.
    resp = _client().get("/api/v1/preflight", headers=_auth())
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "internal_error"


def test_localhost_host_allowed() -> None:
    resp = _client(host="localhost").get("/api/v1/preflight", headers=_auth())
    # 500 (stub raises) — but not a 401/403, proving localhost is loopback.
    assert resp.status_code == 500


# ── Token requirement ────────────────────────────────────────────────────────


def test_missing_token_rejected_401() -> None:
    resp = _client().get("/api/v1/preflight")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_wrong_token_rejected_401() -> None:
    resp = _client().get("/api/v1/preflight", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


def test_x_dkmv_token_header_accepted() -> None:
    resp = _client().get("/api/v1/preflight", headers={"X-DKMV-Token": _TOKEN})
    assert resp.status_code == 500  # passed auth, stub raised


def test_healthz_is_token_exempt() -> None:
    resp = _client().get("/api/v1/healthz")
    assert resp.status_code == 200


# ── Origin / Referer validation ──────────────────────────────────────────────


def test_foreign_origin_rejected_403() -> None:
    headers = {**_auth(), "Origin": "https://evil.example.com"}
    resp = _client().get("/api/v1/preflight", headers=headers)
    assert resp.status_code == 403


def test_loopback_origin_allowed() -> None:
    headers = {**_auth(), "Origin": "http://127.0.0.1:8787"}
    resp = _client().get("/api/v1/preflight", headers=headers)
    assert resp.status_code == 500  # passed access control, stub raised


def test_foreign_referer_rejected_403() -> None:
    headers = {**_auth(), "Referer": "https://evil.example.com/x"}
    resp = _client().get("/api/v1/preflight", headers=headers)
    assert resp.status_code == 403


# ── CSRF on state-changing methods ───────────────────────────────────────────


def test_form_encoded_post_rejected_403_csrf() -> None:
    resp = _client().post(
        "/api/v1/_echo",
        headers={**_auth(), "Content-Type": "application/x-www-form-urlencoded"},
        content="a=b",
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


def test_multipart_post_rejected_403_csrf() -> None:
    resp = _client().post(
        "/api/v1/_echo",
        headers=_auth(),
        files={"f": ("x.txt", b"data")},
    )
    assert resp.status_code == 403


def test_json_post_allowed() -> None:
    resp = _client().post("/api/v1/_echo", headers=_auth(), json={})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_csrf_check_runs_before_auth_on_form_post() -> None:
    # A form POST without a token is still rejected as 403 (origin/CSRF gate is
    # ahead of the token check), not 401.
    resp = _client().post(
        "/api/v1/_echo",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        content="a=b",
    )
    assert resp.status_code == 403
