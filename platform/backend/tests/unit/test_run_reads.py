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


# ── FIX-1: GET /runs list uses ONE bulk spend query (no per-run N+1) ──────────


async def _seed_multi_cost_run(
    url: str, *, key: str, issue_num: int, costs: list[tuple[int, int, float]]
) -> str:
    """Seed a Claude run whose ``costs`` are (task_index, seq, cumulative_cost).

    The segment sum is Σ over distinct task_index of the *last* (highest seq/id)
    cumulative cost — exercising the per-(run_id, task_index) last-cumulative
    dedup in the bulk projection.
    """
    repository = Repository(url)
    await repository.start()
    try:
        run_id, _won = await repository.claim_run(
            idempotency_key=key,
            repo="o/r",
            issue_num=issue_num,
            workflow_id="qa",
            agent="claude",
            model="claude-sonnet-4-6",
            branch=f"dkmv/issue-{issue_num}",
            feature_name=f"issue-{issue_num}",
        )
        await repository.append_events(
            [
                EventRecord(
                    run_id=run_id,
                    sequence=seq,
                    event_type="task_completed",
                    payload={"type": "task_completed"},
                    task_index=task_index,
                    cost_usd=cost,
                    agent="claude",
                )
                for (task_index, seq, cost) in costs
            ]
        )
        return run_id
    finally:
        await repository.close()


def test_list_bulk_spend_values_correct_multi_run(tmp_path: Path) -> None:
    """A multi-run page's spend values match the per-(run_id,task_index) segment sum."""
    client, url = _client(tmp_path / "t.db")
    # run A: two tasks, each with two cumulative-cost events → last per task summed.
    a = _run(
        _seed_multi_cost_run(
            url,
            key="a",
            issue_num=10,
            costs=[(0, 1, 1.0), (0, 2, 2.0), (1, 3, 0.5), (1, 4, 3.0)],
        )
    )
    # run B: one task, last cumulative is 4.25.
    b = _run(_seed_multi_cost_run(url, key="b", issue_num=11, costs=[(0, 1, 4.0), (0, 2, 4.25)]))
    # codex run C: cost excluded → null.
    c = _run(_seed_codex_run(url))

    resp = client.get("/api/v1/runs", headers=auth_headers())
    assert resp.status_code == 200
    items = {row["id"]: row for row in resp.json()["items"]}
    # run A segment sum = last(task0)=2.0 + last(task1)=3.0 = 5.0 (NOT naive SUM=6.5).
    assert items[a]["cost_usd"] == 5.0
    # run B segment sum = last(task0)=4.25 (NOT 8.25).
    assert items[b]["cost_usd"] == 4.25
    # Codex excluded.
    assert items[c]["cost_usd"] is None


def test_list_path_is_one_bulk_spend_query_not_per_run(tmp_path: Path) -> None:
    """The list path issues ONE bulk spend query, never one run_spend per row (FIX-1).

    Builds the page summaries through :func:`build_run_summaries` with a spy
    repository: ``run_spends`` (the bulk query) is called exactly once and
    ``run_spend`` (the per-run query) is never called — i.e. the page is O(1)
    spend queries, not O(N).
    """
    from app.runs.service import build_run_summaries

    url = _migrate(tmp_path / "t.db")
    # Seed several non-Codex runs so a per-run path would be N queries.
    _run(_seed_multi_cost_run(url, key="a", issue_num=20, costs=[(0, 1, 1.0)]))
    _run(_seed_multi_cost_run(url, key="b", issue_num=21, costs=[(0, 1, 2.0)]))
    _run(_seed_multi_cost_run(url, key="c", issue_num=22, costs=[(0, 1, 3.0)]))

    async def _run_with_spy() -> tuple[int, int, list[dict[str, object]]]:
        repository = Repository(url)
        await repository.start()
        try:
            rows = await repository.list_runs(limit=100)

            spend_calls = 0
            bulk_calls = 0
            real_run_spend = repository.run_spend
            real_run_spends = repository.run_spends

            async def _spy_run_spend(run_id: str) -> float:
                nonlocal spend_calls
                spend_calls += 1
                return await real_run_spend(run_id)

            async def _spy_run_spends(run_ids: object) -> dict[str, float]:
                nonlocal bulk_calls
                bulk_calls += 1
                return await real_run_spends(run_ids)  # type: ignore[arg-type]  # DKMVP-ESCAPE: spy passthrough

            repository.run_spend = _spy_run_spend  # type: ignore[method-assign]  # DKMVP-ESCAPE: test spy
            repository.run_spends = _spy_run_spends  # type: ignore[method-assign]  # DKMVP-ESCAPE: test spy
            items = await build_run_summaries(repository, rows)
            return spend_calls, bulk_calls, items
        finally:
            await repository.close()

    spend_calls, bulk_calls, items = _run(_run_with_spy())
    assert len(items) == 3
    # O(1): exactly one bulk query, zero per-run queries (no N+1).
    assert bulk_calls == 1
    assert spend_calls == 0
