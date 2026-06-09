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

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.db.repository import Repository
    from app.hitl.slots import ConcurrencySlots
    from app.orchestrator.admission import AdmissionController
    from app.orchestrator.tick import Candidate, DispatchFn

_log = logging.getLogger(__name__)

#: Statuses whose runs currently HOLD a concurrency slot (the resync target). A
#: ``paused`` run is excluded — it RELEASED its slot at the pause point (INV-9), so
#: counting it would double-reserve. Terminal statuses hold nothing. ``pending``
#: (claimed, container starting) + ``running`` + ``stopping`` each hold one.
SLOT_HOLDING_STATUSES: tuple[str, ...] = ("pending", "running", "stopping")


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

    async def _resync_slots(self, repo: str) -> None:
        """Reconcile the held-slot count DOWN to the DB's slot-holding run count.

        The DB is authoritative (ADR-P001 / NFR-PORT-1): a run that finished, was
        stopped, or was interrupted since last tick no longer holds a slot, but the
        in-memory semaphore still counts the permit it took at dispatch. Each pass we
        compute the true slot-holding count (running/pending/stopping — a *paused*
        run already released its slot via the bridge, INV-9) and **release** the
        excess so completed runs' slots drain and queued candidates can take them
        (AC-1: "the rest queue, then drain as slots free"). This only ever releases
        drifted permits — it never acquires — so it cannot manufacture capacity or
        over-admit. A run that the bridge already released (paused) is not
        double-counted because it is excluded from the slot-holding set.
        """
        # ``read_active_run_memory`` (not ``read_active_runs``) is the count source —
        # it does NOT filter ``issue_num IS NOT NULL``, so a run with no issue (a
        # direct ``POST /runs`` launch) still counts toward its held slot.
        rows = await self.repository.read_active_run_memory(repo, list(SLOT_HOLDING_STATUSES))
        active = len(rows)
        # Release any permits held beyond the true active count (completed runs).
        while self.slots.held > active:
            self.slots.release()

    async def dispatch_candidates(self, repo: str, candidates: list[Candidate]) -> DispatchResult:
        """Dispatch UP TO ``available`` admitted candidates this tick (AC-1/2/3).

        Iterates the (already-sorted) candidates and, for each, enforces the
        per-state cap → the count semaphore (only attempt while slots are free) →
        aggregate admission. An admitted candidate is launched through the existing
        ``launch_run`` boundary; the permit it took is **kept by the run** (released
        by the run's completion/pause path). A denied / state-capped / lost-claim
        candidate is **re-queued** (left for a later tick) and any permit taken for it
        is handed straight back. Returns a :class:`DispatchResult` for the gauges.
        """
        # Reclaim slots of runs that completed since last tick (DB-authoritative) so
        # queued candidates can drain into the freed slots (AC-1).
        await self._resync_slots(repo)

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

            # 2. Count semaphore (AC-1): only attempt while a slot is free this tick.
            #    A held slot frees asynchronously (run completes/pauses) → re-evaluated
            #    next tick; we do not block the whole tick on a held slot.
            if self.slots.available <= 0:
                # No free slots — every remaining candidate queues for a later tick.
                break

            # Take the permit (does not block: available > 0 here). The run keeps it
            # on success; on admission-deny / failed launch we hand it back below.
            await self.slots.acquire_async()
            try:
                # 3. Aggregate admission (AC-3): memory + daily-spend (Codex-excluded).
                decision = await self.admission.evaluate(repo, run_memory=candidate.memory)
                if not decision.admitted:
                    admission_denied += 1
                    _log.info(
                        "dispatch re-queue issue=%s reason=%s (admission denied)",
                        candidate.num,
                        decision.reason,
                    )
                    self.slots.release()  # hand the permit back — never drop the candidate
                    continue

                result = await self.dispatch(candidate)
            except BaseException:
                # A launch error must not strand the slot it took.
                self.slots.release()
                raise

            if result is None:
                # Lost the claim race (INV-5) / transient reject → re-queue + free slot.
                self.slots.release()
                continue

            # Launched: the run now holds the permit (released by its lifecycle path).
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

    v1 ships **no** per-state throttle by default (the global semaphore + aggregate
    admission are the bounds); the seam exists so an operator can throttle a state
    without a code change. If a future ``PER_STATE_CAPS`` setting is added it parses
    here; absent it, the policy is empty (uncapped per-state). Kept as a builder so
    the tick wires one policy from the one settings object.
    """
    raw = getattr(settings, "PER_STATE_CAPS", None)
    if not raw:
        return DispatchPolicy()
    per_state: dict[str, int] = {}
    for pair in str(raw).split(","):
        if ":" not in pair:
            continue
        label, _, cap = pair.partition(":")
        label = label.strip()
        if label and cap.strip().isdigit():
            per_state[label] = int(cap.strip())
    return DispatchPolicy(per_state=per_state)


__all__ = [
    "BoundedDispatcher",
    "DispatchPolicy",
    "DispatchResult",
    "build_policy_from_settings",
]
