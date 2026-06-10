"""G8 — ephemeral SecretStore key foot-gun: loud boot WARN + preflight row.

When ``DKMV_SECRET_KEY`` is unset the SecretStore uses a freshly-GENERATED ephemeral
key each boot, so the connected GitHub PAT becomes undecryptable after a restart — a
silent day-2 data-losing surprise. These tests lock in:

* ``app.main._build_secret_store`` emits a LOUD ``WARNING`` when the key is ephemeral
  (DKMV_SECRET_KEY unset) and is SILENT when a durable key is configured;
* the WARN never logs the key VALUE (INV-4);
* ``secret_key_is_ephemeral`` reflects env / settings presence;
* the ``GET /preflight`` informational ``secret_key`` row reports persistent vs.
  ephemeral (and is never a blocker).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from app.api.deps import secret_key_is_ephemeral
from app.config import Settings
from app.main import _build_secret_store
from app.secrets import SecretStore
from dkmv.runtime import CapabilityReport

from tests.conftest import FakeRuntime, auth_headers, build_client, make_settings

# A durable key VALUE the WARN/log must never echo (a real Fernet key shape).
_DURABLE_KEY = SecretStore.generate_key()


class _RecordCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@contextmanager
def _capture_main_logs() -> Iterator[_RecordCollector]:
    """Capture all ``app.main`` records order-independently (like test_executor).

    ``caplog`` relies on root-logger propagation, which a stray process-wide
    ``logging.disable()`` / ``disable_existing_loggers`` from another suite module
    can mute. Attach our OWN handler directly to ``app.main``, clear any disable for
    the capture, and restore after — so the WARN assertion is deterministic.
    """
    collector = _RecordCollector()
    lg = logging.getLogger("app.main")
    prev_level = lg.level
    prev_disabled = lg.disabled
    prev_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    lg.disabled = False
    lg.setLevel(logging.DEBUG)
    lg.addHandler(collector)
    try:
        yield collector
    finally:
        lg.removeHandler(collector)
        lg.setLevel(prev_level)
        lg.disabled = prev_disabled
        logging.disable(prev_disable)


class _NullRepo:
    """Minimal stand-in: ``_build_secret_store`` only passes it to SecretStore."""


def _settings(*, key: str | None) -> Settings:
    kwargs: dict[str, object] = {}
    if key is not None:
        kwargs["DKMV_SECRET_KEY"] = key
    return make_settings(**kwargs)


# ── secret_key_is_ephemeral predicate ────────────────────────────────────────


def test_predicate_ephemeral_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DKMV_SECRET_KEY", raising=False)
    assert secret_key_is_ephemeral(_settings(key=None)) is True


def test_predicate_persistent_when_settings_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DKMV_SECRET_KEY", raising=False)
    assert secret_key_is_ephemeral(_settings(key=_DURABLE_KEY)) is False


def test_predicate_persistent_when_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DKMV_SECRET_KEY", _DURABLE_KEY)
    assert secret_key_is_ephemeral(_settings(key=None)) is False


# ── the loud boot WARN (and its silence when a key is set) ───────────────────


def test_warn_fires_when_key_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DKMV_SECRET_KEY", raising=False)
    with _capture_main_logs() as logs:
        _build_secret_store(_NullRepo(), _settings(key=None))  # type: ignore[arg-type]  # DKMVP-ESCAPE: SecretStore only stores the repo handle
    assert any("DKMV_SECRET_KEY is not set" in m for m in logs.messages)
    assert any("will NOT survive a restart" in m for m in logs.messages)


def test_no_warn_when_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DKMV_SECRET_KEY", raising=False)
    with _capture_main_logs() as logs:
        _build_secret_store(_NullRepo(), _settings(key=_DURABLE_KEY))  # type: ignore[arg-type]  # DKMVP-ESCAPE: SecretStore only stores the repo handle
    assert not [m for m in logs.messages if "DKMV_SECRET_KEY is not set" in m]


def test_warn_never_logs_the_key_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """INV-4: even when a durable key IS configured, no path logs its value."""
    monkeypatch.delenv("DKMV_SECRET_KEY", raising=False)
    with _capture_main_logs() as logs:
        _build_secret_store(_NullRepo(), _settings(key=_DURABLE_KEY))  # type: ignore[arg-type]  # DKMVP-ESCAPE: SecretStore only stores the repo handle
    for message in logs.messages:
        assert _DURABLE_KEY not in message


# ── the informational preflight row ──────────────────────────────────────────


def _ready_report() -> CapabilityReport:
    return CapabilityReport(
        version="9.9.9",
        docker_available=True,
        docker_version="27.0.0",
        image_exists=True,
        image_name="dkmv-sandbox:latest",
        available_agents=["claude"],
        has_anthropic_key=True,
        has_github_token=True,
        has_codex_key=False,
    )


def _secret_row(body: dict[str, object]) -> dict[str, object]:
    rows = [r for r in body["checks"] if r["id"] == "secret_key"]  # type: ignore[union-attr,index]
    assert len(rows) == 1
    return rows[0]


def test_preflight_row_ephemeral(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DKMV_SECRET_KEY", raising=False)
    client = build_client(
        settings=_settings(key=None),
        runtime=FakeRuntime(_ready_report()),
    )
    body = client.get("/api/v1/preflight", headers=auth_headers()).json()
    row = _secret_row(body)
    assert row["ok"] is False
    assert "ephemeral" in row["sub"]  # type: ignore[operator]
    # Informational only — must NEVER flip ready / appear in blockers.
    assert row["label"] not in body["blockers"]  # type: ignore[operator]


def test_preflight_row_persistent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DKMV_SECRET_KEY", raising=False)
    client = build_client(
        settings=_settings(key=_DURABLE_KEY),
        runtime=FakeRuntime(_ready_report()),
    )
    body = client.get("/api/v1/preflight", headers=auth_headers()).json()
    row = _secret_row(body)
    assert row["ok"] is True
    assert "persistent" in row["sub"]  # type: ignore[operator]
    # The key value never reaches the response.
    assert _DURABLE_KEY not in client.get("/api/v1/preflight", headers=auth_headers()).text
