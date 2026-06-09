"""Slice 2.1 — ``GET /runs`` + ``GET /runs/{id}`` baseline shapes (§8.9, AC-5).

End-to-end over the real app + a migrated SQLite DB. Seeds a run row (and a stage)
directly through the repository, then asserts:

* ``GET /runs/{id}`` carries the §8.9 baseline keys: ``stages``, ``config`` (the
  FR-04-5 keys), ``sandbox``, ``artifacts``, ``pr|null``, ``error|null``.
* A **Codex** run's ``cost_usd`` is ``null`` (FR-06-1a / INV-8) while a Claude run
  surfaces the segment-sum projection.
* ``GET /runs`` returns the list spine; an unknown id → ``404 run_not_found``.
* Both reads inherit access control (no token → 401).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.db import Repository
from app.db.repository import EventRecord
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


def _client(db_path: Path) -> tuple[TestClient, str]:
    url = _migrate(db_path)
    return build_client(settings=make_settings(DATABASE_URL=url)), url


async def _seed_claude_run(url: str) -> str:
    """Seed a Claude run with one completed stage + a cost event; return its id."""
    repository = Repository(url)
    await repository.start()
    try:
        run_id, _won = await repository.claim_run(
            idempotency_key="k1",
            repo="o/r",
            issue_num=5,
            workflow_id="qa",
            agent="claude",
            model="claude-sonnet-4-6",
            branch="dkmv/issue-5",
            feature_name="issue-5",
        )
        await repository.upsert_issue(repo="o/r", num=5, title="Seed issue")
        await repository.upsert_stage(run_id, 0, "analyze", status="done", cost_usd=3.5, turns=4)
        await repository.append_events(
            [
                EventRecord(
                    run_id=run_id,
                    sequence=1,
                    event_type="task_completed",
                    payload={"type": "task_completed"},
                    task_index=0,
                    cost_usd=3.5,
                    agent="claude",
                )
            ]
        )
        return run_id
    finally:
        await repository.close()


async def _seed_codex_run(url: str) -> str:
    repository = Repository(url)
    await repository.start()
    try:
        run_id, _won = await repository.claim_run(
            idempotency_key="k2",
            repo="o/r",
            issue_num=6,
            workflow_id="dev",
            agent="codex",
            model="gpt-5.4",
            branch="dkmv/issue-6",
            feature_name="issue-6",
        )
        return run_id
    finally:
        await repository.close()


# ── AC-5: GET /runs/{id} baseline shape ──────────────────────────────────────


def test_run_detail_baseline_shape(tmp_path: Path) -> None:
    client, url = _client(tmp_path / "t.db")
    run_id = _run(_seed_claude_run(url))

    resp = client.get(f"/api/v1/runs/{run_id}", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()

    # The §8.9 baseline keys (AC-5).
    for key in (
        "id",
        "engine_run_id",
        "repo",
        "issue",
        "workflow_id",
        "agent",
        "model",
        "status",
        "branch",
        "cost_usd",
        "tokens_in",
        "tokens_out",
        "turns",
        "stages",
        "config",
        "sandbox",
        "artifacts",
        "pr",
        "error",
    ):
        assert key in body, f"missing key {key}"

    # config carries exactly the FR-04-5 keys.
    for cfg_key in (
        "repo",
        "branch",
        "feature_name",
        "model",
        "max_turns",
        "timeout_minutes",
        "max_budget_usd",
        "memory_limit",
    ):
        assert cfg_key in body["config"], f"missing config key {cfg_key}"

    # sandbox + stages + issue block.
    assert body["sandbox"]["image"]
    assert body["sandbox"]["health"] == "healthy"
    assert body["issue"] == {"num": 5, "title": "Seed issue"}
    assert len(body["stages"]) == 1
    assert body["stages"][0]["name"] == "analyze"
    assert body["pr"] is None

    # Claude cost is the segment-sum projection (not null).
    assert body["cost_usd"] == 3.5


def test_codex_cost_is_null(tmp_path: Path) -> None:
    client, url = _client(tmp_path / "t.db")
    run_id = _run(_seed_codex_run(url))
    resp = client.get(f"/api/v1/runs/{run_id}", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    # FR-06-1a / INV-8: Codex cost renders null/"—".
    assert body["cost_usd"] is None
    assert body["agent"] == "codex"


def test_run_not_found_404(tmp_path: Path) -> None:
    client, _url = _client(tmp_path / "t.db")
    resp = client.get("/api/v1/runs/does-not-exist", headers=auth_headers())
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "run_not_found"


# ── GET /runs list spine ─────────────────────────────────────────────────────


def test_run_list_spine(tmp_path: Path) -> None:
    client, url = _client(tmp_path / "t.db")
    claude_id = _run(_seed_claude_run(url))
    codex_id = _run(_seed_codex_run(url))

    resp = client.get("/api/v1/runs", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    ids = {row["id"] for row in body["items"]}
    assert claude_id in ids
    assert codex_id in ids
    assert body["next_cursor"] is None
    # Codex row's cost is null in the list spine too.
    codex_row = next(r for r in body["items"] if r["id"] == codex_id)
    assert codex_row["cost_usd"] is None


def test_run_list_repo_filter(tmp_path: Path) -> None:
    client, url = _client(tmp_path / "t.db")
    _run(_seed_claude_run(url))
    resp = client.get("/api/v1/runs?repo=other/repo", headers=auth_headers())
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_run_reads_require_token(tmp_path: Path) -> None:
    client, _url = _client(tmp_path / "t.db")
    assert client.get("/api/v1/runs").status_code == 401
    assert client.get("/api/v1/runs/anything").status_code == 401
