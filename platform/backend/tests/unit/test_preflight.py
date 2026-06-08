"""AC-0.2-3: GET /api/v1/preflight renders get_capabilities() in the §8.9 shape.

Asserts the ``{ ready, checks:[{id,label,sub,ok}], blockers }`` envelope, the
``ready``/``blockers`` derivation from hard-requirement rows, and that no
credential *value* is echoed (only present/missing).
"""

from __future__ import annotations

from typing import Any

from app.api.preflight import build_preflight_payload
from app.config import Settings
from app.main import create_app
from app.runtime import RunService
from dkmv.runtime import CapabilityReport
from fastapi.testclient import TestClient

_TOKEN = "preflight-token"  # noqa: S105 - test fixture, not a real secret


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


class _FakeRuntime:
    def __init__(self, report: CapabilityReport) -> None:
        self._report = report

    def get_capabilities(self) -> CapabilityReport:
        return self._report


def _client(report: CapabilityReport) -> TestClient:
    settings = Settings(_env_file=None, DKMV_PLATFORM_TOKEN=_TOKEN)  # type: ignore[call-arg]  # DKMVP-ESCAPE: pydantic-settings injected kwargs
    run_service = RunService(settings, runtime=_FakeRuntime(report))  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed fake
    app = create_app(settings, run_service=run_service)
    return TestClient(app, base_url="http://127.0.0.1")


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {_TOKEN}"}


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
