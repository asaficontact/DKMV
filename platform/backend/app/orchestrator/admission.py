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

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.config import Settings
    from app.db.repository import Repository

_log = logging.getLogger(__name__)

#: Active (non-terminal) run statuses whose containers hold host memory. A
#: ``paused`` run is genuinely idle and has *released* its slot, but its container
#: is still parked open holding memory (§8.5) — so it DOES count toward the memory
#: budget. ``pending`` (claimed, container starting) counts too. Terminal statuses
#: (``completed``/``failed``/``stopped``/``interrupted``) hold nothing.
MEMORY_HOLDING_STATUSES: tuple[str, ...] = ("pending", "running", "stopping", "paused")

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


@dataclass(slots=True)
class AdmissionController:
    """Evaluates a candidate's memory + daily-spend admission against the caps (AC-3).

    Composed from the typed :class:`Settings` (``HOST_MEMORY_BUDGET`` /
    ``DAILY_SPEND_CAP``) + the single-writer :class:`Repository` (read side). One per
    orchestrator; :meth:`evaluate` is called per candidate per tick **after** the
    count semaphore has a free slot but **before** the launch — a denial re-queues
    (the loop skips the candidate), an admit lets the launch proceed.
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
        total = 0
        for row in rows:
            mem = row.get("memory_limit") or DEFAULT_MEMORY
            total += parse_memory_bytes(str(mem))
        return total

    async def evaluate(self, repo: str, *, run_memory: str | None) -> AdmissionDecision:
        """Admit a candidate iff memory AND daily-spend both fit (AC-3, binding).

        Computes ``Σ(running memory) + this run's memory`` against
        ``HOST_MEMORY_BUDGET`` and today's **Codex-excluded** spend against
        ``DAILY_SPEND_CAP``. A disabled cap (``None``) passes that dimension. Returns
        a structured :class:`AdmissionDecision`; on denial the caller **re-queues**
        (skips this candidate this tick) — never drops, never dispatches over budget.
        """
        memory_budget = self._memory_budget_bytes
        candidate_memory = parse_memory_bytes(run_memory or DEFAULT_MEMORY)
        running_memory = await self._running_memory_bytes(repo)
        projected_memory = running_memory + candidate_memory

        spend_cap = self._spend_cap_usd
        since_iso = start_of_utc_day(now=self.now)
        spent_today = await self.repository.spend_today(repo, since_iso=since_iso)

        # Memory dimension: only enforced when a budget is configured.
        if memory_budget is not None and projected_memory > memory_budget:
            _log.info(
                "admission DENY repo=%s reason=memory projected=%d budget=%d",
                repo,
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
                "admission DENY repo=%s reason=spend spent=%.4f cap=%.4f",
                repo,
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


__all__ = [
    "DEFAULT_MEMORY",
    "MEMORY_HOLDING_STATUSES",
    "AdmissionController",
    "AdmissionDecision",
    "parse_memory_bytes",
    "start_of_utc_day",
]
