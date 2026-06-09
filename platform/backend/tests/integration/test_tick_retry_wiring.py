"""Slice 3.4 — the retry / pause-timeout machinery is LIVE in the production tick.

The unit tests (``test_reconcile_retry.py``) hand-inject a :class:`DecisionRegistry`
and :class:`RetryScheduler` straight into :class:`ReconcileDeps`. That proves the
*reconcile* logic, but it can pass even when the production tick wires neither —
exactly the dead-wiring this slice fixes: ``build_tick_deps`` / ``run_tick`` used to
construct ``ReconcileDeps`` WITHOUT ``decisions=`` / ``retry_scheduler=``, so on a
real tick (the only live path: ``app.main.start_orchestrator`` →
``build_tick_deps`` → ``run_tick``) the pause sweep returned 0 and the retry queue
never drained.

These tests close that gap. They boot the **real app lifespan** (``app.main._lifespan``
— a migrated DB + a stub engine, no Docker) on the test's OWN event loop so the
single-writer Repository, the HITL :class:`DecisionRegistry`, the
:class:`RetryScheduler`, and the orchestrator handle are all composed exactly as in
production, then drive a **real tick** through ``app.state.orchestrator.deps`` — the
production-shaped :class:`TickDeps` ``build_tick_deps`` built, NOT a
``ReconcileDeps`` hand-assembled in the test. They assert end-to-end:

1. an expired pause is auto-resolved by the tick (``resolved_by='timeout'``, a
   single transition — AC-17 / INV-9);
2. a run enqueued on the lifespan-composed scheduler with a due backoff is
   re-dispatched through the launch boundary by the tick (AC-14/15);
3. a manual ``POST /runs/{id}/retry`` then a tick actually re-dispatches it — the
   endpoint and the tick share the SAME scheduler singleton, so the manual enqueue
   drains (AC-16).

The lifespan is entered directly (it is an ``@asynccontextmanager``) so everything
runs on one event loop — a ``TestClient`` would run the lifespan/Repository on a
separate loop and deadlock the cross-loop ``await``s. The tick interval is set huge
so the background loop never fires mid-assertion; each tick is driven explicitly.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.config import Settings
from app.db import Repository
from app.hitl import DecisionRegistry
from app.hitl.pause_bridge import compute_timeout_at
from app.main import _lifespan, create_app
from app.orchestrator.deadlines import due_at_from_now
from app.orchestrator.retry import RetryScheduler
from app.orchestrator.retry_deps import RETRY_SCHEDULER_ATTR
from app.orchestrator.tick import OrchestratorHandle, run_tick
from fastapi import FastAPI

from tests.conftest import TEST_TOKEN, _migrate

pytestmark = pytest.mark.asyncio

_REPO = "octo/widgets"


class _StubRuntime:
    """A duck-typed engine stub: preflight ready, no live handles (no Docker)."""

    class _Report:
        ready = True

    class _Runtime:
        def get_handle(self, _engine_run_id: str) -> None:
            return None

    runtime = _Runtime()

    def get_capabilities(self) -> Any:
        return self._Report()


class _RecordingRedispatch:
    """Records (run_id, start_task) re-dispatches so a tick's drain is observable.

    Swapped onto the LIVE lifespan-composed scheduler's ``redispatch`` (the same
    singleton the tick fires from) so the test exercises the real tick→scheduler
    →re-dispatch path without launching a real container — the point is to prove the
    tick drains the queue, not to run Docker.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def __call__(self, row: dict[str, Any], start_task: str | None) -> str | None:
        self.calls.append((str(row["id"]), start_task))
        return "redispatched"


def _settings(url: str) -> Settings:
    return Settings(  # type: ignore[call-arg]  # DKMVP-ESCAPE: pydantic-settings injected kwargs
        _env_file=None,
        DKMV_PLATFORM_TOKEN=TEST_TOKEN,
        DATABASE_URL=url,
        # Huge interval → the background loop never fires during the test; the tick
        # under assertion is driven explicitly via run_tick.
        TICK_INTERVAL_S=10_000,
    )


def _fresh_url() -> str:
    fd, path = tempfile.mkstemp(prefix="dkmvp-tick-retry-", suffix=".db")
    os.close(fd)
    return _migrate(Path(path))


async def _seed_project(url: str) -> None:
    """Seed a connected project so the lifespan starts the orchestrator loop."""
    repository = Repository(url)
    await repository.start()
    await repository.upsert_project(project_id="p1", repo=_REPO)
    await repository.close()


def _build_app(url: str) -> FastAPI:
    settings = _settings(url)
    from app.runtime import RunService

    run_service = RunService(settings, runtime=_StubRuntime())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed runtime stub
    return create_app(settings, run_service=run_service)


async def _seed_terminal_run(repository: Repository, *, issue_num: int) -> str:
    """Claim a run + drive it to a terminal (retryable) status with no open PR."""
    run_id, _ = await repository.claim_run(
        idempotency_key=f"{issue_num}::qa::main",
        repo=_REPO,
        issue_num=issue_num,
        workflow_id="qa",
        agent="claude",
        branch="dkmv/issue-feature",
    )
    await repository.update_run_fields(run_id, status="failed")
    return run_id


# ── (1) AC-17: the LIVE tick auto-resolves an expired pause (INV-9) ───────────


