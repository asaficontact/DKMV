"""Slice 5.4 — backup verify + restore round-trip (AC-14, §6.5).

The single SQLite file is the **source of truth for spend + audit** (§6.5), so the
``VACUUM INTO`` snapshot must produce a *restorable* DB — not just a file on disk.
These tests exercise the :mod:`app.db.backup` helper end-to-end against a REAL
migrated SQLite DB (no Docker, no engine):

* **AC-14 (binding).** snapshot → verify → restore round-trips: the restored DB's
  row counts AND the Codex-excluded segment-sum **spend rollup** MATCH the source
  (so the spend source of truth genuinely survives a backup).
* A snapshot passes integrity + schema verification; a corrupt/partial file is
  refused (fail-closed) so a bad backup can never replace a good DB.
* The restore moves the prior DB aside (reversible) and re-verifies the installed
  file.

These prove the documented restore procedure (``platform/docs/setup.md``) is real.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from app.db import EventRecord, Repository
from app.db.backup import (
    BackupVerificationError,
    backup_summary,
    restore,
    snapshot,
    verify_backup,
)

from tests.conftest import _migrate  # reuse the alembic-migrate helper

pytestmark = pytest.mark.asyncio

REPO = "octo/widgets"


@pytest_asyncio.fixture
async def seeded(tmp_path: Path) -> tuple[Repository, str]:
    """A started Repository over a migrated DB seeded with spend-bearing rows.

    Seeds a Claude run (priced) + a Codex run (unpriced, excluded from spend) with
    per-task cumulative cost events, so the snapshot↔restore round-trip exercises
    BOTH the row-count preservation and the Codex-excluded segment-sum rollup.
    """
    url = _migrate(tmp_path / "source.db")
    repository = Repository(url)
    await repository.start()

    # Claude run: two tasks, each with a climbing cumulative cost line (segment-sum
    # dedup picks the last per task_index → 2.0 + 5.0 = 7.0).
    claude_id, _ = await repository.claim_run(
        idempotency_key=str(uuid.uuid4()), repo=REPO, issue_num=1, agent="claude"
    )
    await repository.update_run_fields(claude_id, status="completed")

    def _ev(rid: str, seq: int, etype: str, ti: int, cost: float, agent: str) -> EventRecord:
        return EventRecord(
            run_id=rid,
            sequence=seq,
            event_type=etype,
            payload={"c": cost},
            task_index=ti,
            cost_usd=cost,
            agent=agent,
        )

    await repository.append_events(
        [
            _ev(claude_id, 0, "stream", 0, 1.0, "claude"),
            _ev(claude_id, 1, "task_completed", 0, 2.0, "claude"),
            _ev(claude_id, 2, "task_completed", 1, 5.0, "claude"),
        ]
    )
    # Codex run: a real (engine-side) cost event that MUST be excluded from spend.
    codex_id, _ = await repository.claim_run(
        idempotency_key=str(uuid.uuid4()), repo=REPO, issue_num=2, agent="codex"
    )
    await repository.update_run_fields(codex_id, status="completed")
    await repository.append_events([_ev(codex_id, 0, "task_completed", 0, 99.0, "codex")])
    return repository, url


async def test_snapshot_verifies_as_restorable(
    seeded: tuple[Repository, str], tmp_path: Path
) -> None:
    """A VACUUM INTO snapshot passes integrity + schema verification (AC-14)."""
    repository, _url = seeded
    try:
        backup = await snapshot(repository, tmp_path / "snap.db")
        assert backup.exists()
        # Does not raise → integrity_check ok, FK check clean, schema present.
        await verify_backup(backup)
    finally:
        await repository.close()


async def test_snapshot_preserves_row_counts_and_spend_rollup(
    seeded: tuple[Repository, str], tmp_path: Path
) -> None:
    """AC-14 (binding): snapshot row counts + Codex-excluded spend rollup MATCH source."""
    repository, source_url = seeded
    try:
        source_path = source_url.removeprefix("sqlite:///")
        # The live spend rollup the platform projects (Codex-excluded): 7.0, not 106.0.
        live_total = await repository.total_spend()
        assert live_total == pytest.approx(7.0)

        backup = await snapshot(repository, tmp_path / "snap.db")
        source_summary = await backup_summary(source_path)
        snap_summary = await backup_summary(backup)

        # The Codex run's $99 cost is excluded from the rollup on BOTH sides.
        assert source_summary.total_spend_usd == pytest.approx(7.0)
        assert snap_summary.matches(source_summary)
        # The spend-bearing tables round-tripped (2 runs, 4 events).
        assert snap_summary.row_counts["runs"] == 2
        assert snap_summary.row_counts["events"] == 4
    finally:
        await repository.close()


async def test_restore_round_trips_and_matches(
    seeded: tuple[Repository, str], tmp_path: Path
) -> None:
    """snapshot → restore → row counts + spend rollup MATCH the source (AC-14)."""
    repository, _url = seeded
    try:
        backup = await snapshot(repository, tmp_path / "snap.db")
        snap_summary = await backup_summary(backup)
    finally:
        # The platform must be OFFLINE during a restore (no open writer holding WAL
        # connections to the file being swapped) — close before restoring.
        await repository.close()

    # Restore into a FRESH live location (the "stop stack → restore → start" flow).
    live = tmp_path / "restored.db"
    installed = await restore(backup, live)
    assert installed == live
    restored_summary = await backup_summary(live)

    # The restored DB's row counts AND the spend rollup match the snapshot exactly.
    assert restored_summary.matches(snap_summary)
    assert restored_summary.total_spend_usd == pytest.approx(7.0)

    # A re-started Repository over the restored file projects the same spend.
    restored_repo = Repository(f"sqlite:///{live}")
    await restored_repo.start()
    try:
        assert await restored_repo.total_spend() == pytest.approx(7.0)
    finally:
        await restored_repo.close()


async def test_restore_keeps_prior_db_reversible(
    seeded: tuple[Repository, str], tmp_path: Path
) -> None:
    """Restore moves the prior live DB aside so the operation is reversible."""
    repository, _url = seeded
    try:
        backup = await snapshot(repository, tmp_path / "snap.db")
    finally:
        await repository.close()

    live = tmp_path / "live.db"
    live.write_bytes(b"old-bogus-db-content")  # a pre-existing live file
    await restore(backup, live)
    prior = live.with_suffix(live.suffix + ".pre-restore")
    assert prior.exists()  # the prior DB was preserved, not destroyed
    assert prior.read_bytes() == b"old-bogus-db-content"


async def test_verify_refuses_corrupt_backup(tmp_path: Path) -> None:
    """A non-SQLite / corrupt file is refused by verification (fail-closed)."""
    bogus = tmp_path / "corrupt.db"
    bogus.write_bytes(b"this is not a sqlite database header at all")
    with pytest.raises(BackupVerificationError):
        await verify_backup(bogus)


async def test_verify_refuses_missing_file(tmp_path: Path) -> None:
    """A missing backup path is refused (fail-closed)."""
    with pytest.raises(BackupVerificationError):
        await verify_backup(tmp_path / "does-not-exist.db")


async def test_restore_refuses_to_install_corrupt_snapshot(tmp_path: Path) -> None:
    """Restore verifies BEFORE swapping → a corrupt snapshot never replaces the live DB."""
    bogus = tmp_path / "corrupt.db"
    bogus.write_bytes(b"not a db")
    live = tmp_path / "live.db"
    live.write_bytes(b"good-db-content")
    with pytest.raises(BackupVerificationError):
        await restore(bogus, live)
    # The good live DB is untouched (restore failed-closed before the swap).
    assert live.read_bytes() == b"good-db-content"
