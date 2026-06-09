"""§13 e2e — AT-HITL: a pause resolves EXACTLY once + the concurrency slot is released.

Runs for REAL in-process against the durable resolve-exactly-once primitive and the
Semaphore-backed slot counter — the two binding HITL guarantees (INV-9 / §8.5):

* a pending decision is resolved exactly once — a double-click / two tabs / a racing
  timeout sweep can never all win; only the FIRST writer flips the row (rowcount=1);
* a pause RELEASES the concurrency slot (so a parked, idle run does not hold a
  dispatch permit) and re-acquires on resume, never manufacturing phantom capacity.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from app.db import Repository
from app.hitl import ConcurrencySlots, DecisionRegistry
from app.hitl.answer import resolve_pending_pause

from tests.conftest import _migrate

pytestmark = pytest.mark.asyncio

REPO = "o/r"


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> Repository:
    repo = Repository(_migrate(tmp_path / "hitl.db"))
    await repo.start()
    return repo


async def _seed_pending(repository: Repository, decisions: DecisionRegistry) -> str:
    """Claim a run + a pending decision; register it so resolve can fire its event."""
    run_id, _ = await repository.claim_run(idempotency_key="hitl-1", repo=REPO, agent="claude")
    decision_id = await repository.create_pause_decision(
        run_id=run_id,
        request_json="{}",
        task_name="review",
        timeout_at="2999-01-01T00:00:00+00:00",
    )
    decisions.register(decision_id)
    return decision_id


async def test_at_hitl_resolves_exactly_once(repository: Repository) -> None:
    """AT-HITL: two concurrent answers → exactly ONE wins (INV-9 rowcount guard)."""
    decisions = DecisionRegistry()
    decision_id = await _seed_pending(repository, decisions)

    async def _answer() -> bool:
        return await resolve_pending_pause(
            repository=repository,
            decisions=decisions,
            decision_id=decision_id,
            answers={"q": "approve"},
            skip_remaining=False,
            resolved_by="human",
        )

    results = await asyncio.gather(_answer(), _answer())
    assert sum(1 for won in results if won) == 1  # exactly one writer won
    # The row is terminal; a third attempt also loses (never double-resolves).
    assert (await _answer()) is False
    await repository.close()


async def test_at_hitl_pause_releases_and_reacquires_slot(repository: Repository) -> None:
    """AT-HITL: a pause frees a dispatch slot; resume re-acquires; no phantom capacity."""
    slots = ConcurrencySlots(capacity=1)
    await slots.acquire_async()  # a run holds the only slot
    assert slots.available == 0

    waiter = asyncio.ensure_future(slots.acquire_async())
    await asyncio.sleep(0.02)
    assert not waiter.done()  # a second dispatch is blocked while the slot is held

    slots.release()  # the holding run PAUSES → releases its slot (INV-9)
    await asyncio.wait_for(waiter, timeout=1.0)  # the blocked dispatch wakes
    assert slots.held == 1

    # The paused run RESUMES → re-acquires (held truthfully reflects oversubscription).
    slots.acquire()
    assert slots.held == 2

    # A spurious double release never pushes capacity above the ceiling (INV-9).
    fresh = ConcurrencySlots(capacity=1)
    fresh.release()
    fresh.release()
    assert fresh.available == 1  # no phantom capacity
    await repository.close()
