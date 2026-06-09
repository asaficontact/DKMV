"""Concurrency-slot accounting + the Phase-5 admission gate (AC-1 / INV-9).

A paused run is **genuinely idle** — the agent process is not running and the
container is parked at ``await on_pause`` (§8.5). So while a human is away it must
**not** occupy a ``max_concurrent_runs`` slot (a held 8 GB container under a 3-slot
cap is too costly — the reason the pause timeout defaults to 60 min, not 24 h).

This module is the **slot-accounting primitive** (T086) the HITL pause bridge
consumes (release on pause, re-acquire on resume) **and** — as of Phase 5 (T111) —
the **bounded-concurrency gate** the dispatch loop awaits. Both surfaces operate on
**one** ``_held`` counter (the single source of truth) bounded by ``capacity`` so
they cannot drift:

* **Dispatch gate (async, Phase 5).** :meth:`acquire_async` / :meth:`slot` ``await``
  until ``_held < capacity`` (parking on a FIFO of waiter futures when full), then
  increment ``_held`` — it **blocks when full** so a tick that finds more candidates
  than free slots dispatches only ``available`` of them and the rest queue for a
  later tick. ``> max_concurrent_runs`` issues → only N run at once; the rest drain
  as slots free (NFR-SCALE-1).
* **Pause release/reacquire (sync, Phase 2 — INV-9).** The pause bridge calls the
  *synchronous* :meth:`release` when a run parks (decrementing ``_held`` so a queued
  candidate can take the slot) and :meth:`acquire` when it resumes (incrementing
  ``_held`` back). These stay **synchronous** because the bridge runs them inline on
  the serving loop around the engine ``await`` and must not introduce a new await
  point that could deadlock the resume. They mutate the **same** ``_held`` counter
  the async gate reads + waits on, so a pause genuinely frees a dispatch slot — and
  a sync :meth:`release` **wakes the next FIFO waiter** so a blocked
  :meth:`acquire_async` resumes (INV-9 not regressed).

The waiter set is a FIFO of plain ``asyncio.Future``\\s created on the running loop
on demand, so there is **no** loop-bound primitive to construct eagerly and **no**
private-attribute mutation of any stdlib object: ``_held`` is the only state, and a
release pops and resolves the oldest waiter. The held count never goes below zero (a
defensive clamp) so a double-release / spurious resume can't manufacture phantom
capacity; ``_held`` only ever tracks the truth (it may transiently exceed
``capacity`` for a resuming paused run, mirroring real over-subscription).

Single-loop, single-process (PRD §8.3 / ADR-P001): one orchestrator per process.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from collections.abc import AsyncIterator


class ConcurrencySlots:
    """Counter-backed concurrency slots: dispatch gate + pause accounting (T111).

    Tracks how many runs currently **hold** a concurrency slot (``_held``) against a
    fixed ``capacity`` (``max_concurrent_runs``). ``_held`` is the **single source of
    truth** — the async dispatch gate parks until ``_held < capacity`` and the sync
    pause path mutates the same counter and wakes a parked waiter. A launched run holds
    one (taken via the async :meth:`acquire_async` dispatch gate); a paused run
    :meth:`release`-s it (it is idle) and :meth:`acquire`-s it back on resume. When all
    slots are held :meth:`acquire_async` blocks until one frees (AC-1 / NFR-SCALE-1).

    Args:
        capacity: ``max_concurrent_runs`` (PRD env default 3). The hard cap the
            dispatch gate enforces and the pause path accounts against.
    """

    def __init__(self, capacity: int = 3) -> None:
        if capacity < 1:
            raise ValueError("ConcurrencySlots capacity must be >= 1")
        self._capacity = capacity
        self._held = 0
        #: FIFO of futures for dispatch-gate callers blocked because all slots are
        #: held. A :meth:`release` (run completes/pauses) pops + resolves the oldest
        #: so the longest-waiting candidate drains first. Plain futures created on the
        #: running loop on demand — no eagerly-constructed loop-bound primitive.
        self._waiters: deque[asyncio.Future[None]] = deque()

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
        is the real gate). A wedge-free upper bound, never a substitute for the wait.
        """
        return max(0, self._capacity - self._held)

    async def acquire_async(self) -> None:
        """Await a concurrency permit for a run entering the active state (AC-1).

        The **dispatch gate**: takes a slot immediately when ``_held < capacity``;
        otherwise parks on the FIFO until a :meth:`release` wakes it, then re-checks
        and takes the slot. The single point the tick routes a launch through so
        ``> max_concurrent_runs`` candidates cannot all run at once — the excess await
        a free slot here (or queue for a later tick if the loop chose not to block).
        Increments :attr:`held` once the slot is taken.
        """
        while self._held >= self._capacity:
            waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            self._waiters.append(waiter)
            try:
                await waiter
            except BaseException:
                # Cancelled/errored while parked: drop our slot from the FIFO and, if
                # we'd already been handed the wake, pass it on so no slot is stranded.
                self._discard_waiter(waiter)
                raise
        self._held += 1

    def _discard_waiter(self, waiter: asyncio.Future[None]) -> None:
        """Remove a cancelled waiter; if it was already woken, re-wake the next one."""
        with contextlib.suppress(ValueError):
            self._waiters.remove(waiter)
            return
        # Not in the queue → it had already been resolved (handed a wake) but the
        # awaiter was cancelled before consuming it; pass the wake on so the slot a
        # release freed for it is not lost.
        if waiter.cancelled():
            self._wake_one()

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
        await point inside the engine ``await`` round-trip. Increments the **same**
        ``_held`` counter the async gate reads so the resumed run genuinely re-occupies
        a dispatch slot. Best-effort: if the gate already handed every slot out, the
        resuming run's ``_held`` may transiently exceed ``capacity`` — that mirrors
        real over-subscription and ``_held`` still tracks truthfully.
        """
        self._held += 1

    def release(self) -> None:
        """Synchronously hand back a slot (the pause **release** — INV-9 / T086).

        Called by the pause bridge when the run parks at ``await on_pause`` — the
        container is genuinely idle, so the slot is freed and a **queued candidate
        can take it** (this is what makes a pause release a dispatch slot — INV-9 not
        regressed). Decrements the single ``_held`` counter (clamped at zero so a
        double-release can never manufacture phantom capacity) and **wakes the next
        FIFO waiter** so a blocked :meth:`acquire_async` resumes and re-checks
        ``_held < capacity``.
        """
        if self._held <= 0:
            return
        self._held -= 1
        self._wake_one()

    def _wake_one(self) -> None:
        """Resolve the oldest still-pending dispatch-gate waiter, if any (INV-9).

        Synchronous and loop-safe: the waiters are plain futures created on this
        loop, so resolving one schedules its awaiter without an ``await`` here — which
        is exactly why :meth:`release` can wake the async gate from the sync pause
        path. Cancelled waiters are skipped (their slot is freed but no one is
        waiting on it).
        """
        while self._waiters:
            waiter = self._waiters.popleft()
            if not waiter.done():
                waiter.set_result(None)
                return
