"""``POST /runs/{id}/retry`` — enqueue an idempotent retry (slice 3.4 — AC-16).

The manual *Retry now* action the failed-run banner + the retry-queue card drive
(FR-04-7 / FR-06-3). It enqueues a retry for a **failed / interrupted** (or
otherwise terminal-non-success) run and returns ``202`` — the actual idempotent
re-dispatch happens on the next reconcile tick (3.3 → 3.4's
:meth:`app.orchestrator.retry.RetryScheduler.fire_due_retries`), never inline on
the request thread.

Two binding properties:

* **Idempotent endpoint (AC-16).** A second ``POST /runs/{id}/retry`` while a
  retry is **already pending** is a **no-op** — it returns ``202`` again but does
  **not** queue a second retry (the scheduler's
  :meth:`~app.orchestrator.retry.RetryScheduler.enqueue_manual` short-circuits on
  an already-queued state), so a double-click yields exactly **one** queued retry,
  not a duplicate dispatch.
* **Idempotent effects (AC-15 / INV-5 / R-15).** The retry reuses the same
  ``runs`` row and, on re-dispatch, the scheduler detects an existing branch/PR and
  resumes/skips rather than re-opening a PR — so a retry of an issue that already
  has an open PR creates **no duplicate PR** (the §13 resilience bar). That
  detection lives in the scheduler; this endpoint only enqueues.

Inherits the app access-control middleware (INV-1 — loopback ``Host`` + local
token + ``Origin``/CSRF on this state-changing POST). The router registers on the
single ``/api/v1`` parent in :mod:`app.api`. Nothing here touches ``dkmv/``.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.deps import get_repository
from app.api.errors import ApiError, run_not_found
from app.orchestrator.retry_deps import get_retry_scheduler

# No prefix: the ``/api/v1`` version prefix is owned by the single parent router.
router = APIRouter(tags=["runs"])

#: Run statuses a retry is offered for (FR-04-7 / FR-06-3): a failed / timed-out /
#: interrupted / cancelled run. A run that is still **active** (running/paused/…)
#: or already **completed** is not retried — there is nothing to re-dispatch.
_RETRYABLE_STATUSES: frozenset[str] = frozenset({"failed", "timed_out", "interrupted", "cancelled"})


class RetryResponse(BaseModel):
    """The ``POST /runs/{id}/retry`` ``202`` body.

    ``run_id`` is the platform UUID; ``attempt`` is the queued attempt count (so the
    UI can echo ``attempt N/3``); ``queued`` is always ``True`` on a ``202`` (a
    duplicate call returns the same already-queued state, still ``True``).
    """

    run_id: str
    attempt: int
    queued: bool = True


@router.post("/runs/{run_id}/retry", status_code=202)
async def retry_run(run_id: str, request: Request) -> RetryResponse:
    """Enqueue an idempotent retry for a failed/interrupted run → ``202`` (AC-16).

    ``404 run_not_found`` for an unknown run; ``409 run_not_retryable`` for a run
    that is still active or already completed (nothing to re-dispatch). Otherwise
    the scheduler enqueues the retry — idempotently: a second call while a retry is
    already pending returns ``202`` with the **same** queued state (no second
    dispatch). The idempotent re-dispatch (existing-branch/PR detection → no
    duplicate PR, same ``runs`` row) runs on the next reconcile tick.
    """
    async with get_repository(request) as repository:
        row = await repository.get_run(run_id)
        if row is None:
            raise run_not_found(run_id)
        status = str(row.get("status") or "")
        if status not in _RETRYABLE_STATUSES:
            raise ApiError(
                status_code=409,
                code="run_not_retryable",
                message=f"Run is {status or 'unknown'} and cannot be retried.",
                details={"status": status},
            )
        issue_num = row.get("issue_num")
        scheduler = get_retry_scheduler(request)
        state = await scheduler.enqueue_manual(
            run_id, issue_num=int(issue_num) if issue_num is not None else None
        )

    return RetryResponse(run_id=run_id, attempt=state.attempt, queued=True)
