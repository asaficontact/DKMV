"""Slice 3.4 — retry scheduler: backoff, retry queue, idempotent re-dispatch.

Drives :class:`app.orchestrator.retry.RetryScheduler` against a real migrated
SQLite DB (the ``repo`` fixture) with a frozen, injectable clock and a recording
re-dispatch fake. Asserts the binding §8.2 behaviors:

* **AC-14 capped backoff:** the schedule sequence is ``10s, 20s, 40s …`` capped at
  ``300s``; **max 3 attempts**, after which the 4th failure parks the run in the
  **retry queue** (FR-06-3).
* **AC-15 idempotent re-dispatch (INV-5 / R-15 — binding):** a run whose issue
  **already has an open PR** (``runs.pr_num`` set) is **resumed/skipped** on retry —
  **NO duplicate dispatch** (the §13 / AT-Recovery resilience bar). A run with no PR
  is re-dispatched through the (single) launch boundary with ``start_task=<last
  completed stage>``.
* The retry-queue projection renders ``RetryEntry`` rows ``{id, issue, attempt,
  dueIn, lastError}`` (AC-4 / FR-06-3).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.db.repository import Repository
from app.orchestrator.retry import (
    BACKOFF_CAP_S,
    MAX_ATTEMPTS,
    RetryScheduler,
    compute_backoff,
)

_BASE = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _clock(seconds: float = 0.0) -> Any:
    def _now() -> datetime:
        return _BASE + timedelta(seconds=seconds)

    return _now


class _RecordingRedispatch:
    """Records each idempotent re-dispatch; returns a fresh run id (a new dispatch)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.return_value: str | None = "redispatched"

    async def __call__(self, row: dict[str, Any], start_task: str | None) -> str | None:
        self.calls.append((str(row["id"]), start_task))
        return self.return_value


async def _seed_run(
    repo: Repository, *, issue_num: int, pr_num: int | None = None, status: str = "failed"
) -> str:
    run_id, _ = await repo.claim_run(
        idempotency_key=f"{issue_num}::qa::main",
        repo="octo/widgets",
        issue_num=issue_num,
        workflow_id="qa",
        agent="claude",
        branch="dkmv/issue-feature",
    )
    fields: dict[str, Any] = {"status": status}
    if pr_num is not None:
        fields["pr_num"] = pr_num
    await repo.update_run_fields(run_id, **fields)
    return run_id


# ── AC-14: capped exponential backoff + max-3 → retry queue ───────────────────


def test_compute_backoff_sequence_capped_at_300() -> None:
    """``min(10s·2^(attempt-1), 300s)`` — 10, 20, 40, 80, 160, 300, 300, … (AC-14)."""
    assert compute_backoff(1) == 10.0
    assert compute_backoff(2) == 20.0
    assert compute_backoff(3) == 40.0
    assert compute_backoff(4) == 80.0
    assert compute_backoff(5) == 160.0
    assert compute_backoff(6) == BACKOFF_CAP_S  # 320 → capped at 300
    assert compute_backoff(99) == BACKOFF_CAP_S


@pytest.mark.asyncio
async def test_backoff_schedule_and_fourth_failure_parks_in_queue(repo: Repository) -> None:
    """The 3 scheduled attempts use 10/20/40s; the 4th failure parks the run (AC-14)."""
    run_id = await _seed_run(repo, issue_num=41)
    redispatch = _RecordingRedispatch()
    sched = RetryScheduler(repository=repo, redispatch=redispatch, now=_clock())

    # Attempt 1 → 10s backoff.
    s1 = await sched.schedule(run_id, issue_num=41, error="transient")
    assert s1.attempt == 1 and not s1.parked
    assert _due_in(s1.due_at) == 10.0

    # Attempt 2 → 20s.
    s2 = await sched.schedule(run_id, error="transient")
    assert s2.attempt == 2
    assert _due_in(s2.due_at) == 20.0

    # Attempt 3 → 40s.
    s3 = await sched.schedule(run_id, error="transient")
    assert s3.attempt == 3
    assert _due_in(s3.due_at) == 40.0
    assert s3.attempt == MAX_ATTEMPTS and not s3.parked

    # The 4th failure (attempts spent) parks the run in the retry queue.
    s4 = await sched.schedule(run_id, error="still failing")
    assert s4.parked is True
    assert s4.due_at is None

    queue = await sched.read_retry_queue()
    assert [e.id for e in queue] == [run_id]
    entry = queue[0]
    assert entry.issue == 41
    assert entry.attempt == MAX_ATTEMPTS  # "attempt 3/3"
    assert entry.lastError == "still failing"
    assert entry.dueIn == 0  # parked → due now


