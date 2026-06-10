"""Backup verify + restore helper (§6.5, AC-14) — extends the F2 ``VACUUM INTO`` hook.

The single SQLite file is the **source of truth for spend + audit** (§6.5), so a
verified, restorable backup is a v1 ship requirement (AC-14). The F2 layer already
exposes the snapshot primitive — :meth:`app.db.repository.Repository.backup_to`
runs ``VACUUM INTO`` on the writer to produce a fully-checkpointed, defragmented
single-file copy without racing a concurrent write. This module is the thin layer
on top that makes the snapshot an **operable backup story**:

* :func:`snapshot` — take a consistent ``VACUUM INTO`` snapshot to ``dest_path``
  (delegates to the repository's writer-routed hook so it never races a write).
* :func:`verify_backup` — open the snapshot read-only and assert it is a valid,
  non-corrupt SQLite database (``PRAGMA integrity_check`` + ``PRAGMA
  foreign_key_check``) carrying the expected schema. A backup that does not pass
  this is not a backup — verification is what turns "we wrote a file" into "we can
  restore from it."
* :func:`backup_summary` — read the spend/audit-relevant row counts + the total
  spend rollup out of a DB file, so a snapshot↔restore round-trip can be asserted
  to MATCH (the AC-14 test) and an operator can sanity-check a restore.
* :func:`restore` — install a verified snapshot as the live DB file (atomic
  rename, with the prior DB moved aside), then a re-verify. This is the documented
  restore procedure's mechanical core (the human procedure lives in
  ``platform/docs/setup.md``).

The restore is **offline** by contract: the platform must not be running (no open
writer) when a DB file is swapped underneath it — a live ``Repository`` holds WAL
connections. The setup-doc procedure is "stop the stack → restore → start" and
:func:`restore` enforces only the file-level mechanics + verification, never a hot
swap under a running process.

Nothing here reaches into ``dkmv/`` or shells the CLI.
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from app.db.connection import connect
from app.db.repository import Repository
from app.db.spend_sql import COST_EXCLUDED_AGENT, total_spend_sql

#: Tables whose row counts a snapshot↔restore round-trip must preserve (the
#: spend/audit-relevant projection tables — §6.5). ``events`` + ``runs`` carry the
#: segment-sum spend inputs; ``run_totals`` the completion snapshot; ``secrets`` /
#: ``pause_decisions`` the security-relevant rows.
COUNTED_TABLES: tuple[str, ...] = (
    "runs",
    "events",
    "run_totals",
    "run_stages",
    "pause_decisions",
    "issues",
    "secrets",
    "settings",
)


@dataclass(frozen=True, slots=True)
class BackupSummary:
    """Row counts + the total spend rollup of a DB file (the round-trip checksum).

    The AC-14 contract: a snapshot's :class:`BackupSummary` must equal the source
    DB's, and a restore's must equal the snapshot's. ``total_spend_usd`` is the
    **same** Codex-excluded segment-sum rollup the live spend projection uses
    (INV-7/INV-8), so the round-trip proves the spend source of truth survives a
    backup, not just the raw bytes.
    """

    row_counts: dict[str, int]
    total_spend_usd: float

    def matches(self, other: BackupSummary, *, spend_tolerance: float = 1e-9) -> bool:
        """True iff row counts are identical and the spend rollup matches within tol."""
        return self.row_counts == other.row_counts and (
            abs(self.total_spend_usd - other.total_spend_usd) <= spend_tolerance
        )


class BackupVerificationError(RuntimeError):
    """Raised when a snapshot fails integrity / schema verification (AC-14).

    A snapshot that does not pass :func:`verify_backup` is not restorable; the
    restore path refuses to install it (fail-closed) so a corrupt backup can never
    silently replace a good DB.
    """


async def snapshot(repository: Repository, dest_path: str | Path) -> Path:
    """Take a consistent ``VACUUM INTO`` snapshot of the live DB to ``dest_path``.

    Delegates to the F2 :meth:`Repository.backup_to` hook so the snapshot runs on
    the single writer task (never racing a concurrent write transaction — §6.5).
    Returns the snapshot path. The caller typically follows with
    :func:`verify_backup` to confirm the file is restorable before trusting it.
    """
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    await repository.backup_to(str(dest))
    return dest


async def verify_backup(db_path: str | Path, *, require_tables: tuple[str, ...] = ()) -> None:
    """Open ``db_path`` read-only and assert it is a valid, restorable SQLite DB.

    Runs SQLite's own corruption checks — ``PRAGMA integrity_check`` (B-tree /
    page-level integrity) and ``PRAGMA foreign_key_check`` (referential integrity)
    — and confirms the expected tables exist. Raises :class:`BackupVerificationError`
    on any failure. This is what makes a backup *verified*: "we wrote a file" only
    becomes "we can restore from it" once these pass. ``require_tables`` defaults to
    :data:`COUNTED_TABLES` when empty so a real platform snapshot is checked for the
    spend/audit schema.
    """
    path = Path(db_path)
    if not path.exists():
        raise BackupVerificationError(f"backup file does not exist: {path}")
    tables_needed = require_tables or COUNTED_TABLES

    # A non-SQLite / truncated file fails as early as the connection's first PRAGMA
    # (``apply_pragmas`` in :func:`connect`) with a raw ``sqlite3.DatabaseError``
    # ("file is not a database"); translate it (and any later driver error) into
    # BackupVerificationError so the restore path's fail-closed contract holds for a
    # corrupt file, not just a clean integrity failure (AC-14).
    try:
        conn = await connect(f"sqlite:///{path}")
    except sqlite3.DatabaseError as exc:
        raise BackupVerificationError(f"{path} is not a valid SQLite database: {exc}") from exc
    try:
        integrity = list(await conn.execute_fetchall("PRAGMA integrity_check"))
        first = str(integrity[0][0]).lower() if integrity else ""
        if first != "ok":
            raise BackupVerificationError(
                f"integrity_check failed for {path}: {[tuple(r) for r in integrity]}"
            )
        fk_violations = list(await conn.execute_fetchall("PRAGMA foreign_key_check"))
        if fk_violations:
            raise BackupVerificationError(
                f"foreign_key_check found {len(fk_violations)} violation(s) in {path}"
            )
        present = {
            str(r[0])
            for r in await conn.execute_fetchall(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = [t for t in tables_needed if t not in present]
        if missing:
            raise BackupVerificationError(f"backup {path} is missing tables: {missing}")
    except sqlite3.DatabaseError as exc:
        raise BackupVerificationError(f"{path} is not a valid SQLite database: {exc}") from exc
    finally:
        await conn.close()


async def backup_summary(db_path: str | Path) -> BackupSummary:
    """Read row counts + the Codex-excluded total spend rollup from a DB file.

    The round-trip checksum the AC-14 test compares: the same numbers must come out
    of the source DB, its snapshot, and a restore of that snapshot. ``total_spend_usd``
    reuses the canonical ``last_per_task`` segment-sum CTE (per ``(run_id,
    task_index)`` last-cumulative ``cost_usd``, Codex excluded — INV-7/INV-8), so the
    rollup that round-trips is the actual spend source of truth, not a naive sum.
    """
    path = Path(db_path)
    conn = await connect(f"sqlite:///{path}")
    try:
        counts: dict[str, int] = {}
        for table in COUNTED_TABLES:
            rows = list(await conn.execute_fetchall(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608 — table names from a fixed constant tuple
            counts[table] = int(rows[0][0]) if rows else 0
        spend = await _total_spend(conn)
        return BackupSummary(row_counts=counts, total_spend_usd=spend)
    finally:
        await conn.close()


async def restore(
    backup_path: str | Path,
    live_db_path: str | Path,
    *,
    keep_prior_as: str | Path | None = None,
) -> Path:
    """Install a **verified** snapshot as the live DB file (offline restore).

    The mechanical core of the documented restore procedure (the human steps —
    "stop the stack, restore, start" — live in ``platform/docs/setup.md``). This:

    1. **Verifies** ``backup_path`` (:func:`verify_backup`) — refuses to install a
       corrupt/incomplete snapshot (fail-closed), so a bad backup never replaces a
       good DB.
    2. Moves the current live DB aside to ``keep_prior_as`` (default
       ``<live>.pre-restore``) so the restore is reversible, then copies the
       verified snapshot into place (and clears any stale ``-wal`` / ``-shm``
       sidecars so the restored file is the sole truth).
    3. **Re-verifies** the installed file.

    The platform MUST NOT be running (no open :class:`Repository` writer) during a
    restore — a live process holds WAL connections to the file being swapped. This
    helper enforces only the file mechanics + verification, never a hot swap.
    """
    backup = Path(backup_path)
    live = Path(live_db_path)

    # 1. Verify the snapshot before we touch the live DB (fail-closed).
    await verify_backup(backup)

    # 2. Move the current live DB aside (reversible restore), clear WAL/SHM sidecars.
    live.parent.mkdir(parents=True, exist_ok=True)
    if live.exists():
        prior = (
            Path(keep_prior_as)
            if keep_prior_as is not None
            else live.with_suffix(live.suffix + ".pre-restore")
        )
        if prior.exists():
            prior.unlink()
        shutil.move(str(live), str(prior))
    for sidecar in (live.with_name(live.name + "-wal"), live.with_name(live.name + "-shm")):
        if sidecar.exists():
            sidecar.unlink()

    # 3. Install the verified snapshot and re-verify.
    shutil.copy2(str(backup), str(live))
    await verify_backup(live)
    return live


async def _total_spend(conn: aiosqlite.Connection) -> float:
    """Codex-excluded segment-sum total spend over a raw connection (round-trip checksum).

    The backup checksum intentionally segment-sums the **events** of every run (the
    full-scan total — :func:`app.db.spend_sql.total_spend_sql`), NOT the run_totals
    fast-path: a snapshot/restore must verify the actual event-level spend source of
    truth round-trips byte-for-byte, independent of whether a snapshot exists.
    Composes the ONE canonical ``last_per_task`` CTE (Codex excluded — INV-7/INV-8)
    so the checksum can never drift from the live spend definition. Runs against a
    plain read connection so it works over a snapshot/restore file without standing
    up a full :class:`Repository`.
    """
    rows = list(await conn.execute_fetchall(total_spend_sql(), (COST_EXCLUDED_AGENT,)))
    return float(rows[0][0] or 0.0) if rows else 0.0
