"""Slice 2.4 — segment-sum live meters (INV-7 / AC-12, AC-13, §8.3/§6.4).

The binding cost rule: ``run_cost = Σ(final cost_usd of each completed task) +
latest-within-active``, **deduped by ``task_index``** — never a naive ``SUM`` over
events, never keep-latest-overall. The headline test is the **multi-stage climb**:
across stage boundaries the displayed cost climbs toward the run total (~$12) and
NEVER resets toward $0.

Also asserts the Codex handling (AC-13 / INV-8): a Codex run's cost is ``None``
("—"), excluded from spend, while its tokens still count; and a mixed
Claude+Codex pair has spend = Claude-only, tokens = both.
"""

from __future__ import annotations

import json

import pytest
from app.db import Repository
from app.db.repository import EventRecord
from app.runs.meters import compute_run_meters

pytestmark = pytest.mark.asyncio


async def _seed_run(repo: Repository, *, agent: str, key: str) -> str:
    run_id, _won = await repo.claim_run(
        idempotency_key=key,
        repo="o/r",
        issue_num=1,
        workflow_id="plan",
        agent=agent,
        model="claude-sonnet-4-6",
    )
    return run_id


async def _append_segment(
    repo: Repository,
    run_id: str,
    *,
    task_index: int,
    cumulative_costs: list[float],
    final_turns: int,
    final_tokens: tuple[int, int],
    base_seq: int,
) -> None:
    """Append one task's cumulative cost lines; the last carries final turns/tokens.

    Mirrors the engine's per-task cumulative ``cost_usd`` — each line is the
    running total for that task. The segment-sum keeps the LAST (highest-id) one.
    """
    records: list[EventRecord] = []
    last = len(cumulative_costs) - 1
    for i, cost in enumerate(cumulative_costs):
        is_final = i == last
        payload: dict[str, object] = {"type": "stream", "task_index": task_index}
        if is_final:
            payload = {
                "type": "task_completed",
                "task_index": task_index,
                "turns": final_turns,
                "usage": {"input_tokens": final_tokens[0], "output_tokens": final_tokens[1]},
            }
        records.append(
            EventRecord(
                run_id=run_id,
                sequence=base_seq + i,
                event_type="task_completed" if is_final else "stream",
                payload=payload,
                task_index=task_index,
                cost_usd=cost,
            )
        )
    await repo.append_events(records)


async def test_cost_climbs_across_stages_never_resets(repo: Repository) -> None:
    """Multi-stage `plan` run: cost climbs to the run total (~$12), never resets."""
    run_id = await _seed_run(repo, agent="claude", key="plan-climb")
    run_row = await repo.get_run(run_id)
    assert run_row is not None

    # Stage 0 (Analyze): cumulative 1.0 → 3.0 (final 3.0).
    await _append_segment(
        repo,
        run_id,
        task_index=0,
        cumulative_costs=[1.0, 2.0, 3.0],
        final_turns=20,
        final_tokens=(1000, 300),
        base_seq=0,
    )
    after_s0 = (await compute_run_meters(repo, run_row)).cost_usd
    assert after_s0 == pytest.approx(3.0)

    # Stage 1 (Features): its OWN cumulative starts at 0.5 → 4.0. The run total
    # must be 3.0 (stage 0 final) + 4.0 = 7.0 — NOT reset to 4.0 (keep-latest) and
    # NOT 3.0+0.5+1.5+4.0 (naive sum of every line).
    await _append_segment(
        repo,
        run_id,
        task_index=1,
        cumulative_costs=[0.5, 1.5, 4.0],
        final_turns=30,
        final_tokens=(2000, 600),
        base_seq=10,
    )
    after_s1 = (await compute_run_meters(repo, run_row)).cost_usd
    assert after_s1 == pytest.approx(7.0)
    assert after_s1 is not None and after_s0 is not None and after_s1 > after_s0  # climbed

    # Stage 2 (Phases): cumulative 1.0 → 5.0. Run total = 3 + 4 + 5 = 12.
    await _append_segment(
        repo,
        run_id,
        task_index=2,
        cumulative_costs=[1.0, 3.0, 5.0],
        final_turns=40,
        final_tokens=(3000, 900),
        base_seq=20,
    )
    final = await compute_run_meters(repo, run_row)
    assert final.cost_usd == pytest.approx(12.0)  # ≈ the run total
    # Turns aggregate identically: 20 + 30 + 40 = 90.
    assert final.turns == 90
    # Tokens aggregate identically across stages.
    assert final.tokens_in == 6000
    assert final.tokens_out == 1800


async def test_active_task_uses_latest_not_final(repo: Repository) -> None:
    """The active (un-completed) task contributes its LATEST cumulative line."""
    run_id = await _seed_run(repo, agent="claude", key="active-latest")
    run_row = await repo.get_run(run_id)
    assert run_row is not None
    # Stage 0 completed at 2.0; stage 1 active, latest line 1.5 (no task_completed).
    await _append_segment(
        repo,
        run_id,
        task_index=0,
        cumulative_costs=[1.0, 2.0],
        final_turns=10,
        final_tokens=(500, 100),
        base_seq=0,
    )
    await repo.append_events(
        [
            EventRecord(
                run_id=run_id,
                sequence=10,
                event_type="stream",
                payload={"type": "stream"},
                task_index=1,
                cost_usd=0.5,
            ),
            EventRecord(
                run_id=run_id,
                sequence=11,
                event_type="stream",
                payload={"type": "stream"},
                task_index=1,
                cost_usd=1.5,
            ),
        ]
    )
    meters = await compute_run_meters(repo, run_row)
    assert meters.cost_usd == pytest.approx(3.5)  # 2.0 final + 1.5 latest-active


