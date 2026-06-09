"""Human-in-the-loop (HITL) — the pause bridge, answer, timeout, PR-push gate.

The F9 best-effort-durable interrupt (PRD §5.6, §8.5; INV-9; ADR-P007). The
engine ``await``\\s the platform's ``on_pause`` callback at a workflow pause
point; this package owns that callback and the resolve path:

* :mod:`app.hitl.pause_bridge` — the ``on_pause`` bridge: write ``pause_decisions``,
  set ``agent:paused`` (write-queue), release the concurrency slot, emit
  ``pause_requested`` over SSE, await the keyed future, then resume + emit
  ``decision`` (§8.5 steps 1–3).
* :mod:`app.hitl.answer` — resolve-**exactly-once** (rowcount-guard) + resume; the
  shared resolve primitive the answer endpoint + timeout sweep both go through.
* :mod:`app.hitl.timeout` — the UTC ``timeout_at`` auto-resolve sweep (default
  auto-abort) via the same guard (T085; tick-wired in Phase 3).
* :mod:`app.hitl.pr_gate` — the platform-injected PR-push approval gate
  (NFR-SEC-5), reusing the same pause primitive.
* :mod:`app.hitl.registry` / :mod:`app.hitl.slots` — the in-memory await/resume
  rendezvous and the concurrency-slot accounting primitive (T086).
"""

from __future__ import annotations

from app.hitl.answer import AnswerRequest, answer_run_pause, resolve_pending_pause
from app.hitl.pause_bridge import (
    DEFAULT_PAUSE_TIMEOUT_MINUTES,
    PauseBridgeDeps,
    build_pause_bridge,
    compute_timeout_at,
    run_pause_bridge,
)
from app.hitl.pr_gate import (
    build_pr_push_pause_request,
    is_push_approved,
    require_pr_push_approval,
)
from app.hitl.registry import DecisionRegistry
from app.hitl.slots import ConcurrencySlots
from app.hitl.timeout import SweepResult, sweep_expired_pauses

__all__ = [
    "DEFAULT_PAUSE_TIMEOUT_MINUTES",
    "AnswerRequest",
    "ConcurrencySlots",
    "DecisionRegistry",
    "PauseBridgeDeps",
    "SweepResult",
    "answer_run_pause",
    "build_pause_bridge",
    "build_pr_push_pause_request",
    "compute_timeout_at",
    "is_push_approved",
    "require_pr_push_approval",
    "resolve_pending_pause",
    "run_pause_bridge",
    "sweep_expired_pauses",
]
