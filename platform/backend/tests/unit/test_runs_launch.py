"""Slice 2.1 — ``POST /runs`` validation + capability rejection + claim-lock (§8.10).

End-to-end over the real app + a migrated SQLite DB + a fake GitHub client + a
fake engine runtime. Covers:

* **AC-1 / INV-8 (binding)** — a Codex budget/turns body → ``400
  unsupported_for_agent``; the same body on Claude → ``201``; branch on
  ``supports_budget()`` / ``supports_max_turns()`` (never silently ignored).
* **AC-4 (§8.10)** — the validation table: bad branch (regex / ``..`` / leading
  ``-``), un-slugified ``feature_name``, an unknown ``workflow_id``, an
  incompatible explicit ``(agent, model)`` pair, a traversal ``context`` path —
  each → ``400``.
* **AC-3 (§8.4)** — the returned ``run_id`` is a UUID (not the engine
  ``YYMMDD-HHMM`` id), ``runs.engine_run_id`` is null at return time, and the
  issue moved to ``agent:in-progress`` through the write-queue (INV-11).
* **AC-2 (§8.2 / INV-5)** — claim-lock: two identical ``POST /runs`` → one run row
  + one ``409 duplicate_dispatch``.

The fake engine runtime records its ``start`` call and returns a handle whose
``run_id`` is ``None`` (the engine id back-fills via the event stream) so the
test never touches Docker (INV-13).
"""

from __future__ import annotations

import asyncio
import uuid
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


class _FakeHandle:
    """Engine ``RunHandle`` stand-in: ``run_id`` is None (back-fills later)."""

    run_id = None


class FakeRuntime:
    """Engine stand-in that records ``start`` and returns a fake handle.

    Mirrors the ``EmbeddedRuntime.start`` keyword surface so ``RunService.start``
    forwards into it; never constructs a container (INV-13). ``raise_on_start``
    lets a test force a start failure.
    """

    def __init__(self) -> None:
        self.start_calls: list[dict[str, Any]] = []
        self.raise_on_start: Exception | None = None

    async def start(self, **kwargs: Any) -> _FakeHandle:
        if self.raise_on_start is not None:
            raise self.raise_on_start
        self.start_calls.append(kwargs)
        return _FakeHandle()


