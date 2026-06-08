"""Schema assertions on the Alembic-migrated DB (AC-0.3-4, AC-0.3-5).

These query ``sqlite_master`` / ``PRAGMA`` after a real ``alembic upgrade head``
to prove the nine tables, the five binding indexes, the FK ``ON DELETE CASCADE``
on the four child tables, the UUID PK + non-unique engine id + UNIQUE
idempotency key all exist *as the migration produced them*.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from app.db.schema import ALL_TABLE_NAMES, CASCADE_CHILD_TABLES


def _connect(database_url: str) -> sqlite3.Connection:
    path = database_url.removeprefix("sqlite:///")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_all_nine_tables_present(database_url: str) -> None:
    conn = _connect(database_url)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert ALL_TABLE_NAMES.issubset(names), ALL_TABLE_NAMES - names
    assert ALL_TABLE_NAMES == frozenset(
        {
            "projects",
            "issues",
            "runs",
            "run_stages",
            "events",
            "pause_decisions",
            "run_totals",
            "settings",
            "secrets",
        }
    )


def test_five_binding_indexes_present(database_url: str) -> None:
    """The five binding indexes from PRD §6.5 (named or as UNIQUE autoindex)."""
    conn = _connect(database_url)
    try:
        index_sql = {
            r["name"]: (r["sql"] or "")
            for r in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='index'")
        }
        # Named indexes.
        assert "ix_events_run_id_id" in index_sql
        assert "ix_runs_status_started_at" in index_sql
        assert "ix_runs_issue_num" in index_sql
        assert "ix_pause_decisions_status_timeout_at" in index_sql

        # UNIQUE(events.run_id, sequence) — verify the constraint exists via the
        # events table DDL (SQLite materializes it as sqlite_autoindex_events_*).
        events_sql = next(
            r["sql"]
            for r in conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='events'"
            )
        )
        assert "uq_events_run_id_sequence" in events_sql
    finally:
        conn.close()


def test_cascade_on_child_tables(database_url: str) -> None:
    """FK → runs(id) is ON DELETE CASCADE on the four child tables."""
    conn = _connect(database_url)
    try:
        for table in CASCADE_CHILD_TABLES:
            fks = list(conn.execute(f"PRAGMA foreign_key_list({table})"))
            run_fk = [f for f in fks if f["table"] == "runs"]
            assert run_fk, f"{table} missing FK → runs"
            assert run_fk[0]["on_delete"] == "CASCADE", (
                f"{table}.run_id FK not CASCADE: {run_fk[0]['on_delete']}"
            )
    finally:
        conn.close()


def test_runs_idempotency_key_unique(database_url: str) -> None:
    """``idempotency_key`` is UNIQUE (the claim-insert key, INV-5)."""
    conn = _connect(database_url)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        base = (str(uuid.uuid4()), "o/r", "dup-key")
        conn.execute("INSERT INTO runs (id, repo, idempotency_key) VALUES (?, ?, ?)", base)
        conn.commit()
        try:
            conn.execute(
                "INSERT INTO runs (id, repo, idempotency_key) VALUES (?, ?, ?)",
                (str(uuid.uuid4()), "o/r", "dup-key"),
            )
            conn.commit()
            raise AssertionError("duplicate idempotency_key was allowed")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_runs_id_is_platform_uuid_not_engine_id(database_url: str) -> None:
    """``runs.id`` holds a platform UUID; ``engine_run_id`` is separate."""
    conn = _connect(database_url)
    try:
        platform_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO runs (id, repo, engine_run_id, idempotency_key) VALUES (?, ?, ?, ?)",
            (platform_id, "o/r", "260608-1442-feat-ab12", "k1"),
        )
        conn.commit()
        row = next(conn.execute("SELECT id, engine_run_id FROM runs"))
        # PK is a valid UUID; engine id is the distinct human-readable string.
        uuid.UUID(row["id"])
        assert row["id"] != row["engine_run_id"]
        assert row["engine_run_id"] == "260608-1442-feat-ab12"
    finally:
        conn.close()


def test_engine_run_id_not_unique(database_url: str) -> None:
    """``engine_run_id`` is non-unique (collision-weak under concurrency, R-8)."""
    conn = _connect(database_url)
    try:
        for key in ("ka", "kb"):
            conn.execute(
                "INSERT INTO runs (id, repo, engine_run_id, idempotency_key) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), "o/r", "same-engine-id", key),
            )
        conn.commit()  # must not raise — engine_run_id has no UNIQUE constraint
        count = next(
            conn.execute("SELECT COUNT(*) AS c FROM runs WHERE engine_run_id='same-engine-id'")
        )["c"]
        assert count == 2
    finally:
        conn.close()


def test_migration_file_exists() -> None:
    versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    assert (versions / "0001_initial_schema.py").is_file()
