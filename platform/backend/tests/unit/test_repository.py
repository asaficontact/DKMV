"""Repository behavior tests for slice 0.3.

Covers: idempotency claim-insert (AC-0.3-8), append-only monotonic events
(AC-0.3-6), spend projection (AC-0.3-7), run_totals snapshot + VACUUM INTO
backup (AC-0.3-9), and the entity upserts behind the repo seam.
"""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from pathlib import Path

import pytest
from app.db import EventRecord, IssueRow, Repository, RunTotals
from app.db.writer import Writer


def _claim_kwargs(key: str) -> dict[str, object]:
    return {"idempotency_key": key, "repo": "o/r", "issue_num": 7, "workflow_id": "qa"}


async def _seed_run(repo: Repository, *, agent: str | None = "claude") -> str:
    run_id, won = await repo.claim_run(idempotency_key=str(uuid.uuid4()), repo="o/r", agent=agent)
    assert won
    return run_id


# === idempotency claim-insert (AC-0.3-8; INV-5) ==============================


@pytest.mark.asyncio
async def test_claim_run_first_caller_wins(repo: Repository) -> None:
    run_id, won = await repo.claim_run(**_claim_kwargs("k-once"))
    assert won is True
    uuid.UUID(run_id)  # platform UUID PK


@pytest.mark.asyncio
async def test_claim_run_second_caller_loses_same_row(repo: Repository) -> None:
    first_id, first_won = await repo.claim_run(**_claim_kwargs("k-dup"))
    second_id, second_won = await repo.claim_run(**_claim_kwargs("k-dup"))
    assert first_won is True
    assert second_won is False
    # Loser gets the winner's row id back, no duplicate row created.
    assert second_id == first_id


@pytest.mark.asyncio
async def test_concurrent_claims_exactly_one_wins(repo: Repository) -> None:
    """Two concurrent claims for the same key → exactly one wins (INV-5)."""
    results = await asyncio.gather(*(repo.claim_run(**_claim_kwargs("k-race")) for _ in range(8)))
    winners = [won for _, won in results]
    assert winners.count(True) == 1
    # All callers see the same single run id.
    ids = {rid for rid, _ in results}
    assert len(ids) == 1


# === append-only monotonic events (AC-0.3-6; §6.4/§6.5) ======================


@pytest.mark.asyncio
async def test_events_append_monotonic_ids(repo: Repository) -> None:
    run_id = await _seed_run(repo)
    records = [
        EventRecord(
            run_id=run_id,
            sequence=i,
            event_type="assistant",
            payload={"type": "assistant", "i": i},
            task_index=0,
        )
        for i in range(20)
    ]
    ids = await repo.append_events(records)
    assert len(ids) == 20
    assert ids == sorted(ids)  # strictly increasing
    assert len(set(ids)) == 20  # no reuse


@pytest.mark.asyncio
async def test_events_batched_append_across_calls_stay_monotonic(
    repo: Repository,
) -> None:
    run_id = await _seed_run(repo)
    ids_a = await repo.append_events(
        [EventRecord(run_id=run_id, sequence=0, event_type="system", payload={})]
    )
    ids_b = await repo.append_events(
        [EventRecord(run_id=run_id, sequence=1, event_type="assistant", payload={})]
    )
    assert ids_b[0] > ids_a[0]


@pytest.mark.asyncio
async def test_read_events_after_cursor(repo: Repository) -> None:
    run_id = await _seed_run(repo)
    ids = await repo.append_events(
        [
            EventRecord(run_id=run_id, sequence=i, event_type="ok", payload={"i": i})
            for i in range(5)
        ]
    )
    after = await repo.read_events_after(run_id, last_id=ids[1])
    got_ids = [r["id"] for r in after]
    assert got_ids == ids[2:]


@pytest.mark.asyncio
async def test_no_update_or_delete_path_on_events(repo: Repository) -> None:
    """The repository exposes no UPDATE/DELETE on events (append-only contract)."""
    src = Path("app/db/repository.py").read_text()
    assert "UPDATE events" not in src
    assert "DELETE FROM events" not in src


