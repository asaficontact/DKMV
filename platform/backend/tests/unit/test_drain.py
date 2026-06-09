"""Graceful drain on SIGTERM (slice 3.5 — AC-18, INV-10 binding).

The load-bearing durability property: a ``docker compose restart`` (SIGTERM) must
**stop every live run's container** — never bare-cancel a task (which would orphan
a money-spending container). Against a real migrated SQLite DB with a fake
:class:`RunKiller` recording container stops, these tests assert:

* drain calls ``RunHandle.stop(force=True)`` (the recorded kill) for **every** live
  run, leaving none running, and flips each stopped run to ``cancelled``;
* a run the drain could **not** cleanly stop (no live handle) is marked
  **``interrupted``** for the boot sweep — never left running-and-unaccounted;
* the drain deadline is a **UTC-persisted** comparison (a frozen clock past it
  interrupts the remainder), not a slept timer;
* :func:`drain_with_stop` sets the tick ``stop`` event first (stops dispatch).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.db.repository import Repository
from app.orchestrator.drain import DrainDeps, drain, drain_with_stop

pytestmark = pytest.mark.asyncio

_REPO = "octo/widgets"
_BASE = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _clock(seconds: float) -> Any:
    def _now() -> datetime:
        return _BASE + timedelta(seconds=seconds)

    return _now


class _FakeKiller:
    """Records the runs it stopped; a live container exists only for ``alive`` ids."""

    def __init__(self, *, alive_engine_ids: set[str] | None = None, raise_on: str | None = None):
        self.killed: list[str] = []
        self._alive = alive_engine_ids
        self._raise_on = raise_on

    async def kill(self, run_row: dict[str, Any]) -> bool:
        engine_id = run_row.get("engine_run_id")
        if self._raise_on is not None and str(run_row["id"]) == self._raise_on:
            raise RuntimeError("engine stop blew up")
        if not engine_id:
            return False
        if self._alive is not None and str(engine_id) not in self._alive:
            return False
        self.killed.append(str(run_row["id"]))
        return True


async def _seed_run(
    repository: Repository,
    *,
    run_id: str,
    issue_num: int,
    status: str,
    engine_run_id: str | None = None,
) -> None:
    await repository.claim_run(
        idempotency_key=f"{issue_num}::wf::main",
        repo=_REPO,
        issue_num=issue_num,
        workflow_id="wf",
        agent="claude",
        branch="main",
        run_id=run_id,
    )
    fields: dict[str, Any] = {"status": status}
    if engine_run_id is not None:
        fields["engine_run_id"] = engine_run_id
    await repository.update_run_fields(run_id, **fields)


async def _status(repository: Repository, run_id: str) -> str:
    row = await repository.get_run(run_id)
    assert row is not None
    return str(row["status"])


async def test_drain_stops_every_live_container(repo: Repository) -> None:
    """AC-18: SIGTERM drain stops every live run's container (none left running)."""
    await _seed_run(repo, run_id="r-1", issue_num=1, status="running", engine_run_id="e1")
    await _seed_run(repo, run_id="r-2", issue_num=2, status="paused", engine_run_id="e2")
    killer = _FakeKiller(alive_engine_ids={"e1", "e2"})

    result = await drain(DrainDeps(repository=repo, killer=killer, repo=_REPO, now=_clock(0)))

    # Every live run's container was stopped — via stop(force=True), not a bare cancel.
    assert set(killer.killed) == {"r-1", "r-2"}
    assert set(result.stopped) == {"r-1", "r-2"}
    assert result.interrupted == ()
    assert await _status(repo, "r-1") == "cancelled"
    assert await _status(repo, "r-2") == "cancelled"


async def test_drain_interrupts_runs_without_live_handle(repo: Repository) -> None:
    """A run with no live handle (started by another/dead process) → interrupted."""
    await _seed_run(repo, run_id="r-live", issue_num=1, status="running", engine_run_id="alive")
    await _seed_run(repo, run_id="r-orphan", issue_num=2, status="running", engine_run_id="dead")
    killer = _FakeKiller(alive_engine_ids={"alive"})  # only r-live has a live handle

    result = await drain(DrainDeps(repository=repo, killer=killer, repo=_REPO, now=_clock(0)))

    assert result.stopped == ("r-live",)
    assert result.interrupted == ("r-orphan",)
    assert await _status(repo, "r-live") == "cancelled"
    # The undrained run is interrupted (for the boot sweep) — never left running.
    assert await _status(repo, "r-orphan") == "interrupted"


async def test_drain_deadline_interrupts_remainder(repo: Repository) -> None:
    """AC-18/AC-13: a UTC-persisted deadline (not a sleep) interrupts the remainder.

    With a zero-length drain budget and a clock already past it, the drain marks
    every live run ``interrupted`` without stopping (the boot sweep reaps them).
    """
    await _seed_run(repo, run_id="r-1", issue_num=1, status="running", engine_run_id="e1")
    killer = _FakeKiller(alive_engine_ids={"e1"})

    # deadline_s=0 → due_at == now; the per-iteration is_due check fires immediately.
    result = await drain(
        DrainDeps(repository=repo, killer=killer, repo=_REPO, deadline_s=0.0, now=_clock(0))
    )

    assert killer.killed == []  # never even attempted the stop — deadline elapsed
    assert result.interrupted == ("r-1",)
    assert await _status(repo, "r-1") == "interrupted"


async def test_drain_stop_error_interrupts_that_run(repo: Repository) -> None:
    """A per-run stop that raises degrades THAT run to interrupted; others still drain."""
    await _seed_run(repo, run_id="r-ok", issue_num=1, status="running", engine_run_id="e1")
    await _seed_run(repo, run_id="r-bad", issue_num=2, status="running", engine_run_id="e2")
    killer = _FakeKiller(alive_engine_ids={"e1", "e2"}, raise_on="r-bad")

    result = await drain(DrainDeps(repository=repo, killer=killer, repo=_REPO, now=_clock(0)))

    assert result.stopped == ("r-ok",)
    assert result.interrupted == ("r-bad",)
    assert await _status(repo, "r-ok") == "cancelled"
    assert await _status(repo, "r-bad") == "interrupted"


async def test_drain_ignores_terminal_runs(repo: Repository) -> None:
    """Only active runs are drained; already-terminal rows are left untouched."""
    await _seed_run(repo, run_id="r-done", issue_num=1, status="completed", engine_run_id="e1")
    killer = _FakeKiller(alive_engine_ids={"e1"})

    result = await drain(DrainDeps(repository=repo, killer=killer, repo=_REPO, now=_clock(0)))

    assert killer.killed == []
    assert result.considered == 0
    assert await _status(repo, "r-done") == "completed"


async def test_drain_with_stop_halts_dispatch_first(repo: Repository) -> None:
    """drain_with_stop sets the tick stop event (stops dispatch) before draining."""
    await _seed_run(repo, run_id="r-1", issue_num=1, status="running", engine_run_id="e1")
    killer = _FakeKiller(alive_engine_ids={"e1"})
    stop = asyncio.Event()

    result = await drain_with_stop(
        DrainDeps(repository=repo, killer=killer, repo=_REPO, now=_clock(0)), stop=stop
    )

    assert stop.is_set()  # dispatch halted first
    assert result.stopped == ("r-1",)
