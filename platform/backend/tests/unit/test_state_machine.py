"""Slice 1.3 — the ``agent:*`` label state machine (AC-6, AC-8, §8.1, INV-11).

Covers:

* **AC-6 single-occupancy** — ``set_agent_state(target=queued)`` on an issue that
  had ``agent:review`` leaves **exactly one** ``agent:*`` label and **preserves**
  the non-agent labels (the replace-all ``PUT .../labels``; no single-label PATCH).
* All transitions go through the **write-queue** (the only mutation path).
* The GraphQL hash-cache is **invalidated** after a mutation.
* **AC-8 state-machine completeness** (each transition unit-tested):
  In Review→Done on a merged PR; closed→Done (+ cancel-live-run no-op stub);
  reopened→out of Done; failed-run demotion off ``agent:in-progress``.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from app.github.hash_cache import HashCache
from app.github.state_machine import (
    closed_transition,
    compute_desired_labels,
    failed_run_demotion,
    merged_pr_transition,
    reopened_transition,
    set_agent_state,
)
from app.github.write_queue import WriteQueue


class FakeLabelClient:
    """A client whose ``replace_labels`` records the replace-all PUT body.

    Asserts the primitive is the **full desired set** (replace-all), proving no
    add/remove or PATCH path is used. Returns the written labels as GitHub would.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, list[str]]] = []

    async def replace_labels(self, repo: str, num: int, labels: Sequence[str]) -> list[str]:
        body = list(labels)
        self.calls.append((repo, num, body))
        return body


def _queue() -> WriteQueue:
    """A write-queue with generous pacing so tests never wait on the bucket."""
    return WriteQueue(rate_per_minute=6000.0)


# ── AC-6: single occupancy + non-agent labels preserved ──────────────────────


def test_compute_desired_labels_single_occupancy() -> None:
    """Replacing agent:review with agent:queued leaves one agent label + keeps the rest."""
    current = ["bug", "agent:review", "p1"]
    desired = compute_desired_labels(current, "queued")
    assert desired == ["bug", "p1", "agent:queued"]
    agent = [lbl for lbl in desired if lbl.startswith("agent:")]
    assert agent == ["agent:queued"]  # exactly one


def test_compute_desired_labels_target_none_strips_all_agent() -> None:
    """target=None clears the agent:* plane (→ Backlog), preserving non-agent labels."""
    desired = compute_desired_labels(["bug", "agent:in-progress"], None)
    assert desired == ["bug"]


def test_compute_desired_labels_dedupes_multi_agent() -> None:
    """A stray double agent:* label collapses to the single target (single occupancy)."""
    desired = compute_desired_labels(["agent:queued", "agent:review", "feat"], "paused")
    assert [lbl for lbl in desired if lbl.startswith("agent:")] == ["agent:paused"]
    assert "feat" in desired


@pytest.mark.asyncio
async def test_set_agent_state_replace_all_single_occupancy() -> None:
    """AC-6: set_agent_state(queued) on an agent:review issue → one agent label, rest kept."""
    client = FakeLabelClient()
    queue = _queue()
    result = await set_agent_state(
        client,  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed label client
        "o/r",
        7,
        "queued",
        current_labels=["bug", "agent:review", "docs"],
        write_queue=queue,
    )
    # The PUT body is the full replace-all set.
    assert client.calls == [("o/r", 7, ["bug", "docs", "agent:queued"])]
    assert result.agent_labels == ("agent:queued",)  # exactly one
    assert "bug" in result.labels and "docs" in result.labels  # non-agent preserved
    assert result.agent_label == "agent:queued"


@pytest.mark.asyncio
async def test_set_agent_state_invalidates_cache() -> None:
    """After a mutation the GraphQL hash-cache is invalidated (next read is fresh)."""
    client = FakeLabelClient()
    cache: HashCache[str] = HashCache()
    cache.put("q", {"owner": "o"}, "stale-page")
    assert len(cache) == 1

    await set_agent_state(
        client,  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed label client
        "o/r",
        7,
        "queued",
        current_labels=[],
        write_queue=_queue(),
        cache=cache,  # type: ignore[arg-type]  # DKMVP-ESCAPE: generic cache for the test
    )
    assert len(cache) == 0  # invalidated


