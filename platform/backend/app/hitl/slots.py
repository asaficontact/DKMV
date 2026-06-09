"""Concurrency-slot accounting + the Phase-5 admission semaphore (AC-1 / INV-9).

A paused run is **genuinely idle** — the agent process is not running and the
container is parked at ``await on_pause`` (§8.5). So while a human is away it must
**not** occupy a ``max_concurrent_runs`` slot (a held 8 GB container under a 3-slot
cap is too costly — the reason the pause timeout defaults to 60 min, not 24 h).

This module is the **slot-accounting primitive** (T086) the HITL pause bridge
consumes (release on pause, re-acquire on resume) **and** — as of Phase 5 (T111) —
the **bounded-concurrency gate** the dispatch loop awaits. The two surfaces share
**one** ``asyncio.Semaphore(max_concurrent_runs)`` so they cannot drift:

* **Dispatch gate (async, Phase 5).** :meth:`acquire_async` / :meth:`slot` ``await``
  a semaphore permit — it **blocks when full** so a tick that finds more candidates
  than free slots dispatches only ``available`` of them and the rest queue for a
  later tick. ``> max_concurrent_runs`` issues → only N run at once; the rest drain
  as slots free (NFR-SCALE-1).
* **Pause release/reacquire (sync, Phase 2 — INV-9).** The pause bridge calls the
  *synchronous* :meth:`release` when a run parks (handing its permit back so a
  queued candidate can take it) and :meth:`acquire` when it resumes (taking a permit
  back). These stay **synchronous** because the bridge runs them inline on the
  serving loop around the engine ``await`` and must not introduce a new await point
  that could deadlock the resume. They mutate the **same** semaphore + held count as
  the async gate, so a pause genuinely frees a dispatch slot (INV-9 not regressed).

The semaphore is created **lazily on first async use** bound to the running loop
(an ``asyncio.Semaphore`` must be constructed on the loop it is awaited on). The
synchronous pause path manipulates the permit count directly via the same internal
counter, so it works before the first async acquire too. The held count never goes
negative (a defensive clamp) so a double-release / spurious resume can't manufacture
phantom capacity, and a sync release never pushes the semaphore above its capacity.

Single-loop, single-process (PRD §8.3 / ADR-P001): one orchestrator per process.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator


class ConcurrencySlots:
    """Semaphore-backed concurrency slots: dispatch gate + pause accounting (T111).

    Tracks how many runs currently **hold** a concurrency slot against a fixed
    ``capacity`` (``max_concurrent_runs``). A launched run holds one (taken via the
    async :meth:`acquire_async` dispatch gate); a paused run :meth:`release`-s it (it
    is idle) and :meth:`acquire`-s it back on resume. Unlike Phase 2's pure counter,
    the async gate now **awaits a real semaphore permit** — when all slots are held
    :meth:`acquire_async` blocks until one frees (AC-1 / NFR-SCALE-1).

    Args:
        capacity: ``max_concurrent_runs`` (PRD env default 3). The hard cap the
            dispatch gate enforces and the pause path accounts against.
    """

    def __init__(self, capacity: int = 3) -> None:
        if capacity < 1:
            raise ValueError("ConcurrencySlots capacity must be >= 1")
        self._capacity = capacity
        self._held = 0
        #: Lazily created on first async use, bound to the running loop. The sync
        #: pause path mutates ``_held`` + the semaphore's internal counter directly
        #: so it works even before the gate is first awaited.
        self._sem: asyncio.Semaphore | None = None

    @property
    def capacity(self) -> int:
        """The hard slot cap (``max_concurrent_runs``), enforced by the async gate."""
        return self._capacity

    @property
    def held(self) -> int:
        """How many slots are currently held by active (non-paused) runs."""
        return self._held

    @property
    def available(self) -> int:
        """Free-slot count (``capacity - held``, clamped at 0).

        The dispatch loop reads this to decide how many candidates it may even
        *attempt* this tick (it then awaits :meth:`acquire_async` per dispatch, which
        is the real gate). A wedge-free upper bound, never a substitute for the
        semaphore.
        """
        return max(0, self._capacity - self._held)

    def _semaphore(self) -> asyncio.Semaphore:
        """Return the loop-bound semaphore, creating it lazily on first async use.

        Constructed with the *currently-free* permit count (``capacity - held``) so
        if the sync pause path already moved the held count before the first async
        acquire, the semaphore starts consistent with it. Bound to the running loop
        (an ``asyncio.Semaphore`` must be created on the loop it is awaited on).
        """
        if self._sem is None:
            self._sem = asyncio.Semaphore(max(0, self._capacity - self._held))
        return self._sem

    async def acquire_async(self) -> None:
        """Await a concurrency permit for a run entering the active state (AC-1).

        The **dispatch gate**: blocks when all ``capacity`` slots are held until a
        running/paused run frees one. The single point the tick routes a launch
        through so ``> max_concurrent_runs`` candidates cannot all run at once — the
        excess await a permit (here, or queue for a later tick if the loop chose not
        to block). Increments :attr:`held` once the permit is taken.
        """
        await self._semaphore().acquire()
        self._held += 1

    @contextlib.asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Async context manager that holds a permit for the wrapped dispatch.

        ``async with slots.slot():`` awaits a permit on enter (the gate) and frees it
        on exit. Used where a launch's lifetime is scoped to a block; the long-lived
        run path uses :meth:`acquire_async` + an explicit :meth:`release` at run end.
        """
        await self.acquire_async()
        try:
            yield
        finally:
            self.release()

    def acquire(self) -> None:
        """Synchronously take a slot (the pause **resume** re-acquire — INV-9).

        Called by the pause bridge when a paused run resumes — it re-takes the slot
        it released on pause (§8.5). Synchronous so the resume path does not add an
        await point inside the engine ``await`` round-trip. Mutates the **same**
        semaphore the async gate awaits (decrements its permit count) so the resumed
        run genuinely re-occupies a dispatch slot. Best-effort: if the gate raced the
        whole capacity away, ``held`` still tracks truthfully (it may transiently
        exceed capacity for the resuming run, mirroring real over-subscription, and
        the semaphore is left non-negative).
        """
        self._held += 1
        if self._sem is not None:
            # Mirror the take on the loop-bound semaphore so the async gate sees one
            # fewer free permit. Guard against driving it negative if already at 0.
            if self._sem._value > 0:  # noqa: SLF001  # DKMVP-ESCAPE: shared sem counter; sync pause must mirror the async gate's permit count (INV-9)
                self._sem._value -= 1  # noqa: SLF001  # DKMVP-ESCAPE: same shared semaphore as the async dispatch gate

    def release(self) -> None:
        """Synchronously hand back a slot (the pause **release** — INV-9 / T086).

        Called by the pause bridge when the run parks at ``await on_pause`` — the
        container is genuinely idle, so the slot is freed and a **queued candidate
        can take it** (this is what makes a pause release a dispatch slot — INV-9 not
        regressed). Clamped at zero held so a double-release can never manufacture
        phantom capacity; the semaphore is never pushed above its capacity.
        """
        if self._held <= 0:
            return
        self._held -= 1
        if self._sem is not None:
            # Hand the permit back to the async gate (so a blocked dispatch wakes),
            # but never above capacity (a spurious release must not inflate it).
            if self._sem._value < self._capacity:  # noqa: SLF001  # DKMVP-ESCAPE: shared sem counter; bound the give-back at capacity
                self._sem.release()
