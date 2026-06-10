"""Slice 3.4 — retry scheduler edge paths + the ``retry_deps`` composition seam.

Covers the manual-enqueue idempotency at the scheduler level, ``has_pending_retry``,
``clear``, the parked→manual-revive path, the redispatch run-gone / reused-row /
PR-detection-error degradations, and that :func:`build_retry_scheduler` /
:func:`get_retry_scheduler` compose + cache one scheduler on ``app.state``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.db.repository import Repository
from app.orchestrator.retry import MAX_ATTEMPTS, RedispatchOutcome, RetryScheduler
from app.orchestrator.retry_deps import build_retry_scheduler, get_retry_scheduler

pytestmark = pytest.mark.asyncio

_BASE = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _clock(seconds: float = 0.0) -> Any:
    def _now() -> datetime:
        return _BASE + timedelta(seconds=seconds)

    return _now


class _Redispatch:
    def __init__(self, return_value: str | None = "redispatched") -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.return_value = return_value

    async def __call__(self, row: dict[str, Any], start_task: str | None) -> str | None:
        self.calls.append((str(row["id"]), start_task))
        return self.return_value


async def _seed_run(repo: Repository, *, issue_num: int, status: str = "failed") -> str:
    run_id, _ = await repo.claim_run(
        idempotency_key=f"{issue_num}::qa::main",
        repo="octo/widgets",
        issue_num=issue_num,
        workflow_id="qa",
        agent="claude",
        branch="dkmv/issue-feature",
    )
    await repo.update_run_fields(run_id, status=status)
    return run_id


async def test_enqueue_manual_idempotent_and_has_pending(repo: Repository) -> None:
    run_id = await _seed_run(repo, issue_num=71)
    sched = RetryScheduler(repository=repo, redispatch=_Redispatch(), now=_clock())

    first = await sched.enqueue_manual(run_id, issue_num=71)
    assert first.attempt == 1
    assert await sched.has_pending_retry(run_id) is True

    # Second enqueue while pending → no-op (same attempt, one queue entry).
    second = await sched.enqueue_manual(run_id)
    assert second.attempt == 1
    assert len(await sched.read_retry_queue()) == 1


async def test_enqueue_manual_revives_parked_run(repo: Repository) -> None:
    run_id = await _seed_run(repo, issue_num=72)
    sched = RetryScheduler(repository=repo, redispatch=_Redispatch(), now=_clock())
    # Exhaust the automatic attempts → parked.
    for _ in range(MAX_ATTEMPTS + 1):
        await sched.schedule(run_id, issue_num=72, error="boom")
    parked = await sched.read_retry_queue()
    assert parked[0].dueIn == 0  # parked → due now
    assert await sched.has_pending_retry(run_id) is False  # parked is not "pending"

    # A manual Retry now revives it (schedules an immediate re-dispatch).
    revived = await sched.enqueue_manual(run_id)
    assert revived.parked is False
    assert revived.due_at is not None
    assert await sched.has_pending_retry(run_id) is True


async def test_clear_removes_state(repo: Repository) -> None:
    run_id = await _seed_run(repo, issue_num=73)
    sched = RetryScheduler(repository=repo, redispatch=_Redispatch(), now=_clock())
    await sched.schedule(run_id, issue_num=73, error="x")
    assert len(await sched.read_retry_queue()) == 1

    await sched.clear(run_id)
    assert await sched.read_retry_queue() == []


async def test_redispatch_run_gone_is_noop(repo: Repository) -> None:
    sched = RetryScheduler(repository=repo, redispatch=_Redispatch(), now=_clock())
    # A missing run row is a definitive resolution (nothing to dispatch) → SKIPPED.
    assert await sched.redispatch_run("nonexistent") is RedispatchOutcome.SKIPPED


async def test_redispatch_reused_row_returns_skipped(repo: Repository) -> None:
    """A claim-lock reuse (redispatch returns None) is a definitive 'no new dispatch'."""
    run_id = await _seed_run(repo, issue_num=74)
    sched = RetryScheduler(repository=repo, redispatch=_Redispatch(return_value=None), now=_clock())
    assert await sched.redispatch_run(run_id) is RedispatchOutcome.SKIPPED


async def test_pr_detection_error_with_null_pr_num_defers(repo: Repository) -> None:
    """G11 (fail CLOSED): a GitHub detection error + NULL pr_num → DEFER, no re-dispatch.

    The detection cannot tell whether a PR exists, so re-dispatching could open a
    SECOND PR. The guard fails closed (UNKNOWN → DEFER) — the launch is NOT issued
    and the tick re-evaluates next cadence (when GitHub may be reachable).
    """
    run_id = await _seed_run(repo, issue_num=75)  # no DB pr_num

    class _RaisingClient:
        async def find_open_pr_for_branch(self, repo_name: str, branch: str) -> Any:
            raise RuntimeError("github down")

    redispatch = _Redispatch()
    sched = RetryScheduler(
        repository=repo,
        redispatch=redispatch,
        github_client=_RaisingClient(),  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed seam
        now=_clock(),
    )
    assert await sched.redispatch_run(run_id) is RedispatchOutcome.DEFER
    assert redispatch.calls == []  # NOT re-dispatched — no duplicate-PR risk taken


async def test_build_and_get_scheduler_caches_on_app_state(repo: Repository) -> None:
    """build_retry_scheduler composes one scheduler; get_ returns the cached one."""
    app = SimpleNamespace(state=SimpleNamespace(repository=repo, github_client=None))
    built = build_retry_scheduler(app)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed app
    assert isinstance(built, RetryScheduler)

    request = SimpleNamespace(app=app)
    again = get_retry_scheduler(request)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed request
    assert again is built  # cached on app.state, not rebuilt


async def test_redispatch_threads_project_root_from_app_state(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FIX-1: a retry of a registry-NAME run re-dispatches WITH the project_root.

    The ``_redispatch`` closure built by :func:`build_retry_scheduler` must read the
    lifespan-published local project root off ``app.state`` (the canonical deps.py
    seam — FIX-2) and pass it into ``launch_run`` — NOT a hardcoded ``None``. Without
    it a RETRIED run whose ``workflow_id`` is a registered on-disk custom component
    NAME loses project-root resolution, so ``validate_component(name, None)`` /
    ``inspect_component(name, None)`` fail to resolve the NAME and the retry is NOT
    equivalent to its first dispatch (AC-8 custom-component path breaks on retry).
    """
    project_root = Path("/srv/checkout/widgets")
    # The closure reads every singleton off app.state, including project_root (FIX-2).
    state = SimpleNamespace(
        repository=repo,
        github_client=None,
        github_write_queue=object(),
        run_service=object(),
        github_hash_cache=None,
        stream_registry=object(),
        project_root=project_root,
    )
    app = SimpleNamespace(state=state)
    scheduler = build_retry_scheduler(app)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed app

    captured: dict[str, Any] = {}

    async def _fake_launch_run(req: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        captured["workflow_id"] = req.workflow_id
        return SimpleNamespace(run_id="re-1")

    import app.runs.launch as launch_mod

    monkeypatch.setattr(launch_mod, "launch_run", _fake_launch_run)

    # A retried run whose workflow_id is a registry NAME (a registered custom
    # component) — the exact case that breaks when project_root is hardcoded None.
    row = {
        "id": "run-abc",
        "issue_num": 42,
        "repo": "octo/widgets",
        "workflow_id": "my-custom-pipeline",
        "branch": "dkmv/issue-feature",
        "agent": "claude",
    }
    result_run_id = await scheduler.redispatch(row, "qa")  # type: ignore[attr-defined]  # DKMVP-ESCAPE: closure under test

    assert result_run_id == "re-1"
    # The project_root resolved from app.state is threaded through — equivalent to
    # the first dispatch's resolution of the registry NAME (AC-8), not a None.
    assert captured["project_root"] == project_root
    assert captured["workflow_id"] == "my-custom-pipeline"
