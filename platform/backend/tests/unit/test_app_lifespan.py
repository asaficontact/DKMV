"""Slice 2.0 — the app-lifespan composes + tears down the shared singletons.

Phase 1 built the Repository per request (a TestClient stale-loop workaround).
Phase 2's SSE pump (2.3) is a long-lived per-run task that must write through
ONE shared Repository, and the SQLite single-writer contract (INV-6) requires
exactly ONE writer task per process. This slice composes those singletons in a
FastAPI lifespan; these tests lock that in:

* the lifespan puts ONE :class:`Repository` / :class:`SecretStore` /
  :class:`WriteQueue` / GitHub client on ``app.state`` (and the API endpoints
  reuse them — no per-request build);
* the Repository is seeded with ``Redactor.from_settings`` so the **append-only
  events path** scrubs the platform's OWN concrete secret VALUES, not just their
  shapes (the INV-4 backstop slice 0.5 deferred here);
* shutdown tears everything down cleanly (the single writer task is stopped).

Built over a real, migrated SQLite DB; nothing reaches into ``dkmv/``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from app.config import Settings
from app.db import EventRecord, Repository
from app.github.write_queue import WriteQueue
from app.main import create_app
from app.secrets import REDACTION_PLACEHOLDER, Redactor, SecretStore
from fastapi.testclient import TestClient

from tests.conftest import TEST_TOKEN, _migrate

# A concrete, non-standard-shaped secret VALUE the platform holds. Its *shape*
# would NOT be caught by the pattern redactor (it is not a sk-ant-/ghp_/… token)
# — only the known-value backstop (seeded from settings via the lifespan) scrubs
# it. So redaction here proves the events path got the settings-seeded redactor,
# not the pattern-only default.
_KNOWN_VALUE_SECRET = "totally-bespoke-anthropic-key-NONSTANDARD-shape-1234567890"  # noqa: S105


def _settings_with_secret() -> Settings:
    fd, path = tempfile.mkstemp(prefix="dkmvp-lifespan-", suffix=".db")
    os.close(fd)
    url = _migrate(Path(path))
    return Settings(  # type: ignore[call-arg]  # DKMVP-ESCAPE: pydantic-settings injected kwargs
        _env_file=None,
        DKMV_PLATFORM_TOKEN=TEST_TOKEN,
        DATABASE_URL=url,
        ANTHROPIC_API_KEY=_KNOWN_VALUE_SECRET,
    )


def test_lifespan_composes_one_of_each_singleton() -> None:
    """Startup puts exactly one Repository/SecretStore/WriteQueue/client on state."""
    settings = _settings_with_secret()
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1"):
        assert isinstance(app.state.repository, Repository)
        assert isinstance(app.state.secret_store, SecretStore)
        assert isinstance(app.state.github_write_queue, WriteQueue)
        assert app.state.github_client is not None
        # The SecretStore is wired to the SAME shared Repository (not an
        # ephemeral per-request store) — INV-4 persistence through the one DB.
        assert app.state.secret_store._repository is app.state.repository


def test_lifespan_seeds_redactor_from_settings_known_values() -> None:
    """The lifespan seeds the Repository redactor with the settings secret VALUES.

    This is the wiring half of the INV-4 events-path backstop: the lifespan must
    construct the Repository with ``Redactor.from_settings(settings)`` so the
    redactor knows the platform's concrete secret values (not just shapes).
    """
    settings = _settings_with_secret()
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1"):
        repository: Repository = app.state.repository
        assert _KNOWN_VALUE_SECRET in repository._redactor._known_values


@pytest.mark.asyncio
async def test_events_path_known_value_backstop_redacts() -> None:
    """INV-4: the events path scrubs the platform's OWN concrete secret VALUE.

    Drives a write through a Repository built EXACTLY as the lifespan builds it
    (``Redactor.from_settings(settings)``). A bespoke (non-standard-shaped) secret
    the platform holds must be redacted before it lands in the append-only
    ``events`` table — proving the known-value backstop slice 0.5 deferred to the
    lifespan is active on the events path, not just the pattern-only default.
    """
    settings = _settings_with_secret()
    repository = Repository(settings.DATABASE_URL, redactor=Redactor.from_settings(settings))
    await repository.start()
    try:
        run_id, won = await repository.claim_run(
            idempotency_key="lifespan#redact", repo="o/r", agent="claude"
        )
        assert won
        await repository.append_events(
            [
                EventRecord(
                    run_id=run_id,
                    sequence=0,
                    event_type="assistant",
                    # The secret embedded in an event payload (an agent echoing a
                    # credential it was handed).
                    payload={"content": f"leaked {_KNOWN_VALUE_SECRET} here"},
                    task_index=0,
                )
            ]
        )
        rows = await repository.read_events_after(run_id, last_id=0)
        persisted = rows[0]["payload_json"]
        assert _KNOWN_VALUE_SECRET not in persisted
        assert REDACTION_PLACEHOLDER in persisted
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_lifespan_shutdown_stops_the_single_writer() -> None:
    """Shutdown closes the Repository → the single writer task is stopped (INV-6).

    After the lifespan exits, the shared Repository's writer is no longer started,
    so a fresh ``submit`` would raise — there is no orphaned writer task left
    running on a dead loop.
    """
    settings = _settings_with_secret()
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1"):
        repository: Repository = app.state.repository
        assert repository._started is True
    # Lifespan exited → Repository.close() ran.
    assert repository._started is False
