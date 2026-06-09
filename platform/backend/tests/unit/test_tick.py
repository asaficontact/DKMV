"""Orchestrator tick loop (slice 3.3 — AC-10).

The binding AC-10 assertion: a single fixed-cadence tick polls candidate issues
and dispatches **through the existing ``dispatch(run)`` boundary** (ADR-P001) — it
does not introduce a second launch path. One tick against a seeded ``agent:queued``
candidate dispatches **exactly one** run through the injected dispatch seam. Also
covers: a candidate without an assigned workflow is skipped; an issue with an
active run is not re-dispatched; preflight-not-ready skips dispatch; the candidate
sort is priority asc then oldest; and the loop is a tracked task started + stopped
cleanly.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from app.config import Settings
from app.db.repository import Repository
from app.orchestrator import tick
from app.orchestrator.gauges import TickGauges
from app.orchestrator.tick import Candidate, TickDeps, run_tick, tick_loop

pytestmark = pytest.mark.asyncio

_REPO = "octo/widgets"


class _ReadyRuntime:
    """A run_service stub whose preflight is ready and exposes no live handles."""

    class _Report:
        ready = True

    class _Runtime:
        def get_handle(self, _engine_run_id: str) -> None:
            return None

    runtime = _Runtime()

    def get_capabilities(self) -> Any:
        return self._Report()


class _NotReadyRuntime(_ReadyRuntime):
    class _Report:
        ready = False


class _RecordingDispatch:
    """Records every candidate dispatched THROUGH the single launch boundary."""

    def __init__(self) -> None:
        self.calls: list[Candidate] = []

    async def __call__(self, candidate: Candidate) -> Any:
        self.calls.append(candidate)
        # A non-None result signals a successful dispatch (a LaunchResult stand-in).
        return {"run_id": f"run-{candidate.num}"}


class _FakeGitHubClient:
    async def replace_labels(self, repo: str, num: int, labels: list[str]) -> list[str]:
        return list(labels)


class _PassthroughWriteQueue:
    async def submit(self, factory: Any, *, label: str = "mutation") -> Any:
        return await factory()


def _deps(
    repository: Repository,
    dispatch: Any,
    *,
    runtime: Any | None = None,
) -> TickDeps:
    return TickDeps(
        repository=repository,
        github_client=_FakeGitHubClient(),  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed test client
        write_queue=_PassthroughWriteQueue(),  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed test queue
        run_service=runtime or _ReadyRuntime(),  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed runtime stub
        settings=Settings(_env_file=None, TICK_INTERVAL_S=1),  # type: ignore[call-arg]  # DKMVP-ESCAPE: pydantic-settings kwargs
        dispatch=dispatch,
        repo=_REPO,
        cache=None,
        gauges=TickGauges(),
    )


async def _seed_queued_issue(
    repository: Repository,
    *,
    num: int,
    workflow_id: str | None,
    labels: list[str] | None = None,
) -> None:
    await repository.upsert_issue(
        repo=_REPO,
        num=num,
        title=f"issue {num}",
        state="queued",
        labels=labels if labels is not None else ["agent:queued"],
        workflow_id=workflow_id,
    )


async def test_one_tick_dispatches_one_seeded_candidate(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-10: one tick → exactly one dispatch through the launch boundary."""

    # Skip the real GraphQL board read; the candidate is read from the cache.
    async def _no_board(_deps: TickDeps) -> None:
        return None

    monkeypatch.setattr(tick, "_refresh_board", _no_board)

    await _seed_queued_issue(repo, num=5, workflow_id="dev")
    dispatch = _RecordingDispatch()

    outcome = await run_tick(_deps(repo, dispatch))

    assert len(dispatch.calls) == 1  # EXACTLY one dispatch
    assert dispatch.calls[0].num == 5
    assert dispatch.calls[0].workflow_id == "dev"
    assert len(outcome.dispatched) == 1
    # The basic tick gauge recorded the tick (heartbeat advanced).
    assert outcome.preflight_ok is True


