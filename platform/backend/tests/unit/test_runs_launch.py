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
    """Engine ``RunHandle`` stand-in: ``run_id`` is None (back-fills later).

    Satisfies the minimal public ``RunHandle`` surface the slice-2.3 stream wiring
    (``app.sse.run_stream.attach_run_stream``) consumes: ``add_observer`` (register
    the platform observer) and ``wait``/``status``/``result`` (the completion
    supervisor). The fake never emits events, so the pump idles and the supervisor
    closes the (empty) stream immediately — exactly the no-op a launch-only test
    wants. ``add_observer`` records the observer so a test can assert it was wired.
    """

    run_id = None

    def __init__(self) -> None:
        self.observers: list[Any] = []
        self.status = "running"
        self.result = None

    def add_observer(self, observer: Any) -> None:
        self.observers.append(observer)

    async def wait(self, timeout: float | None = None) -> None:
        # A real run does NOT complete by the time POST /runs returns; mirror that
        # by blocking until the completion supervisor is cancelled at shutdown, so
        # the run stays ``running``/un-finalized at return time (the launch tests
        # assert the just-claimed ``pending`` status before the stream finalizes).
        await asyncio.Event().wait()


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


# ── G1: fail-closed isolation gate blocks dispatch when gVisor is missing ─────


def test_launch_blocked_when_gvisor_unavailable(tmp_path: Path, monkeypatch: Any) -> None:
    """SANDBOX_RUNTIME=runsc but runsc not registered + no opt-in → 503, no run row."""
    monkeypatch.setattr("app.executor.runtime_policy.runtime_available", lambda *a, **k: False)
    client, runtime, _gh = _client(tmp_path / "t.db")
    resp = client.post("/api/v1/runs", json=_body(), headers=auth_headers())
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "sandbox_isolation_unavailable"
    # Fail-closed BEFORE the claim-lock: the engine was never started.
    assert runtime.start_calls == []


def test_launch_proceeds_with_weaker_isolation_optin(tmp_path: Path, monkeypatch: Any) -> None:
    """ALLOW_WEAKER_ISOLATION opt-in → dispatch proceeds even when runsc is missing."""
    monkeypatch.setattr("app.executor.runtime_policy.runtime_available", lambda *a, **k: False)
    url = _migrate(tmp_path / "t.db")
    runtime = FakeRuntime()
    client = build_client(
        settings=make_settings(DATABASE_URL=url, ALLOW_WEAKER_ISOLATION=True),
        runtime=runtime,
    )
    set_github_client(client.app, FakeClient())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client
    resp = client.post("/api/v1/runs", json=_body(), headers=auth_headers())
    assert resp.status_code == 201
    assert len(runtime.start_calls) == 1


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


# ── FIX-2: GET /runs/{id} config reflects the launched guardrails ────────────


def test_config_reflects_launched_guardrails_claude(tmp_path: Path) -> None:
    """A Claude launch with explicit guardrails → the §8.9 config block is truthful.

    The validated ``max_turns`` / ``timeout_minutes`` / ``max_budget_usd`` /
    ``memory`` are persisted at ``claim_run`` time, so ``GET /runs/{id}``'s
    ``config`` block carries the actual launched values, not always-null.
    """
    client, _rt, _gh = _client(tmp_path / "t.db")
    resp = client.post(
        "/api/v1/runs",
        json=_body(
            agent="claude",
            max_turns=42,
            timeout_minutes=15,
            max_budget_usd=7.5,
            memory="4g",
        ),
        headers=auth_headers(),
    )
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]

    detail = client.get(f"/api/v1/runs/{run_id}", headers=auth_headers())
    assert detail.status_code == 200
    config = detail.json()["config"]
    assert config["max_turns"] == 42
    assert config["timeout_minutes"] == 15
    assert config["max_budget_usd"] == 7.5
    assert config["memory_limit"] == "4g"


def test_config_memory_defaults_when_unset_claude(tmp_path: Path) -> None:
    """No explicit memory → config persists the resolved default ('8g')."""
    client, _rt, _gh = _client(tmp_path / "t.db")
    resp = client.post("/api/v1/runs", json=_body(agent="claude"), headers=auth_headers())
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]
    config = client.get(f"/api/v1/runs/{run_id}", headers=auth_headers()).json()["config"]
    assert config["memory_limit"] == "8g"
    # No turns/budget supplied → null (not a phantom default).
    assert config["max_turns"] is None
    assert config["max_budget_usd"] is None


def test_config_codex_budget_turns_null(tmp_path: Path) -> None:
    """A Codex launch → config max_turns / max_budget_usd are null (INV-8)."""
    client, _rt, _gh = _client(tmp_path / "t.db")
    resp = client.post(
        "/api/v1/runs",
        json=_body(agent="codex", workflow_id="dev", timeout_minutes=20, memory="2g"),
        headers=auth_headers(),
    )
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]
    config = client.get(f"/api/v1/runs/{run_id}", headers=auth_headers()).json()["config"]
    # Codex never has a budget / turns cap (consistent with the INV-8 rejection).
    assert config["max_turns"] is None
    assert config["max_budget_usd"] is None
    # Time-bound + memory are still persisted for Codex.
    assert config["timeout_minutes"] == 20
    assert config["memory_limit"] == "2g"


def test_runs_post_requires_token(tmp_path: Path) -> None:
    client, _rt, _gh = _client(tmp_path / "t.db")
    resp = client.post("/api/v1/runs", json=_body())
    assert resp.status_code == 401


def test_runs_post_foreign_host_403(tmp_path: Path) -> None:
    url = _migrate(tmp_path / "t.db")
    client = build_client(settings=make_settings(DATABASE_URL=url), host="evil.example.com")
    resp = client.post("/api/v1/runs", json=_body(), headers=auth_headers())
    assert resp.status_code == 403
