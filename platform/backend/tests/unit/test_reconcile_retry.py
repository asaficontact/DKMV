"""Slice 3.4 — reconcile wire-ins: pause-timeout auto-resolve + retry drive.

The 3.4 additions to the reconcile pass (3.3's file, wired this wave):

* **AC-17 (T104 / INV-9):** the pause ``timeout_at`` is re-evaluated by the
  reconcile tick and auto-resolved via the **exactly-once** guard
  (``resolved_by='timeout'``). A single sweep yields exactly one timeout transition;
  a second sweep does **not** double-resolve.
* **AC-14/15:** a stall/orphan :class:`StallSignal` schedules a capped-backoff retry,
  and a due backoff fires the idempotent re-dispatch — all from one
  :func:`reconcile.reconcile_once` pass when a scheduler is wired.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.config import Settings
from app.db.repository import Repository
from app.hitl import DecisionRegistry
from app.hitl.pause_bridge import compute_timeout_at
from app.orchestrator import reconcile
from app.orchestrator.reconcile import ReconcileDeps, StallSignal
from app.orchestrator.retry import RetryScheduler

pytestmark = pytest.mark.asyncio

_REPO = "octo/widgets"
_BASE = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _clock(seconds: float) -> Any:
    def _now() -> datetime:
        return _BASE + timedelta(seconds=seconds)

    return _now


class _NoopKiller:
    async def kill(self, run_row: dict[str, Any]) -> bool:
        return False


class _FakeClient:
    async def replace_labels(self, repo: str, num: int, labels: list[str]) -> list[str]:
        return list(labels)


class _PassthroughQueue:
    async def submit(self, factory: Any, *, label: str = "mutation") -> Any:
        return await factory()


class _RecordingRedispatch:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def __call__(self, row: dict[str, Any], start_task: str | None) -> str | None:
        self.calls.append((str(row["id"]), start_task))
        return "redispatched"


def _deps(
    repository: Repository,
    *,
    decisions: DecisionRegistry | None = None,
    scheduler: RetryScheduler | None = None,
    now_seconds: float = 0.0,
) -> ReconcileDeps:
    return ReconcileDeps(
        repository=repository,
        github_client=_FakeClient(),  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed test client
        write_queue=_PassthroughQueue(),  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed test queue
        killer=_NoopKiller(),
        settings=Settings(_env_file=None, STALL_TIMEOUT_S=300),  # type: ignore[call-arg]  # DKMVP-ESCAPE: pydantic-settings kwargs
        cache=None,
        now=_clock(now_seconds),
        decisions=decisions,
        retry_scheduler=scheduler,
    )


async def _seed_run(repo: Repository, *, issue_num: int, status: str = "failed") -> str:
    run_id, _ = await repo.claim_run(
        idempotency_key=f"{issue_num}::qa::main",
        repo=_REPO,
        issue_num=issue_num,
        workflow_id="qa",
        agent="claude",
        branch="dkmv/issue-feature",
    )
    await repo.update_run_fields(run_id, status=status)
    return run_id


# ── AC-17: pause-timeout auto-resolve wired into reconcile (INV-9) ────────────


async def test_reconcile_auto_resolves_expired_pause_once(repo: Repository) -> None:
    """An expired pause is auto-resolved by reconcile via the exactly-once guard (AC-17)."""
    run_id = await _seed_run(repo, issue_num=61, status="paused")
    decision_id = await repo.create_pause_decision(
        run_id=run_id,
        request_json='{"task_name":"Plan","questions":[],"context":{}}',
        task_name="Plan",
        timeout_at=compute_timeout_at(minutes=60),
    )
    decisions = DecisionRegistry()

    # now() well past timeout_at → reconcile auto-resolves exactly one pause.
    deps = _deps(repo, decisions=decisions, now_seconds=2 * 60 * 60)
    result = await reconcile.reconcile_once(deps, _REPO)
    assert result.pauses_timed_out == 1

    row = await repo.get_pause_decision(decision_id)
    assert row is not None
    assert row["status"] == "answered"
    assert row["resolved_by"] == "timeout"

    # A SECOND reconcile pass does NOT re-resolve (the guard makes it idempotent).
    result2 = await reconcile.reconcile_once(deps, _REPO)
    assert result2.pauses_timed_out == 0


async def test_reconcile_without_registry_skips_pause_sweep(repo: Repository) -> None:
    """No decision registry wired → the pause sweep is a no-op (3.3's default)."""
    run_id = await _seed_run(repo, issue_num=62, status="paused")
    await repo.create_pause_decision(
        run_id=run_id,
        request_json="{}",
        task_name="Plan",
        timeout_at=compute_timeout_at(minutes=60),
    )
    deps = _deps(repo, decisions=None, now_seconds=2 * 60 * 60)
    result = await reconcile.reconcile_once(deps, _REPO)
    assert result.pauses_timed_out == 0


# ── AC-14/15: reconcile drives the retry scheduler from stall signals ─────────


async def test_reconcile_schedules_retry_from_stall_signal(repo: Repository) -> None:
    """drive_retries schedules a capped-backoff retry for a stall signal (AC-14)."""
    run_id = await _seed_run(repo, issue_num=63, status="failed")
    redispatch = _RecordingRedispatch()
    scheduler = RetryScheduler(repository=repo, redispatch=redispatch, now=_clock(0))

    signal = StallSignal(
        run_id=run_id, issue_num=63, reason=reconcile.STALL_REASON, container_killed=True
    )
    fired = await reconcile.drive_retries(_deps(repo, scheduler=scheduler, now_seconds=0), [signal])
    # The signal scheduled a backoff (due in 10s) — not yet due, so nothing fired.
    assert fired == ()
    queue = await scheduler.read_retry_queue()
    assert [e.id for e in queue] == [run_id]
    assert queue[0].lastError == reconcile.STALL_REASON
    assert queue[0].attempt == 1


async def test_reconcile_fires_due_retry(repo: Repository) -> None:
    """Once the backoff is due, a later reconcile pass fires the idempotent re-dispatch."""
    run_id = await _seed_run(repo, issue_num=64, status="failed")
    redispatch = _RecordingRedispatch()
    scheduler = RetryScheduler(repository=repo, redispatch=redispatch, now=_clock(0))
    # Schedule the retry (due in 10s).
    await scheduler.schedule_from_signal(
        StallSignal(run_id=run_id, issue_num=64, reason="stall", container_killed=True)
    )

    # Advance the scheduler clock past due_at and drive (no new signals).
    scheduler.now = _clock(11)
    deps = _deps(repo, scheduler=scheduler, now_seconds=11)
    fired = await reconcile.drive_retries(deps, [])
    assert fired == (run_id,)
    assert redispatch.calls == [(run_id, None)]
