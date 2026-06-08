"""Single-writer task semantics (INV-6): serialization, rollback, lifecycle."""

from __future__ import annotations

import asyncio

import aiosqlite
import pytest
from app.db.writer import Writer


@pytest.mark.asyncio
async def test_submit_before_start_raises(database_url: str) -> None:
    writer = Writer(database_url)
    with pytest.raises(RuntimeError):
        await writer.submit(lambda conn: _noop(conn))


async def _noop(conn: aiosqlite.Connection) -> None:
    return None


@pytest.mark.asyncio
async def test_double_start_is_idempotent(database_url: str) -> None:
    writer = Writer(database_url)
    await writer.start()
    await writer.start()  # no-op, no second task
    try:
        result = await writer.submit(_one)
        assert result == 1
    finally:
        await writer.stop()
        await writer.stop()  # no-op


async def _one(conn: aiosqlite.Connection) -> int:
    return 1


@pytest.mark.asyncio
async def test_failing_job_rolls_back_and_propagates(database_url: str) -> None:
    """A raising job rolls back its transaction and surfaces the exception."""
    writer = Writer(database_url)
    await writer.start()
    try:

        async def _boom(conn: aiosqlite.Connection) -> None:
            await conn.execute("INSERT INTO settings (key, value) VALUES ('k', 'v')")
            raise ValueError("explode")

        with pytest.raises(ValueError, match="explode"):
            await writer.submit(_boom)

        # The rolled-back insert did not persist, and the writer still works.
        async def _read(conn: aiosqlite.Connection) -> int:
            rows = list(await conn.execute_fetchall("SELECT COUNT(*) AS c FROM settings"))
            return int(rows[0]["c"])

        assert await writer.submit(_read) == 0
    finally:
        await writer.stop()


@pytest.mark.asyncio
async def test_writes_are_serialized_in_submission_order(database_url: str) -> None:
    """Jobs run one-at-a-time in order — no interleaving inside a transaction."""
    writer = Writer(database_url)
    await writer.start()
    order: list[int] = []
    try:

        def make(n: int):
            async def _job(conn: aiosqlite.Connection) -> None:
                # Yield control mid-job; serialization must still hold order.
                await asyncio.sleep(0)
                order.append(n)

            return _job

        await asyncio.gather(*(writer.submit(make(n)) for n in range(10)))
        assert order == list(range(10))
    finally:
        await writer.stop()