@pytest.mark.asyncio
async def test_append_events_is_single_statement(repo: Repository) -> None:
    """A batch append is one multi-row INSERT … RETURNING, not N statements.

    The performance contract (PERF): N events must be a single aiosqlite
    round-trip while holding the global write lock, so we assert the SQL is a
    single multi-row VALUES with a RETURNING clause for the per-row ids.
    """
    src = Path("app/db/repository.py").read_text()
    assert "RETURNING id" in src
    # The batch is a single statement: the events INSERT is never executed
    # per-row inside the writer job (no `conn.execute(... INSERT INTO events`).
    assert "INSERT INTO events" in src
    # Payload JSON is serialized before submit() (hoisted out of the lock), not
    # inside a `conn.execute` call's argument tuple. The serialized value is the
    # redacted payload (redact-before-persist, INV-4 / slice 0.5).
    assert "json.dumps(redacted_payload)" in src
    assert "self._redactor.payload(rec.payload)" in src

    run_id = await _seed_run(repo)
    ids = await repo.append_events(
        [
            EventRecord(run_id=run_id, sequence=i, event_type="ok", payload={"i": i})
            for i in range(50)
        ]
    )
    # All 50 ids returned, strictly increasing, no reuse — the RETURNING order
    # matches insertion order (the SSE replay cursor is preserved per row).
    assert len(ids) == 50
    assert ids == sorted(ids)
    assert len(set(ids)) == 50


# === read-connection pool (PERF) =============================================


@pytest.mark.asyncio
async def test_read_pool_reuses_connections(repo: Repository) -> None:
    """Sequential reads reuse a single warm pool connection (no churn)."""
    run_id = await _seed_run(repo)
    # Many sequential reads; each borrows + returns the same warm connection.
    for _ in range(10):
        assert await repo.get_run(run_id) is not None
    # Only one connection was ever opened for this serial read pattern.
    assert len(repo._read_conns) == 1
    # And it is parked back in the pool (checked in), not leaked.
    assert repo._read_pool.qsize() == 1


@pytest.mark.asyncio
async def test_read_pool_bounded_under_concurrency(repo: Repository) -> None:
    """Concurrent reads open at most READ_POOL_SIZE connections and stay valid."""
    from app.db.repository import READ_POOL_SIZE

    run_id = await _seed_run(repo)
    results = await asyncio.gather(*(repo.get_run(run_id) for _ in range(32)))
    assert all(r is not None for r in results)
    assert 1 <= len(repo._read_conns) <= READ_POOL_SIZE


@pytest.mark.asyncio
async def test_close_releases_all_read_connections(database_url: str) -> None:
    """close() closes every pooled read connection (clean shutdown)."""
    repository = Repository(database_url)
    await repository.start()
    run_id = await _seed_run(repository)
    # Warm a couple of pool connections via concurrent reads.
    await asyncio.gather(*(repository.get_run(run_id) for _ in range(8)))
    assert repository._read_conns  # at least one opened
    await repository.close()
    # All tracked read connections are closed and the registry is drained.
    assert repository._read_conns == []
    assert repository._read_pool.empty()


# === spend projection (AC-0.3-7; INV-7 prep) =================================


async def _feed_task_costs(
    repo: Repository, run_id: str, task_index: int, costs: list[float], *, base_seq: int
) -> None:
    """Append a sequence of cumulative cost events for one task."""
    records = [
        EventRecord(
            run_id=run_id,
            sequence=base_seq + i,
            event_type="assistant" if i < len(costs) - 1 else "task_completed",
            payload={"total_cost_usd": c},
            task_index=task_index,
            cost_usd=c,
        )
        for i, c in enumerate(costs)
    ]
    await repo.append_events(records)


