"""Shared pytest fixtures for the persistence slice (0.3).

The DB fixtures build a real, migrated SQLite file via Alembic ``upgrade head``
so tests exercise the *migration-produced* schema (AC-0.3-4), not an ad-hoc
``create_all``. Each test gets an isolated temp DB file and a started
:class:`Repository` whose single writer task is torn down afterward.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app.db import Repository

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _migrate(db_path: Path) -> str:
    """Run ``alembic upgrade head`` against ``db_path``; return its DATABASE_URL."""
    url = f"sqlite:///{db_path}"
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


@pytest.fixture
def database_url(tmp_path: Path) -> Iterator[str]:
    """An isolated, migrated SQLite DB file; yields its DATABASE_URL."""
    db_path = tmp_path / "test.db"
    yield _migrate(db_path)


@pytest_asyncio.fixture
async def repo(database_url: str) -> AsyncIterator[Repository]:
    """A started :class:`Repository` over a migrated temp DB."""
    repository = Repository(database_url)
    await repository.start()
    try:
        yield repository
    finally:
        await repository.close()
