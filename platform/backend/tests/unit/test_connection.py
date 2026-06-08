"""Connection management + binding PRAGMA tests (AC-0.3-1; INV-6)."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.db.connection import BUSY_TIMEOUT_MS, connect, resolve_db_path


def test_busy_timeout_meets_floor() -> None:
    assert BUSY_TIMEOUT_MS >= 5000


def test_resolve_db_path_sqlite_url(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "db.sqlite"
    resolved = resolve_db_path(f"sqlite:///{target}")
    assert resolved == str(target)
    # parent dir is created so first-run upgrade/writer-start never trips.
    assert target.parent.is_dir()


def test_resolve_db_path_async_url(tmp_path: Path) -> None:
    target = tmp_path / "db.sqlite"
    assert resolve_db_path(f"sqlite+aiosqlite:///{target}") == str(target)


def test_resolve_db_path_memory() -> None:
    assert resolve_db_path("sqlite:///:memory:") == ":memory:"
    assert resolve_db_path(":memory:") == ":memory:"


@pytest.mark.asyncio
async def test_pragmas_applied_per_connection(database_url: str) -> None:
    """Every connection sets WAL / NORMAL / busy_timeout>=5000 / foreign_keys=ON."""
    conn = await connect(database_url)
    try:
        journal = (await (await conn.execute("PRAGMA journal_mode")).fetchone())[0]
        sync = (await (await conn.execute("PRAGMA synchronous")).fetchone())[0]
        busy = (await (await conn.execute("PRAGMA busy_timeout")).fetchone())[0]
        fk = (await (await conn.execute("PRAGMA foreign_keys")).fetchone())[0]
    finally:
        await conn.close()

    assert str(journal).lower() == "wal"
    # synchronous=NORMAL is integer 1.
    assert int(sync) == 1
    assert int(busy) >= 5000
    # foreign_keys=ON is integer 1.
    assert int(fk) == 1


@pytest.mark.asyncio
async def test_foreign_keys_enforced(database_url: str) -> None:
    """With foreign_keys=ON, an orphan child insert is rejected."""
    import aiosqlite

    conn = await connect(database_url)
    try:
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute("INSERT INTO run_totals (run_id, cost_usd) VALUES ('nope', 1.0)")
            await conn.commit()
    finally:
        await conn.close()
