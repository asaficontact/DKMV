"""Board aggregate-strip counters — Codex spend exclusion (AC-17, FR-02-4, INV-8).

The binding assertion (AC-17): a repo with **one Claude run + one Codex run**
yields ``spent_today == Claude-only`` (the $0-cost Codex run is excluded from the
spend figure — FR-06-1a / INV-8) while ``tokens_today == both`` (Codex tokens are
real and still count). Also covers the segment-sum spend rule (INV-7: last
cumulative ``cost_usd`` per ``(run_id, task_index)``, never a naive SUM) and the
In-Progress / Needs-You active-run counts.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.api.board import start_of_utc_day
from app.db.repository import EventRecord, Repository

from tests.conftest import auth_headers, build_client, make_settings

REPO = "asaficontact/DKMV"

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


async def _seed_run(
    repo: Repository,
    *,
    agent: str,
    status: str,
    issue_num: int,
    tokens_in: int,
    tokens_out: int,
    task_costs: list[tuple[int, float]],
) -> str:
    """Claim a run, set its status/tokens, and append per-task cumulative cost rows.

    ``task_costs`` is ``[(task_index, cumulative_cost_usd), ...]`` — two rows for
    the same ``task_index`` simulate the cumulative line climbing within a task so
    the segment-sum dedup (last per task_index) is exercised.
    """
    run_id, _ = await repo.claim_run(
        idempotency_key=str(uuid.uuid4()),
        repo=REPO,
        issue_num=issue_num,
        agent=agent,
    )
    await repo.update_run_fields(run_id, status=status, tokens_in=tokens_in, tokens_out=tokens_out)
    records: list[EventRecord] = []
    seq = 0
    for task_index, cost in task_costs:
        # two events per task: an interim then the final cumulative; only the last
        # (highest id) per task_index must count toward the segment sum (INV-7).
        records.append(
            EventRecord(
                run_id=run_id,
                sequence=seq,
                event_type="assistant",
                payload={},
                task_index=task_index,
                cost_usd=round(cost / 2, 4),
                agent=agent,
            )
        )
        seq += 1
        records.append(
            EventRecord(
                run_id=run_id,
                sequence=seq,
                event_type="task_completed",
                payload={},
                task_index=task_index,
                cost_usd=cost,
                agent=agent,
            )
        )
        seq += 1
    if records:
        await repo.append_events(records)
    return run_id


@pytest.mark.asyncio
async def test_aggregate_excludes_codex_spend_counts_codex_tokens(repo: Repository) -> None:
    """One Claude + one Codex run → spend = Claude-only, tokens = both (AC-17)."""
    # Claude: two tasks, cumulative $1.50 + $2.00 = $3.50 (segment sum, not naive).
    await _seed_run(
        repo,
        agent="claude",
        status="running",
        issue_num=247,
        tokens_in=70_000,
        tokens_out=18_000,
        task_costs=[(0, 1.50), (1, 2.00)],
    )
    # Codex: real tokens, but the engine reports $0 — its event "cost" must be
    # ignored entirely in the spend figure (excluded by agent, FR-06-1a).
    await _seed_run(
        repo,
        agent="codex",
        status="running",
        issue_num=251,
        tokens_in=40_000,
        tokens_out=12_000,
        task_costs=[(0, 9.99)],  # illustrative non-zero — must NOT be summed
    )

    agg = await repo.board_aggregate(REPO, since_iso=start_of_utc_day())

    # Spend excludes Codex: only the Claude run's $3.50 segment-sum counts.
    assert agg.spent_today == pytest.approx(3.50)
    # Tokens count BOTH runs: (70k+18k) + (40k+12k) = 140k.
    assert agg.tokens_today == 140_000


@pytest.mark.asyncio
async def test_aggregate_active_run_counts(repo: Repository) -> None:
    """In-Progress vs Needs-You split follows the §5.3.1 authority mapping."""
    await _seed_run(
        repo,
        agent="claude",
        status="running",
        issue_num=10,
        tokens_in=1,
        tokens_out=1,
        task_costs=[(0, 0.10)],
    )
    await _seed_run(
        repo,
        agent="claude",
        status="paused",
        issue_num=11,
        tokens_in=1,
        tokens_out=1,
        task_costs=[(0, 0.20)],
    )
    # A completed run is terminal — it does not inflate the active counts.
    await _seed_run(
        repo,
        agent="claude",
        status="completed",
        issue_num=12,
        tokens_in=1,
        tokens_out=1,
        task_costs=[(0, 0.30)],
    )

    agg = await repo.board_aggregate(REPO, since_iso=start_of_utc_day())

    assert agg.in_progress == 1
    assert agg.needs_you == 1


@pytest.mark.asyncio
async def test_aggregate_empty_repo_is_zeroed(repo: Repository) -> None:
    """A repo with no runs yields an all-zero aggregate (no NULLs leak out)."""
    agg = await repo.board_aggregate("empty/repo", since_iso=start_of_utc_day())
    assert agg.in_progress == 0
    assert agg.needs_you == 0
    assert agg.spent_today == 0.0
    assert agg.tokens_today == 0


# ── API-level (sync TestClient over the real app + migrated DB) ───────────────


def _run[T](coro: Awaitable[T]) -> T:
    """Run a coroutine to completion on a throwaway loop (sync test helper)."""
    return asyncio.new_event_loop().run_until_complete(coro)


def _migrate(db_path: Path) -> str:
    url = f"sqlite:///{db_path}"
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


def test_aggregate_requires_token() -> None:
    """INV-1 — the board aggregate GET is behind access control (no token → 401)."""
    client = build_client()
    resp = client.get(f"/api/v1/repos/{REPO}/board/aggregate")
    assert resp.status_code == 401


def test_aggregate_foreign_host_403() -> None:
    """INV-1 — a foreign Host is rejected (anti-DNS-rebinding)."""
    client = build_client(host="evil.example.com")
    resp = client.get(f"/api/v1/repos/{REPO}/board/aggregate", headers=auth_headers())
    assert resp.status_code == 403


def test_aggregate_endpoint_excludes_codex_spend(tmp_path: Path) -> None:
    """End-to-end: the GET returns Codex-excluded spend + Codex-inclusive tokens."""
    url = _migrate(tmp_path / "test.db")

    async def _seed() -> None:
        repository = Repository(url)
        await repository.start()
        try:
            await _seed_run(
                repository,
                agent="claude",
                status="running",
                issue_num=247,
                tokens_in=70_000,
                tokens_out=18_000,
                task_costs=[(0, 1.50), (1, 2.00)],
            )
            await _seed_run(
                repository,
                agent="codex",
                status="paused",
                issue_num=251,
                tokens_in=40_000,
                tokens_out=12_000,
                task_costs=[(0, 9.99)],
            )
        finally:
            await repository.close()

    _run(_seed())

    client = build_client(settings=make_settings(DATABASE_URL=url))
    resp = client.get(f"/api/v1/repos/{REPO}/board/aggregate", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["repo"] == REPO
    assert body["spent_today"] == pytest.approx(3.50)  # Codex $9.99 excluded
    assert body["tokens_today"] == 140_000  # Codex tokens still counted
    assert body["in_progress"] == 1  # the Claude running run
    assert body["needs_you"] == 1  # the paused Codex run