@pytest.mark.asyncio
async def test_fire_due_retry_redispatches_when_due(repo: Repository) -> None:
    """A scheduled backoff fires its idempotent re-dispatch once due (AC-13/14)."""
    run_id = await _seed_run(repo, issue_num=42, status="failed")
    # Seed a completed stage so the retry resumes from it (start_task).
    await repo.upsert_stage(run_id, 0, "Plan", status="completed")
    redispatch = _RecordingRedispatch()
    sched = RetryScheduler(repository=repo, redispatch=redispatch, now=_clock(0))
    await sched.schedule(run_id, issue_num=42, error="transient")  # due in 10s

    # Not yet due (now=5s) → no re-dispatch.
    sched.now = _clock(5)
    assert await sched.fire_due_retries() == []
    assert redispatch.calls == []

    # Advance the (frozen) clock past due_at (simulating a suspend gap) → fires.
    sched.now = _clock(11)
    fired = await sched.fire_due_retries()
    assert fired == [run_id]
    assert redispatch.calls == [(run_id, "Plan")]  # resumed from the completed stage


# ── AC-15: idempotent re-dispatch — existing PR → NO duplicate ────────────────


@pytest.mark.asyncio
async def test_retry_with_open_pr_creates_no_duplicate(repo: Repository) -> None:
    """A retry of an issue that ALREADY has an open PR does NOT re-dispatch (AC-15)."""
    run_id = await _seed_run(repo, issue_num=43, pr_num=77, status="failed")
    redispatch = _RecordingRedispatch()
    sched = RetryScheduler(repository=repo, redispatch=redispatch, now=_clock())

    dispatched = await sched.redispatch_run(run_id)

    # The open PR (runs.pr_num=77) is detected → resume/skip, NO duplicate dispatch.
    assert dispatched is False
    assert redispatch.calls == []  # the §13 resilience bar: no duplicate PR


@pytest.mark.asyncio
async def test_retry_reuses_same_run_row(repo: Repository) -> None:
    """A retry re-dispatches the SAME run row (same id) — no second claim (INV-5)."""
    run_id = await _seed_run(repo, issue_num=44, status="failed")
    redispatch = _RecordingRedispatch()
    sched = RetryScheduler(repository=repo, redispatch=redispatch, now=_clock())

    dispatched = await sched.redispatch_run(run_id)

    assert dispatched is True
    # The redispatch was handed the SAME run row id (the launch reuses it via the
    # idempotency_key — issue+workflow+branch).
    assert redispatch.calls == [(run_id, None)]


@pytest.mark.asyncio
async def test_github_pr_detection_seam_blocks_duplicate(repo: Repository) -> None:
    """When the GitHub seam reports an open PR for the branch, the retry skips (AC-15)."""
    run_id = await _seed_run(repo, issue_num=45, status="failed")  # no DB pr_num

    class _ClientWithOpenPr:
        async def find_open_pr_for_branch(self, repo_name: str, branch: str) -> dict[str, Any]:
            return {"num": 99, "branch": branch}

    redispatch = _RecordingRedispatch()
    sched = RetryScheduler(
        repository=repo,
        redispatch=redispatch,
        github_client=_ClientWithOpenPr(),  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed PR-detection seam
        now=_clock(),
    )

    assert await sched.redispatch_run(run_id) is False
    assert redispatch.calls == []  # detected via GitHub → no duplicate


# ── helpers ───────────────────────────────────────────────────────────────────


def _due_in(due_at: str | None) -> float:
    """Seconds from ``_BASE`` to a persisted ``due_at`` (the scheduled backoff)."""
    assert due_at is not None
    parsed = datetime.fromisoformat(due_at)
    return (parsed - _BASE).total_seconds()