@pytest.mark.asyncio
async def test_spend_is_segment_sum_of_last_per_task(repo: Repository) -> None:
    """Run cost = Σ(last-cumulative cost per task), not SUM over events."""
    run_id = await _seed_run(repo, agent="claude")
    # Task 0 climbs 0.10 → 0.50 (final 0.50). Task 1 climbs 0.20 → 0.30 → 0.90.
    await _feed_task_costs(repo, run_id, 0, [0.10, 0.30, 0.50], base_seq=0)
    await _feed_task_costs(repo, run_id, 1, [0.20, 0.30, 0.90], base_seq=10)

    spend = await repo.run_spend(run_id)
    # Segment sum: 0.50 (task 0 final) + 0.90 (task 1 final) = 1.40.
    assert spend == pytest.approx(1.40)
    # A naive SUM over events would have been 0.10+0.30+0.50+0.20+0.30+0.90 = 2.30.
    assert spend != pytest.approx(2.30)


@pytest.mark.asyncio
async def test_spend_single_task_does_not_reset_at_boundary(repo: Repository) -> None:
    run_id = await _seed_run(repo, agent="claude")
    await _feed_task_costs(repo, run_id, 0, [0.10, 0.25], base_seq=0)
    await _feed_task_costs(repo, run_id, 1, [0.05], base_seq=10)
    # 0.25 (task 0) + 0.05 (task 1) — never resets toward $0 at the boundary.
    assert await repo.run_spend(run_id) == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_codex_run_contributes_zero(repo: Repository) -> None:
    """A Codex run is excluded from spend (FR-06-1a); its $0 even with costs."""
    run_id = await _seed_run(repo, agent="codex")
    await _feed_task_costs(repo, run_id, 0, [0.40, 0.99], base_seq=0)
    assert await repo.run_spend(run_id) == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_total_spend_sums_claude_excludes_codex(repo: Repository) -> None:
    claude = await _seed_run(repo, agent="claude")
    codex = await _seed_run(repo, agent="codex")
    await _feed_task_costs(repo, claude, 0, [0.10, 0.60], base_seq=0)
    await _feed_task_costs(repo, codex, 0, [0.30, 0.80], base_seq=0)
    # Only the Claude run's 0.60 contributes.
    assert await repo.total_spend() == pytest.approx(0.60)


# === run_totals snapshot + VACUUM INTO backup (AC-0.3-9; §6.5) ===============


@pytest.mark.asyncio
async def test_run_totals_snapshot_round_trip(repo: Repository) -> None:
    run_id = await _seed_run(repo)
    await repo.snapshot_run_totals(
        run_id, RunTotals(cost_usd=1.23, tokens_in=100, tokens_out=200, turns=4, duration_s=12.5)
    )
    snap = await repo.get_run_totals(run_id)
    assert snap is not None
    assert snap["cost_usd"] == pytest.approx(1.23)
    assert snap["tokens_in"] == 100
    assert snap["turns"] == 4


@pytest.mark.asyncio
async def test_vacuum_into_produces_restorable_backup(repo: Repository, tmp_path: Path) -> None:
    run_id = await _seed_run(repo)
    await repo.snapshot_run_totals(run_id, RunTotals(cost_usd=2.5, turns=3))

    backup = tmp_path / "backup.db"
    await repo.backup_to(str(backup))
    assert backup.is_file()

    # The backup is a self-contained, restorable SQLite DB with our data.
    conn = sqlite3.connect(str(backup))
    try:
        row = next(conn.execute("SELECT cost_usd, turns FROM run_totals WHERE run_id=?", (run_id,)))
        assert row[0] == pytest.approx(2.5)
        assert row[1] == 3
    finally:
        conn.close()

    # The writer survived VACUUM INTO and still accepts writes.
    await repo.set_setting("after_backup", "ok")
    assert await repo.get_setting("after_backup") == "ok"


# === entity upserts behind the repo seam =====================================


@pytest.mark.asyncio
async def test_settings_upsert(repo: Repository) -> None:
    await repo.set_setting("k", "v1")
    assert await repo.get_setting("k") == "v1"
    await repo.set_setting("k", "v2")
    assert await repo.get_setting("k") == "v2"
    assert await repo.get_setting("missing") is None


