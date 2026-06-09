"""Platform-injected PR-push approval gate (NFR-SEC-5 / R-14 / T087).

> **Threat (the defining risk of this product class).** The agent runs
> **attacker-influenceable input** — a GitHub *issue body is the prompt* and *repo
> content is the context*, both editable by anyone who can open an issue/PR — while
> holding a live GitHub token + egress. A prompt-injection (OWASP **LLM01**) can
> instruct the agent to push branches / open PRs the operator never intended. The
> PR/branch push is the **irreversible, high-blast-radius** action.

This gate is a **platform-injected** approval checkpoint on that push, implemented
via the **same pause primitive** as workflow-authored pauses
(:func:`app.hitl.pause_bridge.run_pause_bridge`) — but it is injected by the
*platform*, **independent of whether the workflow authored a pause**. An injected
instruction inside an issue body therefore still cannot push a PR without a human
approving it: the gate fires first and ``await``\\s a human decision through the
exact same exactly-once resolve path (``POST /runs/{id}/answer``).

**This is defense-in-depth, not prevention (be honest — §8.6).** It does not
*stop* injection; the network-enforced egress allowlist + repo-scoped ≤1 hr token
are the real containment controls (INV-3 / INV-4). The approval gate adds a human
checkpoint on the one irreversible action so an injected push is caught before it
lands — a backstop layered on top of containment, not a substitute for it.

Nothing here edits ``dkmv/``; it composes the in-process ``PauseRequest`` /
``PauseResponse`` types and the platform's own pause bridge (INV-13).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dkmv.tasks.pause import PauseQuestion, PauseRequest, PauseResponse

from app.hitl.pause_bridge import run_pause_bridge

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.hitl.pause_bridge import PauseBridgeDeps

#: The question id the PR-push approval decision is keyed by (the answer body's
#: ``answers`` maps this id → the chosen option value).
PR_PUSH_QUESTION_ID = "approve_pr_push"

#: Engine-authoritative option shape ``{value, label, description?}`` (§6.1). The
#: ``approve`` option's value is the ``default`` (the recommended option the UI
#: marks) — but the gate is **fail-safe**: anything other than an explicit
#: ``approve`` is treated as a hold (``skip_remaining``), so a timeout auto-abort
#: or an "abort" answer does NOT push.
PR_PUSH_OPTIONS: list[dict[str, str]] = [
    {
        "value": "approve",
        "label": "Approve & push",
        "description": "Push the branch and open the pull request.",
    },
    {
        "value": "abort",
        "label": "Abort — do not push",
        "description": "Stop before any branch/PR push (e.g. the diff looks injected).",
    },
]


def build_pr_push_pause_request(
    *,
    task_name: str = "PR push",
    summary: str | None = None,
) -> PauseRequest:
    """Build the platform-injected PR-push approval :class:`PauseRequest`.

    A normal engine-shaped ``PauseRequest`` (so the decision card renders it like
    any other pause) whose question gates the irreversible push. The recommended
    option is ``approve`` (``default``), but approval is **explicit**: only an
    ``answers[PR_PUSH_QUESTION_ID] == "approve"`` proceeds — see
    :func:`is_push_approved`.
    """
    context = {
        "summary": summary
        or (
            "This run is about to push a branch and open a pull request — an "
            "irreversible action. Issue/repo content is untrusted (prompt-injection "
            "risk), so the push requires your approval."
        )
    }
    question = PauseQuestion(
        id=PR_PUSH_QUESTION_ID,
        question="Approve pushing this branch and opening the pull request?",
        options=PR_PUSH_OPTIONS,
        default="approve",
    )
    return PauseRequest(task_name=task_name, questions=[question], context=context)


def is_push_approved(response: PauseResponse) -> bool:
    """True iff the human **explicitly approved** the push (fail-safe default).

    Approval is explicit: the push proceeds **only** when the answer for
    :data:`PR_PUSH_QUESTION_ID` is exactly ``"approve"``. Every other outcome — an
    ``abort`` answer, a ``skip_remaining`` (Ship-as-is/Abort), or a timeout
    auto-abort (no answers) — is treated as *not approved*, so an injected or
    unattended run never pushes. This is the fail-safe that makes the gate a real
    checkpoint rather than a rubber stamp.
    """
    if response.skip_remaining:
        return False
    return bool(response.answers.get(PR_PUSH_QUESTION_ID) == "approve")


async def require_pr_push_approval(
    deps: PauseBridgeDeps,
    *,
    task_name: str = "PR push",
    summary: str | None = None,
) -> bool:
    """Pause for human approval **before** the PR push; return whether to proceed.

    The platform-injected checkpoint (NFR-SEC-5): builds the PR-push
    :class:`PauseRequest` and drives it through the **same** pause primitive as a
    workflow-authored pause (:func:`app.hitl.pause_bridge.run_pause_bridge`) — so
    it writes a durable ``pause_decisions`` row, sets ``agent:paused``, releases
    the slot, emits ``pause_requested``, and ``await``\\s the human's
    exactly-once ``POST /runs/{id}/answer``. Returns :func:`is_push_approved` —
    the caller pushes **only** on ``True``. Because the gate is the platform's, an
    injected instruction in the issue body cannot bypass it: the push is reached
    only after this returns ``True``.
    """
    request = build_pr_push_pause_request(task_name=task_name, summary=summary)
    response = await run_pause_bridge(deps, request)
    return is_push_approved(response)
