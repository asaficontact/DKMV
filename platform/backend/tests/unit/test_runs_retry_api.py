"""Slice 3.4 — ``POST /runs/{id}/retry`` + the populated ``GET /retry-queue`` (AC-16/AC-4).

* ``POST /runs/{id}/retry`` on a **failed** run returns ``202`` and enqueues exactly
  one retry; a **second** call while the retry is pending is a **no-op** (still
  ``202``, but the queue still holds **one** entry — no duplicate dispatch, AC-16).
* The retry endpoint is access-controlled (no token → 401) and ``404``s an unknown
  run; a non-retryable (active/completed) run is ``409``.
* ``GET /retry-queue`` is **populated** by the scheduler state the endpoint writes
  (``RetryEntry`` shape — AC-4 / FR-06-3), through the SAME app-state scheduler.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.db import Repository
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, build_client, make_settings

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _run[T](coro: Awaitable[T]) -> T:
    return asyncio.new_event_loop().run_until_complete(coro)


def _migrate(db_path: Path) -> str:
    url = f"sqlite:///{db_path}"
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


async def _seed_run(url: str, *, issue_num: int, status: str) -> str:
    repository = Repository(url)
    await repository.start()
    try:
        run_id, _won = await repository.claim_run(
            idempotency_key=f"{issue_num}::qa::main",
            repo="o/r",
            issue_num=issue_num,
            workflow_id="qa",
            agent="claude",
            branch="dkmv/issue-feature",
        )
        await repository.update_run_fields(run_id, status=status)
        return run_id
    finally:
        await repository.close()


def _client(db_path: Path) -> tuple[TestClient, str]:
    url = _migrate(db_path)
    return build_client(settings=make_settings(DATABASE_URL=url)), url


def test_retry_failed_run_returns_202(tmp_path: Path) -> None:
    client, url = _client(tmp_path / "t.db")
    run_id = _run(_seed_run(url, issue_num=51, status="failed"))

    resp = client.post(f"/api/v1/runs/{run_id}/retry", headers=auth_headers())
    assert resp.status_code == 202
    body = resp.json()
    assert body["run_id"] == run_id
    assert body["queued"] is True


def test_retry_is_idempotent_double_call_one_queued(tmp_path: Path) -> None:
    """A second retry while one is pending is a no-op — ONE queued entry (AC-16)."""
    client, url = _client(tmp_path / "t.db")
    run_id = _run(_seed_run(url, issue_num=52, status="interrupted"))

    first = client.post(f"/api/v1/runs/{run_id}/retry", headers=auth_headers())
    second = client.post(f"/api/v1/runs/{run_id}/retry", headers=auth_headers())
    assert first.status_code == 202
    assert second.status_code == 202

    # The retry queue holds exactly ONE entry for this run (no duplicate dispatch).
    queue = client.get("/api/v1/retry-queue", headers=auth_headers()).json()
    matching = [e for e in queue["items"] if e["id"] == run_id]
    assert len(matching) == 1
    entry = matching[0]
    # RetryEntry shape (AC-4 / FR-06-3).
    assert set(entry) == {"id", "issue", "attempt", "dueIn", "lastError"}
    assert entry["issue"] == 52
    assert entry["attempt"] == 1  # the double-call did not bump it to 2


def test_retry_unknown_run_404(tmp_path: Path) -> None:
    client, _url = _client(tmp_path / "t.db")
    resp = client.post("/api/v1/runs/does-not-exist/retry", headers=auth_headers())
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "run_not_found"


def test_retry_active_run_409(tmp_path: Path) -> None:
    """A still-running run cannot be retried — 409 run_not_retryable."""
    client, url = _client(tmp_path / "t.db")
    run_id = _run(_seed_run(url, issue_num=53, status="running"))
    resp = client.post(f"/api/v1/runs/{run_id}/retry", headers=auth_headers())
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "run_not_retryable"


def test_retry_requires_token(tmp_path: Path) -> None:
    client, url = _client(tmp_path / "t.db")
    run_id = _run(_seed_run(url, issue_num=54, status="failed"))
    assert client.post(f"/api/v1/runs/{run_id}/retry").status_code == 401
