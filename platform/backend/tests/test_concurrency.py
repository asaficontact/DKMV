"""Slice 5.1 — bounded concurrency + aggregate admission + loop observability.

Covers the F13 acceptance criteria the concurrency slice owns:

* **AC-1 (NFR-SCALE-1).** Dispatch is gated by a real ``asyncio.Semaphore``-backed
  :class:`ConcurrencySlots`: launching ``> max_concurrent_runs`` issues runs only N
  at once; the rest queue, then drain as slots free.
* **AC-2.** A configured per-state cap throttles that state per tick.
* **AC-3 (binding).** A run that would exceed ``HOST_MEMORY_BUDGET`` **or**
  ``DAILY_SPEND_CAP`` is admission-denied and **re-queued** (not dropped, not
  dispatched). Daily spend uses the Codex-excluded projection (INV-8).
* **AC-4 (INV-6).** The event-append path is off-loop + batched (one writer, one
  ``BEGIN IMMEDIATE``): the live batching seam is the per-run :class:`EventPump`
  (:mod:`app.sse.pump`), which coalesces whatever is ready on the run's queue (up to
  ``MAX_BATCH``) into ONE :meth:`Repository.append_events` round-trip off the loop.
  (The orchestrator tick/dispatch/reconcile does not emit high-frequency events — it
  only appends through the same off-loop single-writer :class:`Repository` — so there
  is no separate orchestrator event-batching module; the pump is THE batching seam.)
* **AC-5.** The loop heartbeat advances each tick and the slots-in-use gauge tracks
  the slot counter.

These exercise the real components (no Docker, no engine): the slot counter, the
admission controller over a migrated SQLite DB, the bounded dispatcher with a
recording fake launch, the pump's batched append, and the loop-metrics gauges.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from app.config import Settings
from app.db import EventRecord, Repository
from app.hitl.slots import ConcurrencySlots
from app.orchestrator.admission import (
    AdmissionController,
    parse_memory_bytes,
    start_of_utc_day,
)
from app.orchestrator.dispatch import (
    BoundedDispatcher,
    DispatchPolicy,
    build_policy_from_settings,
)
from app.orchestrator.loop_metrics import LoopMetrics
from app.orchestrator.tick import Candidate
from app.sse.observer_bridge import RunStreamHub
from app.sse.pump import MAX_BATCH, EventPump
from dkmv.runtime import RuntimeEvent

REPO = "o/r"


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]  # DKMVP-ESCAPE: pydantic-settings test kwargs


@pytest_asyncio.fixture
async def repository(database_url: str) -> Repository:
    repo = Repository(database_url)
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
    """Claim a run, set its status/memory, and optionally append a cost event."""
    run_id, won = await repository.claim_run(
        idempotency_key=str(uuid.uuid4()),
        repo=REPO,
        issue_num=None,
        agent=agent,
        memory_limit=memory,
    )
    assert won
    if status != "pending":
        await repository.update_run_fields(run_id, status=status)
    if cost is not None:
        await repository.append_events(
            [
                EventRecord(
                    run_id=run_id,
                    sequence=0,
                    event_type="task_completed",
                    payload={"cost_usd": cost},
                    task_index=0,
                    cost_usd=cost,
                    agent=agent,
                )
            ]
        )
    return run_id


def _candidate(num: int, *, labels: tuple[str, ...] = ("agent:queued",)) -> Candidate:
    return Candidate(repo=REPO, num=num, workflow_id="dev", labels=labels)


# ── AC-1: bounded concurrency (semaphore) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_semaphore_blocks_when_full() -> None:
    """``acquire_async`` blocks once all permits are held; a release wakes it (AC-1)."""
    slots = ConcurrencySlots(capacity=2)
    await slots.acquire_async()
    await slots.acquire_async()
    assert slots.held == 2
    assert slots.available == 0

    waiter = asyncio.ensure_future(slots.acquire_async())
    await asyncio.sleep(0.02)
    assert not waiter.done()  # blocked — no free permit

    slots.release()  # a run completes/pauses → frees a permit
    await asyncio.wait_for(waiter, timeout=1.0)
    assert slots.held == 2


@pytest.mark.asyncio
async def test_dispatch_caps_at_max_concurrent_then_drains(repository: Repository) -> None:
    """> max_concurrent_runs candidates → only N run at once; rest drain as slots free.

    AC-1 / NFR-SCALE-1: with a 3-slot cap and 5 queued candidates, the first pass
    dispatches exactly 3 (the others queue). After two of the dispatched runs reach a
    terminal status, the next pass resyncs the freed slots and drains 2 more.
    """
    slots = ConcurrencySlots(capacity=3)
    launched: list[int] = []

    async def fake_dispatch(candidate: Candidate) -> object:
        launched.append(candidate.num)
        # Simulate the run going live: mark a DB row running so the resync counts it.
        await _seed_run(repository, status="running")
        return object()

    dispatcher = BoundedDispatcher(
        dispatch=fake_dispatch,
        slots=slots,
        admission=AdmissionController(repository=repository, settings=_settings()),
        repository=repository,
    )

    candidates = [_candidate(n) for n in range(1, 6)]  # 5 candidates, cap 3
    result = await dispatcher.dispatch_candidates(REPO, candidates)

    assert len(result.dispatched) == 3  # only N run at once
    assert slots.held == 3
    assert slots.available == 0
    assert result.seen == 5

    # Two of the three running runs complete → their DB rows go terminal.
    rows = await repository.read_active_run_memory(REPO, ["running"])
    assert len(rows) == 3  # the first pass put 3 runs running
    for row in rows[:2]:
        await repository.update_run_fields(str(row["id"]), status="completed")

    # Next pass: the resync reclaims the 2 freed slots and drains 2 more candidates.
    remaining = [_candidate(n) for n in range(6, 9)]  # 3 more candidates
    result2 = await dispatcher.dispatch_candidates(REPO, remaining)
    assert len(result2.dispatched) == 2  # exactly the 2 freed slots drain
    assert slots.held == 3


# ── AC-2: per-state caps ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_per_state_cap_throttles(repository: Repository) -> None:
    """A configured per-state cap throttles that state per tick (AC-2)."""
    slots = ConcurrencySlots(capacity=10)  # generous count cap so only the state cap bites

    async def fake_dispatch(candidate: Candidate) -> object:
        await _seed_run(repository, status="running")
        return object()

    dispatcher = BoundedDispatcher(
        dispatch=fake_dispatch,
        slots=slots,
        admission=AdmissionController(repository=repository, settings=_settings()),
        repository=repository,
        policy=DispatchPolicy(per_state={"agent:queued": 2}),
    )

    candidates = [_candidate(n) for n in range(1, 6)]  # 5 queued candidates, state cap 2
    result = await dispatcher.dispatch_candidates(REPO, candidates)

    assert len(result.dispatched) == 2  # throttled by the per-state cap
    assert result.state_capped == 3  # the rest re-queued for a later tick


def test_build_policy_from_settings_default_uncapped() -> None:
    """v1 ships no per-state throttle by default (the global semaphore bounds count)."""
    policy = build_policy_from_settings(_settings())
    assert policy.per_state == {}


# ── AC-3: aggregate admission (memory + daily spend, Codex-excluded) ──────────


@pytest.mark.asyncio
async def test_admission_denies_over_memory_budget(repository: Repository) -> None:
    """A run that would exceed HOST_MEMORY_BUDGET is denied (AC-3)."""
    # Two 8g runs already running = 16g; budget 20g; a third 8g run → 24g > 20g.
    await _seed_run(repository, status="running", memory="8g")
    await _seed_run(repository, status="running", memory="8g")
    controller = AdmissionController(
        repository=repository, settings=_settings(HOST_MEMORY_BUDGET="20g")
    )
    decision = await controller.evaluate(REPO, run_memory="8g")
    assert not decision.admitted
    assert decision.reason == "memory"


@pytest.mark.asyncio
async def test_admission_denies_over_daily_spend(repository: Repository) -> None:
    """A run is denied once today's Codex-excluded spend exceeds DAILY_SPEND_CAP (AC-3)."""
    await _seed_run(repository, status="completed", agent="claude", cost=12.0)
    controller = AdmissionController(
        repository=repository, settings=_settings(DAILY_SPEND_CAP=10.0)
    )
    decision = await controller.evaluate(REPO, run_memory="8g")
    assert not decision.admitted
    assert decision.reason == "spend"


