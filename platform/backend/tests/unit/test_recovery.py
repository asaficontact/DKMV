"""Boot crash recovery (slice 3.5 — AC-19, INV-10 / R-15 binding).

On boot, for each non-terminal ``runs`` row the dead process left in-flight,
recovery must: ``docker kill`` the orphan container (via the :class:`OrphanReaper`
seam — a CI fake records the *issued* kills), mark the run ``interrupted``, and
offer a jittered + semaphore-bounded ``start_task`` retry through 3.4's scheduler —
**without** re-attaching to any dead-process container. These tests assert all
three, plus the binding INV-10 structural property: **no ``re_attach`` / ``reattach``
symbol is defined** in the recovery module (the engine has no such API).
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import pytest
from app.db.repository import Repository
from app.orchestrator import recovery as recovery_mod
from app.orchestrator.recovery import RecoveryDeps, recover_orphans

pytestmark = pytest.mark.asyncio

_REPO = "octo/widgets"


class _FakeReaper:
    """Records the orphans a ``docker kill`` was ISSUED for (no real Docker)."""

    def __init__(self, *, killable: set[str] | None = None) -> None:
        self.reaped: list[str] = []
        self._killable = killable

    async def reap(self, run_row: dict[str, Any]) -> bool:
        engine_id = run_row.get("engine_run_id")
        if not engine_id:
            return False
        if self._killable is not None and str(engine_id) not in self._killable:
            return False
        self.reaped.append(str(run_row["id"]))
        return True


class _RecordingScheduler:
    """Records the (run_id, issue_num) retries recovery offered (reuses 3.4's API)."""

    def __init__(self) -> None:
        self.enqueued: list[tuple[str, int | None]] = []

    async def enqueue_manual(self, run_id: str, *, issue_num: int | None = None) -> Any:
        self.enqueued.append((run_id, issue_num))
        return object()


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


def _deps(
    repository: Repository,
    reaper: Any,
    *,
    scheduler: Any | None = None,
    offer_retry: bool = True,
) -> RecoveryDeps:
    return RecoveryDeps(
        repository=repository,
        reaper=reaper,
        repo=_REPO,
        retry_scheduler=scheduler,
        offer_retry=offer_retry,
        jitter_s=0.0,  # deterministic: no wait in tests
        concurrency=asyncio.Semaphore(2),
        rng=random.Random(1234),
    )


async def test_boot_scan_kills_orphan_and_interrupts(repo: Repository) -> None:
    """AC-19: each non-terminal run's orphan container is killed + run → interrupted."""
    await _seed_run(repo, run_id="r-1", issue_num=1, status="running", engine_run_id="e1")
    await _seed_run(repo, run_id="r-2", issue_num=2, status="paused", engine_run_id="e2")
    # A terminal run is NOT an orphan — left untouched.
    await _seed_run(repo, run_id="r-done", issue_num=3, status="completed", engine_run_id="e3")
    reaper = _FakeReaper()

    result = await recover_orphans(_deps(repo, reaper))

    assert set(reaper.reaped) == {"r-1", "r-2"}  # docker kill ISSUED for both orphans
    assert set(result.interrupted) == {"r-1", "r-2"}
    assert await _status(repo, "r-1") == "interrupted"
    assert await _status(repo, "r-2") == "interrupted"
    assert await _status(repo, "r-done") == "completed"  # terminal run untouched


async def test_boot_scan_offers_start_task_retry_for_pushed_stage(repo: Repository) -> None:
    """AC-19: a ``start_task`` retry is offered for an orphan with a pushed stage."""
    await _seed_run(repo, run_id="r-1", issue_num=1, status="running", engine_run_id="e1")
    # A completed stage = a pushed boundary the engine can resume from.
    await repo.upsert_stage("r-1", 0, "plan", status="completed")
    await repo.upsert_stage("r-1", 1, "build", status="running")
    scheduler = _RecordingScheduler()

    result = await recover_orphans(_deps(repo, _FakeReaper(), scheduler=scheduler))

    assert result.retried == ("r-1",)
    assert scheduler.enqueued == [("r-1", 1)]  # reused 3.4's enqueue_manual (issue 1)


async def test_boot_scan_no_retry_without_pushed_stage(repo: Repository) -> None:
    """An orphan with no completed/pushed stage stays interrupted (no auto-retry)."""
    await _seed_run(repo, run_id="r-1", issue_num=1, status="running", engine_run_id="e1")
    # No completed stage → nothing to resume from.
    await repo.upsert_stage("r-1", 0, "plan", status="running")
    scheduler = _RecordingScheduler()

    result = await recover_orphans(_deps(repo, _FakeReaper(), scheduler=scheduler))

    assert result.retried == ()
    assert scheduler.enqueued == []
    assert await _status(repo, "r-1") == "interrupted"


async def test_boot_scan_offer_retry_disabled(repo: Repository) -> None:
    """offer_retry=False leaves every orphan interrupted for a manual Retry now."""
    await _seed_run(repo, run_id="r-1", issue_num=1, status="running", engine_run_id="e1")
    await repo.upsert_stage("r-1", 0, "plan", status="completed")
    scheduler = _RecordingScheduler()

    result = await recover_orphans(
        _deps(repo, _FakeReaper(), scheduler=scheduler, offer_retry=False)
    )

    assert result.retried == ()
    assert scheduler.enqueued == []
    assert await _status(repo, "r-1") == "interrupted"


async def test_boot_scan_interrupts_even_when_no_container_to_kill(repo: Repository) -> None:
    """A run with no live container (reaper returns False) is still interrupted."""
    await _seed_run(repo, run_id="r-1", issue_num=1, status="running")  # no engine_run_id
    reaper = _FakeReaper()

    result = await recover_orphans(_deps(repo, reaper))

    assert reaper.reaped == []  # nothing to docker-kill
    assert result.interrupted == ("r-1",)
    assert await _status(repo, "r-1") == "interrupted"


async def test_no_reattach_symbol_defined() -> None:
    """INV-10 (binding): the recovery module defines NO re_attach/reattach function.

    The engine has no live-run re-attach API (R-15); recovery is kill+interrupt+retry
    only. Assert no callable named like a re-attach exists in the module namespace.
    """
    names = [n.lower() for n in vars(recovery_mod)]
    assert not any("reattach" in n or "re_attach" in n for n in names)
