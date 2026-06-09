"""In-memory keyed-future registry — the await/resume rendezvous for HITL (§8.5).

The pause bridge writes a durable ``pause_decisions`` row, then **awaits an
``asyncio.Future`` keyed by ``decision_id``** (§8.5 step 2). The answer endpoint
(and the timeout sweep) resolve the decision in the DB via the INV-9 exactly-once
guard and — **only when that guarded UPDATE won (rowcount==1)** — fire the keyed
future so the awaiting ``on_pause`` callback returns its :class:`PauseResponse`
and the engine resumes (§8.5 step 3).

This registry is the in-memory half of that handshake. It is **single-loop,
single-process** (ADR-P001): the future is created and resolved on the same event
loop, so no thread-safety machinery is needed. It deliberately holds **only**
volatile state — the durable truth is the ``pause_decisions`` row. Across a
backend restart the future is gone (and so is the suspended run, §8.5.5); the
*decision* survives in the DB, the run is re-launchable from the last pushed
boundary, and the code never promises in-place recovery of the suspended coroutine.
"""

from __future__ import annotations

import asyncio


class DecisionRegistry:
    """Process-wide ``{decision_id: Future[PauseResponse-payload]}`` rendezvous.

    Composed once on ``app.state`` (one loop, one registry — like the
    :class:`~app.sse.observer_bridge.StreamRegistry`). The pause bridge
    :meth:`register`-s a future before awaiting it; the answer endpoint / timeout
    sweep :meth:`resolve`-s it after winning the DB guard. The payload is the
    resolved decision (``answers`` + ``skip_remaining``) the bridge turns into a
    :class:`dkmv.tasks.pause.PauseResponse`.
    """

    def __init__(self) -> None:
        self._waiters: dict[str, asyncio.Future[dict[str, object]]] = {}

    def register(self, decision_id: str) -> asyncio.Future[dict[str, object]]:
        """Create + store the future the pause bridge awaits for ``decision_id``.

        Idempotent for a given id within one process: re-registering returns the
        existing (unresolved) future rather than orphaning the awaiter. The future
        is created on the running loop (the serving loop the bridge awaits on).
        """
        existing = self._waiters.get(decision_id)
        if existing is not None and not existing.done():
            return existing
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, object]] = loop.create_future()
        self._waiters[decision_id] = future
        return future

    def resolve(self, decision_id: str, payload: dict[str, object]) -> bool:
        """Fire the keyed future with the resolved decision payload; True if fired.

        Called **only** by a caller that already won the DB exactly-once guard
        (rowcount==1), so this never double-fires a settled future in the normal
        path; the ``done()`` check is a belt-and-braces guard against a late
        duplicate. Returns ``False`` when there is no registered waiter (e.g. the
        run's coroutine is gone after a restart — the decision is durable but the
        suspended run is not, §8.5.5).
        """
        future = self._waiters.get(decision_id)
        if future is None or future.done():
            return False
        future.set_result(payload)
        return True

    def discard(self, decision_id: str) -> None:
        """Forget a settled decision's future (the bridge calls this after resume)."""
        self._waiters.pop(decision_id, None)

    def pending_count(self) -> int:
        """Number of un-resolved waiters (test/observability hook)."""
        return sum(1 for f in self._waiters.values() if not f.done())
