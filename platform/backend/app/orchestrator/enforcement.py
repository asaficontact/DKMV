"""Capability-aware cost-cap application (INV-8 / ADR-P009, NFR-COST-1, §7.2).

This is the orchestrator-side companion to :mod:`app.api.validation`. Validation
*rejects* a guardrail the resolved agent cannot honor at the API boundary; this
module decides, for an *accepted* launch, **which caps are actually enforced**
and what the effective ``timeout_minutes`` is — branching on the engine adapter's
``supports_budget()`` / ``supports_max_turns()`` (consumed in-process — INV-13).

The honest cost story (ADR-P009):

* **Claude** (``supports_budget``/``supports_max_turns`` = true): ``max_budget_usd``
  + ``max_turns`` + ``timeout_minutes`` are **hard caps** — when the run's spend
  reaches ``max_budget_usd`` the run is **stopped** (the cap *fires*; it is not a
  suggestion). The Settings daily-spend alert + the aggregate daily-spend
  admission cap (5.1) bound spend *across* runs; this is the per-run hard cap.
* **Codex** (both false): ``timeout_minutes`` is the **only** runtime guardrail.
  No budget/turn cap exists to fire; the (validated-away) ``max_budget_usd`` /
  ``max_turns`` are ``None`` here. The default timeout is **strictly tighter**
  than Claude's (:func:`app.config.default_timeout_minutes`) because timeout is
  the sole bound (§7.2 fn3).

A run hitting a fired cap is **stopped**, not paused — the cap is a hard ceiling,
distinct from the HITL soft-threshold pause (the optional ``soft_budget_usd``
pause-for-approval, which is *advisory*).

Nothing here reaches into ``dkmv/`` except through the in-process adapter
registry (INV-13).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import default_timeout_minutes


@dataclass(slots=True, frozen=True)
class AgentCapabilities:
    """The cost-relevant capability snapshot of the run's resolved agent (INV-8).

    Sourced from the engine adapter's ``supports_budget()`` /
    ``supports_max_turns()``. ``supports_budget`` false ⇒ no hard budget cap can
    fire (Codex); ``supports_max_turns`` false ⇒ no turn cap. Both false is the
    timeout-only (Codex) profile.
    """

    agent: str
    supports_budget: bool
    supports_max_turns: bool

    @property
    def timeout_only(self) -> bool:
        """True iff the agent has neither a budget nor a turn cap (Codex)."""
        return not self.supports_budget and not self.supports_max_turns


def capabilities_for(agent: str) -> AgentCapabilities:
    """Read *agent*'s cost capabilities from its engine adapter (INV-13, in-process).

    Branches downstream on ``supports_budget`` / ``supports_max_turns`` — never a
    blanket "budget cap exists." An unknown agent surfaces as no-caps (the
    conservative, timeout-only profile) rather than a false hard-cap promise; the
    API validator (:mod:`app.api.validation`) rejects an unknown agent before this
    is reached on the launch path.
    """
    from dkmv.adapters import get_adapter

    try:
        adapter = get_adapter(agent)
    except Exception:  # noqa: BLE001 - unknown agent → conservative no-caps
        return AgentCapabilities(agent=agent, supports_budget=False, supports_max_turns=False)
    return AgentCapabilities(
        agent=agent,
        supports_budget=adapter.supports_budget(),
        supports_max_turns=adapter.supports_max_turns(),
    )


@dataclass(slots=True, frozen=True)
class EnforcedCaps:
    """The caps that will actually be enforced for a launched run (ADR-P009).

    The capability-aware *resolution* of a launch body's guardrails:

    * ``max_budget_usd`` / ``max_turns`` are carried through **only** when the
      agent supports them (Claude); they are ``None`` for a timeout-only agent
      (Codex) even if the body somehow carried a value — a false hard cap is never
      promised.
    * ``timeout_minutes`` is the explicit value when supplied, else the
      capability-aware default (strictly tighter for Codex — §7.2 fn3). It is
      **always** present (timeout is the universal guardrail).
    * ``budget_cap_active`` / ``turn_cap_active`` say whether a hard cap can fire
      — the enforcement loop checks ``budget_cap_active`` before stopping a run on
      spend, so a Codex run is never stopped on a (non-existent) budget cap.
    """

    agent: str
    max_budget_usd: float | None
    max_turns: int | None
    timeout_minutes: int
    budget_cap_active: bool
    turn_cap_active: bool


def resolve_enforced_caps(
    *,
    agent: str,
    max_budget_usd: float | None,
    max_turns: int | None,
    timeout_minutes: int | None,
) -> EnforcedCaps:
    """Resolve which caps a run enforces, branching on agent capability (INV-8).

    The single capability-aware resolution used at launch:

    * **Claude** → ``max_budget_usd`` + ``max_turns`` are hard caps (carried
      through; ``budget_cap_active`` true when a budget is set), ``timeout_minutes``
      defaults to the Claude default when unset.
    * **Codex** → ``max_budget_usd`` / ``max_turns`` are dropped to ``None`` (no
      cap can fire — they were already validation-rejected at the API boundary),
      ``timeout_minutes`` defaults to the **strictly tighter** Codex default.

    ``timeout_minutes`` is always returned non-``None`` (the universal guardrail).
    """
    caps = capabilities_for(agent)
    effective_budget = max_budget_usd if caps.supports_budget else None
    effective_turns = max_turns if caps.supports_max_turns else None
    effective_timeout = (
        timeout_minutes if timeout_minutes is not None else default_timeout_minutes(agent)
    )
    return EnforcedCaps(
        agent=agent,
        max_budget_usd=effective_budget,
        max_turns=effective_turns,
        timeout_minutes=effective_timeout,
        budget_cap_active=caps.supports_budget and effective_budget is not None,
        turn_cap_active=caps.supports_max_turns and effective_turns is not None,
    )


def budget_cap_fires(caps: EnforcedCaps, spend_usd: float) -> bool:
    """True iff *spend_usd* has reached the run's **active hard budget cap** (AC-8).

    Branches on ``budget_cap_active`` first: a timeout-only agent (Codex) has no
    budget cap, so this is always ``False`` for it — its run is bounded by
    ``timeout_minutes`` alone (AC-7), never stopped on spend. For Claude with a
    set budget, the cap **fires** (the run is stopped) at or above the ceiling —
    it is a hard cap, not a suggestion (ADR-P009).
    """
    if not caps.budget_cap_active or caps.max_budget_usd is None:
        return False
    return spend_usd >= caps.max_budget_usd
