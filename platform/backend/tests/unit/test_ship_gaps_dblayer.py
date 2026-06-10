"""DB-layer ship-gap remediations: G9 (events retention + spend fast-path),
G12 (indexed queued-candidate read), G13 (single-source segment-sum SQL).

All over a real, migrated SQLite file through the :class:`Repository` seam.

* **G9 fast-path equality** — ``total_spend`` / ``daily_spend_series`` read the
  ``run_totals`` snapshot for TERMINAL runs and segment-sum only ACTIVE runs; the
  result must EQUAL the full-events segment-sum for any mixed terminal+active
  fixture (Codex excluded, tokens still real). The full-scan reference is computed
  directly off ``events`` to prove the fast-path is numerically identical.
* **G9 retention prune** — events of a terminal+snapshotted run older than the
  horizon are deleted; an active run's events and a snapshot-less run's events are
  NOT; the spend total is unchanged after the prune (it reads ``run_totals``).
* **G12 indexed candidate read** — ``read_candidate_issues`` returns only
  ``agent:queued`` issues via the index; a non-queued issue is never returned.
* **G13 single-source** — the canonical ``last_per_task`` CTE lives in ONE module
  and every spend SQL site composes it (no forked copy).
"""

from __future__ import annotations

import uuid

import pytest
from app.db import EventRecord, Repository, RunTotals

pytestmark = pytest.mark.asyncio


# ── helpers ───────────────────────────────────────────────────────────────────


async def _seed_run(
    repo: Repository,
    *,
    agent: str = "claude",
    status: str = "running",
    started_at: str | None = None,
    finished_at: str | None = None,
) -> str:
    run_id, won = await repo.claim_run(idempotency_key=str(uuid.uuid4()), repo="o/r", agent=agent)
    assert won
    fields: dict[str, object] = {"status": status}
    if finished_at is not None:
        fields["finished_at"] = finished_at
    await repo.update_run_fields(run_id, **fields)
    if started_at is not None:
        await _set_started_at(repo, run_id, started_at)
    return run_id


async def _set_started_at(repo: Repository, run_id: str, started_at: str) -> None:
    async with repo._read_conn() as conn:
        await conn.execute("UPDATE runs SET started_at = ? WHERE id = ?", (started_at, run_id))
        await conn.commit()


async def _feed_costs(
    repo: Repository, run_id: str, task_index: int, costs: list[float], *, base_seq: int
) -> None:
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


async def _full_scan_total(repo: Repository) -> float:
    """The full-events segment-sum total (the reference the fast-path must equal)."""
    async with repo._read_conn() as conn:
        rows = list(
            await conn.execute_fetchall(
                """
                WITH last_per_task AS (
                    SELECT e.run_id AS run_id, e.cost_usd AS cost_usd
                    FROM events e
                    JOIN (
                        SELECT run_id, task_index, MAX(id) AS max_id
                        FROM events
                        WHERE cost_usd IS NOT NULL
                        GROUP BY run_id, task_index
                    ) m ON e.run_id = m.run_id AND e.id = m.max_id
                )
                SELECT COALESCE(SUM(lpt.cost_usd), 0.0) AS total
                FROM last_per_task lpt
                JOIN runs r ON r.id = lpt.run_id
                WHERE COALESCE(LOWER(r.agent), '') != 'codex'
                """,
            )
        )
    return float(rows[0]["total"] or 0.0)


# ── G9 — fast-path equals full-scan over a mixed terminal+active fixture ───────


async def test_total_spend_fast_path_equals_full_scan(repo: Repository) -> None:
    """G9: run_totals fast-path total == full-events segment-sum (mixed states)."""
    # An ACTIVE Claude run (no snapshot) — segment-summed live.
    active = await _seed_run(repo, agent="claude", status="running")
    await _feed_costs(repo, active, 0, [0.10, 0.50], base_seq=0)
    await _feed_costs(repo, active, 1, [0.20, 0.90], base_seq=10)

    # A TERMINAL Claude run WITH a snapshot — read from run_totals (events present
    # so the full-scan reference still sees its cost).
    terminal = await _seed_run(repo, agent="claude", status="completed")
    await _feed_costs(repo, terminal, 0, [0.30, 1.40], base_seq=0)
    await repo.snapshot_run_totals(terminal, RunTotals(cost_usd=1.40))

    # A Codex run (terminal + snapshot) — excluded from spend, tokens real.
    codex = await _seed_run(repo, agent="codex", status="completed")
    await _feed_costs(repo, codex, 0, [0.50, 2.00], base_seq=0)
    await repo.snapshot_run_totals(codex, RunTotals(cost_usd=2.00, tokens_in=99))

    fast = await repo.total_spend()
    full = await _full_scan_total(repo)
    # active 0.50+0.90=1.40, terminal snapshot 1.40, codex excluded → 2.80.
    assert fast == pytest.approx(2.80)
    assert fast == pytest.approx(full)