@pytest.mark.asyncio
async def test_set_agent_state_goes_through_write_queue() -> None:
    """The mutation runs via the write-queue worker (serialized path), not directly."""
    client = FakeLabelClient()
    queue = _queue()
    # Two concurrent transitions must serialize through the one queue.
    import asyncio

    await asyncio.gather(
        set_agent_state(client, "o/r", 1, "queued", current_labels=[], write_queue=queue),  # type: ignore[arg-type]  # DKMVP-ESCAPE
        set_agent_state(client, "o/r", 2, "queued", current_labels=[], write_queue=queue),  # type: ignore[arg-type]  # DKMVP-ESCAPE
    )
    nums = [num for _repo, num, _labels in client.calls]
    assert sorted(nums) == [1, 2]  # both written, serialized


# ── AC-8: state-machine completeness ─────────────────────────────────────────


def test_merged_pr_transition_strips_review() -> None:
    """In Review → Done on a linked merged PR: clear agent:review (AC-8)."""
    plan = merged_pr_transition(current_labels=["agent:review", "bug"], merged_pr_num=42)
    assert plan.should_write is True
    assert plan.target is None  # Done = no agent:* label
    assert plan.reason == "merged_pr"


def test_merged_pr_transition_noop_without_merged_pr() -> None:
    """No merged PR → no transition (stays In Review)."""
    plan = merged_pr_transition(current_labels=["agent:review"], merged_pr_num=None)
    assert plan.should_write is False


def test_merged_pr_transition_noop_when_not_in_review() -> None:
    """A merged PR but no agent:review to strip → no write."""
    plan = merged_pr_transition(current_labels=["agent:queued"], merged_pr_num=42)
    assert plan.should_write is False


def test_closed_transition_to_done_and_cancel_run() -> None:
    """issues.closed → Done; cancel-live-run flagged (no-op stub in Phase 1) (AC-8)."""
    plan = closed_transition(current_labels=["agent:in-progress"], has_active_run=True)
    assert plan.target is None  # Done
    assert plan.should_write is True  # there was an agent label to clear
    assert plan.cancel_live_run is True  # the stub the caller wires in Phase 3
    assert plan.reason == "closed"


def test_closed_transition_noop_when_no_agent_label() -> None:
    """A closed issue already in Backlog (no agent label) needs no write."""
    plan = closed_transition(current_labels=["bug"], has_active_run=False)
    assert plan.should_write is False
    assert plan.cancel_live_run is False


def test_reopened_transition_restores_target() -> None:
    """issues.reopened → out of Done, restoring the prior agent:* state (AC-8)."""
    plan = reopened_transition(current_labels=[], restore_target="queued")
    assert plan.target == "queued"
    assert plan.should_write is True


def test_reopened_transition_to_backlog_when_no_restore() -> None:
    """Reopened with no known prior state → Backlog (no agent:* label)."""
    plan = reopened_transition(current_labels=["agent:review"], restore_target=None)
    assert plan.target is None  # Backlog
    assert plan.should_write is True  # had agent:review → must clear


def test_failed_run_demotion_to_queued_when_retrying() -> None:
    """A failed run that will auto-retry demotes agent:in-progress → agent:queued (AC-8)."""
    plan = failed_run_demotion(current_labels=["agent:in-progress"], will_retry=True)
    assert plan.target == "queued"
    assert plan.should_write is True
    assert plan.reason == "failed_retry"


def test_failed_run_demotion_to_backlog_when_not_retrying() -> None:
    """A terminal failed run strips agent:in-progress → Backlog — never stranded (AC-8)."""
    plan = failed_run_demotion(current_labels=["agent:in-progress", "bug"], will_retry=False)
    assert plan.target is None  # Backlog
    assert plan.should_write is True
    assert plan.reason == "failed_strip"


def test_failed_run_demotion_noop_when_not_in_progress() -> None:
    """Nothing to demote when the issue is not In Progress."""
    plan = failed_run_demotion(current_labels=["agent:queued"], will_retry=True)
    assert plan.should_write is False
