"""SQLite connection management with the binding concurrency contract (INV-6).

Every connection — writer or reader — is opened through :func:`connect`, which
applies the four binding PRAGMAs from PRD §6.5:

* ``journal_mode=WAL``      — readers don't block the single writer.
* ``synchronous=NORMAL``    — safe under WAL, far faster than FULL.
* ``busy_timeout>=5000``    — wait up to 5 s for the write lock instead of
  failing immediately with ``database is locked``.
* ``foreign_keys=ON``       — SQLite does not enforce FKs unless asked, per
  connection (the ``ON DELETE CASCADE`` in the schema is inert otherwise).

The pragmas are applied per *connection* (not once at migration time) because
SQLite scopes ``foreign_keys`` and ``busy_timeout`` to the connection. WAL mode
is database-global and sticky once set, but we set it on every connection so a
fresh DB file is configured by whoever opens it first.

This module does **not** decide who writes — that is the single serialized
writer task in :mod:`app.db.writer`. It only knows how to open a correctly
configured connection and how to translate the ``DATABASE_URL`` setting into a
filesystem path.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite

#: Minimum busy_timeout in milliseconds (INV-6 / PRD §6.5: ``busy_timeout>=5000``).
BUSY_TIMEOUT_MS = 5000

#: The four binding pragmas, applied to every connection in order.
_PRAGMAS: tuple[str, ...] = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}",
    "PRAGMA foreign_keys=ON",
)


def resolve_db_path(database_url: str) -> str:
    """Translate a ``DATABASE_URL`` into an aiosqlite path string.

    Accepts the SQLAlchemy-style ``sqlite:///relative/path.db`` and
    ``sqlite:////absolute/path.db`` URLs used in ``Settings.DATABASE_URL`` as
    well as the async ``sqlite+aiosqlite://`` variant and a bare path. The
    special in-memory form ``:memory:`` is passed through unchanged.

    The parent directory is created if it does not exist so a first-run
    ``alembic upgrade head`` / writer start never trips over a missing ``data/``
    folder.
    """
    raw = database_url
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break

    if raw in (":memory:", "", "/:memory:"):
        return ":memory:"

    path = Path(raw)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


async def apply_pragmas(conn: aiosqlite.Connection) -> None:
    """Apply the four binding PRAGMAs (INV-6) to an open connection."""
    for pragma in _PRAGMAS:
        await conn.execute(pragma)
    await conn.commit()


async def connect(database_url: str) -> aiosqlite.Connection:
    """Open a new aiosqlite connection with the binding pragmas applied.

    ``isolation_level=None`` puts the driver in *autocommit* mode so the
    repository/writer control transaction boundaries explicitly with
    ``BEGIN IMMEDIATE`` … ``COMMIT`` (required for INV-6's short, serialized
    write transactions; the default deferred BEGIN would not take the write lock
    until the first write statement, defeating the immediate-lock contract).
    """
    path = resolve_db_path(database_url)
    conn = await aiosqlite.connect(path, isolation_level=None)
    conn.row_factory = aiosqlite.Row
    await apply_pragmas(conn)
    return conn