async def test_live_tick_auto_resolves_expired_pause() -> None:
    """A real tick (production deps) auto-resolves an expired pause, exactly once."""
    url = _fresh_url()
    await _seed_project(url)
    app = _build_app(url)

    async with _lifespan(app):
        handle = app.state.orchestrator
        assert isinstance(handle, OrchestratorHandle)
        # The production tick deps MUST carry the lifespan-composed registry — this
        # is the wiring the dead-code bug dropped (it would be None on a real tick).
        assert isinstance(handle.deps.decisions, DecisionRegistry)
        assert handle.deps.decisions is app.state.decision_registry

        repository: Repository = app.state.repository
        run_id, _ = await repository.claim_run(
            idempotency_key="71::qa::main",
            repo=_REPO,
            issue_num=71,
            workflow_id="qa",
            agent="claude",
            branch="dkmv/issue-feature",
        )
        await repository.update_run_fields(run_id, status="paused")
        # An ALREADY-expired UTC deadline (60 min in the past) so the real wall-clock
        # tick sweeps it without a frozen-clock injection (the deadline is UTC-
        # persisted and re-evaluated against now() — AC-13, no asyncio.sleep timer).
        decision_id = await repository.create_pause_decision(
            run_id=run_id,
            request_json='{"task_name":"Plan","questions":[],"context":{}}',
            task_name="Plan",
            timeout_at=compute_timeout_at(minutes=-60),
        )

        # Drive ONE real tick through the production-shaped deps.
        outcome = await run_tick(handle.deps)
        assert outcome.reconcile.pauses_timed_out == 1

        row = await repository.get_pause_decision(decision_id)
        assert row is not None
        assert row["status"] == "answered"
        assert row["resolved_by"] == "timeout"

        # A SECOND tick does NOT re-resolve (the exactly-once guard — INV-9).
        outcome2 = await run_tick(handle.deps)
        assert outcome2.reconcile.pauses_timed_out == 0


# ── (2) AC-14/15: the LIVE tick fires a due backoff through the launch boundary ─


async def test_live_tick_fires_due_backoff_through_redispatch() -> None:
    """A run enqueued on the lifespan scheduler with a due backoff is re-dispatched."""
    url = _fresh_url()
    await _seed_project(url)
    app = _build_app(url)

    async with _lifespan(app):
        handle = app.state.orchestrator
        assert isinstance(handle, OrchestratorHandle)
        scheduler = handle.deps.retry_scheduler
        # The production tick deps MUST carry the lifespan-composed scheduler — the
        # other half of the dead-wiring fix — and it is the SAME app.state singleton.
        assert isinstance(scheduler, RetryScheduler)
        assert scheduler is getattr(app.state, RETRY_SCHEDULER_ATTR)

        repository: Repository = app.state.repository
        run_id = await _seed_terminal_run(repository, issue_num=72)

        # Swap in a recorder so the drain is observable without launching a container
        # (still the LIVE singleton; only its launch boundary is the recorder).
        recorder = _RecordingRedispatch()
        scheduler.redispatch = recorder

        # Persist an ALREADY-due backoff (due_at in the past) so the real-clock tick
        # fires it — a UTC-persisted deadline, re-evaluated, not slept on.
        state = await scheduler.schedule(run_id, issue_num=72, error="stall")
        state.due_at = due_at_from_now(-5.0)
        await scheduler._write_state(state)  # noqa: SLF001 — test seeds a past deadline

        outcome = await run_tick(handle.deps)
        assert outcome.reconcile.retries_fired == (run_id,)
        assert recorder.calls == [(run_id, None)]

        # The fired backoff is consumed — a second tick does not re-fire it.
        outcome2 = await run_tick(handle.deps)
        assert outcome2.reconcile.retries_fired == ()


# ── (3) AC-16: a manual POST /runs/{id}/retry then a tick drains the queue ─────


async def test_manual_retry_then_tick_drains_the_same_scheduler() -> None:
    """POST /runs/{id}/retry + a tick re-dispatch — endpoint & tick share one queue."""
    url = _fresh_url()
    await _seed_project(url)
    app = _build_app(url)

    async with _lifespan(app):
        handle = app.state.orchestrator
        assert isinstance(handle, OrchestratorHandle)
        scheduler = handle.deps.retry_scheduler
        assert isinstance(scheduler, RetryScheduler)

        repository: Repository = app.state.repository
        run_id = await _seed_terminal_run(repository, issue_num=73)

        # Record re-dispatches on the LIVE singleton the endpoint also resolves.
        recorder = _RecordingRedispatch()
        scheduler.redispatch = recorder

        # The manual retry endpoint enqueues an IMMEDIATE (due-now) retry onto the
        # process-wide scheduler the tick fires from (same singleton). Issued over
        # ASGITransport on THIS loop (no second lifespan) with a loopback Host + the
        # bearer token (INV-1); the empty body passes the JSON-only CSRF gate.
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8787"
        ) as client:
            resp = await client.post(
                f"/api/v1/runs/{run_id}/retry",
                headers={"Authorization": f"Bearer {TEST_TOKEN}"},
            )
        assert resp.status_code == 202, resp.text
        assert resp.json()["queued"] is True

        # The endpoint resolved the SAME app.state scheduler the tick fires from.
        assert getattr(app.state, RETRY_SCHEDULER_ATTR) is scheduler

        # Before the tick the queue holds the manual retry (it has NOT drained yet).
        queue_before = await scheduler.read_retry_queue()
        assert [e.id for e in queue_before] == [run_id]

        # ONE real tick drains it — the dead-wiring bug left this enqueue stranded.
        outcome = await run_tick(handle.deps)
        assert outcome.reconcile.retries_fired == (run_id,)
        assert recorder.calls == [(run_id, None)]
