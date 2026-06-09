"""Slice 2.5 — the ``on_pause`` bridge (AC-18 / INV-9 / §8.5).

Exercises the durable HITL bridge directly over a migrated SQLite DB + a fake
GitHub client + a real :class:`WriteQueue` / :class:`StreamRegistry` /
:class:`DecisionRegistry` / :class:`ConcurrencySlots` (no Docker, no engine —
INV-13). Asserts the §8.5 step-1 side effects fire when the engine ``await``\\s
the bridge at a pause point:

* a ``pause_decisions`` row is written ``status='pending'`` with the request
  payload + a UTC ``timeout_at``;
* the issue moves to ``agent:paused`` via the write-queue (INV-11 replace-all);
* the run's concurrency **slot is released** while parked (T086) and
  **re-acquired** on resume;
* a ``pause_requested`` event is enqueued on the run's stream hub (SSE);
* the bridge **awaits** the keyed event and resolves only when fired (INV-9);
* the resumed :class:`PauseResponse` carries the chosen answers + ``skip_remaining``.

No copy in the bridge over-claims in-place resume (the AC-18 grep asserts that
repo-wide).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import pytest_asyncio
from app.db import Repository
from app.github.client import GitHubClient, Repo, WritePermission
from app.github.write_queue import WriteQueue
from app.hitl import ConcurrencySlots, DecisionRegistry, build_pause_bridge
from app.hitl.answer import resolve_pending_pause
from app.hitl.pause_bridge import PauseBridgeDeps
from app.sse.observer_bridge import StreamRegistry
from dkmv.tasks.pause import PauseQuestion, PauseRequest


class _FakeClient(GitHubClient):
    """GitHub client recording each ``agent:*`` replace-all PUT (INV-11)."""

    def __init__(self) -> None:
        self.replace_calls: list[tuple[str, int, list[str]]] = []

    async def list_repos(self) -> list[Repo]:  # pragma: no cover - unused
        return []

    async def check_write_permission(self, repo: str) -> WritePermission:  # pragma: no cover
        return WritePermission(repo=repo, can_write=True, role="write")

    async def graphql(  # pragma: no cover - unused
        self, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        return {"data": {}}

    async def replace_labels(self, repo: str, num: int, labels: Any) -> list[str]:
        self.replace_calls.append((repo, num, list(labels)))
        return list(labels)


@pytest_asyncio.fixture
async def write_queue() -> WriteQueue:
    """A started write-queue with a generous rate so the label PUT runs promptly."""
    return WriteQueue(rate_per_minute=600)


def _pause_request() -> PauseRequest:
    """A plan-style pause: one question, engine ``{value,label,description?}`` options."""
    return PauseRequest(
        task_name="Analyze",
        questions=[
            PauseQuestion(
                id="phases",
                question="How would you like to proceed?",
                options=[
                    {"value": "all", "label": "Proceed with all 4 phases", "description": "Keep"},
                    {"value": "merge34", "label": "Merge phases 3 & 4"},
                ],
                default="all",
            )
        ],
        context={"summary": "I found 4 candidate phases."},
    )


async def _seed_run(repo: Repository, *, issue_num: int = 7) -> str:
    """Claim a run row so the FK from ``pause_decisions`` resolves; return its id."""
    run_id, won = await repo.claim_run(
        idempotency_key=f"{issue_num}::qa::main",
        repo="o/r",
        issue_num=issue_num,
        workflow_id="qa",
        agent="claude",
        branch="dkmv/issue-7",
        feature_name="issue-7",
    )
    assert won
    return run_id


def _deps(
    *,
    run_id: str,
    issue_num: int,
    repository: Repository,
    client: _FakeClient,
    wq: WriteQueue,
    registry: StreamRegistry,
    decisions: DecisionRegistry,
    slots: ConcurrencySlots,
) -> PauseBridgeDeps:
    return PauseBridgeDeps(
        run_id=run_id,
        repo="o/r",
        issue_num=issue_num,
        repository=repository,
        github_client=client,
        write_queue=wq,
        stream_registry=registry,
        decisions=decisions,
        slots=slots,
        cache=None,
        current_labels=("bug",),
    )


async def _await_parked(repo: Repository, decisions: DecisionRegistry, run_id: str) -> None:
    """Spin until the bridge has written the pending row + registered its waiter."""
    for _ in range(50):
        pending = await repo.read_pending_pause(run_id)
        if pending is not None and decisions.pending_count() == 1:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("pause bridge never reached its await")


@pytest.mark.asyncio
async def test_pause_bridge_side_effects_and_resume(
    repo: Repository, write_queue: WriteQueue
) -> None:
    run_id = await _seed_run(repo)
    client = _FakeClient()
    registry = StreamRegistry()
    hub = registry.get_or_create(run_id)
    decisions = DecisionRegistry()
    slots = ConcurrencySlots()
    slots.acquire()  # the launched run holds one slot
    assert slots.held == 1

    deps = _deps(
        run_id=run_id,
        issue_num=7,
        repository=repo,
        client=client,
        wq=write_queue,
        registry=registry,
        decisions=decisions,
        slots=slots,
    )
    bridge = build_pause_bridge(deps)

    # Drive the engine's on_pause callback as a background task; it parks on the
    # keyed event after performing the step-1 side effects.
    pause_task = asyncio.ensure_future(bridge(_pause_request()))
    await _await_parked(repo, decisions, run_id)

    # ── durable decision row (status=pending, UTC timeout_at, request payload) ──
    pending = await repo.read_pending_pause(run_id)
    assert pending is not None
    assert pending["status"] == "pending"
    assert pending["task_name"] == "Analyze"
    assert pending["timeout_at"] is not None and pending["timeout_at"].endswith("+00:00")
    assert "candidate phases" in pending["request_json"]

    # ── issue moved to agent:paused via the write-queue (INV-11 replace-all) ────
    assert client.replace_calls, "expected an agent:paused replace-all PUT"
    _, num, labels = client.replace_calls[-1]
    assert num == 7
    assert "agent:paused" in labels
    assert "bug" in labels  # non-agent labels preserved

    # ── the slot was released while parked (T086) ──────────────────────────────
    assert slots.held == 0

    # ── pause_requested event enqueued on the run's stream hub (SSE) ────────────
    event = await asyncio.wait_for(hub.queue.get(), timeout=1.0)
    assert event.event_type == "pause_requested"
    assert event.data["decision_id"] == pending["id"]

    # ── still parked: no PauseResponse yet ─────────────────────────────────────
    assert not pause_task.done()

    # ── resolve exactly-once → fires the keyed event → engine resumes ──────────
    won = await resolve_pending_pause(
        repository=repo,
        decisions=decisions,
        decision_id=str(pending["id"]),
        answers={"phases": "merge34"},
        skip_remaining=False,
        resolved_by="human",
    )
    assert won

    response = await asyncio.wait_for(pause_task, timeout=1.0)
    assert response.answers == {"phases": "merge34"}
    assert response.skip_remaining is False

    # ── slot re-acquired on resume ─────────────────────────────────────────────
    assert slots.held == 1

    # ── decision event emitted with the human-readable label ───────────────────
    decision_event = await asyncio.wait_for(hub.queue.get(), timeout=1.0)
    assert decision_event.event_type == "decision"
    assert "Merge phases 3 & 4" in decision_event.content

    await write_queue.stop(grace=0.5)


@pytest.mark.asyncio
async def test_pause_bridge_skip_remaining_response(
    repo: Repository, write_queue: WriteQueue
) -> None:
    """Ship-as-is / Abort → the resumed PauseResponse carries ``skip_remaining``."""
    run_id = await _seed_run(repo, issue_num=8)
    client = _FakeClient()
    registry = StreamRegistry()
    registry.get_or_create(run_id)
    decisions = DecisionRegistry()
    slots = ConcurrencySlots()
    deps = _deps(
        run_id=run_id,
        issue_num=8,
        repository=repo,
        client=client,
        wq=write_queue,
        registry=registry,
        decisions=decisions,
        slots=slots,
    )
    bridge = build_pause_bridge(deps)
    pause_task = asyncio.ensure_future(bridge(_pause_request()))
    await _await_parked(repo, decisions, run_id)

    pending = await repo.read_pending_pause(run_id)
    assert pending is not None
    won = await resolve_pending_pause(
        repository=repo,
        decisions=decisions,
        decision_id=str(pending["id"]),
        answers={},
        skip_remaining=True,
        resolved_by="human",
    )
    assert won
    response = await asyncio.wait_for(pause_task, timeout=1.0)
    assert response.skip_remaining is True
    await write_queue.stop(grace=0.5)
