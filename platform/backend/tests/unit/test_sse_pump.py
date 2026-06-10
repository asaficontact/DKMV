"""Slice 2.3 — the per-run event pump: persist + project + fan out (§8.3, AC-8).

Covers :class:`app.sse.pump.EventPump` over a real migrated SQLite DB:

* the pump **batch-appends** events to the append-only ``events`` table THROUGH the
  repository (single-writer + redactor), assigning the monotonic ``events.id``
  cursor;
* it **projects ``run_stages``** from lifecycle frames (a ``task_started`` →
  ``running``, ``task_completed`` → ``done`` with its final cost — INV-7);
* it **fans out** one :class:`StreamFrame` per persisted event to subscribers, the
  frame body being the outer ``RuntimeEvent`` (§6.4) keyed by ``events.id``;
* **INV-4 no-regression:** a secret in an event payload is **redacted** before it
  reaches the ``events`` table (the redactor runs in the repository write path).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app.db import Repository
from app.secrets import Redactor
from app.sse.observer_bridge import RunStreamHub, Subscriber
from app.sse.pump import EventPump, event_to_body, event_to_record
from dkmv.runtime import RuntimeEvent

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _migrate(db_path: Path) -> str:
    url = f"sqlite:///{db_path}"
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> AsyncIterator[Repository]:
    url = _migrate(tmp_path / "pump.db")
    repo = Repository(url, redactor=Redactor())
    await repo.start()
    try:
        yield repo
    finally:
        await repo.close()


async def _seed_run(repo: Repository) -> str:
    run_id, _ = await repo.claim_run(
        idempotency_key="pump-k1",
        repo="o/r",
        issue_num=1,
        workflow_id="plan",
        agent="claude",
        branch="dkmv/issue-1",
        feature_name="issue-1",
    )
    return run_id


def _event(
    run_id: str,
    *,
    seq: int,
    event_type: str,
    task_index: int = -1,
    task_name: str = "",
    cost_usd: float = 0.0,
    turns: int = 0,
    data: dict | None = None,
) -> RuntimeEvent:
    return RuntimeEvent(
        sequence=seq,
        timestamp=datetime.now(UTC),
        run_id=run_id,
        task_name=task_name,
        task_index=task_index,
        event_type=event_type,
        cost_usd=cost_usd,
        turns=turns,
        data=data or {},
    )


@pytest.mark.asyncio
async def test_pump_persists_projects_and_fans_out(repository: Repository) -> None:
    """The pump appends events, updates run_stages, and fans out frames (§8.3)."""
    loop = asyncio.get_running_loop()
    run_id = await _seed_run(repository)
    hub = RunStreamHub(run_id, loop)
    sub = Subscriber()
    hub.add_subscriber(sub)
    pump = EventPump(repository=repository, hub=hub)
    pump_task = asyncio.ensure_future(pump.run())

    # Feed a stage lifecycle via the inbound queue (as the observer would).
    hub.queue.put_nowait(
        _event(run_id, seq=1, event_type="task_started", task_index=0, task_name="analyze")
    )
    hub.queue.put_nowait(
        _event(
            run_id,
            seq=2,
            event_type="task_completed",
            task_index=0,
            task_name="analyze",
            cost_usd=3.5,
            turns=4,
        )
    )
    # Let the pump drain + persist + signal close.
    await asyncio.sleep(0.2)
    hub.mark_closed()
    await asyncio.wait_for(pump_task, timeout=2.0)

    # Persisted to the append-only events table with monotonic ids.
    backlog = await repository.read_events_after(run_id, 0)
    assert [r["event_type"] for r in backlog] == ["task_started", "task_completed"]
    assert backlog[0]["id"] < backlog[1]["id"]

    # run_stages projected: stage 0 is done with its final cost (INV-7).
    stages = await repository.read_run_stages(run_id)
    assert len(stages) == 1
    assert stages[0]["status"] == "done"
    assert stages[0]["cost_usd"] == pytest.approx(3.5)

    # Fanned out: the subscriber saw both frames keyed by events.id.
    frames = sub.drain_nowait()
    assert [f.event_type for f in frames] == ["task_started", "task_completed"]
    assert frames[1].event_id == backlog[1]["id"]
    # The frame body is the OUTER RuntimeEvent (§6.4).
    assert frames[1].body["cost_usd"] == pytest.approx(3.5)
    assert frames[1].body["task_index"] == 0


@pytest.mark.asyncio
async def test_pump_redacts_secret_before_persist(repository: Repository) -> None:
    """INV-4 no-regression: a secret in a payload is redacted before events (§8.6)."""
    loop = asyncio.get_running_loop()
    run_id = await _seed_run(repository)
    hub = RunStreamHub(run_id, loop)
    pump = EventPump(repository=repository, hub=hub)
    pump_task = asyncio.ensure_future(pump.run())

    leaked = "sk-ant-api03-SECRETSECRETSECRETSECRET"
    hub.queue.put_nowait(
        _event(
            run_id,
            seq=1,
            event_type="assistant",
            data={"content_text": f"using key {leaked}"},
        )
    )
    await asyncio.sleep(0.15)
    hub.mark_closed()
    await asyncio.wait_for(pump_task, timeout=2.0)

    backlog = await repository.read_events_after(run_id, 0)
    assert len(backlog) == 1
    # The raw secret must NOT appear in the persisted payload (redacted).
    assert leaked not in backlog[0]["payload_json"]


@pytest.mark.asyncio
async def test_pump_persists_engine_run_id_early(repository: Repository) -> None:
    """G3: the engine id is written to the DB on the FIRST stamped frame, NOT at close.

    Closing the orphan-recovery window — the reaper's only container handle is
    ``runs.engine_run_id``. Here the pump processes the first engine-stamped event
    (its ``run_id`` is the engine ``YYMMDD-HHMM`` id, different from the platform
    UUID) and we assert the run row carries ``engine_run_id`` **before** the run is
    ever closed/completed.
    """
    loop = asyncio.get_running_loop()
    run_id = await _seed_run(repository)
    hub = RunStreamHub(run_id, loop)
    pump = EventPump(repository=repository, hub=hub)
    pump_task = asyncio.ensure_future(pump.run())

    engine_id = "260610-1230-analyze"
    # An engine-stamped frame: its run_id is the engine id (≠ the platform UUID).
    hub.queue.put_nowait(
        _event(engine_id, seq=1, event_type="task_started", task_index=0, task_name="analyze")
    )
    # Drain the frame WITHOUT closing the run (mid-run, no completion yet).
    for _ in range(50):
        row = await repository.get_run(run_id)
        assert row is not None
        if row["engine_run_id"]:
            break
        await asyncio.sleep(0.01)

    # The engine id was persisted to the run row mid-run (before any close).
    assert not hub.closed.is_set()
    row = await repository.get_run(run_id)
    assert row is not None
    assert row["engine_run_id"] == engine_id

    # The early write fires exactly once: more frames don't re-issue it (idempotent).
    hub.queue.put_nowait(_event(engine_id, seq=2, event_type="assistant", task_index=0))
    await asyncio.sleep(0.05)
    hub.mark_closed()
    await asyncio.wait_for(pump_task, timeout=2.0)
    row = await repository.get_run(run_id)
    assert row is not None
    assert row["engine_run_id"] == engine_id


def test_event_to_record_normalizes_task_index() -> None:
    """The engine's -1 'no task' sentinel maps to NULL task_index (INV-7 prep)."""
    rec = event_to_record(_event("r1", seq=1, event_type="stream", task_index=-1))
    assert rec.task_index is None
    rec2 = event_to_record(
        _event("r1", seq=2, event_type="task_completed", task_index=0, cost_usd=2.0)
    )
    assert rec2.task_index == 0
    assert rec2.cost_usd == pytest.approx(2.0)


def test_event_to_body_carries_outer_shape() -> None:
    """The SSE body carries the outer RuntimeEvent §6.4 fields, data = inner dict."""
    body = event_to_body(
        _event(
            "r1",
            seq=7,
            event_type="result",
            task_index=1,
            cost_usd=1.25,
            turns=3,
            data={"num_turns": 3},
        )
    )
    assert body["sequence"] == 7
    assert body["event_type"] == "result"
    assert body["cost_usd"] == pytest.approx(1.25)
    assert body["turns"] == 3
    assert body["data"] == {"num_turns": 3}
    assert isinstance(body["timestamp"], str)  # ISO-8601
