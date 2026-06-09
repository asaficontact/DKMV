"""``POST /runs/{id}/answer`` — resolve a pause exactly-once + resume (§8.5/§8.9).

The HTTP entry to the F9 resolve path (the resolve-once logic + engine resume live
in :mod:`app.hitl.answer`). A **state-changing POST** behind the app-wide
:class:`~app.security.AccessControlMiddleware` (INV-1 — loopback ``Host`` + local
token + ``Origin``/CSRF), so a malicious page cannot answer a pause on the
operator's behalf.

* Body: ``{answers:{question_id: <chosen option value>}, skip_remaining}`` (§8.5).
  The UI sends the chosen option **value** (the engine-authoritative ``{value,
  label}`` shape — §6.1), and ``skip_remaining`` for Ship-as-is / Abort.
* Resolves the run's pending decision **exactly once** via the rowcount-guarded
  transition (INV-9) → fires the awaiting ``on_pause`` bridge → the engine resumes.
* Returns ``200 {resolved:true}`` on the winning transition, or
  ``409 pause_already_resolved`` when the pause was already answered / timed out
  (a double-click, a second tab, or a racing timeout sweep) — §8.9.

The repository resolved here is the **lifespan-owned** one (the same single writer
the pause bridge + pump hold), so the guarded ``UPDATE`` and the bridge's awaited
future are on the same loop / DB. Nothing here touches ``dkmv/`` (INV-13).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.deps import get_decision_registry
from app.api.errors import run_not_found
from app.db.repository import Repository
from app.hitl.answer import AnswerRequest, answer_run_pause

# No prefix here: the ``/api/v1`` version prefix is owned by the single parent
# router in :mod:`app.api`, which this router attaches to.
router = APIRouter(tags=["hitl"])


class AnswerPauseBody(BaseModel):
    """The ``POST /runs/{id}/answer`` body (§8.5 ``PauseResponse`` shape).

    ``answers`` maps each ``question_id`` → the chosen option **value** (NOT the
    label — the UI sends the engine-authoritative value, §6.1). ``skip_remaining``
    is set by Ship-as-is / Abort to skip the rest of the workflow.
    """

    answers: dict[str, str] = Field(
        default_factory=dict,
        description="question_id → chosen option value (the engine value, not the label).",
    )
    skip_remaining: bool = Field(
        default=False, description="Skip the remaining workflow (Ship-as-is / Abort)."
    )


def _lifespan_repository(request: Request) -> Repository:
    """Resolve the lifespan-owned :class:`Repository` (the bridge's single writer).

    The pause bridge + event pump hold the lifespan-owned ``app.state.repository``
    (the single writer, INV-6). The answer's guarded ``UPDATE`` must run on the SAME
    DB/loop so winning the guard and firing the bridge's awaited future line up — so
    we resolve that singleton, never a per-request Repository. Asserts it is present
    (the lifespan composed it at startup; a no-lifespan bare client is unsupported
    for this endpoint, which needs the long-lived bridge state).
    """
    repository = getattr(request.app.state, "repository", None)
    assert isinstance(repository, Repository)
    return repository


@router.post("/runs/{run_id}/answer")
async def answer_pause(run_id: str, body: AnswerPauseBody, request: Request) -> dict[str, bool]:
    """Resolve a run's open pause exactly-once and resume the engine (§8.5/§8.9).

    Looks up the run, then resolves its pending decision through the INV-9
    rowcount-guard (``resolved_by='human'``); on the winning transition the awaiting
    ``on_pause`` bridge returns its :class:`PauseResponse` and the engine resumes.
    Returns ``200 {resolved:true}`` or — when the pause was already resolved (double
    submit / second tab / racing timeout) — ``409 pause_already_resolved`` (raised
    by :func:`app.hitl.answer.answer_run_pause`). A ``404 run_not_found`` for an
    unknown platform UUID. A state-changing POST behind the INV-1 middleware.
    """
    repository = _lifespan_repository(request)
    if await repository.get_run(run_id) is None:
        raise run_not_found(run_id)
    decisions = get_decision_registry(request)
    return await answer_run_pause(
        repository=repository,
        decisions=decisions,
        run_id=run_id,
        request=AnswerRequest(answers=dict(body.answers), skip_remaining=body.skip_remaining),
    )
