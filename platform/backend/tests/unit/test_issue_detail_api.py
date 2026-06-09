"""Slice 2.1 — ``GET /issues/{num}`` detail (markdown body, labels, comments) (§5.4).

End-to-end over the real app + a fake GitHub client that scripts the issue-detail
GraphQL response. Asserts:

* The detail body carries the markdown ``body``, ``labels``, ``author``, and the
  ``comments`` thread (distinct from the board-list shape).
* The ``active_run`` block reflects a paused/running run on the issue (the
  existing-run alert source, slice 2.2) — read from the authoritative DB row.
* A missing issue → ``404 issue_not_found``; the route inherits access control.
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
    return asyncio.new_event_loop().run_until_complete(coro)


def _migrate(db_path: Path) -> str:
    url = f"sqlite:///{db_path}"
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


def _detail_payload(*, num: int = 5, body: str = "## Heading\n\n- item") -> dict[str, Any]:
    return {
        "data": {
            "repository": {
                "issue": {
                    "number": num,
                    "title": f"Issue {num}",
                    "body": body,
                    "state": "OPEN",
                    "url": f"https://github.com/o/r/issues/{num}",
                    "createdAt": "2026-06-08T10:00:00Z",
                    "author": {"login": "alice", "avatarUrl": "https://a/avatar"},
                    "labels": {"nodes": [{"name": "bug", "color": "d73a4a"}]},
                    "comments": {
                        "nodes": [
                            {
                                "id": "c1",
                                "body": "first comment",
                                "createdAt": "2026-06-08T11:00:00Z",
                                "author": {"login": "bob", "avatarUrl": None},
                            }
                        ]
                    },
                }
            }
        }
    }


class FakeDetailClient(GitHubClient):
    """A GitHubClient whose GraphQL returns a scripted issue-detail payload."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def list_repos(self) -> list[Repo]:  # pragma: no cover
        return []

    async def check_write_permission(self, repo: str) -> WritePermission:  # pragma: no cover
        return WritePermission(repo=repo, can_write=True, role="write")

    async def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return self._payload

    async def replace_labels(  # pragma: no cover - not exercised
        self, repo: str, num: int, labels: Any
    ) -> list[str]:
        return list(labels)


def _client(db_path: Path, payload: dict[str, Any]) -> TestClient:
    url = _migrate(db_path)
    client = build_client(settings=make_settings(DATABASE_URL=url))
    set_github_client(client.app, FakeDetailClient(payload))  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client
    return client


async def _seed_paused_run(url: str, num: int) -> None:
    repository = Repository(url)
    await repository.start()
    try:
        run_id, _won = await repository.claim_run(
            idempotency_key=f"k-{num}", repo="o/r", issue_num=num, agent="claude"
        )
        await repository.update_run_fields(run_id, status="paused")
    finally:
        await repository.close()


# ── detail shape ─────────────────────────────────────────────────────────────


def test_issue_detail_body_labels_comments(tmp_path: Path) -> None:
    client = _client(tmp_path / "t.db", _detail_payload())
    resp = client.get("/api/v1/issues/o/r/5", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["num"] == 5
    assert body["body"] == "## Heading\n\n- item"  # raw markdown for the MD renderer
    assert body["author"] == {"login": "alice", "avatar": "https://a/avatar"}
    assert body["labels"] == [{"name": "bug", "color": "d73a4a"}]
    assert len(body["comments"]) == 1
    assert body["comments"][0]["author"]["login"] == "bob"
    assert body["active_run"] is None


def test_issue_detail_active_run_block(tmp_path: Path) -> None:
    url = _migrate(tmp_path / "t.db")
    client = build_client(settings=make_settings(DATABASE_URL=url))
    set_github_client(client.app, FakeDetailClient(_detail_payload()))  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client
    _run(_seed_paused_run(url, 5))

    resp = client.get("/api/v1/issues/o/r/5", headers=auth_headers())
    assert resp.status_code == 200
    # The existing-run alert source (slice 2.2): a paused run on the issue.
    assert resp.json()["active_run"]["status"] == "paused"


def test_issue_detail_missing_404(tmp_path: Path) -> None:
    client = _client(tmp_path / "t.db", {"data": {"repository": {"issue": None}}})
    resp = client.get("/api/v1/issues/o/r/999", headers=auth_headers())
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "issue_not_found"


def test_issue_detail_requires_token(tmp_path: Path) -> None:
    client = _client(tmp_path / "t.db", _detail_payload())
    assert client.get("/api/v1/issues/o/r/5").status_code == 401