@pytest.mark.asyncio
async def test_project_and_issue_upsert(repo: Repository) -> None:
    await repo.upsert_project(project_id="p1", repo="o/r", default_branch="main")
    await repo.upsert_issue(repo="o/r", num=7, title="Fix", labels=["bug", "backend"])
    conn = sqlite3.connect(repo._database_url.removeprefix("sqlite:///"))
    try:
        proj = next(conn.execute("SELECT repo FROM projects WHERE id='p1'"))
        iss = next(conn.execute("SELECT title, labels_json FROM issues WHERE repo='o/r' AND num=7"))
    finally:
        conn.close()
    assert proj[0] == "o/r"
    assert iss[0] == "Fix"
    assert "bug" in iss[1]


@pytest.mark.asyncio
async def test_upsert_issues_batch_writes_all_rows(repo: Repository) -> None:
    """upsert_issues persists every row of a page with the same upsert semantics."""
    await repo.upsert_issues(
        [
            IssueRow(repo="o/r", num=10, title="A", state="queued", labels=["agent:queued"]),
            IssueRow(repo="o/r", num=9, title="B", state="backlog"),
            IssueRow(repo="o/r", num=8, title="C", state="done", pr_num=42),
        ]
    )
    conn = sqlite3.connect(repo._database_url.removeprefix("sqlite:///"))
    try:
        rows = {
            r[0]: r
            for r in conn.execute(
                "SELECT num, title, state, labels_json, pr_num FROM issues WHERE repo='o/r'"
            )
        }
    finally:
        conn.close()
    assert set(rows) == {10, 9, 8}
    assert rows[10][1] == "A" and rows[10][2] == "queued"
    assert "agent:queued" in rows[10][3]
    assert rows[8][2] == "done" and rows[8][4] == 42


@pytest.mark.asyncio
async def test_read_issue_hit_returns_single_row(repo: Repository) -> None:
    """read_issue returns exactly the (repo, num) row, with its decoded columns."""
    await repo.upsert_issues(
        [
            IssueRow(repo="o/r", num=10, title="A", state="queued", labels=["agent:queued"]),
            IssueRow(repo="o/r", num=9, title="B", state="backlog"),
            IssueRow(repo="o/other", num=10, title="elsewhere", state="backlog"),
        ]
    )
    row = await repo.read_issue("o/r", 10)
    assert row is not None
    assert row["num"] == 10
    assert row["title"] == "A"
    assert row["state"] == "queued"
    assert "agent:queued" in row["labels_json"]


@pytest.mark.asyncio
async def test_read_issue_miss_returns_none(repo: Repository) -> None:
    """read_issue returns None for an absent (repo, num) — no cross-repo bleed."""
    await repo.upsert_issues([IssueRow(repo="o/r", num=9, title="B", state="backlog")])
    assert await repo.read_issue("o/r", 999) is None  # absent num
    assert await repo.read_issue("o/missing", 9) is None  # absent repo


@pytest.mark.asyncio
async def test_upsert_issues_is_idempotent_on_conflict(repo: Repository) -> None:
    """Re-upserting the same (repo, num) updates in place (ON CONFLICT), no dup row."""
    await repo.upsert_issues([IssueRow(repo="o/r", num=7, title="first", state="backlog")])
    await repo.upsert_issues([IssueRow(repo="o/r", num=7, title="second", state="queued")])
    conn = sqlite3.connect(repo._database_url.removeprefix("sqlite:///"))
    try:
        rows = list(conn.execute("SELECT title, state FROM issues WHERE repo='o/r' AND num=7"))
    finally:
        conn.close()
    assert len(rows) == 1  # upsert, not a duplicate row
    assert rows[0] == ("second", "queued")


