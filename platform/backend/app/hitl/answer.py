"""Resolve a pause **exactly once** + resume the run (INV-9 / §8.5 step 3).

``POST /runs/{id}/answer`` (the route is :mod:`app.api.answer`) lands here. The
binding behavior (INV-9) is the **guarded transition**::

    UPDATE pause_decisions
       SET status='answered', answer_json=…, resolved_by='human'
     WHERE id=? AND status='pending'

and firing the in-memory keyed future **only on ``rowcount == 1``**. That single
atomic guard is what makes a double-click, two browser tabs, and a racing timeout
sweep all safe: exactly one of them flips the row and resumes the engine; every
other attempt matches zero rows and is rejected ``409 pause_already_resolved``.
The resolver (this module) is shared by the answer endpoint (``resolved_by=
'human'``) and the timeout sweep (``resolved_by='timeout'``) — one guard, two
callers — so they can never double-resolve the same decision.

On the winning transition the resolved payload (``answers`` + ``skip_remaining``)
is handed to the awaiting ``on_pause`` bridge via the
:class:`~app.hitl.registry.DecisionRegistry`; the bridge returns the
:class:`~dkmv.tasks.pause.PauseResponse` → the engine resumes (re-acquiring a
concurrency slot) and emits the ``decision`` event. Nothing here edits ``dkmv/``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.api.errors import ApiError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.db.repository import Repository
    from app.hitl.registry import DecisionRegistry


def pause_already_resolved(decision_id: str | None = None) -> ApiError:
    """409 — the pause was already answered / timed out (§8.9 ``pause_already_resolved``).

    Returned whenever the exactly-once guard matched zero rows: a second submit, a
    second tab, or a sweep that already auto-resolved this decision. The first
    resolution stands; this one is a no-op the UI can surface as "already decided".
    """
    details = {"decision_id": decision_id} if decision_id else None
    return ApiError(
        409,
        "pause_already_resolved",
        "This pause has already been resolved.",
        details=details,
    )


@dataclass(frozen=True, slots=True)
class AnswerResult:
    """The outcome of a winning ``POST /runs/{id}/answer`` resolution.

    ``resolved`` is always ``True`` here (a lost guard raises
    ``409 pause_already_resolved`` before this is built). ``decision_id`` surfaces
    the **precise** ``pause_decisions.id`` that was flipped (computed in
    :func:`answer_run_pause` from the pending row, §8.5) so the route's §8.6 audit
    line records the real decision id — a multi-pause run no longer collapses every
    resolution to the run id (slice 5.3 / AC-12 / FIX-3). The HTTP body shape stays
    the §8.9 ``{"resolved": true}`` map (the route projects ``resolved`` out)."""

    decision_id: str
    resolved: bool = True


@dataclass(slots=True)
class AnswerRequest:
    """The resolved decision body (the §8.5 ``PauseResponse`` payload).

    ``answers`` maps each ``question_id`` to the chosen option's **value** (the
    engine-authoritative ``{value,label}`` shape — the UI sends the value, not the
    label, §6.1). ``skip_remaining`` is set by Ship-as-is / Abort (skip the rest of
    the workflow). The engine stores ``answers[question_id]`` verbatim as the
    question's ``user_answer``.
    """

    answers: dict[str, str] = field(default_factory=dict)
    skip_remaining: bool = False


async def resolve_pending_pause(
    *,
    repository: Repository,
    decisions: DecisionRegistry,
    decision_id: str,
    answers: dict[str, str],
    skip_remaining: bool,
    resolved_by: str,
) -> bool:
    """Win-or-lose the exactly-once guard; fire the keyed future iff this won (INV-9).

    The shared resolve primitive both the answer endpoint and the timeout sweep go
    through. It performs the guarded ``UPDATE … WHERE status='pending'`` through the
    single writer and, **only when that returned ``rowcount == 1``**, fires the
    in-memory future the awaiting ``on_pause`` bridge is parked on (carrying the
    resolved ``answers`` + ``skip_remaining`` + ``resolved_by``). Returns ``True``
    iff this call won the transition; the answer route maps ``False`` →
    ``409 pause_already_resolved``. Firing the future only on the DB win is what
    closes the double-resolve window (a future fired without winning the row would
    double-resume the engine).
    """
    answer_json = json.dumps({"answers": answers, "skip_remaining": skip_remaining})
    won = await repository.resolve_pause_decision(
        decision_id,
        answer_json=answer_json,
        resolved_by=resolved_by,
    )
    if not won:
        return False
    # The DB transition won → fire the awaiting bridge exactly once. The payload
    # carries resolved_by so the bridge's decision event distinguishes a human
    # answer from a timeout auto-resolve.
    decisions.resolve(
        decision_id,
        {
            "answers": answers,
            "skip_remaining": skip_remaining,
            "resolved_by": resolved_by,
        },
    )
    return True


async def answer_run_pause(
    *,
    repository: Repository,
    decisions: DecisionRegistry,
    run_id: str,
    request: AnswerRequest,
) -> AnswerResult:
    """Resolve a run's open pause from ``POST /runs/{id}/answer`` (human path).

    Finds the run's pending decision, then resolves it exactly-once via
    :func:`resolve_pending_pause` (``resolved_by='human'``). A run with no open
    pending pause (already resolved / never paused) → ``409 pause_already_resolved``
    so a duplicate submit is rejected rather than silently no-op'ing. On the win,
    the awaiting bridge resumes the engine; returns an :class:`AnswerResult` carrying
    ``resolved=True`` + the **precise** flipped ``pause_decisions.id`` (so the route's
    §8.6 audit line records the real decision id — FIX-3, not the run id). The route
    projects ``{"resolved": True}`` out of it for the §8.9 HTTP body.
    """
    pending = await repository.read_pending_pause(run_id)
    if pending is None:
        raise pause_already_resolved()
    decision_id = str(pending["id"])
    won = await resolve_pending_pause(
        repository=repository,
        decisions=decisions,
        decision_id=decision_id,
        answers=request.answers,
        skip_remaining=request.skip_remaining,
        resolved_by="human",
    )
    if not won:
        # A racing timeout sweep / second tab won the guard first.
        raise pause_already_resolved(decision_id)
    return AnswerResult(decision_id=decision_id, resolved=True)
