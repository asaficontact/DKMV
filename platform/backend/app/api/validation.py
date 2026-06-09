"""Shared §8.10 capability-aware guardrail validation (INV-8 / ADR-P009).

The single place a launch body's **cost guardrails** are checked against the
*resolved* agent's adapter capability. It is consumed by the launch path
(:mod:`app.runs.launch`) and is the module the §8.10 ``unsupported_for_agent``
contract lives in (the phase brief's ``app/api/validation.py``).

The load-bearing rule (INV-8, binding):

* Enforcement **branches on the adapter capability**, never a blanket
  "budget cap exists" assumption. The branch is on the engine adapter's
  ``supports_budget()`` / ``supports_max_turns()`` — consumed in-process via
  :func:`dkmv.adapters.get_adapter` (INV-13; never the CLI).
* **Claude** (``supports_budget``/``supports_max_turns`` = true): ``max_budget_usd``
  + ``max_turns`` are accepted (enforced as hard caps downstream — see
  :mod:`app.orchestrator.enforcement`).
* **Codex** (both false): a supplied ``max_budget_usd`` / ``max_turns`` is a
  ``400 unsupported_for_agent`` — **never silently ignored**. The engine has no
  such cap for Codex, so accepting one would be a false hard-cap promise that
  lets a runaway Codex run burn money bounded only by wall-clock. Codex is
  **timeout-only** (its tighter default timeout lives in :mod:`app.config`).

Nothing here reaches into ``dkmv/`` except through the in-process adapter
registry (INV-13).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.api.errors import ApiError, validation_error


@dataclass(slots=True)
class GuardrailRequest:
    """The cost-guardrail subset of a launch body checked against capability.

    A tiny structural view so the validator does not depend on the full
    :class:`~app.runs.launch.LaunchRequest` shape (and is reusable from any cap
    path). ``max_budget_usd`` / ``max_turns`` are the capability-gated fields;
    ``None`` means "not supplied" (no check fires).
    """

    max_budget_usd: float | None = None
    max_turns: int | None = None


def unsupported_for_agent(field_name: str, agent: str) -> ApiError:
    """400 — a guardrail field is unsupported by the resolved agent (INV-8 / §8.10).

    Raised when ``max_budget_usd`` / ``max_turns`` is supplied for an agent whose
    ``supports_budget()`` / ``supports_max_turns()`` is false (Codex). The code is
    the exact §8.10 ``unsupported_for_agent`` so the UI can branch precisely rather
    than treating it as a generic ``validation_error`` — and so the AC-6 grep/test
    matches the code verbatim.
    """
    return ApiError(
        400,
        "unsupported_for_agent",
        f"{field_name} is not supported by agent '{agent}' "
        f"(Codex runs are time-bounded, not cost-bounded).",
        details={"field": field_name, "agent": agent},
    )


def agent_is_known(agent: str) -> bool:
    """True iff *agent* is a registered engine adapter name (else a 400 is raised).

    Consumed in-process via :func:`dkmv.adapters.get_adapter` (INV-13).
    """
    from dkmv.adapters import get_adapter

    try:
        get_adapter(agent)
    except Exception:  # noqa: BLE001 - unknown agent → not known
        return False
    return True


def validate_agent_capabilities(agent: str, req: GuardrailRequest) -> None:
    """Reject budget/turn guardrails the **resolved** *agent* cannot honor (INV-8).

    Branches on the adapter's ``supports_budget()`` / ``supports_max_turns()``:
    for Codex (both false) a supplied ``max_budget_usd`` / ``max_turns`` is a
    ``400 unsupported_for_agent`` — never silently ignored — because the engine
    has no such cap and a false hard-cap promise would let a Codex run run away.
    An unknown agent name is a ``400 validation_error`` (it never reaches the
    engine). This is the §8.10 capability gate the launch path delegates to.
    """
    from dkmv.adapters import get_adapter

    if not agent_is_known(agent):
        raise validation_error(
            f"unknown agent '{agent}'",
            details={"field": "agent"},
        )
    adapter = get_adapter(agent)
    if req.max_budget_usd is not None and not adapter.supports_budget():
        raise unsupported_for_agent("max_budget_usd", agent)
    if req.max_turns is not None and not adapter.supports_max_turns():
        raise unsupported_for_agent("max_turns", agent)