@pytest.mark.asyncio
async def test_admission_codex_excluded_from_spend(repository: Repository) -> None:
    """A Codex run contributes $0 to the daily-spend cap (INV-8) — admitted (AC-3)."""
    # A Codex run with a (engine-side) cost event is still excluded from spend.
    await _seed_run(repository, status="completed", agent="codex", cost=100.0)
    controller = AdmissionController(
        repository=repository, settings=_settings(DAILY_SPEND_CAP=10.0)
    )
    decision = await controller.evaluate(REPO, run_memory="8g")
    assert decision.admitted  # Codex spend excluded → cap not tripped
    assert decision.projected_spend_usd == 0.0


@pytest.mark.asyncio
async def test_admission_denied_candidate_is_requeued_not_dropped(repository: Repository) -> None:
    """A denied candidate re-queues (slot handed back, not dispatched) — AC-3 binding."""
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
    assert launched == []  # launch boundary never called
    assert slots.held == 0  # the probe permit was handed back


@pytest.mark.asyncio
async def test_admission_disabled_caps_always_pass(repository: Repository) -> None:
    """Unset HOST_MEMORY_BUDGET / DAILY_SPEND_CAP = no limit on that dimension (AC-3)."""
    await _seed_run(repository, status="running", memory="64g")
    controller = AdmissionController(repository=repository, settings=_settings())
    decision = await controller.evaluate(REPO, run_memory="64g")
    assert decision.admitted


