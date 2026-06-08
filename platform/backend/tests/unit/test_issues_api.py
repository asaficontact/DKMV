"""Slice 1.2 — ``POST /projects/{repo}/sync`` + ``GET /repos/{repo}/issues``.

End-to-end over the real app + a migrated SQLite DB + a fake GitHub client:

* INV-1 — both routes inherit access control (no token → 401; foreign Host →
  403); the sync POST is state-changing.
* AC-3/AC-4 — sync imports issues through the repository and ensures the four
  ``agent:*`` labels (idempotently).
* AC-5 — the board list derives state per §5.3.1 and applies the authority rule
  (an issue with an active run + a stale label → the DB run row wins).

The tests are **synchronous** (they drive the sync ``TestClient``, whose own
event-loop portal must not be nested inside an outer async test). Direct DB
seeding for the authority-rule test runs its coroutine on a throwaway loop via
:func:`_run` against the same WAL file the app reads.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from app.db import Repository
from app.github.client import GitHubClient, Repo, WritePermission
from app.github.provider import set_github_client
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, build_client, make_settings

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _run[T](coro: Awaitable[T]) -> T:
    """Run a coroutine to completion on a throwaway event loop (sync test helper)."""
    return asyncio.new_event_loop().run_until_complete(coro)


def _migrate(db_path: Path) -> str:
    url = f"sqlite:///{db_path}"
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


def _client(db_path: Path) -> tuple[TestClient, str]:
    """Build a TestClient over a fresh migrated DB; return ``(client, url)``."""
    url = _migrate(db_path)
    return build_client(settings=make_settings(DATABASE_URL=url)), url


def _issue_node(
    number: int,
    *,
    state: str = "OPEN",
    updated_at: str = "2026-06-08T10:00:00Z",
    closed_at: str | None = None,
    labels: list[str] | None = None,
    merged_pr: int | None = None,
) -> dict[str, Any]:
    timeline_nodes: list[dict[str, Any]] = []
    if merged_pr is not None:
        timeline_nodes.append({"source": {"number": merged_pr, "merged": True}})
    return {
        "number": number,
        "title": f"Issue {number}",
        "state": state,
        "updatedAt": updated_at,
        "closedAt": closed_at,
        "assignees": {"nodes": []},
        "labels": {"nodes": [{"name": n, "color": "ededed"} for n in (labels or [])]},
        "timelineItems": {"nodes": timeline_nodes},
    }


def _one_page(
    open_nodes: list[dict[str, Any]],
    *,
    closed_nodes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "data": {
            "repository": {
                "open": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": open_nodes,
                },
                "closed": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": closed_nodes or [],
                },
            }
        }
    }


class FakeClient(GitHubClient):
    """A :class:`GitHubClient` whose GraphQL + label-create are scripted."""

    def __init__(self, page: dict[str, Any]) -> None:
        self._page = page
        self.existing_labels: set[str] = set()
        self.label_calls: list[str] = []

    async def list_repos(self) -> list[Repo]:  # pragma: no cover - not exercised
        return []

    async def check_write_permission(self, repo: str) -> WritePermission:  # pragma: no cover
        return WritePermission(repo=repo, can_write=True, role="write")

    async def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return self._page

    async def create_label(
        self, repo: str, *, name: str, color: str, description: str = ""
    ) -> bool:
        self.label_calls.append(name)
        if name in self.existing_labels:
            return False
        self.existing_labels.add(name)
        return True


# ── INV-1 access control ─────────────────────────────────────────────────────


def test_sync_requires_token() -> None:
    client = build_client()
    resp = client.post("/api/v1/projects/o/r/sync")
    assert resp.status_code == 401


def test_sync_foreign_host_403() -> None:
    client = build_client(host="evil.example.com")
    resp = client.post("/api/v1/projects/o/r/sync", headers=auth_headers())
    assert resp.status_code == 403


def test_list_issues_requires_token() -> None:
    client = build_client()
    resp = client.get("/api/v1/repos/o/r/issues")
    assert resp.status_code == 401


# ── AC-3/AC-4: sync imports + ensures labels ─────────────────────────────────


def test_sync_imports_issues_and_creates_labels(tmp_path: Path) -> None:
    client, _url = _client(tmp_path / "t.db")
    fake = FakeClient(_one_page([_issue_node(10, labels=["agent:queued"]), _issue_node(9)]))
    set_github_client(client.app, fake)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client

    resp = client.post("/api/v1/projects/o/r/sync", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 2
    assert set(body["labels"]["created"]) == {
        "agent:queued",
        "agent:in-progress",
        "agent:paused",
        "agent:review",
    }

    # A re-sync is idempotent on labels (no duplicate-label error; AC-4).
    resp2 = client.post("/api/v1/projects/o/r/sync", headers=auth_headers())
    assert resp2.status_code == 200
    assert resp2.json()["labels"]["created"] == []


def test_resync_does_not_recreate_labels(tmp_path: Path) -> None:
    """A second sync skips the four GitHub create-label calls (FIX-2).

    Once the ``agent:*`` labels are ensured on first connect, routine incremental
    polls must NOT re-issue ``POST /labels`` (GitHub secondary-rate-limit budget).
    """
    client, _url = _client(tmp_path / "t.db")
    fake = FakeClient(_one_page([_issue_node(10)]))
    set_github_client(client.app, fake)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client

    r1 = client.post("/api/v1/projects/o/r/sync", headers=auth_headers())
    assert r1.status_code == 200
    assert len(fake.label_calls) == 4  # all four created on first sync (AC-4)

    fake.label_calls.clear()
    r2 = client.post("/api/v1/projects/o/r/sync", headers=auth_headers())
    assert r2.status_code == 200
    # The guard short-circuited: no create_label call on the second sync.
    assert fake.label_calls == []
    # Labels still reported as present (idempotent shape preserved).
    assert set(r2.json()["labels"]["existing"]) == {
        "agent:queued",
        "agent:in-progress",
        "agent:paused",
        "agent:review",
    }


def test_forced_ensure_recreates_labels(tmp_path: Path) -> None:
    """``?ensure_labels=true`` forces a re-ensure even after the flag is set (FIX-2)."""
    client, _url = _client(tmp_path / "t.db")
    fake = FakeClient(_one_page([_issue_node(10)]))
    set_github_client(client.app, fake)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client

    client.post("/api/v1/projects/o/r/sync", headers=auth_headers())
    fake.label_calls.clear()
    r = client.post("/api/v1/projects/o/r/sync?ensure_labels=true", headers=auth_headers())
    assert r.status_code == 200
    assert len(fake.label_calls) == 4  # forced path re-issues the ensure


# ── AC-5: board list derivation + authority rule ─────────────────────────────


def test_board_list_applies_authority_rule(tmp_path: Path) -> None:
    """An issue with a stale agent:queued label + an active run → run row wins."""
    client, url = _client(tmp_path / "t.db")
    fake = FakeClient(_one_page([_issue_node(10, labels=["agent:queued"])]))
    set_github_client(client.app, fake)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client

    # Import the issue (cached state = queued from the label).
    client.post("/api/v1/projects/o/r/sync", headers=auth_headers())

    # Seed an ACTIVE run (status running) on issue 10 directly against the WAL file.
    _seed_active_run(url, repo="o/r", num=10, status="running")

    resp = client.get("/api/v1/repos/o/r/issues", headers=auth_headers())
    assert resp.status_code == 200
    items = resp.json()["items"]
    issue10 = next(i for i in items if i["num"] == 10)
    # The stale label says "queued" but the live run wins → In Progress (AC-5).
    assert issue10["state"] == "in_progress"
    assert issue10["run_status"] == "running"


def test_board_list_without_run_uses_label(tmp_path: Path) -> None:
    """With no active run the agent:* label governs the column (§5.3.1)."""
    client, _url = _client(tmp_path / "t.db")
    fake = FakeClient(_one_page([_issue_node(11, labels=["agent:review"])]))
    set_github_client(client.app, fake)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client
    client.post("/api/v1/projects/o/r/sync", headers=auth_headers())

    resp = client.get("/api/v1/repos/o/r/issues", headers=auth_headers())
    items = resp.json()["items"]
    issue = next(i for i in items if i["num"] == 11)
    assert issue["state"] == "in_review"
    assert issue["run_status"] is None


def test_board_list_closed_issue_renders_done(tmp_path: Path) -> None:
    """A CLOSED issue with no PR + no agent:* label renders in Done (AC-5 / §5.3.1).

    Read-path regression: the board read must honor the persisted closed/Done
    signal end-to-end (it previously hardcoded is_closed=False and flattened a
    closed issue to backlog).
    """
    client, _url = _client(tmp_path / "t.db")
    fake = FakeClient(
        _one_page(
            [],
            closed_nodes=[
                _issue_node(20, state="CLOSED", closed_at="2026-06-08T00:00:00Z"),
            ],
        )
    )
    set_github_client(client.app, fake)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client
    client.post("/api/v1/projects/o/r/sync", headers=auth_headers())

    resp = client.get("/api/v1/repos/o/r/issues", headers=auth_headers())
    assert resp.status_code == 200
    issue = next(i for i in resp.json()["items"] if i["num"] == 20)
    assert issue["state"] == "done"
    assert issue["run_status"] is None


def test_board_list_closed_with_merged_pr_renders_done(tmp_path: Path) -> None:
    """A closed issue with a linked merged PR renders in Done end-to-end (§5.3.1)."""
    client, _url = _client(tmp_path / "t.db")
    fake = FakeClient(
        _one_page(
            [],
            closed_nodes=[
                _issue_node(
                    21,
                    state="CLOSED",
                    closed_at="2026-06-08T00:00:00Z",
                    labels=["agent:review"],  # stale label must not pull it back
                    merged_pr=99,
                ),
            ],
        )
    )
    set_github_client(client.app, fake)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client
    client.post("/api/v1/projects/o/r/sync", headers=auth_headers())

    resp = client.get("/api/v1/repos/o/r/issues", headers=auth_headers())
    issue = next(i for i in resp.json()["items"] if i["num"] == 21)
    assert issue["state"] == "done"
    assert issue["pr_num"] == 99


def test_board_list_open_no_label_renders_backlog(tmp_path: Path) -> None:
    """An OPEN issue with no agent:* label renders in Backlog (§5.3.1)."""
    client, _url = _client(tmp_path / "t.db")
    fake = FakeClient(_one_page([_issue_node(22)]))
    set_github_client(client.app, fake)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client
    client.post("/api/v1/projects/o/r/sync", headers=auth_headers())

    resp = client.get("/api/v1/repos/o/r/issues", headers=auth_headers())
    issue = next(i for i in resp.json()["items"] if i["num"] == 22)
    assert issue["state"] == "backlog"


def _seed_active_run(url: str, *, repo: str, num: int, status: str) -> None:
    """Insert an active run via the repository writer (its own loop), then set status."""

    async def _job() -> None:
        repository = Repository(url)
        await repository.start()
        try:
            run_id, _won = await repository.claim_run(
                idempotency_key=f"{repo}#{num}#run",
                repo=repo,
                issue_num=num,
            )
            await repository.update_run_fields(run_id, status=status)
        finally:
            await repository.close()

    _run(_job())
