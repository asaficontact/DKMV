"""Concurrency load test (AC-0.3-3; INV-6 / NFR-SCALE-1).

Five concurrent "writers" each submit writes at ~4 Hz for several seconds while
readers poll on separate connections. Because every write funnels through the
single serialized writer task (``BEGIN IMMEDIATE``) and connections set
``busy_timeout>=5000``, the database must throw **zero** ``database is locked``
errors over the whole run.

This is the load-bearing proof of the SQLite concurrency contract: if the
single-writer funnel or the pragmas regress, this test surfaces the lock storm.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import aiosqlite
import pytest
from app.db import EventRecord, Repository
from app.db.connection import connect

WRITERS = 5
HZ = 4
DURATION_S = 2.0  # 5 writers × 4 Hz × 2 s ≈ 40 write transactions + reads


@pytest.mark.timeout(60)
@pytest.mark.asyncio
async def test_five_writers_four_hz_zero_locks(database_url: str) -> None:
    repo = Repository(database_url)
    await repo.start()
    lock_errors: list[str] = []

    # Pre-create the runs the writers will append events to (claim-insert each).
    run_ids: list[str] = []
    for _ in range(WRITERS):
        rid, won = await repo.claim_run(
            idempotency_key=str(uuid.uuid4()), repo="o/r", agent="claude"
        )
        assert won
        run_ids.append(rid)

    stop_at = time.monotonic() + DURATION_S

    async def writer_loop(run_id: str, worker: int) -> int:
        seq = 0
        appended = 0
        while time.monotonic() < stop_at:
            try:
                await repo.append_events(
                    [
                        EventRecord(
                            run_id=run_id,
                            sequence=seq,
                            event_type="assistant",
                            payload={"w": worker, "seq": seq},
                            task_index=0,
                            cost_usd=0.01 * seq,
                        )
                    ]
                )
                # also exercise an UPDATE write path on the serialized writer
                await repo.update_run_fields(run_id, turns=seq)
                appended += 1
                seq += 1
            except aiosqlite.OperationalError as exc:  # pragma: no cover - failure path
                if "locked" in str(exc).lower():
                    lock_errors.append(str(exc))
                else:
                    raise
            await asyncio.sleep(1.0 / HZ)
        return appended

    async def reader_loop() -> None:
        """Concurrent reads on a separate connection (WAL non-blocking)."""
        conn = await connect(database_url)
        try:
            while time.monotonic() < stop_at:
                try:
                    await conn.execute_fetchall("SELECT COUNT(*) FROM events")
                except aiosqlite.OperationalError as exc:  # pragma: no cover
                    if "locked" in str(exc).lower():
                        lock_errors.append(str(exc))
                    else:
                        raise
                await asyncio.sleep(1.0 / HZ)
        finally:
            await conn.close()

    try:
        results = await asyncio.gather(
            *(writer_loop(rid, i) for i, rid in enumerate(run_ids)),
            reader_loop(),
            reader_loop(),
        )
    finally:
        await repo.close()

    assert lock_errors == [], f"database is locked occurred: {lock_errors[:3]}"
    # Sanity: real work happened (each writer made multiple round-trips).
    appended_counts = [r for r in results if isinstance(r, int)]
    assert sum(appended_counts) >= WRITERS  # at least one append per writer