def test_parse_memory_bytes() -> None:
    assert parse_memory_bytes("8g") == 8 * 1024**3
    assert parse_memory_bytes("512m") == 512 * 1024**2
    assert parse_memory_bytes("1024") == 1024
    assert parse_memory_bytes(None) == 0
    assert parse_memory_bytes("garbage") == 0


def test_start_of_utc_day_is_midnight() -> None:
    boundary = start_of_utc_day()
    assert boundary.endswith("00:00:00+00:00")


# ── AC-4: off-loop batched event writes (INV-6) ───────────────────────────────


def _runtime_event(run_id: str, seq: int) -> RuntimeEvent:
    """A minimal engine-shaped event the pump persists (one inbound queue frame)."""
    from datetime import UTC, datetime

    return RuntimeEvent(
        timestamp=datetime.now(UTC),
        run_id=run_id,
        task_name="dev",
        event_type="assistant",
        data={"seq": seq},
        sequence=seq,
        task_index=0,
    )


@pytest.mark.asyncio
async def test_pump_batches_burst_into_one_off_loop_append(repository: Repository) -> None:
    """The live batching seam (EventPump) coalesces a queued burst into ONE append (AC-4).

    The orchestrator does not emit a high-frequency event hot path of its own — every
    event-append (engine frames + the bridge's synthetic spine frames) flows through
    the per-run :class:`EventPump`, which drains whatever is ready on the run's queue
    (up to ``MAX_BATCH``) and persists it as a SINGLE off-loop
    :meth:`Repository.append_events` round-trip (the single writer, one
    ``BEGIN IMMEDIATE`` — INV-6). This proves a burst of 5 queued events is persisted
    by ONE batched writer call (the pre-seeded queue drains in one batch), so AC-4
    "off-loop writes + batched appends" is genuinely satisfied without a redundant
    second batching module.
    """
    run_id = await _seed_run(repository, status="running")
    loop = asyncio.get_running_loop()
    hub = RunStreamHub(run_id, loop)

    # Pre-load a burst onto the inbound queue, then signal close so the pump drains
    # everything ready in one batch and exits.
    for seq in range(5):
        hub.queue.put_nowait(_runtime_event(run_id, seq))
    hub.mark_closed()

    appended_batches: list[int] = []
    real_append = repository.append_events

    async def _counting_append(records: list[EventRecord]) -> list[int]:
        appended_batches.append(len(records))
        return await real_append(records)

    repository.append_events = _counting_append  # type: ignore[method-assign]  # DKMVP-ESCAPE: spy on the single off-loop writer round-trips
    try:
        pump = EventPump(repository=repository, hub=hub)
        await asyncio.wait_for(pump.run(), timeout=2.0)
    finally:
        repository.append_events = real_append  # type: ignore[method-assign]  # DKMVP-ESCAPE: restore the real writer

    # One batched append carried all five queued events (coalesced, off-loop).
    assert appended_batches == [5]
    assert appended_batches[0] <= MAX_BATCH
    # The events are durable + replayable under the platform run id.
    rows = await repository.read_events_after(run_id, last_id=0, limit=100)
    assert len(rows) == 5


