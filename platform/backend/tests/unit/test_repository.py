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
from app.db import EventRecord, Repository, RunTotals


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
