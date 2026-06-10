"""Compose the :class:`RetryScheduler` from ``app.state`` (slice 3.4 seam).

The retry scheduler needs three things: the single-writer :class:`Repository`
(its persisted state, INV-6), the GitHub client (the existing-PR detection seam,
INV-5/R-15), and a ``redispatch`` callable that routes a run **through the
existing :func:`app.runs.launch.launch_run` boundary** (ADR-P001 — there is
exactly ONE launch path; the retry path introduces no second dispatch mechanism).

This module is the small composition seam (kept out of ``retry.py`` so the
scheduler stays pure + test-injectable, and out of ``runs_retry.py`` so the API
file is just the endpoint). It builds the ``redispatch`` closure that reconstructs
the §8.4 :class:`~app.runs.launch.LaunchRequest` from the **existing ``runs`` row**
(same issue/workflow/branch → the same ``idempotency_key``, so the claim-lock
**reuses** the row, INV-5) and re-launches with ``start_task=<last completed
stage>``. Nothing here touches ``dkmv/``; re-dispatch is the in-process launch
boundary, never the CLI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.db.repository import Repository
from app.orchestrator.retry import RetryScheduler

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import Request
    from starlette.applications import Starlette

    from app.github.client import GitHubClient
    from app.github.graphql import BoardPage
    from app.github.hash_cache import HashCache
    from app.github.write_queue import WriteQueue
    from app.runtime import RunService

#: ``app.state`` attribute name for the process-wide retry scheduler (one per app).
RETRY_SCHEDULER_ATTR = "retry_scheduler"


def build_retry_scheduler(app: Starlette) -> RetryScheduler:
    """Compose the process-wide :class:`RetryScheduler` from ``app.state``.

    Resolves the lifespan-owned singletons (the single-writer :class:`Repository`,
    the GitHub client + serialized :class:`WriteQueue` + board cache, the engine
    :class:`RunService`) and binds a ``redispatch`` closure that re-launches a run
    through the **existing** ``launch_run`` boundary (ADR-P001). The scheduler is
    cached on ``app.state`` so the tick (firing due backoffs), ``POST
    /runs/{id}/retry`` (enqueuing), and ``GET /retry-queue`` (projecting) all share
    **one** instance over **one** persisted state.
    """
    state = app.state
    repository: Repository = state.repository
    github_client: GitHubClient | None = getattr(state, "github_client", None)

    async def _redispatch(row: dict[str, Any], start_task: str | None) -> str | None:
        """Re-launch ``row`` via ``launch_run`` (same row, INV-5) — ADR-P001.

        Reconstructs the §8.4 launch request from the existing run row so the
        ``idempotency_key`` (issue+workflow+branch) is **identical** — the claim-lock
        reuses the same ``runs`` row rather than claiming a second. Re-launches with
        ``start_task`` so the engine resumes from the last pushed stage. Returns the
        platform run id iff a fresh dispatch happened, else ``None`` (the claim-lock
        reused the row — INV-5 — or it was rejected; the tick treats either as "no
        new dispatch").
        """
        from app.api.deps import project_root_from_state
        from app.runs.launch import LaunchRequest, duplicate_dispatch, launch_run
        from app.runs.service import DEFAULT_MEMORY
        from app.sse.run_stream import LifecycleDeps, attach_run_stream

        write_queue: WriteQueue = state.github_write_queue
        run_service: RunService = state.run_service
        cache: HashCache[BoardPage] | None = getattr(state, "github_hash_cache", None)
        # The lifespan-published local project root (slice 4.2 / DKMV_PROJECT_ROOT),
        # read through the canonical deps.py seam exactly like the tick + POST /runs
        # (FIX-2). Threading it in lets a RETRIED run whose ``workflow_id`` is a
        # registry NAME (a registered on-disk custom component) resolve the same way
        # its first dispatch did — a retry is equivalent to first dispatch (AC-8 /
        # FIX-1). ``None`` when no local root is configured (built-ins / absolute
        # paths only) — the prior hardcoded ``None`` silently broke the NAME path.
        project_root = project_root_from_state(state)
        registry = state.stream_registry
        stream_tasks = getattr(state, "run_stream_tasks", None)
        if stream_tasks is None:
            stream_tasks = set()
            state.run_stream_tasks = stream_tasks

        lifecycle = (
            LifecycleDeps(github_client=github_client, write_queue=write_queue, cache=cache)
            if github_client is not None
            else None
        )

        def _attach_stream(run_id: str, handle: Any) -> None:
            attach_run_stream(
                run_id=run_id,
                handle=handle,
                registry=registry,
                repository=repository,
                tasks=stream_tasks,
                lifecycle=lifecycle,
            )

        issue_num = row.get("issue_num")
        repo = str(row.get("repo") or "")
        workflow_id = str(row.get("workflow_id") or "")
        branch = str(row.get("branch") or "")
        default_feature = f"issue-{issue_num}" if issue_num else "retry"
        feature_name = str(row.get("feature_name") or default_feature)
        # Re-populate the original cost-governance caps from the stored ``runs``
        # row (FIX-5.2 / INV-8). The launch path persisted ``max_budget_usd`` /
        # ``max_turns`` / ``timeout_minutes`` at ``claim_run`` (the §8.9 config
        # block source); a retry MUST carry them forward so a RETRIED Claude run
        # keeps the SAME hard budget/turn cap its first dispatch enforced — without
        # this the row's enforced caps were silently dropped and the retry ran with
        # only the default timeout (a cost-governance escape). The capability layer
        # still runs inside ``launch_run``: ``resolve_enforced_caps`` force-drops
        # budget/turns to ``None`` for a Codex agent, so threading them here is safe
        # for Codex (no smuggle on retry) and correct for Claude (caps preserved) —
        # a retry is equivalent to the first dispatch.
        stored_max_budget_usd = row.get("max_budget_usd")
        stored_max_turns = row.get("max_turns")
        stored_timeout_minutes = row.get("timeout_minutes")
        req = LaunchRequest(
            issue_num=int(issue_num) if issue_num is not None else 0,
            repo=repo,
            workflow_id=workflow_id,
            agent=str(row.get("agent") or "auto"),
            branch=branch,
            feature_name=feature_name,
            model=row.get("model"),
            max_turns=int(stored_max_turns) if stored_max_turns is not None else None,
            timeout_minutes=(
                int(stored_timeout_minutes) if stored_timeout_minutes is not None else None
            ),
            max_budget_usd=(
                float(stored_max_budget_usd) if stored_max_budget_usd is not None else None
            ),
            memory=row.get("memory_limit") or DEFAULT_MEMORY,
            start_task=start_task,
        )
        try:
            result = await launch_run(
                req,
                repository=repository,
                run_service=run_service,
                github_client=github_client,  # type: ignore[arg-type]  # DKMVP-ESCAPE: client is present in production; None only in a bare test that injects its own redispatch
                write_queue=write_queue,
                cache=cache,
                connected_repo=repo,
                project_root=project_root,
                default_memory=DEFAULT_MEMORY,
                current_labels=[],
                attach_stream=_attach_stream,
            )
        except type(duplicate_dispatch("")):
            # The claim-lock reused the existing row (INV-5) — no second dispatch.
            return None
        return result.run_id

    scheduler = RetryScheduler(
        repository=repository,
        redispatch=_redispatch,
        github_client=github_client,
    )
    setattr(state, RETRY_SCHEDULER_ATTR, scheduler)
    return scheduler


def get_retry_scheduler(request: Request) -> RetryScheduler:
    """Return (composing on first use) the process-wide :class:`RetryScheduler`.

    The serving path (``POST /runs/{id}/retry``, ``GET /retry-queue``) resolves the
    one scheduler from ``app.state`` so it shares the same persisted state the tick
    fires from. A test that injected its own scheduler on ``app.state`` is returned
    it verbatim; otherwise one is composed via :func:`build_retry_scheduler` and
    cached. (The scheduler's state lives in the DB, so a freshly-composed instance
    sees the same queue.)
    """
    existing = getattr(request.app.state, RETRY_SCHEDULER_ATTR, None)
    if isinstance(existing, RetryScheduler):
        return existing
    return build_retry_scheduler(request.app)
