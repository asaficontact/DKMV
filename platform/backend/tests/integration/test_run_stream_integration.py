"""FIX-1/FIX-2 — a launched run actually streams (the dead-code gap closed).

This is the integration test the streaming-core fix requires: it launches a run
through the **real** facade path (``RunService`` → ``EmbeddedRuntime.start`` →
``RunHandle``) wired into the slice-2.3 stream by ``app.sse.run_stream.attach_run_stream``,
faking ONLY the innermost engine emission (``ComponentRunner.run``) — exactly the
seam 2.1's integration test fakes. The fake emits a few ``RuntimeEvent``-shaped
raw dicts through the engine's own ``on_event`` callback, so the whole bridge runs
in-process (INV-13, no Docker): engine ``EventBus.emit`` → the platform
``PlatformEventObserver`` (registered on the handle) → ``call_soon_threadsafe`` →
the run's hub queue → the ``EventPump`` → the append-only ``events`` table +
``run_stages`` projection + live SSE fan-out.

It asserts the three things that were dead before the fix:

* **(a)** the emitted events land in the ``events`` table (durable replay log);
* **(b)** ``run_stages`` is projected (the stepper read model);
* **(c)** a live SSE subscriber attached to the run's hub receives the fanned-out
  frames.

It also asserts **FIX-2**: ``POST /runs`` sets the HttpOnly ``SameSite=Strict`` SSE
cookie on its response, and the SSE endpoint then 200s with that cookie (and 401s
without it) — so a real browser ``EventSource`` authenticates without a URL token.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from app.runtime import RunService
from app.security.access_control import SSE_TOKEN_COOKIE
from app.sse.observer_bridge import StreamRegistry, Subscriber
from dkmv.runtime import EmbeddedRuntime
from dkmv.tasks.models import ComponentResult
from fastapi.testclient import TestClient

from tests.conftest import TEST_TOKEN, auth_headers, make_settings

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _migrate(db_path: Path) -> str:
    url = f"sqlite:///{db_path}"
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


#: The raw engine events the fake ComponentRunner emits (the engine wraps each raw
#: dict into a RuntimeEvent via EventBus.emit; ``lifecycle`` frames carry their own
#: task context). A two-stage lifecycle with a final per-task cost.
_RAW_EVENTS: list[dict[str, Any]] = [
    {"type": "task_started", "lifecycle": True, "task_name": "analyze", "task_index": 0},
    {"type": "assistant", "content_text": "working", "_task_idx": 0, "_task_name": "analyze"},
    {
        "type": "task_completed",
        "lifecycle": True,
        "task_name": "analyze",
        "task_index": 0,
        "cost_usd": 3.5,
    },
]


def _fake_component_run(runtime: EmbeddedRuntime) -> None:
    """Bind a fake ``ComponentRunner.run`` on ``runtime`` that emits then completes.

    Mirrors 2.1's integration seam: replaces ONLY the engine's innermost
    Docker-bound collaborator while keeping the rest of the facade real (source
    resolution, run-id back-fill, the ``source_provenance.json`` artifact the
    facade writes on ``on_run_id``). It uses the engine's **real** ``RunManager``
    to create the run directory (so the facade's ``save_artifact`` succeeds), takes
    the resulting engine ``YYMMDD-HHMM`` ``run_id``, calls ``on_run_id`` (the
    platform back-fills ``engine_run_id`` from the stream), emits the raw event
    sequence through ``on_event`` (yielding the loop between emits so the
    ``call_soon_threadsafe`` hand-off + pump drain interleave), and returns a
    terminal ``ComponentResult``.
    """
    run_manager = runtime._run_manager  # noqa: SLF001 - test reuses the engine's real RunManager

    async def _run(
        *,
        component_dir: Path,
        repo: str,
        branch: str | None,
        feature_name: str,
        on_event: Any = None,
        on_run_id: Any = None,
        **_kwargs: Any,
    ) -> ComponentResult:
        from dkmv.core.models import BaseComponentConfig

        base_config = BaseComponentConfig(
            repo=repo,
            branch=branch,
            feature_name=feature_name,
            model="claude-sonnet-4-6",
            max_turns=10,
            timeout_minutes=5,
            keep_alive=False,
            verbose=False,
        )
        run_id = run_manager.start_run(component_dir.name, base_config)
        if on_run_id is not None:
            on_run_id(run_id)  # the engine id the platform back-fills from the stream
        for raw in _RAW_EVENTS:
            if on_event is not None:
                # The engine's EventBus stamps each emitted RuntimeEvent.run_id with
                # the engine id (set via on_run_id above); the platform captures it
                # off the stream — no need to inject it into the raw dict here.
                on_event(raw)
            await asyncio.sleep(0)  # let the bridge + pump interleave
        return ComponentResult(
            run_id=run_id,
            component=component_dir.name,
            status="completed",
            repo=repo,
            branch=branch or "",
            feature_name=feature_name,
            total_cost_usd=3.5,
            duration_seconds=1.0,
            task_results=[],
        )

    runtime._component_runner.run = _run  # type: ignore[method-assign,assignment]  # DKMVP-ESCAPE: in-process test seam for the Docker-bound collaborator


@pytest.mark.asyncio
async def test_launched_run_streams_to_events_stages_and_subscriber(tmp_path: Path) -> None:
    """FIX-1: a launched run persists events, projects stages, and fans out live."""
    url = _migrate(tmp_path / "stream.db")
    settings = make_settings(DATABASE_URL=url, OUTPUT_DIR=tmp_path / "out")

    # Real EmbeddedRuntime (only ComponentRunner.run is faked) → real RunHandle.
    runtime = EmbeddedRuntime(output_dir=tmp_path / "out")
    _fake_component_run(runtime)
    run_service = RunService(settings, runtime=runtime)

    from app.db import Repository
    from app.secrets import Redactor
    from app.sse.run_stream import attach_run_stream

    repository = Repository(url, redactor=Redactor())
    await repository.start()
    try:
        registry = StreamRegistry()
        # Claim the run row (the launch path does this before start).
        run_id, won = await repository.claim_run(
            idempotency_key="stream-itest",
            repo="o/r",
            issue_num=1,
            workflow_id="plan",
            agent="claude",
            branch="dkmv/issue-1",
            feature_name="issue-1",
        )
        assert won

        # Start the engine (returns a RunHandle BEFORE the run coroutine emits).
        handle = await run_service.start(
            component="plan", repo="https://example.com/o/r.git", feature_name="issue-1"
        )
        # Wire the run into the stream (FIX-1) + attach a live subscriber to the hub.
        hub = attach_run_stream(
            run_id=run_id, handle=handle, registry=registry, repository=repository
        )
        sub = Subscriber()
        hub.add_subscriber(sub)

        # Drive the run to completion (the fake emits then returns).
        await handle.wait()
        # Let the supervisor close the hub + drain the pump's trailing batch.
        for _ in range(50):
            if hub.closed.is_set():
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)

        # (a) events landed in the append-only events table (durable replay log).
        backlog = await repository.read_events_after(run_id, 0)
        types = [r["event_type"] for r in backlog]
        assert types == ["task_started", "assistant", "task_completed"]
        assert backlog[0]["id"] < backlog[-1]["id"]  # monotonic cursor

        # (b) run_stages projected: stage 0 done with its final segment cost (INV-7).
        stages = await repository.read_run_stages(run_id)
        assert len(stages) == 1
        assert stages[0]["status"] == "done"
        assert stages[0]["cost_usd"] == pytest.approx(3.5)

        # (c) the live subscriber received the fanned-out frames.
        frames = sub.drain_nowait()
        assert [f.event_type for f in frames] == ["task_started", "assistant", "task_completed"]

        # The engine id back-filled onto the platform run row (§8.4): it is the
        # engine YYMMDD-HHMM id carried on the event stream — NOT the platform UUID.
        row = await repository.get_run(run_id)
        assert row is not None
        engine_id = row["engine_run_id"]
        assert engine_id and engine_id != run_id
        assert engine_id == handle.run_id  # the id the engine surfaced
        # The finished run's hub was discarded (no leak).
        assert registry.get(run_id) is None
    finally:
        await repository.close()


def _build_client(url: str) -> TestClient:
    """Build a lifespan-entered TestClient over the real app + a faked engine run."""
    from app.github.client import GitHubClient, Repo, WritePermission
    from app.github.provider import set_github_client
    from app.main import create_app

    settings = make_settings(DATABASE_URL=url, OUTPUT_DIR=Path(url[len("sqlite:///") :]).parent)
    runtime = EmbeddedRuntime(output_dir=settings.OUTPUT_DIR)
    _fake_component_run(runtime)
    run_service = RunService(settings, runtime=runtime)
    app = create_app(settings, run_service=run_service)

    class _GH(GitHubClient):
        async def list_repos(self) -> list[Repo]:  # pragma: no cover - not exercised
            return []

        async def check_write_permission(self, repo: str) -> WritePermission:  # pragma: no cover
            return WritePermission(repo=repo, can_write=True, role="write")

        async def graphql(  # pragma: no cover - not exercised
            self, query: str, variables: dict[str, Any]
        ) -> dict[str, Any]:
            return {"data": {}}

        async def replace_labels(self, repo: str, num: int, labels: Any) -> list[str]:
            return list(labels)

    client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
    client.__enter__()
    set_github_client(app, _GH())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client
    return client


def test_post_runs_sets_sse_cookie_and_sse_authenticates(tmp_path: Path) -> None:
    """FIX-2: POST /runs sets the SSE cookie; the SSE endpoint 200s with it, 401s without."""
    url = _migrate(tmp_path / "cookie.db")
    client = _build_client(url)
    try:
        resp = client.post(
            "/api/v1/runs",
            json={
                "issue_num": 1,
                "repo": "o/r",
                "workflow_id": "plan",
                "agent": "claude",
                "branch": "dkmv/issue-1",
                "feature_name": "issue-1",
            },
            headers=auth_headers(),
        )
        assert resp.status_code == 201
        run_id = resp.json()["run_id"]

        # FIX-2: the HttpOnly SameSite=Strict SSE cookie is set on the response.
        set_cookie = resp.headers.get("set-cookie", "")
        assert SSE_TOKEN_COOKIE in set_cookie
        assert "HttpOnly" in set_cookie
        assert "samesite=strict" in set_cookie.lower()

        # The SSE endpoint 401s WITHOUT the cookie (fresh client, cookies cleared).
        client.cookies.clear()
        no_cookie = client.get(f"/api/v1/runs/{run_id}/events")
        assert no_cookie.status_code == 401

        # …and 200s WITH the SSE cookie (the same loopback token).
        with client.stream(
            "GET",
            f"/api/v1/runs/{run_id}/events",
            cookies={SSE_TOKEN_COOKIE: TEST_TOKEN},
        ) as stream:
            assert stream.status_code == 200
            # Drain a little so the generator runs (then the context closes it).
            next(stream.iter_text(), "")
    finally:
        client.__exit__(None, None, None)
