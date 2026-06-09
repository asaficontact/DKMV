"""Pause-timeout auto-resolve sweep (INV-9 / §8.5 step 4 / T085).

Each pause carries a UTC ``timeout_at`` (default 60 min — see
``app.hitl.pause_bridge.DEFAULT_PAUSE_TIMEOUT_MINUTES``).
A paused run must **never hang** and an idle 8 GB container must **never hold a
concurrency slot indefinitely**, so an auto-resolve sweep re-evaluates ``now() >=
timeout_at`` and resolves expired pauses on the human's behalf.

Two binding properties (INV-9):

* **UTC, re-evaluated — not an in-memory timer.** The deadline is a persisted UTC
  timestamp (§8.5 step 4), so it survives across reconnects and is compared against
  ``now()`` each sweep — a slow/asleep process can't drop a timer and hang a pause.
* **Same exactly-once guard.** The sweep resolves through the **identical**
  ``UPDATE … WHERE status='pending'`` guard the human answer path uses
  (:func:`app.hitl.answer.resolve_pending_pause`, ``resolved_by='timeout'``) — so a
  pause a human answers in the *same* tick is resolved by exactly one of them
  (rowcount==1 wins, the other no-ops). The default policy is **auto-abort**
  (``skip_remaining=True``, no answers → the engine skips the remaining workflow).

**Phase scope (§3).** This is the *minimal hook*: in Phase 2 it is exercised by a
**directly-invoked** :func:`sweep_expired_pauses` in tests; wiring it into the
reconcile tick is Phase 3 (T104). ``now`` is injectable so a test can fast-forward
past ``timeout_at`` without sleeping. Nothing here edits ``dkmv/``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.hitl.answer import resolve_pending_pause

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.db.repository import Repository
    from app.hitl.registry import DecisionRegistry

#: The default timeout policy: **auto-abort** the run (skip the remaining
#: workflow) with no answers. PRD §8.5 step 4 notes this is configurable to
#: auto-approve-recommended; Phase 2 ships the conservative auto-abort default.
TIMEOUT_SKIP_REMAINING = True


def _utc_now() -> datetime:
    """Current UTC time (the sweep's clock; injectable for tests)."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class SweepResult:
    """Outcome of one :func:`sweep_expired_pauses` pass.

    ``resolved`` is the count of pauses *this* sweep auto-resolved on timeout
    (won the exactly-once guard). ``expired`` is how many were past their deadline
    when read — ``resolved`` can be lower when a human answered one between the read
    and the guarded write (that one no-ops here, correctly resolved once overall).
    """

    expired: int
    resolved: int


async def sweep_expired_pauses(
    *,
    repository: Repository,
    decisions: DecisionRegistry,
    now: Callable[[], datetime] | None = None,
) -> SweepResult:
    """Auto-resolve every ``pending`` pause whose UTC ``timeout_at <= now`` (INV-9).

    Reads the expired-pending pauses (``timeout_at <= now``, the indexed sweep
    query) and resolves each through the **same exactly-once guard** the human
    answer path uses (``resolved_by='timeout'``, default auto-abort). A pause a
    human answers in the same tick is resolved by exactly one path — the guard's
    ``rowcount==1`` decides which — so the run never double-resolves and never
    double-resumes. ``now`` is injectable (a test fast-forwards past ``timeout_at``);
    it defaults to UTC ``now()``. Returns the expired/resolved counts.
    """
    clock = now or _utc_now
    now_iso = clock().isoformat()
    expired = await repository.read_expired_pending_pauses(now_iso=now_iso)
    resolved = 0
    for row in expired:
        decision_id = str(row["id"])
        won = await resolve_pending_pause(
            repository=repository,
            decisions=decisions,
            decision_id=decision_id,
            answers={},
            skip_remaining=TIMEOUT_SKIP_REMAINING,
            resolved_by="timeout",
        )
        if won:
            resolved += 1
    return SweepResult(expired=len(expired), resolved=resolved)