async def test_total_spend_terminal_without_snapshot_falls_back_to_events(
    repo: Repository,
) -> None:
    """G9: a terminal run with NO snapshot still counts (live segment-sum fallback)."""
    terminal = await _seed_run(repo, agent="claude", status="completed")
    await _feed_costs(repo, terminal, 0, [0.10, 0.75], base_seq=0)
    # No snapshot written → must fall through to the events segment-sum.
    assert await repo.total_spend() == pytest.approx(0.75)
    assert await repo.total_spend() == pytest.approx(await _full_scan_total(repo))


async def test_daily_spend_series_fast_path_equals_full_scan(repo: Repository) -> None:
    """G9: daily series merges terminal-snapshot + active buckets, equals full-scan."""
    # Two runs on the same day: one terminal+snapshotted, one active.
    term = await _seed_run(
        repo, agent="claude", status="completed", started_at="2026-06-01T10:00:00+00:00"
    )
    await _feed_costs(repo, term, 0, [0.40], base_seq=0)
    await repo.snapshot_run_totals(term, RunTotals(cost_usd=0.40))
    act = await _seed_run(
        repo, agent="claude", status="running", started_at="2026-06-01T12:00:00+00:00"
    )
    await _feed_costs(repo, act, 0, [0.60], base_seq=0)
    # A second day, terminal only.
    term2 = await _seed_run(
        repo, agent="claude", status="completed", started_at="2026-06-02T09:00:00+00:00"
    )
    await _feed_costs(repo, term2, 0, [1.00], base_seq=0)
    await repo.snapshot_run_totals(term2, RunTotals(cost_usd=1.00))

    series = await repo.daily_spend_series()
    by_day = {pt["date"]: pt["usd"] for pt in series}
    assert by_day["2026-06-01"] == pytest.approx(1.00)  # 0.40 + 0.60
    assert by_day["2026-06-02"] == pytest.approx(1.00)
    # The series total reconciles with the fast-path total + the full scan.
    assert sum(pt["usd"] for pt in series) == pytest.approx(await repo.total_spend())
    assert sum(pt["usd"] for pt in series) == pytest.approx(await _full_scan_total(repo))


# ── G9 — retention prune ───────────────────────────────────────────────────────


async def _count_events(repo: Repository, run_id: str) -> int:
    async with repo._read_conn() as conn:
        rows = list(
            await conn.execute_fetchall(
                "SELECT COUNT(*) AS n FROM events WHERE run_id = ?", (run_id,)
            )
        )
    return int(rows[0]["n"])


async def test_prune_deletes_only_terminal_snapshotted_old_runs(repo: Repository) -> None:
    """G9: prune removes a terminal+snapshotted old run's events; spares the rest."""
    horizon = "2026-06-05T00:00:00+00:00"

    # (1) terminal + snapshot + finished BEFORE the horizon → PRUNED.
    pruned = await _seed_run(
        repo, agent="claude", status="completed", finished_at="2026-06-01T00:00:00+00:00"
    )
    await _feed_costs(repo, pruned, 0, [0.10, 0.40], base_seq=0)
    await repo.snapshot_run_totals(pruned, RunTotals(cost_usd=0.40))

    # (2) ACTIVE run with events → never pruned (not terminal).
    active = await _seed_run(repo, agent="claude", status="running")
    await _feed_costs(repo, active, 0, [0.20, 0.70], base_seq=0)

    # (3) terminal but NO snapshot → never pruned (spend would be lost).
    no_snap = await _seed_run(
        repo, agent="claude", status="failed", finished_at="2026-06-01T00:00:00+00:00"
    )
    await _feed_costs(repo, no_snap, 0, [0.05, 0.25], base_seq=0)

    # (4) terminal + snapshot but finished AFTER the horizon → not yet due.
    recent = await _seed_run(
        repo, agent="claude", status="completed", finished_at="2026-06-09T00:00:00+00:00"
    )
    await _feed_costs(repo, recent, 0, [0.30], base_seq=0)
    await repo.snapshot_run_totals(recent, RunTotals(cost_usd=0.30))

    total_before = await repo.total_spend()

    deleted = await repo.prune_events_for_terminal_runs(older_than_iso=horizon)

    assert deleted == 2  # only run (1)'s two events
    assert await _count_events(repo, pruned) == 0
    assert await _count_events(repo, active) == 2  # active spared
    assert await _count_events(repo, no_snap) == 2  # snapshot-less spared
    assert await _count_events(repo, recent) == 1  # not yet due

    # Spend total is UNCHANGED after the prune — the pruned run's cost survives via
    # its run_totals snapshot (the fast-path reads it, not its now-gone events).
    assert await repo.total_spend() == pytest.approx(total_before)