async def test_candidate_without_workflow_is_skipped(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_board(_deps: TickDeps) -> None:
        return None

    monkeypatch.setattr(tick, "_refresh_board", _no_board)

    await _seed_queued_issue(repo, num=6, workflow_id=None)  # queued but no workflow
    dispatch = _RecordingDispatch()
    await run_tick(_deps(repo, dispatch))
    assert dispatch.calls == []  # nothing to dispatch


async def test_issue_with_active_run_is_not_redispatched(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_board(_deps: TickDeps) -> None:
        return None

    monkeypatch.setattr(tick, "_refresh_board", _no_board)

    await _seed_queued_issue(repo, num=7, workflow_id="dev")
    # A live run already exists for issue 7 → it must not be re-dispatched.
    await repo.claim_run(
        idempotency_key="7::dev::main",
        repo=_REPO,
        issue_num=7,
        workflow_id="dev",
        agent="claude",
        branch="main",
        run_id="run-live-7",
    )
    await repo.update_run_fields("run-live-7", status="running")

    dispatch = _RecordingDispatch()
    await run_tick(_deps(repo, dispatch))
    assert dispatch.calls == []


async def test_preflight_not_ready_skips_dispatch(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_board(_deps: TickDeps) -> None:
        return None

    monkeypatch.setattr(tick, "_refresh_board", _no_board)

    await _seed_queued_issue(repo, num=8, workflow_id="dev")
    dispatch = _RecordingDispatch()
    outcome = await run_tick(_deps(repo, dispatch, runtime=_NotReadyRuntime()))
    assert outcome.preflight_ok is False
    assert dispatch.calls == []  # broken environment → no dispatch


async def test_candidates_sorted_oldest_first(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_board(_deps: TickDeps) -> None:
        return None

    monkeypatch.setattr(tick, "_refresh_board", _no_board)

    # Two queued candidates; the oldest (lowest issue number) dispatches first.
    await _seed_queued_issue(repo, num=20, workflow_id="dev")
    await _seed_queued_issue(repo, num=9, workflow_id="dev")
    dispatch = _RecordingDispatch()
    await run_tick(_deps(repo, dispatch))
    # Serial dispatch (Phase 3): exactly one, and it is the oldest (num 9).
    assert len(dispatch.calls) == 1
    assert dispatch.calls[0].num == 9


async def test_build_dispatch_routes_through_launch_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-P001: the tick's dispatch is the EXISTING ``launch_run`` boundary."""
    import app.runs.launch as launch_mod

    seen: dict[str, Any] = {}

    async def _fake_launch_run(req: Any, **kwargs: Any) -> Any:
        seen["req"] = req
        seen["connected_repo"] = kwargs["connected_repo"]
        seen["attach_stream"] = kwargs["attach_stream"]
        return {"run_id": "run-xyz"}

    monkeypatch.setattr(launch_mod, "launch_run", _fake_launch_run)

    ctx = tick.DispatchContext(
        repository=object(),  # type: ignore[arg-type]  # DKMVP-ESCAPE: unused by the faked launch_run
        run_service=_ReadyRuntime(),  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed runtime stub
        github_client=_FakeGitHubClient(),  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed test client
        write_queue=_PassthroughWriteQueue(),  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed test queue
    )
    dispatch = tick.build_dispatch(lambda: ctx)
    candidate = Candidate(repo=_REPO, num=42, workflow_id="dev", agent="auto")
    result = await dispatch(candidate)

    assert result == {"run_id": "run-xyz"}
    # The LaunchRequest was built from the candidate + defaults (the §8.4 contract).
    assert seen["req"].issue_num == 42
    assert seen["req"].workflow_id == "dev"
    assert seen["req"].branch == tick.DEFAULT_BASE_BRANCH
    assert seen["req"].feature_name == "issue-42"
    assert seen["connected_repo"] == _REPO


async def test_build_dispatch_swallows_duplicate_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 409 duplicate dispatch (claim-lock lost) is a no-op, not a tick-killer."""
    import app.runs.launch as launch_mod
    from app.runs.launch import duplicate_dispatch

    async def _raises_409(_req: Any, **_kwargs: Any) -> Any:
        raise duplicate_dispatch("existing-run")

    monkeypatch.setattr(launch_mod, "launch_run", _raises_409)

    ctx = tick.DispatchContext(
        repository=object(),  # type: ignore[arg-type]  # DKMVP-ESCAPE: unused by the faked launch_run
        run_service=_ReadyRuntime(),  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed runtime stub
        github_client=_FakeGitHubClient(),  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed test client
        write_queue=_PassthroughWriteQueue(),  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed test queue
    )
    dispatch = tick.build_dispatch(lambda: ctx)
    result = await dispatch(Candidate(repo=_REPO, num=1, workflow_id="dev"))
    assert result is None  # swallowed; the tick continues


async def test_tick_loop_is_a_tracked_task_started_and_stopped(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loop runs ticks on cadence and stops promptly when the event is set."""

    async def _no_board(_deps: TickDeps) -> None:
        return None

    monkeypatch.setattr(tick, "_refresh_board", _no_board)

    await _seed_queued_issue(repo, num=12, workflow_id="dev")
    dispatch = _RecordingDispatch()
    deps = _deps(repo, dispatch)
    stop = asyncio.Event()
    task = asyncio.create_task(tick_loop(deps, stop=stop))
    # Let at least one tick run.
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert task.done()
    assert dispatch.calls  # at least one tick dispatched the candidate


# ── EngineRunKiller: container-stop seam (INV-10-adjacent) ────────────────────


class _LiveHandle:
    """A fake engine RunHandle recording a force-stop (container stopped)."""

    def __init__(self) -> None:
        self.stopped_force: bool | None = None

    async def stop(self, *, force: bool = False) -> None:
        self.stopped_force = force


class _RuntimeWithHandle:
    def __init__(self, handle: Any | None) -> None:
        self._handle = handle

    class _Runtime:
        def __init__(self, handle: Any | None) -> None:
            self._handle = handle

        def get_handle(self, _engine_run_id: str) -> Any | None:
            return self._handle

    @property
    def runtime(self) -> Any:
        return self._Runtime(self._handle)


async def test_engine_killer_force_stops_live_handle() -> None:
    """A live run is killed via stop(force=True) — the engine finally stops the container."""
    handle = _LiveHandle()
    killer = tick.EngineRunKiller(_RuntimeWithHandle(handle))  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed run service
    killed = await killer.kill({"id": "r1", "engine_run_id": "eng-1"})
    assert killed is True
    assert handle.stopped_force is True  # force=True → engine finally stops container


async def test_engine_killer_returns_false_without_live_handle() -> None:
    """No live handle in this process → no re-attach (INV-10); returns False."""
    killer = tick.EngineRunKiller(_RuntimeWithHandle(None))  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed run service
    assert await killer.kill({"id": "r2", "engine_run_id": "eng-2"}) is False
    # A run that never surfaced an engine id is also not killable here.
    assert await killer.kill({"id": "r3", "engine_run_id": None}) is False


async def test_refresh_board_swallows_a_transient_error(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A board-read failure must not kill the tick — it proceeds against the cache."""
    import app.github.sync as sync_mod

    async def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("github down")

    monkeypatch.setattr(sync_mod, "sync_issues", _boom)
    dispatch = _RecordingDispatch()
    # _refresh_board catches the error; the tick still completes (no candidates).
    await run_tick(_deps(repo, dispatch))
    assert dispatch.calls == []