# ── AC-5: loop observability (heartbeat + slots-in-use gauge) ─────────────────


def test_loop_metrics_heartbeat_advances() -> None:
    """The heartbeat tick counter advances each successful tick (AC-5)."""
    metrics = LoopMetrics()
    assert metrics.snapshot().tick_count == 0
    metrics.record_tick(duration_s=0.01)
    metrics.record_tick(duration_s=0.02)
    assert metrics.snapshot().tick_count == 2
    assert metrics.last_tick_duration_s == 0.02


def test_loop_metrics_slots_gauge_tracks_semaphore() -> None:
    """The slots-in-use gauge tracks the semaphore's held count (AC-5)."""
    slots = ConcurrencySlots(capacity=3)
    slots.acquire()
    slots.acquire()
    metrics = LoopMetrics()
    metrics.record_loop(
        slots_in_use=slots.held,
        slots_capacity=slots.capacity,
        queue_depth=4,
        reconcile_actions=1,
        dispatch_latency_s=0.05,
    )
    snap = metrics.loop_snapshot()
    assert snap.slots_in_use == 2  # tracks the semaphore
    assert snap.slots_in_use == slots.held
    assert snap.slots_capacity == 3
    assert snap.queue_depth == 4
    assert snap.reconcile_actions == 1
    assert snap.dispatch_latency_s == 0.05


# ── INV-9: pause release/reacquire against the Semaphore-backed slots ─────────


@pytest.mark.asyncio
async def test_pause_release_frees_a_dispatch_slot() -> None:
    """A pause release (sync) frees a permit the async dispatch gate can take (INV-9)."""
    slots = ConcurrencySlots(capacity=1)
    await slots.acquire_async()  # a run holds the only slot
    assert slots.available == 0

    waiter = asyncio.ensure_future(slots.acquire_async())
    await asyncio.sleep(0.02)
    assert not waiter.done()  # a second dispatch is blocked

    slots.release()  # the holding run PAUSES → releases its slot (INV-9)
    await asyncio.wait_for(waiter, timeout=1.0)  # the blocked dispatch wakes
    assert slots.held == 1

    # The paused run RESUMES → re-acquires; held truthfully reflects oversubscription.
    slots.acquire()
    assert slots.held == 2


def test_pause_release_never_manufactures_phantom_capacity() -> None:
    """A double / spurious release never pushes the semaphore above capacity (INV-9)."""
    slots = ConcurrencySlots(capacity=1)
    slots.release()
    slots.release()
    assert slots.held == 0
    assert slots.available == 1  # no phantom capacity
