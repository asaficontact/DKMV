"""Bounded, admitted dispatch — the Phase-5 cap layered into the tick (AC-1/2/3).

Phase 3 dispatched **one** candidate per tick (serial, no cap). Phase 5 layers the
concurrency cap + aggregate admission + per-state caps **into the same** dispatch
path — it does **not** add a second launch mechanism. The tick still calls the
existing ``launch_run`` boundary (ADR-P001) via the same ``dispatch`` callable; this
module is the **gate** in front of it. Per tick:

1. **Per-state caps (AC-2).** Optionally throttle how many candidates of a given
   ``agent:*`` state may dispatch this tick (e.g. cap ``agent:queued``). Candidates
   over a configured per-state cap are **left queued** for a later tick.
2. **Count semaphore (AC-1).** Acquire a permit from
   :class:`app.hitl.slots.ConcurrencySlots` — the SAME semaphore a pause releases
   and a resume re-acquires (INV-9 not regressed). ``> max_concurrent_runs``
   candidates → only ``available`` slots dispatch; the rest queue, then drain as
   slots free. The loop dispatches **up to** ``available`` candidates per tick (not
   just one) — it does not *block* a tick waiting for a held slot (a held slot frees
   asynchronously when its run completes/pauses), it dispatches what fits now and
   re-evaluates next tick.
3. **Aggregate admission (AC-3).** For each candidate that would take a slot, the
   :class:`app.orchestrator.admission.AdmissionController` checks
   ``Σ memory + this run ≤ HOST_MEMORY_BUDGET`` and ``Σ today's spend ≤
   DAILY_SPEND_CAP`` (Codex-excluded — INV-8). A denied candidate **re-queues** (the
   permit is handed straight back, the candidate is skipped this tick) — never
   dropped, never dispatched over budget.

A dispatched candidate **keeps** its slot for the lifetime of its run; a *failed*
launch (admitted but ``launch_run`` returned ``None`` / raised) **releases** the
permit it took so a lost-claim race does not strand a slot. A run's slot is
reclaimed two ways, both honoured here:

* **Pause** releases the slot synchronously via the bridge (INV-9), and **resume**
  re-acquires it — the SAME semaphore, so a paused run frees a dispatch slot.
* **Completion** is reclaimed by a per-pass **resync** (:meth:`_resync_slots`): the
  DB is authoritative (NFR-PORT-1 / ADR-P001), so at the top of each pass the held
  count is reconciled **down** to the number of slot-holding (active, non-paused)
  runs in the DB. A run that finished since last tick (now terminal) thus frees its
  slot the next tick — restart-safe and without coupling the permit lifetime to a
  fragile cross-module task hook. The resync only ever *releases* drifted permits
  (it never fabricates capacity), so it cannot over-admit.

Nothing here touches ``dkmv/`` or the CLI; admission + resync are pure reads.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.orchestrator.statuses import SLOT_HOLDING_STATUSES

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.db.repository import Repository
    from app.hitl.slots import ConcurrencySlots
    from app.orchestrator.admission import AdmissionController
    from app.orchestrator.tick import Candidate, DispatchFn

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """The outcome of one bounded-dispatch pass (for the tick + the gauges).

    ``dispatched`` is the list of :class:`LaunchResult`\\s launched this tick (up to
    the free-slot count); ``admission_denied`` / ``state_capped`` count the
    candidates re-queued for a later tick (denied by the aggregate caps, or throttled
    by a per-state cap) so the heartbeat can report the backlog being shed. ``seen``
    is the total candidate count the gate evaluated (the queue depth gauge).
    """

    dispatched: tuple[Any, ...] = ()
    admission_denied: int = 0
    state_capped: int = 0
    seen: int = 0


@dataclass(slots=True)
class DispatchPolicy:
    """The per-state caps the bounded dispatcher enforces (AC-2).

    Maps a candidate ``agent:*`` state label to the max number of candidates of that
    state that may dispatch **per tick** (e.g. ``{"agent:queued": 2}`` throttles the
    queued state to two launches a tick so a flood of new issues drains gradually).
    A state absent from the map is uncapped (only the global count semaphore +
    admission bound it). The default policy is empty (no per-state throttle — the
    count semaphore is the only count bound), matching the PRD default posture.
    """

    per_state: dict[str, int] = field(default_factory=dict)

    def cap_for(self, labels: tuple[str, ...]) -> int | None:
        """Return the tightest per-state cap that applies to a candidate, or ``None``.

        A candidate may carry several ``agent:*`` labels; the most restrictive
        configured cap wins so no per-state throttle is exceeded. ``None`` means no
        per-state cap applies (the candidate is bounded only by the global semaphore
        + admission).
        """
        caps = [self.per_state[label] for label in labels if label in self.per_state]
        return min(caps) if caps else None


@dataclass(slots=True)
class BoundedDispatcher:
    """Gates the existing ``launch_run`` dispatch with the cap + admission (AC-1/2/3).

    Composed from the SAME ``dispatch`` callable the Phase-3 tick used (so there is
    exactly ONE launch path — ADR-P001), the shared
    :class:`~app.hitl.slots.ConcurrencySlots` semaphore (so the cap and the pause
    release/reacquire share one permit pool — INV-9), the aggregate
    :class:`~app.orchestrator.admission.AdmissionController`, and the per-state
    :class:`DispatchPolicy`. :meth:`dispatch_candidates` is the per-tick entry point.
    """

    dispatch: DispatchFn
    slots: ConcurrencySlots
    admission: AdmissionController
    repository: Repository
    policy: DispatchPolicy = field(default_factory=DispatchPolicy)

    def _resync_slots_from_rows(self, memory_rows: list[dict[str, Any]]) -> None:
        """Reconcile the held-slot count DOWN to the DB's slot-holding run count.

        The DB is authoritative (ADR-P001 / NFR-PORT-1): a run that finished, was
        stopped, or was interrupted since last tick no longer holds a slot, but the
        in-memory counter still counts the slot it took at dispatch. Each pass we
        compute the true slot-holding count (running/pending/stopping — a *paused*
        run already released its slot via the bridge, INV-9) and **release** the
        excess so completed runs' slots drain and queued candidates can take them
        (AC-1: "the rest queue, then drain as slots free"). This only ever releases
        drifted slots — it never acquires — so it cannot manufacture capacity or
        over-admit. A run that the bridge already released (paused) is not
        double-counted because it is excluded from the slot-holding set.

        Takes the **already-read** memory-holding rows (read once per tick — the
        MINOR double-read fix) and filters them to the slot-holding subset locally,
        so the resync shares the same read the admission baseline uses. The rows are
        from ``read_active_run_memory`` (not ``read_active_runs``) which does NOT
        filter ``issue_num IS NOT NULL``, so a run with no issue (a direct
        ``POST /runs`` launch) still counts toward its held slot.
        """
        slot_holding = {s for s in SLOT_HOLDING_STATUSES}
        active = sum(1 for row in memory_rows if str(row.get("status")) in slot_holding)
        # Release any slots held beyond the true active count (completed runs).
        while self.slots.held > active:
            self.slots.release()

    async def dispatch_candidates(self, repo: str, candidates: list[Candidate]) -> DispatchResult:
        """Dispatch UP TO ``available`` admitted candidates this tick (AC-1/2/3).

        Reads the aggregate admission inputs **once at the top of the tick** (PERF):
        a single ``read_active_run_memory`` (the memory-holding rows — also the source
        for the slot resync, shared) + a single ``spend_today``. Then iterates the
        (already-sorted) candidates and, for each, enforces the per-state cap → the
        count gate (only attempt while slots are free) → the **pure** aggregate
        admission ``decide`` against an **in-memory running memory total** (baseline Σ
        memory + memory of runs admitted so far this tick + this candidate's memory ≤
        ``HOST_MEMORY_BUDGET``; spend constant). So admission costs O(1) DB reads per
        tick, not O(C) — yet the decision is identical (same deny+requeue, same
        Codex-excluded spend INV-8). An admitted candidate is launched through the
        existing ``launch_run`` boundary; the slot it took is **kept by the run**
        (released by its completion/pause path). A denied / state-capped / lost-claim
        candidate is **re-queued** (left for a later tick) and any slot taken for it
        is handed straight back. Returns a :class:`DispatchResult` for the gauges.
        """
        from app.orchestrator.admission import (
            DEFAULT_MEMORY as _DEFAULT_MEMORY,
        )
        from app.orchestrator.admission import (
            MEMORY_HOLDING_STATUSES,
            parse_memory_bytes,
        )
        from app.orchestrator.admission import (
            sum_memory_bytes as _sum_memory_bytes,
        )

        # ── ONE per-tick aggregate read (PERF): the memory-holding rows + spend. ──
        memory_rows = await self.repository.read_active_run_memory(
            repo, list(MEMORY_HOLDING_STATUSES)
        )
        # Reclaim slots of runs that completed since last tick (DB-authoritative),
        # reusing the rows just read (shared single read — the MINOR fix). Queued
        # candidates can then drain into the freed slots (AC-1).
        self._resync_slots_from_rows(memory_rows)

        # Build the per-tick admission snapshot from the shared memory read + one
        # spend read. ``spent_today`` is constant within the tick (dispatching adds no
        # cost); ``baseline_memory`` is the start-of-tick Σ memory. Per-candidate
        # admission then adds the in-memory ``admitted_memory`` running total.
        baseline_memory = _sum_memory_bytes(memory_rows)
        spent_today = await self.repository.spend_today(repo, since_iso=self._since_iso())
        snapshot = self.admission.build_snapshot(
            baseline_memory_bytes=baseline_memory, spent_today_usd=spent_today
        )
        admitted_memory = 0  # Σ memory of runs admitted so far THIS tick (in-memory).

        dispatched: list[Any] = []
        admission_denied = 0
        state_capped = 0
        state_used: Counter[str] = Counter()

        for candidate in candidates:
            # 1. Per-state cap (AC-2): would this candidate's state exceed its per-tick
            #    throttle? If so, leave it queued (re-evaluated next tick).
            cap = self.policy.cap_for(candidate.labels)
            if cap is not None:
                state_label = self._capped_state(candidate.labels, cap_keys=self.policy.per_state)
                if state_label is not None and state_used[state_label] >= cap:
                    state_capped += 1
                    continue

            # 2. Count gate (AC-1): only attempt while a slot is free this tick. A held
            #    slot frees asynchronously (run completes/pauses) → re-evaluated next
            #    tick; we do not block the whole tick on a held slot.
            if self.slots.available <= 0:
                # No free slots — every remaining candidate queues for a later tick.
                break

            # 3. Aggregate admission (AC-3): the PURE per-candidate decision against
            #    the per-tick snapshot + the in-memory admitted-memory total (no DB
            #    read). Evaluated BEFORE taking the slot so a denied candidate never
            #    even touches the gate (identical deny+requeue behaviour).
            decision = self.admission.decide(
                snapshot,
                run_memory=candidate.memory,
                admitted_memory_bytes=admitted_memory,
            )
            if not decision.admitted:
                admission_denied += 1
                _log.info(
                    "dispatch re-queue issue=%s reason=%s (admission denied)",
                    candidate.num,
                    decision.reason,
                )
                continue

            # Take the slot (does not block: available > 0 here). The run keeps it on
            # success; on a failed launch we hand it back below.
            await self.slots.acquire_async()
            try:
                result = await self.dispatch(candidate)
            except BaseException:
                # A launch error must not strand the slot it took.
                self.slots.release()
                raise

            if result is None:
                # Lost the claim race (INV-5) / transient reject → re-queue + free slot.
                self.slots.release()
                continue

            # Launched: the run now holds the slot (released by its lifecycle path).
            # Add its memory to the in-memory running total so the NEXT candidate this
            # tick is sized against it (keeps the memory bound real without a re-read).
            admitted_memory += parse_memory_bytes(candidate.memory or _DEFAULT_MEMORY)
            dispatched.append(result)
            state_label = self._capped_state(candidate.labels, cap_keys=self.policy.per_state)
            if state_label is not None:
                state_used[state_label] += 1

        return DispatchResult(
            dispatched=tuple(dispatched),
            admission_denied=admission_denied,
            state_capped=state_capped,
            seen=len(candidates),
        )

    def _since_iso(self) -> str:
        """The UTC start-of-day boundary for the per-tick spend read (shared clock).

        Uses the admission controller's injected clock so a frozen-clock test drives
        the same UTC-day window the per-candidate path used.
        """
        from app.orchestrator.admission import start_of_utc_day

        return start_of_utc_day(now=self.admission.now)

    @staticmethod
    def _capped_state(labels: tuple[str, ...], *, cap_keys: dict[str, int]) -> str | None:
        """The candidate's capped state label (the tightest configured one), if any.

        Picks the label that the tightest cap applies to so the per-tick usage count
        is attributed to the right state. ``None`` when no configured state applies.
        """
        applicable = [(cap_keys[label], label) for label in labels if label in cap_keys]
        if not applicable:
            return None
        return min(applicable)[1]


def build_policy_from_settings(settings: Any) -> DispatchPolicy:
    """Build the :class:`DispatchPolicy` from settings (AC-2).

    v1 ships **no** per-state throttle by default (the global concurrency cap +
    aggregate admission are the bounds); the seam exists so an operator can throttle
    a state without a code change. The typed :attr:`Settings.PER_STATE_CAPS` field
    parses the ``'label:cap,label:cap'`` env string into a ``{label: cap}`` dict at
    settings-load time (alongside the other admission knobs), so this builder simply
    surfaces it onto the :class:`DispatchPolicy`. Absent / empty → an uncapped policy.
    Kept as a builder so the tick wires one policy from the one settings object.
    """
    caps = getattr(settings, "PER_STATE_CAPS", None) or {}
    return DispatchPolicy(per_state=dict(caps))


__all__ = [
    "SLOT_HOLDING_STATUSES",
    "BoundedDispatcher",
    "DispatchPolicy",
    "DispatchResult",
    "build_policy_from_settings",
]
