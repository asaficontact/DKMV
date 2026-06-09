"""UTC-persisted deadline evaluation (PRD §8.2 — AC-13, binding).

Every orchestrator deadline — a retry ``backoff`` due-time, a pause ``timeout_at``,
a per-run ``stall`` cutoff — is a **UTC timestamp persisted in the DB** and
**re-evaluated against ``now()`` each tick**. It is **NEVER** an in-memory
slept-until timer.

Why this matters (the failure this guards): a laptop suspend / a
``docker compose restart`` freezes the event loop. An in-memory await-until-due
timer either evaporates with the process or wakes "late" by exactly the suspend
gap — so a deadline that should have fired during the gap is silently missed. By
contrast a persisted UTC ``due_at`` compared against a fresh ``now()`` on the next
tick fires correctly the instant the loop resumes, **however long** the gap was.
The deadline survives the suspend because it lives in the DB, not in a coroutine's
stack.

This module is therefore deliberately **timer-free**: it holds only the pure
comparison ``now() >= due_at`` over ISO-8601 UTC strings (the platform's one
timestamp format — :func:`app.db.repository._utc_now_iso`), plus the small
helpers that compute the next ISO ``due_at`` from a ``now`` + a delay. The
``now`` clock is **injectable everywhere** so a test can advance a *frozen* clock
past a persisted ``due_at`` — simulating a suspend gap of any length — and assert
the deadline fires, with no real waiting.

The binding grep (AC-13) over this file for the await-until-due primitive is
asserted **empty** — no deadline here is implemented as a slept timer.

Nothing in this module touches ``dkmv/`` or the network; it is pure time math.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

#: The platform's single time format: timezone-aware UTC ISO-8601, byte-identical
#: to :func:`app.db.repository._utc_now_iso`. Persisted ``due_at`` / ``timeout_at``
#: / event ``ts`` are all written this way, so a *lexicographic* string compare is
#: a correct *chronological* compare for same-format timestamps.
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """Current timezone-aware UTC time (the orchestrator's default clock).

    Injectable everywhere a deadline is evaluated so a test can pass a frozen /
    advanced clock instead — there is never a hidden ``datetime.now()`` a test
    cannot control (which is what lets the suspend-gap test work without sleeping).
    """
    return datetime.now(UTC)


def to_iso(moment: datetime) -> str:
    """Render a UTC ``datetime`` as the platform's ISO-8601 string.

    Coerces a naive datetime to UTC (treating it as already-UTC) so a deadline
    computed from a test's frozen clock serializes identically to the repository's
    ``_utc_now_iso``; a same-format string is what makes the lexicographic compare
    in :func:`is_due` chronologically correct.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat()


def parse_iso(value: str) -> datetime | None:
    """Parse a persisted UTC ISO-8601 ``due_at`` back to an aware ``datetime``.

    Returns ``None`` for an empty / unparseable value (a row with no deadline set)
    so callers treat "no deadline" as "never due" rather than crashing a tick on a
    malformed cell. A naive parse result is coerced to UTC (the platform never
    writes a naive timestamp, but a hand-seeded test row might).
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def is_due(due_at: str | None, *, now: Clock = utc_now) -> bool:
    """``True`` iff a persisted UTC ``due_at`` is at-or-before ``now()`` (AC-13).

    The single deadline predicate the whole orchestrator routes through. It is a
    pure comparison against a *fresh* ``now()`` — **never** a slept-until timer —
    so a deadline whose ``due_at`` fell inside a suspend gap fires on the very next
    tick after the loop resumes, no matter how long the gap was. ``due_at = None``
    (no deadline) is never due. ``now`` is injectable so a frozen-clock test can
    advance past ``due_at`` and assert this returns ``True`` with no sleeping.
    """
    if due_at is None:
        return False
    parsed = parse_iso(due_at)
    if parsed is None:
        return False
    return now() >= parsed


def due_at_from_now(delay_seconds: float, *, now: Clock = utc_now) -> str:
    """Compute a persisted ``due_at`` = ``now() + delay`` as a UTC ISO string.

    The forward-direction helper a scheduler uses to *write* a deadline (3.4's
    backoff ``due_at``, 3.5's drain deadline): the result is stored in the DB and
    later re-evaluated by :func:`is_due` each tick. Computing it from an injectable
    ``now`` keeps deadline *creation* deterministic in tests too.
    """
    return to_iso(now() + timedelta(seconds=delay_seconds))


def seconds_since(ts: str | None, *, now: Clock = utc_now) -> float | None:
    """Elapsed seconds between a persisted UTC ``ts`` and ``now()`` (or ``None``).

    The reconcile stall check (:mod:`app.orchestrator.reconcile`) uses this to ask
    "how long since this run's last event ts?" against a fresh ``now()`` — again a
    re-evaluation, not a timer. Returns ``None`` when ``ts`` is absent/unparseable
    so the caller can treat "no events yet" distinctly from "0 seconds ago".
    """
    parsed = parse_iso(ts) if ts is not None else None
    if parsed is None:
        return None
    return (now() - parsed).total_seconds()


@dataclass(frozen=True, slots=True)
class Deadline:
    """A single named, persisted UTC deadline re-evaluated each tick (AC-13).

    A thin value object pairing a ``kind`` (``"backoff"`` / ``"timeout_at"`` /
    ``"stall"``) with its persisted UTC ``due_at`` so a tick can carry a batch of
    heterogeneous deadlines through one :func:`is_due` evaluation. The deadline
    *lives in the DB*; this object is just the in-tick view of one persisted row,
    constructed fresh each tick (never held across ticks as a live timer).
    """

    kind: str
    due_at: str | None
    ref: str = ""

    def fires(self, *, now: Clock = utc_now) -> bool:
        """``True`` iff this persisted deadline is due at ``now()`` (no sleep)."""
        return is_due(self.due_at, now=now)


__all__ = [
    "Clock",
    "Deadline",
    "due_at_from_now",
    "is_due",
    "parse_iso",
    "seconds_since",
    "to_iso",
    "utc_now",
]