async def test_prune_disabled_horizon_is_safe(repo: Repository) -> None:
    """G9: a future/just-now horizon prunes nothing when no run is old enough."""
    terminal = await _seed_run(
        repo, agent="claude", status="completed", finished_at="2026-06-09T00:00:00+00:00"
    )
    await _feed_costs(repo, terminal, 0, [0.50], base_seq=0)
    await repo.snapshot_run_totals(terminal, RunTotals(cost_usd=0.50))
    deleted = await repo.prune_events_for_terminal_runs(older_than_iso="2026-06-01T00:00:00+00:00")
    assert deleted == 0
    assert await _count_events(repo, terminal) == 1


# ── G12 — indexed queued-candidate read ────────────────────────────────────────


async def test_read_candidate_issues_returns_only_queued(repo: Repository) -> None:
    """G12: with many issues, only the agent:queued ones come back (index-backed)."""
    # A handful of non-queued issues across the other states + Backlog.
    await repo.upsert_issue(repo="o/r", num=1, labels=[], workflow_id="dev")  # backlog
    await repo.upsert_issue(repo="o/r", num=2, labels=["agent:in-progress"], workflow_id="dev")
    await repo.upsert_issue(repo="o/r", num=3, labels=["agent:review"], workflow_id="dev")
    await repo.upsert_issue(repo="o/r", num=4, labels=["agent:paused"], workflow_id="dev")
    # The two queued candidates (plus a non-agent label preserved).
    await repo.upsert_issue(repo="o/r", num=5, labels=["agent:queued", "bug"], workflow_id="dev")
    await repo.upsert_issue(repo="o/r", num=6, labels=["agent:queued"], workflow_id="qa")

    rows = await repo.read_candidate_issues("o/r")
    nums = {int(r["num"]) for r in rows}
    assert nums == {5, 6}
    # A non-queued issue is never returned.
    assert 2 not in nums
    assert 1 not in nums
    # Every returned row carries the queued label (the index predicate held).
    for r in rows:
        assert "agent:queued" in r["labels_json"]


async def test_upsert_issue_derives_agent_state_from_labels(repo: Repository) -> None:
    """G12: agent_state is derived from labels by precedence and persisted."""
    await repo.upsert_issue(
        repo="o/r", num=10, labels=["agent:in-progress", "agent:queued"], workflow_id="dev"
    )
    async with repo._read_conn() as conn:
        rows = list(
            await conn.execute_fetchall(
                "SELECT agent_state FROM issues WHERE repo = ? AND num = ?", ("o/r", 10)
            )
        )
    # in-progress outranks queued (precedence) → the issue is NOT a queued candidate.
    assert rows[0]["agent_state"] == "in-progress"
    assert await repo.read_candidate_issues("o/r") == []


def test_repository_and_sync_agent_state_derivations_agree() -> None:
    """G12: the db-layer + github-layer agent_state derivations use the SAME precedence.

    ``Repository._agent_state_from_labels`` (single-row upsert) and
    ``sync.derive_agent_state`` (batch sync) must never disagree, or a queued issue
    could be indexed differently depending on which write path touched it.
    """
    from app.db import repository as repo_mod
    from app.github.sync import derive_agent_state

    cases: list[list[str]] = [
        [],
        ["bug"],
        ["agent:queued"],
        ["agent:review"],
        ["agent:paused"],
        ["agent:in-progress"],
        ["agent:queued", "agent:in-progress"],  # precedence: in-progress wins
        ["agent:review", "agent:paused"],  # precedence: paused wins
    ]
    for labels in cases:
        assert repo_mod._agent_state_from_labels(labels) == derive_agent_state(labels)


# ── G13 — single-source segment-sum SQL ────────────────────────────────────────


def test_segment_sum_cte_has_one_source() -> None:
    """G13: the canonical last_per_task CTE lives in app.db.spend_sql, composed everywhere.

    Asserts the projection sites do NOT each hand-roll their own
    ``WITH last_per_task AS`` copy: the body comes from the one ``last_per_task_cte``
    helper. (repository.read_run_segments keeps a per-run variant — documented as the
    one twin — and the full-scan reference in this test file is intentional.)
    """
    from pathlib import Path

    from app.db import spend_sql

    # The canonical builder exists and emits the CTE shape.
    cte = spend_sql.last_per_task_cte()
    assert "WITH last_per_task AS" in cte
    assert spend_sql.AGENT_NOT_CODEX_SQL in spend_sql.total_spend_sql()

    # repository.py and backup.py compose the helper; they do not re-declare the CTE
    # via a literal "WITH last_per_task AS" of their own (the per-run read_run_segments
    # in repository uses a different, GROUP BY task_index, payload-returning shape).
    backup_src = Path("app/db/backup.py").read_text()
    assert "WITH last_per_task AS" not in backup_src
    assert "total_spend_sql" in backup_src
