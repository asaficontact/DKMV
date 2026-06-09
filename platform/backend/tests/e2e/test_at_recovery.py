"""§13 e2e — AT-Recovery: boot recovery kills the orphan + marks ``interrupted`` +
offers ``start_task`` — no duplicate PR, no orphaned container (INV-10).

Runs for REAL in-process against the boot-recovery path: for each non-terminal run
a dead process left in-flight, recovery ``docker kill``-s the orphan container (via
the reaper seam — a fake records the issued kills, no real Docker), marks the run
``interrupted``, and offers a ``start_task`` retry from the last pushed boundary —
WITHOUT ever re-attaching to a dead-process container (INV-10 / R-15). The "no
duplicate PR" guarantee is structural: recovery never re-launches a still-running
run (it interrupts first) and the engine resumes from the pushed boundary, so the
push is not re-issued for an already-pushed stage.
"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from app.db import Repository
from app.orchestrator import recovery as recovery_mod
from app.orchestrator.recovery import RecoveryDeps, recover_orphans

from tests.conftest import _migrate

pytestmark = pytest.mark.asyncio

_REPO = "octo/widgets"


class _FakeReaper:
    """Records the orphans a ``docker kill`` was ISSUED for (no real Docker)."""

    def __init__(self) -> None:
        self.reaped: list[str] = []

    async def reap(self, run_row: dict[str, Any]) -> bool:
        if not run_row.get("engine_run_id"):
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


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> Repository:
    repo = Repository(_migrate(tmp_path / "recovery.db"))
    await repo.start()
    return repo


async def _seed(
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


def _deps(repository: Repository, reaper: Any, scheduler: Any) -> RecoveryDeps:
    return RecoveryDeps(
        repository=repository,
        reaper=reaper,
        repo=_REPO,
        retry_scheduler=scheduler,
        offer_retry=True,
        jitter_s=0.0,
        concurrency=asyncio.Semaphore(2),
        rng=random.Random(1234),
    )


async def test_at_recovery_kills_orphan_interrupts_and_offers_start_task(
    repository: Repository,
) -> None:
    """AT-Recovery: kill orphan + mark interrupted + start_task from the pushed boundary."""
    await _seed(repository, run_id="r-1", issue_num=1, status="running", engine_run_id="e1")
    # A completed stage = a pushed boundary the engine can resume from (no dup push).
    await repository.upsert_stage("r-1", 0, "plan", status="completed")
    await repository.upsert_stage("r-1", 1, "build", status="running")
    # A terminal run is NOT an orphan — left untouched (no spurious re-launch / dup PR).
    await _seed(repository, run_id="r-done", issue_num=2, status="completed", engine_run_id="e2")

    reaper = _FakeReaper()
    scheduler = _RecordingScheduler()
    result = await recover_orphans(_deps(repository, reaper, scheduler))

    # The orphan container was docker-killed (no orphaned money-spending container).
    assert reaper.reaped == ["r-1"]
    # The run was marked interrupted (not left "running" forever).
    row = await repository.get_run("r-1")
    assert row is not None and row["status"] == "interrupted"
    # A start_task retry was offered for the pushed stage (resume, not restart).
    assert result.retried == ("r-1",)
    assert scheduler.enqueued == [("r-1", 1)]
    # The terminal run is untouched (recovery never re-launches it → no duplicate PR).
    done = await repository.get_run("r-done")
    assert done is not None and done["status"] == "completed"
    await repository.close()


async def test_at_recovery_never_reattaches(repository: Repository) -> None:
    """AT-Recovery (INV-10 binding): the recovery module defines NO re-attach symbol."""
    names = [n.lower() for n in vars(recovery_mod)]
    assert not any("reattach" in n or "re_attach" in n for n in names)
    await repository.close()
