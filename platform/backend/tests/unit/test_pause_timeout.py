"""Slice 2.5 — pause-timeout auto-resolve sweep (AC-20 / INV-9 / §8.5 step 4).

Each pause carries a UTC ``timeout_at`` (default 60 min). The minimal auto-resolve
sweep re-evaluates ``now() >= timeout_at`` and resolves expired pauses via the
**same exactly-once guard** the human path uses (``resolved_by='timeout'``, default
auto-abort). Asserts:

* fast-forwarding ``now()`` past ``timeout_at`` yields exactly one
  ``resolved_by='timeout'`` transition;
* a not-yet-expired pause is left ``pending`` (the deadline is real, not eager);
* a human-resolved pause is NOT re-resolved by a later sweep (the guard makes the
  sweep idempotent against an already-answered decision).

``now`` is injected so the test fast-forwards without sleeping (Phase 2 invokes the
sweep directly — the reconcile-tick wiring is Phase 3, T104).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.db import Repository
from app.hitl import DecisionRegistry, sweep_expired_pauses
from app.hitl.answer import resolve_pending_pause
from app.hitl.pause_bridge import compute_timeout_at


async def _seed_pause(repo: Repository, *, issue_num: int, timeout_at: str) -> str:
    run_id, _ = await repo.claim_run(
        idempotency_key=f"{issue_num}::qa::main",
        repo="o/r",
        issue_num=issue_num,
        workflow_id="qa",
        agent="claude",
    )
    return await repo.create_pause_decision(
        run_id=run_id,
        request_json='{"task_name":"Analyze","questions":[],"context":{}}',
        task_name="Analyze",
        timeout_at=timeout_at,
    )


@pytest.mark.asyncio
async def test_timeout_sweep_auto_aborts_expired(repo: Repository) -> None:
    decisions = DecisionRegistry()
    # A pause that expires 60 min from now.
    decision_id = await _seed_pause(repo, issue_num=21, timeout_at=compute_timeout_at(minutes=60))

    # Fast-forward now() past timeout_at — a single timeout transition fires.
    far_future = datetime.now(UTC) + timedelta(hours=2)
    result = await sweep_expired_pauses(
        repository=repo, decisions=decisions, now=lambda: far_future
    )
    assert result.expired == 1
    assert result.resolved == 1

    row = await repo.get_pause_decision(decision_id)
    assert row is not None
    assert row["status"] == "answered"
    assert row["resolved_by"] == "timeout"


@pytest.mark.asyncio
async def test_timeout_sweep_leaves_unexpired_pending(repo: Repository) -> None:
    decisions = DecisionRegistry()
    decision_id = await _seed_pause(repo, issue_num=22, timeout_at=compute_timeout_at(minutes=60))

    # now() BEFORE the deadline → nothing expires.
    result = await sweep_expired_pauses(repository=repo, decisions=decisions, now=datetime.now)
    # The just-created pause expires in ~60 min, so the current sweep finds none.
    assert result.resolved == 0
    row = await repo.get_pause_decision(decision_id)
    assert row is not None
    assert row["status"] == "pending"


@pytest.mark.asyncio
async def test_timeout_sweep_skips_already_answered(repo: Repository) -> None:
    """A human-answered pause is not re-resolved by a later expiry sweep (guard)."""
    decisions = DecisionRegistry()
    decision_id = await _seed_pause(repo, issue_num=23, timeout_at=compute_timeout_at(minutes=60))

    # Human resolves first.
    won = await resolve_pending_pause(
        repository=repo,
        decisions=decisions,
        decision_id=decision_id,
        answers={"q": "v"},
        skip_remaining=False,
        resolved_by="human",
    )
    assert won

    # A later sweep (now well past the deadline) finds no pending row to resolve.
    far_future = datetime.now(UTC) + timedelta(hours=2)
    result = await sweep_expired_pauses(
        repository=repo, decisions=decisions, now=lambda: far_future
    )
    assert result.resolved == 0

    row = await repo.get_pause_decision(decision_id)
    assert row is not None
    assert row["resolved_by"] == "human"  # the human's resolution stands
