"""Slice 1.3 — ``POST /issues/{num}/agent-state`` (AC-9, FR-02-3, §8.1).

End-to-end over the real app + a migrated SQLite DB + a fake GitHub client:

* INV-1 — the route inherits access control (no token → 401; foreign Host → 403);
  it is a state-changing ``POST``.
* AC-9 — ``target: queued`` sets ``agent:queued`` (→ Queued); ``target: none``
  strips it (→ Backlog). The transition goes through ``set_agent_state`` →
  ``replace_labels`` (the replace-all ``PUT``), preserving non-agent labels.
* Invalid targets (the run-driven columns) are rejected at validation.

Synchronous tests (driving the sync ``TestClient``), mirroring ``test_issues_api``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Sequence
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from app.github.client import GitHubClient, Repo, WritePermission
from app.github.provider import set_github_client
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


def _issue_node(number: int, *, labels: list[str] | None = None) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"Issue {number}",
        "state": "OPEN",
        "updatedAt": "2026-06-08T10:00:00Z",
        "closedAt": None,
        "assignees": {"nodes": []},
        "labels": {"nodes": [{"name": n, "color": "ededed"} for n in (labels or [])]},
        "timelineItems": {"nodes": []},
    }


def _one_page(open_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    page_info = {"hasNextPage": False, "endCursor": None}
    return {
        "data": {
            "repository": {
                "open": {"pageInfo": page_info, "nodes": open_nodes},
                "closed": {"pageInfo": page_info, "nodes": []},
            }
        }
    }


class FakeClient(GitHubClient):
    """A GitHubClient whose GraphQL + label primitives are scripted in-memory."""

    def __init__(self, page: dict[str, Any]) -> None:
        self._page = page
        self.existing_labels: set[str] = set()
        self.replace_calls: list[tuple[str, int, list[str]]] = []

    async def list_repos(self) -> list[Repo]:  # pragma: no cover - not exercised
        return []

    async def check_write_permission(self, repo: str) -> WritePermission:  # pragma: no cover
        return WritePermission(repo=repo, can_write=True, role="write")

    async def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return self._page

    async def create_label(
        self, repo: str, *, name: str, color: str, description: str = ""
    ) -> bool:
        if name in self.existing_labels:
            return False
        self.existing_labels.add(name)
        return True

    async def replace_labels(self, repo: str, num: int, labels: Sequence[str]) -> list[str]:
        body = list(labels)
        self.replace_calls.append((repo, num, body))
        return body


def _client(db_path: Path, page: dict[str, Any]) -> tuple[TestClient, FakeClient]:
    url = _migrate(db_path)
    client = build_client(settings=make_settings(DATABASE_URL=url))
    fake = FakeClient(page)
    set_github_client(client.app, fake)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client
    return client, fake


# ── INV-1 access control ─────────────────────────────────────────────────────


def test_agent_state_requires_token() -> None:
    client = build_client()
    resp = client.post("/api/v1/issues/o/r/5/agent-state", json={"target": "queued"})
    assert resp.status_code == 401


def test_agent_state_foreign_host_403() -> None:
    client = build_client(host="evil.example.com")
    resp = client.post(
        "/api/v1/issues/o/r/5/agent-state", json={"target": "queued"}, headers=auth_headers()
    )
    assert resp.status_code == 403


# ── AC-9: queued sets the label; none strips it ──────────────────────────────


def test_agent_state_queued_sets_label(tmp_path: Path) -> None:
    """target=queued sets agent:queued via the replace-all PUT (→ Queued)."""
    client, fake = _client(tmp_path / "t.db", _one_page([_issue_node(10, labels=["bug"])]))
    client.post("/api/v1/projects/o/r/sync", headers=auth_headers())

    resp = client.post(
        "/api/v1/issues/o/r/10/agent-state", json={"target": "queued"}, headers=auth_headers()
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_label"] == "agent:queued"
    assert "bug" in body["labels"]  # non-agent label preserved
    # The replace-all PUT carried the full desired set (bug + agent:queued).
    repo, num, written = fake.replace_calls[-1]
    assert (repo, num) == ("o/r", 10)
    assert set(written) == {"bug", "agent:queued"}


def test_agent_state_none_strips_label(tmp_path: Path) -> None:
    """target=none clears agent:queued (→ Backlog), preserving non-agent labels (AC-9)."""
    client, fake = _client(
        tmp_path / "t.db", _one_page([_issue_node(11, labels=["agent:queued", "feat"])])
    )
    client.post("/api/v1/projects/o/r/sync", headers=auth_headers())

    resp = client.post(
        "/api/v1/issues/o/r/11/agent-state", json={"target": "none"}, headers=auth_headers()
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_label"] is None
    assert body["labels"] == ["feat"]  # agent label stripped, feat preserved
    _repo, _num, written = fake.replace_calls[-1]
    assert "agent:queued" not in written


def test_agent_state_queued_then_none_round_trip(tmp_path: Path) -> None:
    """A full Backlog→Queued→Backlog round trip via the endpoint (AC-9)."""
    client, fake = _client(tmp_path / "t.db", _one_page([_issue_node(12)]))
    client.post("/api/v1/projects/o/r/sync", headers=auth_headers())

    r1 = client.post(
        "/api/v1/issues/o/r/12/agent-state", json={"target": "queued"}, headers=auth_headers()
    )
    assert r1.json()["agent_label"] == "agent:queued"

    # The board read now reflects Queued (cache persisted + re-derived).
    board = client.get("/api/v1/repos/o/r/issues", headers=auth_headers()).json()["items"]
    assert next(i for i in board if i["num"] == 12)["state"] == "queued"

    r2 = client.post(
        "/api/v1/issues/o/r/12/agent-state", json={"target": "none"}, headers=auth_headers()
    )
    assert r2.json()["agent_label"] is None

    board2 = client.get("/api/v1/repos/o/r/issues", headers=auth_headers()).json()["items"]
    assert next(i for i in board2 if i["num"] == 12)["state"] == "backlog"


def test_agent_state_rejects_run_driven_target(tmp_path: Path) -> None:
    """Only queued|none are draggable; a run-driven target (in-progress) is 400."""
    client, _fake = _client(tmp_path / "t.db", _one_page([_issue_node(13)]))
    client.post("/api/v1/projects/o/r/sync", headers=auth_headers())

    resp = client.post(
        "/api/v1/issues/o/r/13/agent-state",
        json={"target": "in-progress"},
        headers=auth_headers(),
    )
    assert resp.status_code == 400


def test_agent_state_shares_one_write_queue(tmp_path: Path) -> None:
    """All agent-state mutations route through the single process-wide write-queue."""
    client, _fake = _client(tmp_path / "t.db", _one_page([_issue_node(14)]))
    client.post("/api/v1/projects/o/r/sync", headers=auth_headers())
    client.post(
        "/api/v1/issues/o/r/14/agent-state", json={"target": "queued"}, headers=auth_headers()
    )
    # The endpoint installed exactly one WriteQueue singleton on app.state.
    from app.github.write_queue import WriteQueue

    queue = client.app.state.github_write_queue  # type: ignore[attr-defined]  # DKMVP-ESCAPE: TestClient app is ASGIApp-typed
    assert isinstance(queue, WriteQueue)
