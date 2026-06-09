"""Slice 3.1 — ``GET /runs`` history filters + cursor pagination, ``GET /runs/{id}``.

End-to-end over the real app + a migrated SQLite DB. Seeds runs through the
repository, then asserts (AC-1, AC-2):

* ``GET /runs`` supports ``workflow`` / ``agent`` / ``status`` filters (each
  narrows the result set) and cursor pagination (``?limit`` → a ``next_cursor``
  on a bounded page; following the cursor returns the next page).
* ``GET /runs/{id}`` returns the full §8.9 detail keys (``stages`` / ``sandbox`` /
  ``artifacts`` / ``config`` / ``pr`` / ``error``); an unknown id → ``404
  run_not_found`` in the error envelope.
* The history API reads the platform ``runs`` read model, NOT the engine
  ``list_runs`` directory scan (§6.5) — asserted by a source grep.
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


async def _seed_run(
    url: str,
    *,
    key: str,
    issue_num: int,
    workflow_id: str,
    agent: str,
    status: str = "completed",
    cost: float | None = None,
    pr_num: int | None = None,
    issue_title: str | None = None,
) -> str:
    repository = Repository(url)
    await repository.start()
    try:
        run_id, _won = await repository.claim_run(
            idempotency_key=key,
            repo="o/r",
            issue_num=issue_num,
            workflow_id=workflow_id,
            agent=agent,
            model="claude-sonnet-4-6" if agent == "claude" else "gpt-5.4",
            branch=f"dkmv/issue-{issue_num}",
            feature_name=f"issue-{issue_num}",
        )
        fields: dict[str, object] = {"status": status}
        if pr_num is not None:
            fields["pr_num"] = pr_num
        await repository.update_run_fields(run_id, **fields)
        await repository.upsert_issue(
            repo="o/r", num=issue_num, title=issue_title or f"Issue {issue_num}"
        )
        if cost is not None:
            await repository.append_events(
                [
                    EventRecord(
                        run_id=run_id,
                        sequence=1,
                        event_type="task_completed",
                        payload={"type": "task_completed"},
                        task_index=0,
                        cost_usd=cost,
                        agent=agent,
                    )
                ]
            )
        return run_id
    finally:
        await repository.close()


# ── AC-1: filters narrow the result set ──────────────────────────────────────


def test_filter_by_workflow_narrows(tmp_path: Path) -> None:
    client, url = _client(tmp_path / "t.db")
    _run(_seed_run(url, key="a", issue_num=1, workflow_id="qa", agent="claude"))
    _run(_seed_run(url, key="b", issue_num=2, workflow_id="dev", agent="claude"))

    all_resp = client.get("/api/v1/runs", headers=auth_headers())
    assert len(all_resp.json()["items"]) == 2

    qa_resp = client.get("/api/v1/runs?workflow=qa", headers=auth_headers())
    items = qa_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["workflow_id"] == "qa"


def test_filter_by_agent_narrows(tmp_path: Path) -> None:
    client, url = _client(tmp_path / "t.db")
    _run(_seed_run(url, key="a", issue_num=1, workflow_id="qa", agent="claude"))
    _run(_seed_run(url, key="b", issue_num=2, workflow_id="qa", agent="codex"))

    resp = client.get("/api/v1/runs?agent=codex", headers=auth_headers())
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["agent"] == "codex"


def test_filter_by_status_narrows(tmp_path: Path) -> None:
    client, url = _client(tmp_path / "t.db")
    _run(_seed_run(url, key="a", issue_num=1, workflow_id="qa", agent="claude", status="completed"))
    _run(_seed_run(url, key="b", issue_num=2, workflow_id="qa", agent="claude", status="failed"))

    resp = client.get("/api/v1/runs?status=failed", headers=auth_headers())
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "failed"


def test_blank_filter_is_noop(tmp_path: Path) -> None:
    """A bare ``?workflow=`` (empty string) does not narrow to empty (it is a no-op)."""
    client, url = _client(tmp_path / "t.db")
    _run(_seed_run(url, key="a", issue_num=1, workflow_id="qa", agent="claude"))
    resp = client.get("/api/v1/runs?workflow=", headers=auth_headers())
    assert len(resp.json()["items"]) == 1


def test_combined_filters_intersect(tmp_path: Path) -> None:
    client, url = _client(tmp_path / "t.db")
    _run(_seed_run(url, key="a", issue_num=1, workflow_id="qa", agent="claude", status="completed"))
    _run(_seed_run(url, key="b", issue_num=2, workflow_id="qa", agent="codex", status="completed"))
    _run(_seed_run(url, key="c", issue_num=3, workflow_id="dev", agent="claude", status="failed"))

    resp = client.get(
        "/api/v1/runs?workflow=qa&agent=claude&status=completed", headers=auth_headers()
    )
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["issue_num"] == 1


# ── FR-06-4: the Issue-title + PR columns are populated in the summary ────────


def test_summary_carries_issue_title_and_pr_num(tmp_path: Path) -> None:
    """GET /runs RunSummary exposes ``issue_title`` (from the issues cache) + ``pr_num``.

    The history RunsTable renders an "Issue (#num title)" column and a "PR" badge;
    the projection must surface the joined title + the run's linked PR number, not
    just ``issue_num`` (FR-06-4).
    """
    client, url = _client(tmp_path / "t.db")
    _run(
        _seed_run(
            url,
            key="a",
            issue_num=7,
            workflow_id="qa",
            agent="claude",
            pr_num=314,
            issue_title="Add OAuth flow",
        )
    )
    items = client.get("/api/v1/runs", headers=auth_headers()).json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["issue_num"] == 7
    assert row["issue_title"] == "Add OAuth flow"
    assert row["pr_num"] == 314


async def _seed_repo_only_run(url: str) -> None:
    """Seed a run with no linked issue (issue_num NULL) — a repo-only ad-hoc run."""
    repository = Repository(url)
    await repository.start()
    try:
        run_id, _won = await repository.claim_run(
            idempotency_key="repo-only",
            repo="o/r",
            issue_num=None,
            workflow_id="dev",
            agent="claude",
            model="claude-sonnet-4-6",
            branch="dkmv/adhoc",
            feature_name="adhoc",
        )
        await repository.update_run_fields(run_id, status="completed")
    finally:
        await repository.close()


def test_summary_issue_title_null_for_repo_only_run(tmp_path: Path) -> None:
    """A run with no issue (issue_num NULL) carries ``issue_title``/``pr_num`` as null."""
    client, url = _client(tmp_path / "t.db")
    _run(_seed_repo_only_run(url))
    items = client.get("/api/v1/runs", headers=auth_headers()).json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["issue_num"] is None
    assert row["issue_title"] is None
    assert row["pr_num"] is None


# ── AC-1: cursor pagination ───────────────────────────────────────────────────


def test_cursor_pagination_bounded_page_returns_next_cursor(tmp_path: Path) -> None:
    client, url = _client(tmp_path / "t.db")
    for i in range(3):
        _run(_seed_run(url, key=f"k{i}", issue_num=i, workflow_id="qa", agent="claude"))

    page1 = client.get("/api/v1/runs?limit=2", headers=auth_headers()).json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None

    page2 = client.get(
        f"/api/v1/runs?limit=2&cursor={page1['next_cursor']}", headers=auth_headers()
    ).json()
    assert len(page2["items"]) == 1
    assert page2["next_cursor"] is None

    # No overlap between pages (3 distinct run ids across the two pages).
    ids = {r["id"] for r in page1["items"]} | {r["id"] for r in page2["items"]}
    assert len(ids) == 3


def test_last_page_has_null_cursor(tmp_path: Path) -> None:
    client, url = _client(tmp_path / "t.db")
    _run(_seed_run(url, key="a", issue_num=1, workflow_id="qa", agent="claude"))
    resp = client.get("/api/v1/runs?limit=100", headers=auth_headers()).json()
    assert resp["next_cursor"] is None


# ── AC-2: GET /runs/{id} full detail + 404 ────────────────────────────────────


def test_run_detail_full_shape(tmp_path: Path) -> None:
    client, url = _client(tmp_path / "t.db")
    run_id = _run(_seed_run(url, key="a", issue_num=5, workflow_id="qa", agent="claude", cost=3.5))
    body = client.get(f"/api/v1/runs/{run_id}", headers=auth_headers()).json()
    for key in ("stages", "sandbox", "artifacts", "config", "pr", "error", "issue"):
        assert key in body, f"missing detail key {key}"
    assert body["sandbox"]["image"]
    assert body["issue"] == {"num": 5, "title": "Issue 5"}
    assert body["cost_usd"] == 3.5


def test_unknown_id_404_run_not_found(tmp_path: Path) -> None:
    client, _url = _client(tmp_path / "t.db")
    resp = client.get("/api/v1/runs/nope", headers=auth_headers())
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "run_not_found"


def test_history_reads_require_token(tmp_path: Path) -> None:
    client, _url = _client(tmp_path / "t.db")
    assert client.get("/api/v1/runs").status_code == 401
    assert client.get("/api/v1/runs/anything").status_code == 401


# ── §6.5: history reads the platform read model, NOT the engine list_runs scan ─


def test_history_does_not_use_engine_list_runs() -> None:
    """The history API source carries no engine ``list_runs`` directory scan (§6.5)."""
    src = (_BACKEND_ROOT / "app" / "api" / "history.py").read_text()
    assert "list_runs" not in src or "list_runs_filtered" in src
    # The only ``list_runs`` token allowed is the platform read helper name.
    assert "EmbeddedRuntime" not in src
    assert "get_stats" not in src
