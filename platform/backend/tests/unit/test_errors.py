"""AC-0.2-5: API error envelope + status-code conventions (§8.9).

Asserts a validation failure → ``400 {"error":{"code":"validation_error",...}}``
and an unknown run → ``404 {"error":{"code":"run_not_found", ...}}`` (and an
unknown issue → ``issue_not_found``) through the installed exception handlers,
plus the factory/envelope unit behavior. Pins the **semantic 404 contract**:
domain 404s carry a specific top-level code (``run_not_found`` /
``issue_not_found``); the generic ``not_found`` code is reserved for the
framework fallback (unmatched route / bare ``HTTPException(404)``).
"""

from __future__ import annotations

from typing import Any

from app.api.errors import (
    NOT_FOUND_CODE,
    ApiError,
    install_error_handlers,
    issue_not_found,
    not_found,
    run_not_found,
    validation_error,
)
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel


def _envelope_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    router = APIRouter(prefix="/api/v1")

    class _Body(BaseModel):
        n: int

    @router.post("/_validate")
    def _validate(body: _Body) -> dict[str, int]:  # pragma: no cover - body invalid path
        return {"n": body.n}

    @router.get("/runs/{run_id}")
    def _get_run(run_id: str) -> dict[str, str]:
        # Phase 0 has no DB; emulate "unknown run" → 404 envelope.
        raise run_not_found(run_id)

    @router.get("/_boom")
    def _boom() -> dict[str, str]:
        raise RuntimeError("unexpected")

    @router.get("/_framework_404")
    def _framework_404() -> dict[str, str]:
        # Non-string detail forces the handler's message-fallback branch.
        raise HTTPException(status_code=404, detail={"why": "structured"})

    app.include_router(router)
    return app


def _client() -> TestClient:
    # raise_server_exceptions=False so the installed Exception handler turns an
    # uncaught error into the 500 envelope rather than re-raising into the test.
    return TestClient(_envelope_app(), raise_server_exceptions=False)


# ── §8.9 status + envelope ───────────────────────────────────────────────────


def test_validation_error_400_envelope() -> None:
    resp = _client().post("/api/v1/_validate", json={"n": "not-an-int"})
    assert resp.status_code == 400
    body: dict[str, Any] = resp.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "validation_error"
    assert "message" in body["error"]
    assert "fields" in body["error"]["details"]


def test_run_not_found_404_envelope() -> None:
    # AC-0.2-5 (literal): an unknown run returns the *semantic* top-level code
    # ``run_not_found`` (not the generic ``not_found``), with a resource hint.
    resp = _client().get("/api/v1/runs/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "run_not_found"
    assert body["error"]["details"]["resource"] == "run"
    assert "does-not-exist" in body["error"]["message"]


def test_unhandled_error_500_no_leak() -> None:
    resp = _client().get("/api/v1/_boom")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "internal_error"
    # The raised message must not leak into the response.
    assert "unexpected" not in body["error"]["message"]


def test_unmatched_route_404_uses_generic_framework_code() -> None:
    # Framework 404 (unmatched route) carries the *generic* ``not_found`` code —
    # the fallback reserved for routes no domain helper produced.
    resp = _client().get("/api/v1/nope")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == NOT_FOUND_CODE


def test_framework_404_with_structured_detail_falls_back_to_clean_message() -> None:
    # When the framework HTTPException carries a non-string detail, the handler
    # uses the clean human-message fallback (not the code, not the raw detail).
    resp = _client().get("/api/v1/_framework_404")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == NOT_FOUND_CODE
    assert body["error"]["message"] == "Not found"


# ── Factory / envelope unit behavior ─────────────────────────────────────────


def test_not_found_factories_use_semantic_top_level_codes() -> None:
    # Factory-level (AC-0.2-5): the generic helper keeps ``not_found`` (framework
    # fallback), but the domain helpers carry their own semantic top-level code.
    generic = not_found().to_envelope()["error"]
    assert generic["code"] == NOT_FOUND_CODE
    assert generic["code"] == "not_found"
    assert "details" not in generic  # no resource → no details key

    run = run_not_found("r1").to_envelope()["error"]
    assert run["code"] == "run_not_found"
    assert run["details"] == {"resource": "run"}

    issue = issue_not_found("acme/widget", 7).to_envelope()["error"]
    assert issue["code"] == "issue_not_found"
    assert issue["details"] == {"resource": "issue"}


def test_envelope_includes_details_only_when_present() -> None:
    bare = ApiError(409, "duplicate_dispatch", "dup").to_envelope()
    assert bare == {"error": {"code": "duplicate_dispatch", "message": "dup"}}
    with_details = validation_error("bad", details={"field": "x"}).to_envelope()
    assert with_details["error"]["details"] == {"field": "x"}


def test_error_headers_propagate() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/x")
    def _x() -> dict[str, str]:
        raise ApiError(
            429,
            "rate_limited",
            "slow down",
            headers={"Retry-After": "30"},
        )

    resp = TestClient(app).get("/x")
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "30"
    assert resp.json()["error"]["code"] == "rate_limited"
