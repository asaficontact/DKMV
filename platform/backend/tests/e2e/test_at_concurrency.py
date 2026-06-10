"""§13 e2e — AT-Concurrency: only N runs at once + admission deny/requeue over caps.

Runs for REAL in-process against the bounded dispatcher + the aggregate-resource
admission controller over a migrated SQLite DB (no Docker, no engine). The binding
NFR-SCALE-1 / §8.2 behaviors:

* with a 3-slot semaphore and 5 queued candidates, exactly N=3 dispatch at once; the
  rest queue and drain as slots free;
* a run that would exceed ``HOST_MEMORY_BUDGET`` **or** ``DAILY_SPEND_CAP`` is
  admission-DENIED and RE-QUEUED (slot handed back, launch boundary never called) —
  never silently dropped, never dispatched. Daily spend uses the Codex-excluded
  projection (INV-8): a Codex run contributes $0 and never trips the spend cap.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from app.config import Settings
from app.db import EventRecord, Repository
from app.hitl.slots import ConcurrencySlots
from app.orchestrator.admission import AdmissionController
from app.orchestrator.dispatch import BoundedDispatcher
from app.orchestrator.tick import Candidate

from tests.conftest import _migrate

pytestmark = pytest.mark.asyncio

REPO = "o/r"


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]  # DKMVP-ESCAPE: pydantic-settings test kwargs


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> Repository:
    repo = Repository(_migrate(tmp_path / "conc.db"))
    await repo.start()
    return repo


async def _seed_run(
    repository: Repository,
    *,
    status: str = "running",
    agent: str = "claude",
    memory: str | None = "8g",
    cost: float | None = None,
) -> str:
    run_id, _ = await repository.claim_run(
        idempotency_key=str(uuid.uuid4()), repo=REPO, agent=agent, memory_limit=memory
    )
    if status != "pending":
        await repository.update_run_fields(run_id, status=status)
    if cost is not None:
        await repository.append_events(
            [EventRecord(run_id, 0, "task_completed", {}, task_index=0, cost_usd=cost, agent=agent)]
        )
    return run_id


def _candidate(num: int) -> Candidate:
    return Candidate(repo=REPO, num=num, workflow_id="dev", labels=("agent:queued",))


async def test_at_concurrency_only_n_run_at_once_then_drain(repository: Repository) -> None:
    """AT-Concurrency: >max_concurrent_runs candidates → only N at once, rest drain."""
    slots = ConcurrencySlots(capacity=3)
    launched: list[int] = []

    async def fake_dispatch(candidate: Candidate) -> object:
        launched.append(candidate.num)
        await _seed_run(repository, status="running")
        return object()

    dispatcher = BoundedDispatcher(
        dispatch=fake_dispatch,
        slots=slots,
        admission=AdmissionController(repository=repository, settings=_settings()),
        repository=repository,
    )
    result = await dispatcher.dispatch_candidates(REPO, [_candidate(n) for n in range(1, 6)])
    assert len(result.dispatched) == 3  # only N=3 run at once
    assert slots.held == 3
    assert result.seen == 5  # the other 2 queued (seen but not dispatched)

    # Two running runs complete → the next pass drains exactly the 2 freed slots.
    rows = await repository.read_active_run_memory(REPO, ["running"])
    for row in rows[:2]:
        await repository.update_run_fields(str(row["id"]), status="completed")
    result2 = await dispatcher.dispatch_candidates(REPO, [_candidate(n) for n in range(6, 9)])
    assert len(result2.dispatched) == 2
    await repository.close()


async def test_at_concurrency_admission_denies_and_requeues_over_spend(
    repository: Repository,
) -> None:
    """AT-Concurrency: a run over DAILY_SPEND_CAP is admission-denied + re-queued, not dropped."""
    await _seed_run(repository, status="completed", agent="claude", cost=50.0)
    slots = ConcurrencySlots(capacity=3)
    launched: list[int] = []

    async def fake_dispatch(candidate: Candidate) -> object:
        launched.append(candidate.num)
        return object()

    dispatcher = BoundedDispatcher(
        dispatch=fake_dispatch,
        slots=slots,
        admission=AdmissionController(
            repository=repository, settings=_settings(DAILY_SPEND_CAP=10.0)
        ),
        repository=repository,
    )
    result = await dispatcher.dispatch_candidates(REPO, [_candidate(1)])
    assert result.dispatched == ()  # not dispatched (over cap)
    assert result.admission_denied == 1  # re-queued, not dropped
    assert launched == []  # the launch boundary was never called
    assert slots.held == 0  # the probe permit was handed back
    await repository.close()


async def test_at_concurrency_codex_excluded_from_spend_cap(repository: Repository) -> None:
    """AT-Concurrency: a Codex run's $0 spend never trips DAILY_SPEND_CAP (INV-8)."""
    await _seed_run(repository, status="completed", agent="codex", cost=100.0)
    controller = AdmissionController(
        repository=repository, settings=_settings(DAILY_SPEND_CAP=10.0)
    )
    decision = await controller.evaluate(REPO, run_memory="8g")
    assert decision.admitted  # Codex spend excluded → cap not tripped
    assert decision.projected_spend_usd == 0.0
    await repository.close()
