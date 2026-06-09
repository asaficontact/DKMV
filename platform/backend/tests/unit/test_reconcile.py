"""Orchestrator reconciliation (slice 3.3 — AC-11, AC-12, INV-11 binding).

Covers the three §8.2 reconcile responsibilities against a real migrated SQLite
DB (the ``repo`` fixture), with a fake :class:`RunKiller` recording container
kills and a fake GitHub client + write-queue recording label PUTs:

* **AC-12 stall detection:** a run with no events for ``STALL_TIMEOUT_S`` (a
  frozen clock past the cutoff) is killed (container stopped) + a stall signal
  emitted. A fresh run is left alone.
* **AC-11 authority rule (INV-11):** a running issue with a stray human label edit
  → the DB row wins (NO board write); a human terminal move (issue → Done) → the
  run is stopped and the label cleared via ``set_agent_state`` on the write-queue.
* **AC-12 orphan sweep:** a container under a terminal run row is killed.

INV-11 is asserted structurally: every label change goes through the write-queue
(the fake records the submitted mutation), there is no direct GitHub mutation, and
only the replace-all labels PUT is ever constructed (never the fictional
single-label patch endpoint).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.config import Settings
from app.db.repository import EventRecord, Repository
from app.orchestrator import reconcile
from app.orchestrator.reconcile import ReconcileDeps

pytestmark = pytest.mark.asyncio

_REPO = "octo/widgets"
_BASE = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _clock(seconds: float) -> Any:
    def _now() -> datetime:
        return _BASE + timedelta(seconds=seconds)

    return _now


class _FakeKiller:
    """Records the runs it was asked to kill; reports a container was stopped."""

    def __init__(self, *, alive_engine_ids: set[str] | None = None) -> None:
        self.killed: list[str] = []
        # Which runs have a live container (resolve True). Default: any run with an
        # engine_run_id is considered live in this process.
        self._alive = alive_engine_ids

    async def kill(self, run_row: dict[str, Any]) -> bool:
        engine_id = run_row.get("engine_run_id")
        if not engine_id:
            return False
        if self._alive is not None and str(engine_id) not in self._alive:
            return False
        self.killed.append(str(run_row["id"]))
        return True


class _FakeGitHubClient:
    """Records ``replace_labels`` (the replace-all PUT) — the only mutation path."""

    def __init__(self) -> None:
        self.replace_calls: list[tuple[str, int, list[str]]] = []

    async def replace_labels(self, repo: str, num: int, labels: list[str]) -> list[str]:
        self.replace_calls.append((repo, num, list(labels)))
        return list(labels)


class _PassthroughWriteQueue:
    """A write-queue stand-in that runs the submitted mutation inline.

    Records that the label change was routed THROUGH the queue (INV-11) — reconcile
    must never call GitHub directly.
    """

    def __init__(self) -> None:
        self.submitted: list[str] = []

    async def submit(self, factory: Any, *, label: str = "mutation") -> Any:
        self.submitted.append(label)
        return await factory()


async def _seed_run(
    repository: Repository,
    *,
    run_id: str,
    issue_num: int,
    status: str,
    engine_run_id: str | None = None,
) -> None:
    await repository.claim_run(
        idempotency_key=f"{issue_num}::wf::main",
        repo=_REPO,
        issue_num=issue_num,
        workflow_id="wf",
        agent="claude",
        branch="main",
        run_id=run_id,
    )
    fields: dict[str, Any] = {"status": status}
    if engine_run_id is not None:
        fields["engine_run_id"] = engine_run_id
    await repository.update_run_fields(run_id, **fields)


def _deps(
    repository: Repository,
    killer: Any,
    *,
    client: Any | None = None,
    queue: Any | None = None,
    now_seconds: float = 0.0,
) -> ReconcileDeps:
    return ReconcileDeps(
        repository=repository,
        github_client=client or _FakeGitHubClient(),  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed test client
        write_queue=queue or _PassthroughWriteQueue(),  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed test queue
        killer=killer,
        settings=Settings(_env_file=None, STALL_TIMEOUT_S=300),  # type: ignore[call-arg]  # DKMVP-ESCAPE: pydantic-settings kwargs
        cache=None,
        now=_clock(now_seconds),
    )


# ── AC-12: stall detection ────────────────────────────────────────────────────


async def test_stall_detection_with_frozen_clock(repo: Repository) -> None:
    await _seed_run(repo, run_id="r-stall", issue_num=1, status="running", engine_run_id="eng-1")
    # Event ts at base; clock advanced 400s (> 300 cutoff) → stalled.
    await repo.append_events(
        [
            EventRecord(
                run_id="r-stall",
                sequence=1,
                event_type="task_progress",
                payload={},
                ts=_BASE.isoformat(),
            )
        ]
    )
    killer = _FakeKiller()
    result = await reconcile.detect_stalls(_deps(repo, killer, now_seconds=400), _REPO)

    assert killer.killed == ["r-stall"]  # container killed (stopped), not bare-cancel
    assert len(result) == 1
    assert result[0].reason == reconcile.STALL_REASON
    assert result[0].container_killed is True


async def test_fresh_run_is_not_stalled(repo: Repository) -> None:
    await _seed_run(repo, run_id="r-fresh", issue_num=2, status="running", engine_run_id="eng-2")
    await repo.append_events(
        [
            EventRecord(
                run_id="r-fresh",
                sequence=1,
                event_type="task_progress",
                payload={},
                ts=_BASE.isoformat(),
            )
        ]
    )
    killer = _FakeKiller()
    # Only 100s elapsed (< 300 cutoff) → not stalled.
    result = await reconcile.detect_stalls(_deps(repo, killer, now_seconds=100), _REPO)
    assert killer.killed == []
    assert result == []


# ── AC-11 / INV-11: authority rule ────────────────────────────────────────────


async def test_authority_rule_db_row_wins_over_stray_label_edit(repo: Repository) -> None:
    """A running issue with a stray human label edit → DB row wins, board unchanged."""
    await _seed_run(repo, run_id="r-live", issue_num=10, status="running", engine_run_id="eng-10")
    # The board cache reflects a stray human edit (agent:queued) but the issue is
    # NOT closed (state != done) — the active-run DB row is authoritative.
    await repo.upsert_issue(
        repo=_REPO,
        num=10,
        title="live",
        state="in_progress",
        labels=["agent:queued"],
        workflow_id="wf",
    )
    killer = _FakeKiller()
    client = _FakeGitHubClient()
    queue = _PassthroughWriteQueue()
    result = await reconcile.refresh_labels(_deps(repo, killer, client=client, queue=queue), _REPO)

    assert result.writes == 0  # DB row wins → NO board write
    assert client.replace_calls == []  # no GitHub mutation at all
    assert queue.submitted == []
    assert killer.killed == []  # run is not stopped


async def test_human_terminal_move_stops_run_and_clears_label(repo: Repository) -> None:
    """A human moved a running issue to Done → stop the run, clear the label via queue."""
    await _seed_run(repo, run_id="r-term", issue_num=11, status="running", engine_run_id="eng-11")
    # The human closed the issue (state derived to 'done') while it had agent:in-progress.
    await repo.upsert_issue(
        repo=_REPO,
        num=11,
        title="closed",
        state="done",
        labels=["agent:in-progress"],
        workflow_id="wf",
    )
    killer = _FakeKiller()
    client = _FakeGitHubClient()
    queue = _PassthroughWriteQueue()
    result = await reconcile.refresh_labels(_deps(repo, killer, client=client, queue=queue), _REPO)

    assert result.terminal_stops == 1
    assert killer.killed == ["r-term"]  # the live run's container is stopped
    # The run row was marked cancelled (terminal).
    row = await repo.get_run("r-term")
    assert row is not None and row["status"] == "cancelled"
    # The stale agent:* label was cleared via the write-queue (INV-11) — a
    # replace-all PUT to Backlog (no agent:* label remains), never PATCH.
    assert result.writes == 1
    assert queue.submitted  # routed THROUGH the queue, not a direct GitHub call
    assert len(client.replace_calls) == 1
    _, num, labels = client.replace_calls[0]
    assert num == 11
    assert not any(name.startswith("agent:") for name in labels)


# ── AC-12: orphan-container sweep ─────────────────────────────────────────────


async def test_orphan_sweep_kills_terminal_run_container(repo: Repository) -> None:
    # A completed run whose container lingered (still has an engine_run_id).
    await _seed_run(
        repo, run_id="r-orphan", issue_num=20, status="completed", engine_run_id="eng-20"
    )
    killer = _FakeKiller()
    result = await reconcile.sweep_orphans(_deps(repo, killer), _REPO)

    assert killer.killed == ["r-orphan"]
    assert len(result) == 1
    assert result[0].reason == reconcile.ORPHAN_REASON
    assert result[0].container_killed is True


async def test_orphan_sweep_skips_run_with_no_live_container(repo: Repository) -> None:
    # A terminal run started by a now-dead process: no live handle → killer returns
    # False (we never re-attach — INV-10; that orphan is 3.5's boot docker kill).
    await _seed_run(repo, run_id="r-dead", issue_num=21, status="failed", engine_run_id="eng-21")
    killer = _FakeKiller(alive_engine_ids=set())  # nothing alive in this process
    result = await reconcile.sweep_orphans(_deps(repo, killer), _REPO)
    assert killer.killed == []
    assert result == []


async def test_reconcile_once_aggregates_all_three(repo: Repository) -> None:
    # One stalled active run + one orphan terminal run.
    await _seed_run(repo, run_id="r-a", issue_num=30, status="running", engine_run_id="eng-30")
    await repo.append_events(
        [
            EventRecord(
                run_id="r-a",
                sequence=1,
                event_type="task_progress",
                payload={},
                ts=_BASE.isoformat(),
            )
        ]
    )
    await _seed_run(repo, run_id="r-b", issue_num=31, status="completed", engine_run_id="eng-31")
    killer = _FakeKiller()
    result = await reconcile.reconcile_once(_deps(repo, killer, now_seconds=400), _REPO)
    assert len(result.stalled) == 1
    assert len(result.orphans) == 1
    assert {s.run_id for s in result.signals} == {"r-a", "r-b"}
