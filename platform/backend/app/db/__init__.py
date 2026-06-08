"""Persistence layer (SQLite WAL + single serialized writer) — PRD §6.5.

All database access in the backend goes through :class:`Repository`. Writes are
funneled to a single serialized writer task using ``BEGIN IMMEDIATE`` (INV-6);
reads open their own connections under WAL. The schema (nine tables + binding
indexes + FK ``ON DELETE CASCADE``) is defined once in :mod:`app.db.schema` and
shared with Alembic via ``target_metadata``.

This package is self-contained: it does not import or wire anything into
``app.main`` / ``app.api`` / ``app.runtime`` — DB lifecycle wiring is a later
slice's job. Consumers construct a :class:`Repository` and ``await`` its
``start()`` / ``close()``.
"""

from __future__ import annotations

from app.db.connection import (
    BUSY_TIMEOUT_MS,
    apply_pragmas,
    connect,
    resolve_db_path,
)
from app.db.repository import (
    COST_EXCLUDED_AGENT,
    EventRecord,
    Repository,
    RunTotals,
)
from app.db.schema import (
    ALL_TABLE_NAMES,
    CASCADE_CHILD_TABLES,
    metadata,
)
from app.db.writer import Writer

__all__ = [
    "ALL_TABLE_NAMES",
    "BUSY_TIMEOUT_MS",
    "CASCADE_CHILD_TABLES",
    "COST_EXCLUDED_AGENT",
    "EventRecord",
    "Repository",
    "RunTotals",
    "Writer",
    "apply_pragmas",
    "connect",
    "metadata",
    "resolve_db_path",
]