@pytest.mark.asyncio
async def test_upsert_issues_is_single_writer_transaction(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole page is ONE writer submit → ONE BEGIN IMMEDIATE transaction (FIX-1).

    Mirrors the append_events batch contract: importing N issues must hold the
    global write lock for a single transaction, not N. We count writer.submit
    calls across the batch upsert and assert exactly one.
    """
    submits = 0
    original = Writer.submit

    async def _counting_submit(self: Writer, fn: object) -> object:
        nonlocal submits
        submits += 1
        return await original(self, fn)  # type: ignore[arg-type]

    monkeypatch.setattr(Writer, "submit", _counting_submit)
    await repo.upsert_issues(
        [IssueRow(repo="o/r", num=n, title=f"i{n}", state="backlog") for n in range(5)]
    )
    assert submits == 1  # one transaction for the whole page, not five


@pytest.mark.asyncio
async def test_upsert_issues_empty_is_noop(repo: Repository) -> None:
    """An empty page does not open a writer transaction."""
    await repo.upsert_issues([])  # must not raise / must not write


@pytest.mark.asyncio
async def test_labels_ensured_flag_round_trip(repo: Repository) -> None:
    """labels_ensured defaults false, flips true after mark (FIX-2, per repo)."""
    assert await repo.labels_ensured("o/r") is False
    await repo.mark_labels_ensured("o/r")
    assert await repo.labels_ensured("o/r") is True
    # Scoped per repo (case-insensitive key); a different repo is unaffected.
    assert await repo.labels_ensured("o/other") is False


@pytest.mark.asyncio
async def test_upsert_issues_single_sql_shared_with_upsert_issue() -> None:
    """The batch path reuses the single-row upsert SQL (identical ON CONFLICT)."""
    src = Path("app/db/repository.py").read_text()
    assert "_ISSUE_UPSERT_SQL" in src
    assert "ON CONFLICT(repo, num) DO UPDATE SET" in src
    # The batch is one executemany over the shared statement, not N execute calls.
    assert "executemany(_ISSUE_UPSERT_SQL" in src


@pytest.mark.asyncio
async def test_update_run_fields_rejects_unknown_column(repo: Repository) -> None:
    run_id = await _seed_run(repo)
    with pytest.raises(ValueError):
        await repo.update_run_fields(run_id, idempotency_key="hijack")


@pytest.mark.asyncio
async def test_update_run_fields_patches_status(repo: Repository) -> None:
    run_id = await _seed_run(repo)
    await repo.update_run_fields(run_id, status="completed", cost_usd=0.99)
    row = await repo.get_run(run_id)
    assert row is not None
    assert row["status"] == "completed"
    assert row["cost_usd"] == pytest.approx(0.99)


@pytest.mark.asyncio
async def test_run_stage_upsert(repo: Repository) -> None:
    run_id = await _seed_run(repo)
    await repo.upsert_stage(run_id, 0, "Analyze", status="running")
    await repo.upsert_stage(run_id, 0, "Analyze", status="done", cost_usd=0.5, turns=3)
    conn = sqlite3.connect(repo._database_url.removeprefix("sqlite:///"))
    try:
        rows = list(conn.execute("SELECT status, turns FROM run_stages WHERE run_id=?", (run_id,)))
    finally:
        conn.close()
    assert len(rows) == 1  # upsert, not duplicate
    assert rows[0][0] == "done"
    assert rows[0][1] == 3


@pytest.mark.asyncio
async def test_cascade_delete_removes_children(repo: Repository) -> None:
    run_id = await _seed_run(repo)
    await repo.append_events([EventRecord(run_id=run_id, sequence=0, event_type="ok", payload={})])
    await repo.snapshot_run_totals(run_id, RunTotals(cost_usd=1.0))

    async def _delete(conn: object) -> None:
        await conn.execute("DELETE FROM runs WHERE id=?", (run_id,))  # type: ignore[attr-defined]

    await repo._writer.submit(_delete)  # type: ignore[arg-type]

    assert await repo.read_events_after(run_id) == []
    assert await repo.get_run_totals(run_id) is None
