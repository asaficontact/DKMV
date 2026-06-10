"""AC-0.2-3: GET /api/v1/preflight renders get_capabilities() in the §8.9 shape.

Asserts the ``{ ready, checks:[{id,label,sub,ok}], blockers }`` envelope, the
``ready``/``blockers`` derivation from hard-requirement rows, and that no
credential *value* is echoed (only present/missing).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.api.preflight import build_preflight_payload
from dkmv.runtime import CapabilityReport
from fastapi.testclient import TestClient

from tests.conftest import FakeRuntime, auth_headers, build_client

# The conftest autouse ``_gvisor_available_by_default`` patches ``runtime_available``
# → True for the whole suite (a properly-provisioned host); the fail-closed blocker
# is asserted explicitly in ``test_sandbox_runtime_blocker_when_runsc_missing``.


def _ready_report() -> CapabilityReport:
    return CapabilityReport(
        version="9.9.9",
        docker_available=True,
        docker_version="27.0.0",
        image_exists=True,
        image_name="dkmv-sandbox:latest",
        available_agents=["claude", "codex"],
        has_anthropic_key=True,
        has_github_token=True,
        has_codex_key=False,
    )


def _client(report: CapabilityReport) -> TestClient:
    return build_client(runtime=FakeRuntime(report), raise_server_exceptions=True)


def _auth() -> dict[str, str]:
    return auth_headers()


# ── Envelope shape (AC-0.2-3) ────────────────────────────────────────────────


def test_envelope_shape() -> None:
    body: dict[str, Any] = _client(_ready_report()).get("/api/v1/preflight", headers=_auth()).json()
    assert set(body) == {"ready", "checks", "blockers"}
    assert isinstance(body["checks"], list) and body["checks"]
    for row in body["checks"]:
        assert set(row) == {"id", "label", "sub", "ok"}
        assert isinstance(row["id"], str)
        assert isinstance(row["label"], str)
        assert isinstance(row["ok"], bool)
    assert isinstance(body["blockers"], list)


def test_ready_true_when_hard_requirements_met() -> None:
    resp = _client(_ready_report()).get("/api/v1/preflight", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["blockers"] == []


def test_blocker_when_image_missing() -> None:
    report = _ready_report()
    report.image_exists = False
    body = build_preflight_payload(report)
    assert body["ready"] is False
    assert "Sandbox image present" in body["blockers"]


def test_blocker_when_no_model_credential() -> None:
    report = _ready_report()
    report.has_anthropic_key = False
    report.has_codex_key = False
    body = build_preflight_payload(report)
    assert body["ready"] is False
    assert "Model credential present" in body["blockers"]


def test_codex_key_alone_satisfies_model_credential() -> None:
    report = _ready_report()
    report.has_anthropic_key = False
    report.has_codex_key = True
    body = build_preflight_payload(report)
    assert "Model credential present" not in body["blockers"]


def test_github_not_a_hard_blocker() -> None:
    report = _ready_report()
    report.has_github_token = False
    body = build_preflight_payload(report)
    # GitHub row is present and not-ok, but it is not a blocker.
    gh = next(c for c in body["checks"] if c["id"] == "github_token")
    assert gh["ok"] is False
    assert "GitHub connected" not in body["blockers"]


def test_no_credential_value_leaked() -> None:
    # The 'sub' fields must never carry an actual key value — only present/missing.
    report = _ready_report()
    body = build_preflight_payload(report)
    subs = {c["id"]: c["sub"] for c in body["checks"]}
    assert subs["anthropic_key"] in {"present", "missing"}
    assert subs["github_token"] in {"present", "missing"}


# ── G1: gVisor sandbox-runtime preflight row ─────────────────────────────────


def test_sandbox_runtime_row_present_and_ok_on_gvisor_host() -> None:
    body = _client(_ready_report()).get("/api/v1/preflight", headers=_auth()).json()
    row = next(c for c in body["checks"] if c["id"] == "sandbox_runtime")
    assert row["ok"] is True
    assert "Sandbox isolation (gVisor)" not in body["blockers"]


def test_sandbox_runtime_blocker_when_runsc_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fail-closed (G1): runsc required but unavailable + no opt-in → hard blocker.
    monkeypatch.setattr("app.executor.runtime_policy.runtime_available", lambda *a, **k: False)
    body = _client(_ready_report()).get("/api/v1/preflight", headers=_auth()).json()
    row = next(c for c in body["checks"] if c["id"] == "sandbox_runtime")
    assert row["ok"] is False
    assert "Sandbox isolation (gVisor)" in body["blockers"]
    assert body["ready"] is False
