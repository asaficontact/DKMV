"""Security-baseline suite (AC-0.5-5; PRD §13 security profile; US-04, US-23).

Run via ``pytest -q -k security_baseline``. Each test name carries the
``security_baseline`` token so the AC-0.5-5 selector picks the whole suite up.
Covers the five baseline guarantees:

1. **egress denied** — a non-allowlisted host is blocked, an allowlisted one is
   reachable (INV-3).
2. **no secret in events** — a payload carrying every known secret pattern is
   scrubbed before it lands in the append-only ``events`` table (INV-4).
3. **Host/Origin/CSRF reject + missing-token** — 403 / 401 (INV-1).
4. **token scope** — a repo-scoped run token cannot push to a second repo (INV-4).
5. **brokered socket** — the backend never mounts the raw ``docker.sock``; it is
   on the proxy service only (INV-3 / ADR-P005).
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.config import Settings
from app.db import Repository
from app.db.repository import EventRecord
from app.executor.egress import EgressPolicy
from app.main import create_app
from app.runtime import RunService
from app.secrets.github_token import GitHubTokenMinter, TokenScopeError
from app.secrets.redaction import REDACTION_PLACEHOLDER, Redactor
from app.secrets.store import SecretStore
from fastapi import APIRouter
from fastapi.testclient import TestClient

from tests.conftest import StubRuntime, auth_headers, make_settings

_REPO_ROOT = Path(__file__).resolve().parents[3]  # platform/

# Synthetic secret literals shaped like the real credentials (fragment-joined so
# this test file does not itself carry a contiguous secret literal).
_ANTHROPIC = "sk" + "-ant-" + "api03-" + "E" * 40
_GH_CLASSIC = "gh" + "p_" + "F" * 36
_GH_FINE = "github" + "_pat_" + "G" * 40


# ── 1. egress denied ──────────────────────────────────────────────────────────


def test_security_baseline_egress_denies_non_allowlisted_host() -> None:
    policy = EgressPolicy(hosts=("api.github.com", "api.anthropic.com"))
    # Non-allowlisted host BLOCKED.
    assert policy.is_allowed("exfil.attacker.com") is False
    # Allowlisted host reachable.
    assert policy.is_allowed("api.github.com") is True
    assert policy.is_allowed("api.anthropic.com") is True


def test_security_baseline_egress_default_on_never_allow_all() -> None:
    class _Settings:
        egress_hosts: list[str] = []

    policy = EgressPolicy.from_settings(_Settings())
    assert policy.is_allowed("exfil.attacker.com") is False


# ── 2. no secret in events ────────────────────────────────────────────────────


async def test_security_baseline_no_secret_value_in_events(database_url: str) -> None:
    redactor = Redactor(known_values=["nonstandard-shaped-secret-xyz12345"])
    repository = Repository(database_url, redactor=redactor)
    await repository.start()
    try:
        # Events FK → runs(id); claim a run first.
        run_id, _ = await repository.claim_run(idempotency_key="sec-key", repo="o/r")
        record = EventRecord(
            run_id=run_id,
            sequence=1,
            event_type="assistant_message",
            payload={
                "text": f"leaking {_ANTHROPIC} and {_GH_CLASSIC} and {_GH_FINE}",
                "nested": {"v": "nonstandard-shaped-secret-xyz12345"},
            },
        )
        await repository.append_events([record])

        rows = await repository.read_events_after(run_id, 0)
        assert len(rows) == 1
        persisted = rows[0]["payload_json"]
        # Whatever the agent emitted, NO secret value reaches the events table.
        for secret in (_ANTHROPIC, _GH_CLASSIC, _GH_FINE, "nonstandard-shaped-secret-xyz12345"):
            assert secret not in persisted
        # And the structure is still intact (redaction does not corrupt the row).
        parsed = json.loads(persisted)
        assert "text" in parsed
    finally:
        await repository.close()


# ── 2b. no secret in LOGS (boot path: filter is attached by create_app) ───────


@pytest.fixture
def _isolated_root_logger() -> Iterator[None]:
    """Snapshot + restore the root logger's filters/handlers around a test.

    ``create_app()`` attaches a process-wide :class:`RedactingLogFilter` to the
    root logger; this fixture removes anything the test added so the filter does
    not leak into (or accumulate across) other tests.
    """
    root = logging.getLogger()
    before_filters = list(root.filters)
    before_handlers = list(root.handlers)
    before_level = root.level
    try:
        yield
    finally:
        for flt in list(root.filters):
            if flt not in before_filters:
                root.removeFilter(flt)
        for hdl in list(root.handlers):
            if hdl not in before_handlers:
                root.removeHandler(hdl)
        root.setLevel(before_level)


def test_security_baseline_create_app_scrubs_secrets_from_logs(
    _isolated_root_logger: None,
) -> None:
    """create_app() must attach the RedactingLogFilter to the ROOT logger.

    This exercises the BOOT PATH end-to-end (not the filter in isolation): we
    build the real app, then emit a log record carrying every known secret —
    both by *shape* (sk-ant-…, ghp_…, github_pat_…) and by the platform's OWN
    concrete *values* (settings-seeded) — through the standard logging pipeline
    and assert the EMITTED output is scrubbed. If create_app() did not wire the
    filter (the prior gap), the secrets would survive and this test would fail.
    """
    # Platform's own concrete secret VALUES (non-standard shapes on purpose, so
    # only the settings-seeded known-value scrub — not the pattern scrub — can
    # catch them). Proves Redactor.from_settings(settings) was used at boot.
    own_github = "operator-github-pat-value-12345"
    own_anthropic = "operator-anthropic-key-value-67890"
    own_codex = "operator-codex-key-value-abcdef"
    own_platform = "operator-platform-token-value-xyz"
    settings = make_settings(
        GITHUB_TOKEN=own_github,
        ANTHROPIC_API_KEY=own_anthropic,
        CODEX_API_KEY=own_codex,
        DKMV_PLATFORM_TOKEN=own_platform,
    )

    # Configure the root handler that captures log output FIRST — mirroring boot
    # ordering, where the process's logging handlers exist (uvicorn/log config)
    # before the app factory runs. A child module-logger ("app.test.boot_path")
    # propagates its records up to this root handler.
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)

    # Build the real app — this is the step under test. create_app() must attach
    # the settings-seeded RedactingLogFilter to the root logger + its handlers,
    # so the records reaching the buffer below are scrubbed.
    create_app(
        settings,
        run_service=RunService(settings, runtime=StubRuntime()),  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed stub
    )

    logger = logging.getLogger("app.test.boot_path")
    secrets_by_shape = (_ANTHROPIC, _GH_CLASSIC, _GH_FINE)
    secrets_by_value = (own_github, own_anthropic, own_codex, own_platform)
    for secret in (*secrets_by_shape, *secrets_by_value):
        logger.info("emitting credential: %s", secret)
    handler.flush()

    emitted = buffer.getvalue()
    # NOT one secret — shape OR value — survives into the emitted log output.
    for secret in (*secrets_by_shape, *secrets_by_value):
        assert secret not in emitted, f"secret leaked into logs: {secret!r}"
    # And redaction actually happened (sanity: the placeholder is present).
    assert REDACTION_PLACEHOLDER in emitted


# ── 3. Host/Origin/CSRF reject + missing-token ───────────────────────────────


def _app(settings: Settings | None = None) -> Any:
    settings = settings or make_settings()
    run_service = RunService(settings, runtime=StubRuntime())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed stub
    app = create_app(settings, run_service=run_service)
    router = APIRouter(prefix="/api/v1")

    @router.post("/_echo")
    def _echo() -> dict[str, bool]:  # pragma: no cover - reached only past access control
        return {"ok": True}

    app.include_router(router)
    return app


def test_security_baseline_foreign_host_rejected_403() -> None:
    client = TestClient(_app(), base_url="http://attacker.example.com")
    resp = client.get("/api/v1/preflight", headers=auth_headers())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


def test_security_baseline_foreign_origin_rejected_403() -> None:
    client = TestClient(_app(), base_url="http://127.0.0.1")
    resp = client.get(
        "/api/v1/preflight",
        headers={**auth_headers(), "Origin": "http://attacker.example.com"},
    )
    assert resp.status_code == 403


def test_security_baseline_csrf_form_post_rejected_403() -> None:
    client = TestClient(_app(), base_url="http://127.0.0.1", raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/_echo",
        headers={**auth_headers(), "Content-Type": "application/x-www-form-urlencoded"},
        data="x=1",
    )
    assert resp.status_code == 403


def test_security_baseline_missing_token_rejected_401() -> None:
    client = TestClient(_app(), base_url="http://127.0.0.1", raise_server_exceptions=False)
    resp = client.get("/api/v1/preflight")
    assert resp.status_code == 401


# ── 4. token scope ────────────────────────────────────────────────────────────


async def test_security_baseline_token_cannot_push_to_second_repo() -> None:
    store = SecretStore(key=SecretStore.generate_key())
    minter = GitHubTokenMinter(store, base_token="ghp-operator-pat")
    token = await minter.mint("octo/target-repo", run_id="run-1")
    # Authorized for its own repo.
    token.authorize_push("octo/target-repo")
    # Refused for any other repo (the prompt-injection containment guarantee).
    with pytest.raises(TokenScopeError):
        token.authorize_push("octo/other-repo")


# ── 5. brokered socket (backend has no direct docker.sock) ────────────────────


def test_security_baseline_backend_has_no_raw_docker_socket() -> None:
    compose = yaml.safe_load((_REPO_ROOT / "docker-compose.yml").read_text())
    services = compose["services"]
    sock = "/var/run/docker.sock"

    def _mounts_sock(service: dict[str, Any]) -> bool:
        return any(sock in str(vol) for vol in service.get("volumes", []) or [])

    # The socket is mounted on EXACTLY the proxy, never the backend (ADR-P005).
    assert _mounts_sock(services["docker-proxy"])
    assert not _mounts_sock(services["backend"])
    # The backend reaches Docker through the brokered proxy.
    assert services["backend"]["environment"]["DOCKER_HOST"].startswith("tcp://docker-proxy")