class FakeClient(GitHubClient):
    """A :class:`GitHubClient` whose label replace-all is recorded."""

    def __init__(self) -> None:
        self.replace_calls: list[tuple[str, int, list[str]]] = []

    async def list_repos(self) -> list[Repo]:  # pragma: no cover - not exercised
        return []

    async def check_write_permission(self, repo: str) -> WritePermission:  # pragma: no cover
        return WritePermission(repo=repo, can_write=True, role="write")

    async def graphql(  # pragma: no cover - not exercised here
        self, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        return {"data": {}}

    async def replace_labels(self, repo: str, num: int, labels: Any) -> list[str]:
        self.replace_calls.append((repo, num, list(labels)))
        return list(labels)


def _client(db_path: Path) -> tuple[TestClient, FakeRuntime, FakeClient]:
    """Build a TestClient over a fresh migrated DB + fake engine + fake GitHub."""
    url = _migrate(db_path)
    runtime = FakeRuntime()
    client = build_client(settings=make_settings(DATABASE_URL=url), runtime=runtime)
    fake_gh = FakeClient()
    set_github_client(client.app, fake_gh)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client
    return client, runtime, fake_gh


def _body(**overrides: Any) -> dict[str, Any]:
    """A valid ``POST /runs`` body; overrides patch individual fields."""
    base: dict[str, Any] = {
        "issue_num": 7,
        "repo": "o/r",
        "workflow_id": "qa",
        "agent": "claude",
        "branch": "dkmv/issue-7-fix",
        "feature_name": "issue-7-fix",
    }
    base.update(overrides)
    return base


# ── AC-1 / INV-8: Codex budget/turns rejected; Claude accepted ───────────────


def test_codex_budget_rejected_400(tmp_path: Path) -> None:
    client, _rt, _gh = _client(tmp_path / "t.db")
    resp = client.post(
        "/api/v1/runs",
        json=_body(agent="codex", workflow_id="dev", max_budget_usd=10.0),
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "unsupported_for_agent"


def test_codex_max_turns_rejected_400(tmp_path: Path) -> None:
    client, _rt, _gh = _client(tmp_path / "t.db")
    resp = client.post(
        "/api/v1/runs",
        json=_body(agent="codex", workflow_id="dev", max_turns=50),
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "unsupported_for_agent"


def test_claude_same_budget_body_accepted_201(tmp_path: Path) -> None:
    client, runtime, _gh = _client(tmp_path / "t.db")
    resp = client.post(
        "/api/v1/runs",
        json=_body(agent="claude", max_budget_usd=10.0, max_turns=50),
        headers=auth_headers(),
    )
    assert resp.status_code == 201
    # The engine was started exactly once with the budget passed through.
    assert len(runtime.start_calls) == 1
    assert runtime.start_calls[0]["max_budget_usd"] == 10.0


# ── AC-4: §8.10 validation table ─────────────────────────────────────────────


def test_branch_traversal_rejected(tmp_path: Path) -> None:
    client, _rt, _gh = _client(tmp_path / "t.db")
    resp = client.post("/api/v1/runs", json=_body(branch="dkmv/../etc"), headers=auth_headers())
    assert resp.status_code == 400
    assert resp.json()["error"]["details"]["field"] == "branch"


def test_branch_leading_dash_rejected(tmp_path: Path) -> None:
    client, _rt, _gh = _client(tmp_path / "t.db")
    resp = client.post("/api/v1/runs", json=_body(branch="-evil"), headers=auth_headers())
    assert resp.status_code == 400
    assert resp.json()["error"]["details"]["field"] == "branch"


def test_branch_bad_chars_rejected(tmp_path: Path) -> None:
    client, _rt, _gh = _client(tmp_path / "t.db")
    resp = client.post("/api/v1/runs", json=_body(branch="bad branch!"), headers=auth_headers())
    assert resp.status_code == 400


def test_feature_name_not_slug_rejected(tmp_path: Path) -> None:
    client, _rt, _gh = _client(tmp_path / "t.db")
    resp = client.post(
        "/api/v1/runs", json=_body(feature_name="Not A Slug"), headers=auth_headers()
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["details"]["field"] == "feature_name"


def test_unknown_workflow_rejected(tmp_path: Path) -> None:
    client, _rt, _gh = _client(tmp_path / "t.db")
    resp = client.post(
        "/api/v1/runs", json=_body(workflow_id="no-such-workflow"), headers=auth_headers()
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["details"]["field"] == "workflow_id"


def test_incompatible_explicit_agent_model_rejected(tmp_path: Path) -> None:
    client, _rt, _gh = _client(tmp_path / "t.db")
    # Claude agent + a Codex model is an explicit incompatible pair → 400.
    resp = client.post(
        "/api/v1/runs",
        json=_body(agent="claude", model="gpt-5.4"),
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["details"]["field"] == "model"


def test_context_traversal_rejected(tmp_path: Path) -> None:
    client, _rt, _gh = _client(tmp_path / "t.db")
    resp = client.post(
        "/api/v1/runs",
        json=_body(context=["../../etc/passwd"]),
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["details"]["field"] == "context"


# ── AC-3: platform UUID + engine_run_id null + label → in-progress ───────────


def test_returns_platform_uuid_and_moves_label(tmp_path: Path) -> None:
    url = _migrate(tmp_path / "t.db")
    runtime = FakeRuntime()
    client = build_client(settings=make_settings(DATABASE_URL=url), runtime=runtime)
    fake_gh = FakeClient()
    set_github_client(client.app, fake_gh)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client

    resp = client.post("/api/v1/runs", json=_body(), headers=auth_headers())
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]
    # AC-3: the returned id is the platform UUID, not the engine YYMMDD-HHMM id.
    assert uuid.UUID(run_id)

    # AC-3: engine_run_id is null at return time (it back-fills via the stream).
    async def _check() -> dict[str, Any] | None:
        repository = Repository(url)
        await repository.start()
        try:
            return await repository.get_run(run_id)
        finally:
            await repository.close()

    row = _run(_check())
    assert row is not None
    assert row["engine_run_id"] is None
    assert row["status"] == "pending"
    assert row["agent"] == "claude"

    # INV-11: the issue moved to agent:in-progress via the replace-all label PUT.
    assert fake_gh.replace_calls, "expected a set_agent_state replace_labels call"
    _repo, num, labels = fake_gh.replace_calls[-1]
    assert num == 7
    assert "agent:in-progress" in labels


def test_auto_agent_resolves_to_workflow_agent(tmp_path: Path) -> None:
    client, runtime, _gh = _client(tmp_path / "t.db")
    resp = client.post(
        "/api/v1/runs", json=_body(agent="auto", workflow_id="qa"), headers=auth_headers()
    )
    assert resp.status_code == 201
    # auto → workflow.agent (qa resolves to a concrete agent the engine accepts).
    assert runtime.start_calls[0]["agent"] in {"claude", "codex"}


# ── AC-2 / INV-5: claim-lock — duplicate dispatch → 409 ──────────────────────


def test_duplicate_dispatch_409(tmp_path: Path) -> None:
    client, _rt, _gh = _client(tmp_path / "t.db")
    body = _body()
    first = client.post("/api/v1/runs", json=body, headers=auth_headers())
    assert first.status_code == 201
    second = client.post("/api/v1/runs", json=body, headers=auth_headers())
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "duplicate_dispatch"


def test_concurrent_identical_dispatch_one_row_one_409(tmp_path: Path) -> None:
    """Two identical claims on one DB → exactly one run row + one 409 (INV-5).

    Drives the claim helper directly under a shared writer to exercise the
    ``ON CONFLICT DO NOTHING`` race deterministically (the HTTP layer is sync, so
    the concurrency is at the repository claim).
    """
    url = _migrate(tmp_path / "t.db")
    from app.runs.launch import idempotency_key

    async def _race() -> tuple[int, int]:
        repository = Repository(url)
        await repository.start()
        try:
            key = idempotency_key(7, "qa", "dkmv/issue-7-fix")
            results = await asyncio.gather(
                repository.claim_run(idempotency_key=key, repo="o/r", issue_num=7),
                repository.claim_run(idempotency_key=key, repo="o/r", issue_num=7),
            )
            wins = sum(1 for (_id, won) in results if won)
            ids = {rid for (rid, _won) in results}
            return wins, len(ids)
        finally:
            await repository.close()

    wins, distinct_ids = _run(_race())
    assert wins == 1  # exactly one claim won the row
    assert distinct_ids == 1  # both calls resolve to the same run id


def test_runs_post_requires_token(tmp_path: Path) -> None:
    client, _rt, _gh = _client(tmp_path / "t.db")
    resp = client.post("/api/v1/runs", json=_body())
    assert resp.status_code == 401


def test_runs_post_foreign_host_403(tmp_path: Path) -> None:
    url = _migrate(tmp_path / "t.db")
    client = build_client(settings=make_settings(DATABASE_URL=url), host="evil.example.com")
    resp = client.post("/api/v1/runs", json=_body(), headers=auth_headers())
    assert resp.status_code == 403
