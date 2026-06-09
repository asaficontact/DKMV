"""The app-lifespan starts + stops the orchestrator tick loop (slice 3.3 — AC-10).

The tick loop is a long-lived tracked :class:`asyncio.Task` started in
``app.main._lifespan`` once a project repo is known, and **cancelled on shutdown**.
These tests lock that wiring in over a real migrated DB + a stub engine (no Docker):

* a project seeded in the DB → the lifespan starts the orchestrator (the handle is
  on ``app.state.orchestrator`` and its task is live), and shutdown stops it;
* no project connected → the lifespan skips it (``app.state.orchestrator is None``)
  so a fresh install never starts a loop with nothing to poll.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pytest
from app.config import Settings
from app.db import Repository
from app.main import create_app
from app.orchestrator.tick import OrchestratorHandle
from fastapi.testclient import TestClient

from tests.conftest import TEST_TOKEN, _migrate

pytestmark = pytest.mark.asyncio


class _StubRuntime:
    class _Report:
        ready = True

    class _Runtime:
        def get_handle(self, _engine_run_id: str) -> None:
            return None

    runtime = _Runtime()

    def get_capabilities(self) -> Any:
        return self._Report()


def _settings(url: str) -> Settings:
    return Settings(  # type: ignore[call-arg]  # DKMVP-ESCAPE: pydantic-settings injected kwargs
        _env_file=None,
        DKMV_PLATFORM_TOKEN=TEST_TOKEN,
        DATABASE_URL=url,
        TICK_INTERVAL_S=1,
    )


def _fresh_url() -> str:
    fd, path = tempfile.mkstemp(prefix="dkmvp-orch-", suffix=".db")
    os.close(fd)
    return _migrate(Path(path))


async def test_lifespan_starts_orchestrator_when_project_exists() -> None:
    url = _fresh_url()
    # Seed a connected project so the lifespan resolves a repo to poll.
    repository = Repository(url)
    await repository.start()
    await repository.upsert_project(project_id="p1", repo="octo/widgets")
    await repository.close()

    from app.runtime import RunService

    settings = _settings(url)
    run_service = RunService(settings, runtime=_StubRuntime())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed runtime stub
    app = create_app(settings, run_service=run_service)
    with TestClient(app, base_url="http://127.0.0.1"):
        handle = app.state.orchestrator
        assert isinstance(handle, OrchestratorHandle)
        assert not handle.task.done()  # the loop task is live
        assert handle.deps.repo == "octo/widgets"
    # After shutdown the orchestrator task is cancelled/stopped.
    assert handle.task.done()


async def test_lifespan_skips_orchestrator_without_a_project() -> None:
    url = _fresh_url()  # migrated but no projects row
    from app.runtime import RunService

    settings = _settings(url)
    run_service = RunService(settings, runtime=_StubRuntime())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed runtime stub
    app = create_app(settings, run_service=run_service)
    with TestClient(app, base_url="http://127.0.0.1"):
        assert app.state.orchestrator is None  # nothing to poll → no loop
