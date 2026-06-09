"""Concurrency-slot accounting — the primitive Phase 5's admission gate consumes.

A paused run is **genuinely idle** — the agent process is not running and the
container is parked at ``await on_pause`` (§8.5). So while a human is away it must
**not** occupy a ``max_concurrent_runs`` slot (a held 8 GB container under a 3-slot
cap is too costly — the reason the pause timeout defaults to 60 min, not 24 h).

This module is the **slot-accounting primitive** (T086): the HITL bridge releases
a slot on pause and re-acquires one on resume, and this counter is what records
that. **Phase 2 does NOT enforce a cap** — `max_concurrent_runs` admission control
is Phase 5 (F13). Building the release/reacquire accounting here is the seam Phase
5's `Semaphore` consumes: when the enforcement gate lands, "acquire" blocks on the
semaphore and "release" hands the permit back; until then this is a pure counter
the test asserts moves (released on pause, reacquired on resume) so the behavior is
correct before the cap exists.

Single-loop, single-process (PRD §8.3 / ADR-P001): no locking is needed — every
mutation runs on the one event loop. The counter never goes negative (a defensive
clamp) so a double-release / spurious resume can't manufacture phantom capacity.
"""

from __future__ import annotations


class ConcurrencySlots:
    """In-memory slot accounting for active (non-paused) runs (T086).

    Tracks how many runs currently **hold** a concurrency slot. A launched run
    holds one; a paused run :meth:`release`-s it (it is idle) and :meth:`acquire`-s
    it back on resume. Phase 2 does not block on capacity — :meth:`acquire` always
    succeeds — but the count is the accounting Phase 5's admission semaphore will
    enforce against ``max_concurrent_runs``.

    Args:
        capacity: The advisory ``max_concurrent_runs`` (recorded for Phase 5; not
            enforced in Phase 2). Defaults to the PRD env default of 3.
    """

    def __init__(self, capacity: int = 3) -> None:
        self._capacity = capacity
        self._held = 0

    @property
    def capacity(self) -> int:
        """The advisory slot cap (enforced in Phase 5, recorded here)."""
        return self._capacity

    @property
    def held(self) -> int:
        """How many slots are currently held by active (non-paused) runs."""
        return self._held

    @property
    def available(self) -> int:
        """Advisory free-slot count (``capacity - held``, clamped at 0)."""
        return max(0, self._capacity - self._held)

    def acquire(self) -> None:
        """Take a slot for a run that is (re)entering the active state.

        Called when a run launches and again when a paused run resumes
        (re-acquiring the slot it released on pause — §8.5). In Phase 2 this never
        blocks; Phase 5 makes it await a ``Semaphore`` permit.
        """
        self._held += 1

    def release(self) -> None:
        """Hand back the slot held by a run that is going idle (paused/finished).

        Called by the pause bridge when the run parks at ``await on_pause`` — the
        container is genuinely idle, so the slot is freed (T086). Clamped at zero
        so a double-release can never manufacture phantom capacity.
        """
        if self._held > 0:
            self._held -= 1