async def test_codex_cost_excluded_tokens_count(repo: Repository) -> None:
    """A Codex run's cost is None ("—") + excluded; its tokens still count (AC-13)."""
    run_id = await _seed_run(repo, agent="codex", key="codex-1")
    run_row = await repo.get_run(run_id)
    assert run_row is not None
    await _append_segment(
        repo,
        run_id,
        task_index=0,
        cumulative_costs=[2.0, 4.0],
        final_turns=15,
        final_tokens=(1200, 400),
        base_seq=0,
    )
    meters = await compute_run_meters(repo, run_row)
    assert meters.cost_usd is None  # rendered "—", not $0.00
    assert meters.cost_excluded is True
    assert meters.tokens_in == 1200 and meters.tokens_out == 400  # tokens count
    assert meters.turns == 15


async def test_mixed_claude_codex_spend_claude_only_tokens_both(repo: Repository) -> None:
    """Mixed pair: spend = Claude-only; tokens = both (AC-13 / INV-8)."""
    claude_id = await _seed_run(repo, agent="claude", key="mix-claude")
    codex_id = await _seed_run(repo, agent="codex", key="mix-codex")
    claude_row = await repo.get_run(claude_id)
    codex_row = await repo.get_run(codex_id)
    assert claude_row is not None and codex_row is not None

    await _append_segment(
        repo,
        claude_id,
        task_index=0,
        cumulative_costs=[3.0],
        final_turns=10,
        final_tokens=(1000, 200),
        base_seq=0,
    )
    await _append_segment(
        repo,
        codex_id,
        task_index=0,
        cumulative_costs=[9.0],
        final_turns=12,
        final_tokens=(5000, 800),
        base_seq=0,
    )

    claude_m = await compute_run_meters(repo, claude_row)
    codex_m = await compute_run_meters(repo, codex_row)

    # Spend = Claude-only: the Codex $9 contributes nothing.
    total_spend = (claude_m.cost_usd or 0.0) + (codex_m.cost_usd or 0.0)
    assert total_spend == pytest.approx(3.0)
    assert codex_m.cost_usd is None

    # Tokens = both agents' tokens.
    total_tokens = claude_m.tokens_in + claude_m.tokens_out + codex_m.tokens_in + codex_m.tokens_out
    assert total_tokens == (1000 + 200) + (5000 + 800)


async def test_meter_matches_persisted_spend_projection(repo: Repository) -> None:
    """The live meter cost equals the persisted segment-sum spend (no divergence)."""
    run_id = await _seed_run(repo, agent="claude", key="match-spend")
    run_row = await repo.get_run(run_id)
    assert run_row is not None
    await _append_segment(
        repo,
        run_id,
        task_index=0,
        cumulative_costs=[1.0, 4.0],
        final_turns=10,
        final_tokens=(0, 0),
        base_seq=0,
    )
    await _append_segment(
        repo,
        run_id,
        task_index=1,
        cumulative_costs=[2.0, 6.0],
        final_turns=10,
        final_tokens=(0, 0),
        base_seq=10,
    )
    meters = await compute_run_meters(repo, run_row)
    spend = await repo.run_spend(run_id)
    assert meters.cost_usd == pytest.approx(spend) == pytest.approx(10.0)


async def test_no_naive_sum_over_events(repo: Repository) -> None:
    """A single task's many cumulative lines do NOT sum (no double-count)."""
    run_id = await _seed_run(repo, agent="claude", key="no-naive")
    run_row = await repo.get_run(run_id)
    assert run_row is not None
    # One task, four cumulative lines 1→2→3→4. The meter is 4 (the final), NOT 10.
    await _append_segment(
        repo,
        run_id,
        task_index=0,
        cumulative_costs=[1.0, 2.0, 3.0, 4.0],
        final_turns=8,
        final_tokens=(0, 0),
        base_seq=0,
    )
    meters = await compute_run_meters(repo, run_row)
    assert meters.cost_usd == pytest.approx(4.0)


async def test_payload_json_is_inner_data_shape(repo: Repository) -> None:
    """The persisted payload (meter source) is the inner RuntimeEvent.data (§6.4)."""
    run_id = await _seed_run(repo, agent="claude", key="inner")
    await _append_segment(
        repo,
        run_id,
        task_index=0,
        cumulative_costs=[1.0],
        final_turns=5,
        final_tokens=(10, 20),
        base_seq=0,
    )
    segments = await repo.read_run_segments(run_id)
    payload = json.loads(segments[0]["payload_json"])
    # The inner data dict keys, not the outer wrapper (no `sequence`/`run_id`).
    assert payload["type"] == "task_completed"
    assert payload["turns"] == 5
    assert "sequence" not in payload and "run_id" not in payload
