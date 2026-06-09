"""Aggregate-resource admission for dispatch (PRD §8.2 / NFR-SCALE-1 — AC-3).

The ``asyncio.Semaphore`` (slice 5.1 / :mod:`app.hitl.slots`) bounds the *count* of
concurrent runs, but a count alone does not bound the two **expensive** dimensions:
total host **memory** committed to live sandbox containers and total **money** spent
today. A 3-slot cap of 8 GB containers can still OOM a 16 GB host, and three Claude
runs can still blow the daily budget. So a candidate is admitted **only if BOTH**:

* ``Σ(running container memory) + this run's memory ≤ HOST_MEMORY_BUDGET`` — and
* ``Σ(today's spend) ≤ DAILY_SPEND_CAP``.

**Codex exclusion (INV-8 / FR-06-1a).** The daily-spend side reads the Phase-0
**Codex-excluded** spend projection: a Codex run reports ``$0`` from the engine and
**never trips the spend cap**. Its **memory still counts** toward the memory budget
(a Codex container is just as real). The asymmetry is deliberate — Codex is
time-bounded, not cost-bounded (§7.2), so only its memory is a governed resource.

**Denial re-queues, never drops (binding).** A denied candidate is **left in the
queue** (it keeps its ``agent:queued`` label and active-run-free state) so a *later*
tick — once a running run completes and frees memory, or the UTC day rolls and the
spend window resets — re-evaluates and admits it. Admission returns a structured
:class:`AdmissionDecision`; the dispatch loop **skips** a denied candidate (does not
launch it, does not delete it). It is never silently dropped and never dispatched
over budget.

A disabled cap (``HOST_MEMORY_BUDGET`` / ``DAILY_SPEND_CAP`` = ``None``) is treated
as "no limit on that dimension" — that dimension always passes (the count semaphore
still bounds concurrency). Pure reads through the repository seam (NFR-PORT-1);
nothing here writes, touches ``dkmv/``, or shells the CLI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.orchestrator.deadlines import Clock, to_iso, utc_now
from app.orchestrator.statuses import MEMORY_HOLDING_STATUSES

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.config import Settings
    from app.db.repository import Repository

_log = logging.getLogger(__name__)

#: Fallback per-container memory when a run row stored no ``memory_limit`` (the
#: launch default — :data:`app.runs.service.DEFAULT_MEMORY`). Kept here as a string
#: so the same parser handles it; a candidate/run with no explicit memory is sized
#: at the platform default rather than treated as free.
DEFAULT_MEMORY = "8g"


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    """The outcome of evaluating one candidate against the aggregate caps (AC-3).

    ``admitted`` is the gate the dispatch loop branches on. ``reason`` is one of
    ``"ok"`` / ``"memory"`` / ``"spend"`` for the heartbeat log + tests so a denial
    is attributable to the dimension that tripped (and a test asserts a memory-over
    vs a spend-over candidate is denied for the right reason). ``projected_memory_*``
    / ``projected_spend`` carry the numbers the decision was made on (for the
    observability gauges + assertions).
    """

    admitted: bool
    reason: str
    projected_memory_bytes: int
    memory_budget_bytes: int | None
    projected_spend_usd: float
    spend_cap_usd: float | None


def parse_memory_bytes(value: str | None) -> int:
    """Parse a Docker-style memory string (``'8g'`` / ``'512m'`` / ``'1024'``) → bytes.

    Accepts the same ``<number><unit>`` shape the engine/Docker use (``b``/``k``/
    ``m``/``g``, case-insensitive; bare number = bytes). Returns ``0`` for ``None``
    / empty / unparseable so a malformed cell never crashes a tick — it is sized at
    zero rather than blocking the whole loop (the count semaphore still bounds it).
    """
    if not value:
        return 0
    text = value.strip().lower()
    if not text:
        return 0
    units = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
    unit = text[-1]
    if unit in units:
        number = text[:-1]
        factor = units[unit]
    else:
        number = text
        factor = 1
    try:
        return int(float(number) * factor)
    except ValueError:
        return 0


def sum_memory_bytes(rows: list[dict[str, object]]) -> int:
    """Σ parsed ``memory_limit`` over memory-holding run rows (the admission baseline).

    Each row's ``memory_limit`` is parsed (a missing/empty cell sized at the platform
    :data:`DEFAULT_MEMORY` so a run is never treated as free — under-counting would
    over-commit the budget). Shared by the controller's per-call read and the dispatch
    loop's single per-tick read so both size memory identically.
    """
    total = 0
    for row in rows:
        mem = row.get("memory_limit") or DEFAULT_MEMORY
        total += parse_memory_bytes(str(mem))
    return total


def start_of_utc_day(*, now: Clock = utc_now) -> str:
    """The UTC start-of-day ISO boundary for the daily-spend window (AC-3).

    Re-evaluated each admission against a fresh ``now()`` (never cached) so the
    spend window rolls over at the UTC midnight automatically — a candidate denied
    near a day boundary is admitted on the next tick once the day flips and the
    window resets. Injectable clock so a frozen-clock test drives the window.
    """
    moment = now()
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return to_iso(midnight)


@dataclass(frozen=True, slots=True)
class AdmissionSnapshot:
    """The per-tick aggregate snapshot of tick-invariant admission inputs (PERF).

    Both admission dimensions are read from the DB **once per tick**, not once per
    candidate, because neither rises from *dispatching* within a tick:

    * ``spent_today`` is **constant within the tick** — dispatching a run does not add
      cost (cost accrues from the run's later events, off-tick), and the UTC-day
      window is fixed for the pass. So a single read is exact for every candidate.
    * ``baseline_memory_bytes`` is the Σ memory of the runs already memory-holding at
      the **start** of the tick. As the tick admits runs, Σ memory rises only by the
      memory of runs **this tick** admitted — tracked in-memory by the caller
      (``admitted_memory_bytes``) and added on top of this baseline. So one baseline
      read + an in-memory running total reproduces the exact per-candidate
      ``Σ(running) + this`` the per-call path computed, with O(1) DB reads per tick
      instead of O(C).

    ``memory_budget_bytes`` / ``spend_cap_usd`` are the parsed caps (``None`` =
    disabled) carried so :meth:`AdmissionController.decide` is a pure function of the
    snapshot + the candidate.
    """

    baseline_memory_bytes: int
    memory_budget_bytes: int | None
    spent_today_usd: float
    spend_cap_usd: float | None


@dataclass(slots=True)
class AdmissionController:
    """Evaluates a candidate's memory + daily-spend admission against the caps (AC-3).

    Composed from the typed :class:`Settings` (``HOST_MEMORY_BUDGET`` /
    ``DAILY_SPEND_CAP``) + the single-writer :class:`Repository` (read side). One per
    orchestrator. The dispatch loop reads a single :meth:`snapshot` per tick (the
    tick-invariant aggregates) then calls the pure :meth:`decide` per candidate
    against an in-memory running total (O(1) DB reads/tick — PERF). The legacy
    per-candidate :meth:`evaluate` (snapshot+decide in one call) is retained for the
    single-shot callers/tests. A denial re-queues (the loop skips the candidate); an
    admit lets the launch proceed.
    """

    repository: Repository
    settings: Settings
    now: Clock = utc_now

    @property
    def _memory_budget_bytes(self) -> int | None:
        """Parsed ``HOST_MEMORY_BUDGET`` in bytes, or ``None`` (no memory cap)."""
        budget = self.settings.HOST_MEMORY_BUDGET
        if not budget:
            return None
        return parse_memory_bytes(budget)

    @property
    def _spend_cap_usd(self) -> float | None:
        """The ``DAILY_SPEND_CAP`` in USD, or ``None`` (no spend cap)."""
        return self.settings.DAILY_SPEND_CAP

    async def _running_memory_bytes(self, repo: str) -> int:
        """Σ memory of this repo's memory-holding runs (running/pending/paused).

        Reads the active runs' ``memory_limit`` and sums the parsed bytes. A run with
        no stored ``memory_limit`` is sized at the platform default so it is never
        treated as free (under-counting would let the budget be over-committed).
        """
        rows = await self.repository.read_active_run_memory(repo, list(MEMORY_HOLDING_STATUSES))
        return sum_memory_bytes(rows)

    def build_snapshot(
        self, *, baseline_memory_bytes: int, spent_today_usd: float
    ) -> AdmissionSnapshot:
        """Wrap pre-read aggregates + the parsed caps into an :class:`AdmissionSnapshot`.

        Lets the dispatch loop **share its single per-tick memory read** with this
        controller (the dispatcher already reads the memory-holding rows once for the
        slot resync — the MINOR double-read fix): it computes ``baseline_memory_bytes``
        from those rows and reads ``spent_today`` once, then hands both here so the
        snapshot carries the caps without re-reading the DB.
        """
        return AdmissionSnapshot(
            baseline_memory_bytes=baseline_memory_bytes,
            memory_budget_bytes=self._memory_budget_bytes,
            spent_today_usd=spent_today_usd,
            spend_cap_usd=self._spend_cap_usd,
        )

    async def snapshot(self, repo: str) -> AdmissionSnapshot:
        """Read the tick-invariant aggregate inputs ONCE per tick (PERF / AC-3).

        Issues exactly **two** DB reads — the baseline Σ memory of the runs already
        memory-holding at the start of the tick and today's Codex-excluded spend —
        plus the two parsed caps. The dispatch loop calls this once at the top of the
        tick and then evaluates every candidate against the snapshot via :meth:`decide`
        (adding the memory of runs admitted so far this tick in-memory), so admission
        costs O(1) DB reads per tick instead of O(C). Neither aggregate rises from
        dispatching within the tick (spend accrues off-tick; Σ memory rises only as
        THIS tick admits runs — tracked in-memory by the caller), so the single read
        is exact for every candidate.
        """
        return AdmissionSnapshot(
            baseline_memory_bytes=await self._running_memory_bytes(repo),
            memory_budget_bytes=self._memory_budget_bytes,
            spent_today_usd=await self.repository.spend_today(
                repo, since_iso=start_of_utc_day(now=self.now)
            ),
            spend_cap_usd=self._spend_cap_usd,
        )

    def decide(
        self,
        snapshot: AdmissionSnapshot,
        *,
        run_memory: str | None,
        admitted_memory_bytes: int = 0,
    ) -> AdmissionDecision:
        """Pure per-candidate decision against a per-tick :class:`AdmissionSnapshot`.

        Reproduces the exact per-call decision with **zero** DB reads: projected
        memory is ``baseline (start-of-tick Σ memory) + admitted_memory_bytes (runs
        THIS tick already admitted) + this candidate's memory``, and projected spend is
        the constant ``spent_today`` from the snapshot. ``admitted_memory_bytes`` is
        the running total the dispatch loop maintains in-memory across the tick so
        admitting run K accounts for runs 1..K-1 just admitted — identical to the old
        per-candidate re-read (each re-read would have seen those K-1 runs once their
        DB rows went live, but within a single tick they have not yet; the in-memory
        total is what keeps the bound real). A disabled cap (``None``) passes that
        dimension. On denial the caller **re-queues** — never drops, never over-budget.
        """
        candidate_memory = parse_memory_bytes(run_memory or DEFAULT_MEMORY)
        projected_memory = snapshot.baseline_memory_bytes + admitted_memory_bytes + candidate_memory
        memory_budget = snapshot.memory_budget_bytes
        spend_cap = snapshot.spend_cap_usd
        spent_today = snapshot.spent_today_usd

        # Memory dimension: only enforced when a budget is configured.
        if memory_budget is not None and projected_memory > memory_budget:
            _log.info(
                "admission DENY reason=memory projected=%d budget=%d",
                projected_memory,
                memory_budget,
            )
            return AdmissionDecision(
                admitted=False,
                reason="memory",
                projected_memory_bytes=projected_memory,
                memory_budget_bytes=memory_budget,
                projected_spend_usd=spent_today,
                spend_cap_usd=spend_cap,
            )

        # Spend dimension: Codex-excluded (INV-8) — a Codex run contributes $0 to
        # ``spent_today`` so it never trips this cap. Enforced only when configured.
        if spend_cap is not None and spent_today > spend_cap:
            _log.info(
                "admission DENY reason=spend spent=%.4f cap=%.4f",
                spent_today,
                spend_cap,
            )
            return AdmissionDecision(
                admitted=False,
                reason="spend",
                projected_memory_bytes=projected_memory,
                memory_budget_bytes=memory_budget,
                projected_spend_usd=spent_today,
                spend_cap_usd=spend_cap,
            )

        return AdmissionDecision(
            admitted=True,
            reason="ok",
            projected_memory_bytes=projected_memory,
            memory_budget_bytes=memory_budget,
            projected_spend_usd=spent_today,
            spend_cap_usd=spend_cap,
        )

    async def evaluate(self, repo: str, *, run_memory: str | None) -> AdmissionDecision:
        """Admit one candidate iff memory AND daily-spend both fit (AC-3, binding).

        The single-shot convenience path (a snapshot read + a :meth:`decide` with no
        prior in-tick admissions). The dispatch loop uses :meth:`snapshot` +
        :meth:`decide` directly to read the aggregates once per tick; this keeps the
        one-candidate callers/tests on a single call. A disabled cap (``None``) passes
        that dimension. On denial the caller **re-queues** — never drops, never over.
        """
        snap = await self.snapshot(repo)
        return self.decide(snap, run_memory=run_memory)


__all__ = [
    "DEFAULT_MEMORY",
    "MEMORY_HOLDING_STATUSES",
    "AdmissionController",
    "AdmissionDecision",
    "AdmissionSnapshot",
    "parse_memory_bytes",
    "start_of_utc_day",
    "sum_memory_bytes",
]
