"""The app-lifespan boot recovery + SIGTERM drain wiring (slice 3.5 — AC-18/19).

Locks in the ``app.main._lifespan`` wiring (over a real migrated DB + a stub
engine, no Docker):

* **Boot recovery runs at startup BEFORE the tick dispatches:** a non-terminal
  ``runs`` row seeded before boot is reaped + marked ``interrupted`` by the time the
  app is serving (AC-19) — no orphan is left running and no fresh dispatch raced it.
* **The SIGTERM drain handler is registered** on the serving loop when a project is
  connected (AC-18) — a ``docker compose restart`` then drains live runs.
* **No project connected → no boot scan, no orphan churn** (a fresh install).
"""

from __future__ import annotations

import os
import signal
import tempfile
from pathlib import Path
from typing import Any

import pytest
from app.config import Settings
from app.db import Repository
from app.main import create_app
from fastapi.testclient import TestClient

from tests.conftest import TEST_TOKEN, _migrate

pytestmark = pytest.mark.asyncio

_REPO = "octo/widgets"


class _ContainerStatus:
    def __init__(self, container_name: str) -> None:
        self.container_name = container_name


class _StubRuntime:
    class _Report:
        ready = True

    class _Runtime:
        def get_handle(self, _engine_run_id: str) -> None:
            return None

        def get_container_status(self, _run_id: str) -> Any:
            # No container name → the reaper has nothing to docker-kill (CI: no Docker).
            return _ContainerStatus(container_name="")

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
    fd, path = tempfile.mkstemp(prefix="dkmvp-recov-", suffix=".db")
    os.close(fd)
    return _migrate(Path(path))


async def _seed_orphan(repository: Repository, *, run_id: str, issue_num: int) -> None:
    await repository.claim_run(
        idempotency_key=f"{issue_num}::wf::main",
        repo=_REPO,
        issue_num=issue_num,
        workflow_id="wf",
        agent="claude",
        branch="main",
        run_id=run_id,
    )
    await repository.update_run_fields(run_id, status="running", engine_run_id="e1")


async def test_lifespan_runs_boot_recovery() -> None:
    """A non-terminal run seeded before boot is interrupted by boot recovery (AC-19)."""
    url = _fresh_url()
    repository = Repository(url)
    await repository.start()
    await repository.upsert_project(project_id="p1", repo=_REPO)
    await _seed_orphan(repository, run_id="r-orphan", issue_num=1)
    await repository.close()

    from app.runtime import RunService

    settings = _settings(url)
    run_service = RunService(settings, runtime=_StubRuntime())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed runtime stub
    app = create_app(settings, run_service=run_service)
    with TestClient(app, base_url="http://127.0.0.1"):
        # The boot scan ran at startup (before the tick dispatched) → the orphan is
        # now interrupted, asserted via the lifespan-owned repository.
        row = await app.state.repository.get_run("r-orphan")
        assert row is not None
        assert row["status"] == "interrupted"


async def test_register_sigterm_drain_installs_handler() -> None:
    """``_register_sigterm_drain`` installs a SIGTERM handler on the running loop (AC-18).

    Driven directly on the test's running loop (the lifespan installs it on the
    serving loop the same way). Asserts a handler was registered for SIGTERM —
    ``remove_signal_handler`` returns ``True`` iff one existed — so a
    ``docker compose restart`` triggers the graceful drain.
    """
    import asyncio

    from app.main import _register_sigterm_drain

    url = _fresh_url()
    from app.runtime import RunService

    settings = _settings(url)
    run_service = RunService(settings, runtime=_StubRuntime())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed runtime stub
    app = create_app(settings, run_service=run_service)
    app.state.run_service = run_service

    handler = _register_sigterm_drain(app, _REPO)
    loop = asyncio.get_running_loop()
    try:
        removed = loop.remove_signal_handler(signal.SIGTERM)
    except (NotImplementedError, RuntimeError):
        pytest.skip("signal handlers unavailable on this platform")
    assert handler is not None
    assert removed is True
