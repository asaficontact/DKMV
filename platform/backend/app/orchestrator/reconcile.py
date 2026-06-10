"""Reconciliation — stall detection, label refresh, orphan sweep (PRD §8.2).

Reconcile runs **every tick** (driven by :mod:`app.orchestrator.tick`) and is the
"reconcile from external truth (Docker) + the persisted state DB" half of the
in-process orchestrator (ADR-P001). It implements the three §8.2 reconcile
responsibilities, all binding:

**(a) Stall detection (AC-12).** Liveness comes from the **event stream**, not a
per-container busy-poll: a run with no new ``events`` row for ``STALL_TIMEOUT_S``
(default 300 s) is treated as stalled → its container is **killed** (the engine
``RunHandle.stop(force=True)`` cancels the run task and the engine's ``finally``
stops the container — never a bare task-cancel that would orphan a money-spending
container, INV-10-adjacent) and a **stall/retry signal** is emitted. The retry
*scheduler* is 3.4; 3.3 emits the signal + does the kill. The stall cutoff is a
**UTC-persisted** comparison (the last event ``ts`` vs. a fresh ``now()`` via
:mod:`app.orchestrator.deadlines`) — never an in-memory timer — so it survives a
suspend (AC-13).

**(b) GitHub-label refresh under the authority rule (AC-11, INV-11 — binding).**
For an issue with an **active run the DB ``runs`` row is authoritative** (§8.1):
a stray human label edit does **not** move the board while the run is live. But if
a human moved the issue to a **terminal/non-active** state (closed → Done), the
run is **stopped** (terminal → also clean the workspace). **Every** label change
routes through the Phase-1 serialized **write-queue** via
:func:`app.github.state_machine.set_agent_state` (``PUT .../labels`` replace-all,
single-occupancy) — **never** a direct GitHub call from the orchestrator, **never**
the fictional single-label patch endpoint (INV-11). When the DB row wins, reconcile
leaves the board unchanged (no write at all).

**(c) Orphan-container sweep (AC-12).** A container still labeled with a ``run_id``
whose ``runs`` row is **terminal** is an orphan (a finished/cancelled run whose
container lingered) → it is **killed** (container stopped). This reaps a leftover
money-spending container the graceful path missed.

What 3.3 does **not** do: the retry *scheduler* (3.4 — reconcile only emits the
stall signal here), and the pause-timeout auto-resolve wire-in (3.4 / T104 adds a
call to :func:`app.hitl.timeout.sweep_expired_pauses` here in a later wave). The
boot-recovery / graceful-drain orphan handling for a *dead* process is 3.5.

Nothing here touches ``dkmv/`` directly: container control goes through an
injected :class:`RunKiller` seam (the tick binds it to the in-process engine
handle), and GitHub mutation goes through the write-queue. The orchestrator issues
**no** direct ``requests``/``httpx`` GitHub call.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from app.db.spend_sql import TERMINAL_RUN_STATUSES as TERMINAL_RUN_STATUSES
from app.github.sync import ACTIVE_RUN_STATUSES
from app.orchestrator.deadlines import Clock, seconds_since, utc_now

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.config import Settings
    from app.db.repository import Repository
    from app.github.client import GitHubClient
    from app.github.graphql import BoardPage
    from app.github.hash_cache import HashCache
    from app.github.write_queue import WriteQueue
    from app.hitl.registry import DecisionRegistry
    from app.orchestrator.retry import RetryScheduler

_log = logging.getLogger(__name__)

# ``TERMINAL_RUN_STATUSES`` (the §8.1-active complement) is re-exported above from
# the db layer (:data:`app.db.spend_sql.TERMINAL_RUN_STATUSES`) so the reconcile
# pass, the G9 spend fast-path, and the events-retention prune all agree on "is
# this run finished?" from ONE definition.

#: Reason codes carried on a :class:`StallSignal` so 3.4's retry scheduler (and the
#: structured logs) can branch on *why* a kill happened.
STALL_REASON = "stall"
ORPHAN_REASON = "orphan"
HUMAN_TERMINAL_REASON = "human_terminal_move"


class RunKiller(Protocol):
    """Container-kill seam: stop a live run's container (INV-10-adjacent).

    The orchestrator must **never** bare-cancel a run's ``asyncio.Task`` without
    stopping its container (an orphaned 8 GB container keeps spending — INV-10).
    The tick binds this to the in-process engine: ``kill(run_row)`` resolves the
    engine ``RunHandle`` (by ``engine_run_id``) and calls ``stop(force=True)`` so
    the engine's ``finally`` stops the container. A test injects a fake recording
    which runs it was asked to kill. Returns ``True`` iff a container was actually
    stopped (a run with no live handle in this process — started by a now-dead
    process — returns ``False``; that orphan is 3.5's boot-recovery ``docker kill``,
    never a re-attach here).
    """

    async def kill(self, run_row: dict[str, Any]) -> bool: ...


@dataclass(frozen=True, slots=True)
class StallSignal:
    """A stall/retry signal emitted for a killed run (3.4 consumes it).

    3.3 emits this (and performs the kill); 3.4's retry scheduler reads it to
    schedule a capped-backoff retry. ``reason`` is one of :data:`STALL_REASON` /
    :data:`ORPHAN_REASON` / :data:`HUMAN_TERMINAL_REASON`. ``container_killed``
    records whether a live container was actually stopped (vs. no live handle).
    """

    run_id: str
    issue_num: int | None
    reason: str
    container_killed: bool


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """Outcome of one :func:`reconcile_once` pass (for tests + the tick log).

    ``stalled`` / ``orphans`` are the stall + orphan-sweep signals emitted this
    pass; ``label_writes`` counts the authority-rule label refreshes routed through
    the write-queue (``0`` when every active run's DB row won, leaving the board
    unchanged); ``stopped_for_terminal_move`` is the count of runs stopped because a
    human moved their issue to a terminal state.
    """

    stalled: tuple[StallSignal, ...] = ()
    orphans: tuple[StallSignal, ...] = ()
    label_writes: int = 0
    stopped_for_terminal_move: int = 0
    #: Count of pauses auto-resolved on timeout this pass (``resolved_by='timeout'``,
    #: INV-9 — AC-17). ``0`` when no pause expired (or no decision registry wired).
    pauses_timed_out: int = 0
    #: Run ids whose due backoff fired an idempotent re-dispatch this pass (3.4 —
    #: AC-14/15). Empty when no retry scheduler is wired or none were due.
    retries_fired: tuple[str, ...] = ()

    @property
    def signals(self) -> tuple[StallSignal, ...]:
        """All stall/retry signals emitted this pass (stall + orphan)."""
        return (*self.stalled, *self.orphans)

    @property
    def action_count(self) -> int:
        """Total reconcile actions taken this pass (the loop-observability gauge).

        Sums the mutating actions — stalls killed, orphans reaped, authority-rule
        label refreshes, human-terminal stops, pause timeouts auto-resolved, and
        backoff re-dispatches fired — so the loop's ``reconcile_actions`` gauge
        (5.1 / AC-5) surfaces a thrashing reconcile pass. A pure read-only derive
        over the existing fields; it adds no state.
        """
        return (
            len(self.stalled)
            + len(self.orphans)
            + self.label_writes
            + self.stopped_for_terminal_move
            + self.pauses_timed_out
            + len(self.retries_fired)
        )


@dataclass(slots=True)
class ReconcileDeps:
    """Everything one reconcile pass needs, resolved from the app-state seam.

    The tick composes this from the lifespan-owned singletons (``deps.py``):
    the single-writer :class:`Repository` (INV-6), the GitHub client + serialized
    :class:`WriteQueue` + board hash-cache (INV-11), the :class:`RunKiller`
    container seam (INV-10-adjacent), and the typed :class:`Settings` (the stall
    cutoff). ``now`` is injectable so a frozen-clock test can drive the
    UTC-persisted stall deadline past ``due`` without sleeping (AC-13).
    """

    repository: Repository
    github_client: GitHubClient
    write_queue: WriteQueue
    killer: RunKiller
    settings: Settings
    cache: HashCache[BoardPage] | None = None
    now: Clock = field(default=utc_now)
    #: HITL decision registry for the pause-timeout auto-resolve sweep (T104 /
    #: AC-17 — INV-9). When wired, :func:`reconcile_once` runs
    #: :func:`app.hitl.timeout.sweep_expired_pauses` each pass through the SAME
    #: exactly-once guard the human answer path uses. ``None`` (the 3.3 default)
    #: leaves the sweep out — 3.4 wires it via the lifespan-composed registry.
    decisions: DecisionRegistry | None = None
    #: The 3.4 retry scheduler. When wired, :func:`reconcile_once` schedules a
    #: capped-backoff retry for each stall/orphan :class:`StallSignal` and fires any
    #: due backoff (idempotent re-dispatch) each pass. ``None`` leaves retry out
    #: (3.3's reconcile only emits the signals; 3.4 consumes them here).
    retry_scheduler: RetryScheduler | None = None


async def reconcile_once(deps: ReconcileDeps, repo: str) -> ReconcileResult:
    """Run one reconcile pass for ``repo`` (stall + label authority + orphan sweep).

    The §8.2 responsibilities in order:

    1. :func:`detect_stalls` — kill + signal runs with no events for
       ``STALL_TIMEOUT_S`` (AC-12), using the UTC-persisted last-event-ts vs. a
       fresh ``now()`` (AC-13).
    2. :func:`refresh_labels` — the authority rule (AC-11 / INV-11): the active-run
       DB row wins over a stray human label edit (no write); a human terminal move
       **stops** the run. All label writes via the write-queue.
    3. :func:`sweep_orphans` — kill containers whose ``run_id``'s row is terminal
       (AC-12).
    4. :func:`sweep_pause_timeouts` — auto-resolve any pause whose UTC ``timeout_at``
       has expired, via the exactly-once guard (``resolved_by='timeout'``, T104 /
       AC-17 / INV-9). Only when a :class:`DecisionRegistry` is wired (3.4).
    5. **Retry (3.4):** schedule a capped-backoff retry for each stall/orphan signal
       and fire any due backoff (idempotent re-dispatch). Only when a
       :class:`~app.orchestrator.retry.RetryScheduler` is wired.

    Returns a :class:`ReconcileResult` aggregating the pass. The tick calls this
    each cadence; a single pass is also the unit the AC tests drive directly.
    """
    stalled = await detect_stalls(deps, repo)
    label = await refresh_labels(deps, repo)
    orphans = await sweep_orphans(deps, repo)
    pauses_timed_out = await sweep_pause_timeouts(deps)
    retries_fired = await drive_retries(deps, (*stalled, *orphans))
    return ReconcileResult(
        stalled=tuple(stalled),
        orphans=tuple(orphans),
        label_writes=label.writes,
        stopped_for_terminal_move=label.terminal_stops,
        pauses_timed_out=pauses_timed_out,
        retries_fired=retries_fired,
    )


# ── (a) stall detection (AC-12) ───────────────────────────────────────────────


async def detect_stalls(deps: ReconcileDeps, repo: str) -> list[StallSignal]:
    """Kill + signal active runs with no events for ``STALL_TIMEOUT_S`` (AC-12).

    For each **active** run in ``repo``, read the UTC ``ts`` of its latest persisted
    event and compare it against a fresh ``now()`` (:func:`seconds_since` — a
    re-evaluation, never an in-memory timer, AC-13). When the gap exceeds the
    configured ``STALL_TIMEOUT_S``, the run is stalled → its container is
    **killed** through the :class:`RunKiller` seam (``stop(force=True)`` so the
    engine ``finally`` stops the container — never a bare task-cancel, INV-10) and
    a :class:`StallSignal` is emitted for 3.4's retry scheduler. A run with no
    events *yet* (just launched) has no stall ts and is skipped — the launch path
    set ``started_at``, but stall is measured from event activity, so a run that
    has never emitted is given the benefit of the doubt until its first event.
    """
    cutoff = deps.settings.STALL_TIMEOUT_S
    active = await _read_active_run_rows(deps.repository, repo)
    last_ts = await _latest_event_ts(deps.repository, [str(r["id"]) for r in active])
    signals: list[StallSignal] = []
    for row in active:
        run_id = str(row["id"])
        ts = last_ts.get(run_id)
        age = seconds_since(ts, now=deps.now) if ts is not None else None
        if age is None or age < cutoff:
            continue
        killed = await deps.killer.kill(row)
        _log.warning(
            "orchestrator.reconcile stall run=%s issue=%s age_s=%.0f killed=%s",
            run_id,
            row.get("issue_num"),
            age,
            killed,
        )
        signals.append(
            StallSignal(
                run_id=run_id,
                issue_num=_as_int(row.get("issue_num")),
                reason=STALL_REASON,
                container_killed=killed,
            )
        )
    return signals


# ── (b) label refresh under the authority rule (AC-11, INV-11) ────────────────


@dataclass(frozen=True, slots=True)
class _LabelOutcome:
    """Internal: label-refresh counters returned to :func:`reconcile_once`."""

    writes: int = 0
    terminal_stops: int = 0


async def refresh_labels(deps: ReconcileDeps, repo: str) -> _LabelOutcome:
    """Authority-rule label refresh for ``repo`` (AC-11 / INV-11 — binding).

    For each cached issue that has an **active run**:

    * **DB row wins (default).** A stray human label edit does **not** move the
      board while the run is live (§8.1 authority rule): reconcile makes **no**
      GitHub write — the active-run DB row is the source of truth and the board is
      left unchanged. (A drift between the live run's expected ``agent:*`` label
      and the human edit is intentionally *not* re-written every tick; the run's
      own lifecycle transitions own the label, so a tick-driven re-write would be a
      label storm — INV-11's failure mode.)
    * **Human terminal move → stop the run.** If the human moved the issue to a
      **terminal/non-active** state — closed (Done) — the human's intent wins:
      reconcile **stops the run** (container killed via the :class:`RunKiller`
      seam, terminal → also clean the workspace) and clears any stale ``agent:*``
      label to Backlog via :func:`set_agent_state` on the **write-queue** (INV-11
      — replace-all ``PUT``, never the fictional single-label patch, never a direct
      GitHub call).

    Returns the (write count, terminal-stop count). The "DB row wins" path returns
    zero writes — the assertion the AC-11 test makes (board unchanged).
    """
    from app.github.state_machine import set_agent_state

    cached = await deps.repository.read_issues(repo)
    active_rows = await deps.repository.read_active_runs(repo, sorted(ACTIVE_RUN_STATUSES))
    active_by_issue = {
        int(r["issue_num"]): r for r in active_rows if r.get("issue_num") is not None
    }
    if not active_by_issue:
        return _LabelOutcome()

    # Map issue_num → the active run's full row (for the container kill on a
    # terminal move) via a second active-run read keyed on the run id.
    run_rows_by_issue = await _active_run_rows_by_issue(deps.repository, repo)

    writes = 0
    terminal_stops = 0
    for issue in cached:
        num = int(issue["num"])
        if num not in active_by_issue:
            continue
        labels = _decode_labels(issue.get("labels_json"))
        is_terminal_move = str(issue.get("state") or "") == "done"
        if not is_terminal_move:
            # DB row is authoritative — leave the board unchanged (no write). A
            # stray human label edit on a running issue is ignored here.
            continue

        # The human moved the issue to a terminal state while a run was live → the
        # human's intent wins. Stop the run (container killed; terminal → clean
        # workspace) and clear the stale agent:* label to Backlog via the queue.
        run_row = run_rows_by_issue.get(num)
        if run_row is not None:
            killed = await deps.killer.kill(run_row)
            await deps.repository.update_run_fields(str(run_row["id"]), status="cancelled")
            _log.info(
                "orchestrator.reconcile human terminal move issue=%s run=%s killed=%s",
                num,
                run_row["id"],
                killed,
            )
            terminal_stops += 1
        if any(name.startswith("agent:") for name in labels):
            await set_agent_state(
                deps.github_client,
                repo,
                num,
                None,  # clear to Backlog (Done is the absence of an agent:* label)
                current_labels=labels,
                write_queue=deps.write_queue,
                cache=deps.cache,
            )
            writes += 1
    return _LabelOutcome(writes=writes, terminal_stops=terminal_stops)


# ── (c) orphan-container sweep (AC-12) ────────────────────────────────────────


async def sweep_orphans(deps: ReconcileDeps, repo: str) -> list[StallSignal]:
    """Kill containers whose ``run_id``'s ``runs`` row is **terminal** (AC-12).

    A container still alive under a run whose DB row has gone terminal
    (completed/failed/cancelled/…) is an orphan the normal completion path missed.
    Reconcile asks the :class:`RunKiller` to stop each such container (it resolves
    a live engine handle by ``engine_run_id`` and ``stop(force=True)``s it — a
    no-op returning ``False`` for a run with no live handle in this process, which
    is 3.5's boot ``docker kill`` territory, never a re-attach). Emits a
    :class:`StallSignal` (``reason="orphan"``) per killed orphan for the audit log.
    """
    terminal = await _read_terminal_run_rows_with_container(deps.repository, repo)
    signals: list[StallSignal] = []
    for row in terminal:
        killed = await deps.killer.kill(row)
        if not killed:
            continue
        _log.info(
            "orchestrator.reconcile orphan-swept run=%s status=%s",
            row["id"],
            row.get("status"),
        )
        signals.append(
            StallSignal(
                run_id=str(row["id"]),
                issue_num=_as_int(row.get("issue_num")),
                reason=ORPHAN_REASON,
                container_killed=True,
            )
        )
    return signals


# ── (d) pause-timeout auto-resolve (T104 / AC-17 — INV-9) ─────────────────────


async def sweep_pause_timeouts(deps: ReconcileDeps) -> int:
    """Auto-resolve pauses whose UTC ``timeout_at`` has expired (T104 / AC-17 — INV-9).

    The Phase-2 pause-timeout sweep (:func:`app.hitl.timeout.sweep_expired_pauses`)
    wired into the reconcile tick. The pause ``timeout_at`` (default 60 min →
    auto-abort) is a **UTC persisted deadline** re-evaluated against a fresh
    ``now()`` each tick (the same suspend-surviving deadline path as stall/backoff —
    AC-13), and on expiry the pause is auto-resolved via the **exactly-once** guard
    the human answer path uses (``UPDATE … WHERE status='pending'``,
    ``resolved_by='timeout'``) — so a pause a human answers in the *same* tick is
    resolved by exactly one of them (no double-resolve, INV-9). A no-op when no
    :class:`DecisionRegistry` is wired (3.3's default — 3.4 supplies it). Returns the
    count of pauses this pass auto-resolved on timeout.
    """
    if deps.decisions is None:
        return 0
    from app.hitl.timeout import sweep_expired_pauses

    result = await sweep_expired_pauses(
        repository=deps.repository,
        decisions=deps.decisions,
        now=deps.now,
    )
    if result.resolved:
        _log.info("orchestrator.reconcile pause-timeout auto-resolved count=%d", result.resolved)
    return result.resolved


# ── (e) retry: schedule from signals + fire due backoffs (3.4 — AC-14/15) ─────


async def drive_retries(deps: ReconcileDeps, signals: Sequence[StallSignal]) -> tuple[str, ...]:
    """Schedule capped-backoff retries for ``signals`` + fire due backoffs (3.4).

    The reconcile→retry bridge (only active when a
    :class:`~app.orchestrator.retry.RetryScheduler` is wired — 3.3's reconcile alone
    just emits the :class:`StallSignal`):

    1. For each stall/orphan signal, schedule a capped-backoff retry (AC-14) —
       persisting a UTC backoff ``due_at`` (re-evaluated next tick, never slept on).
    2. Fire any retry whose backoff ``due_at`` is now due
       (:meth:`~app.orchestrator.retry.RetryScheduler.fire_due_retries`) through the
       **idempotent** re-dispatch (existing-branch/PR detection → no duplicate PR,
       same ``runs`` row — AC-15 / INV-5 / R-15).

    Returns the run_ids re-dispatched this pass. A no-op (empty tuple) when no
    scheduler is wired.
    """
    scheduler = deps.retry_scheduler
    if scheduler is None:
        return ()
    for signal in signals:
        await scheduler.schedule_from_signal(signal)
    fired = await scheduler.fire_due_retries()
    return tuple(fired)


# ── repository reads (through the public read seam — INV-6) ───────────────────


async def _read_active_run_rows(repository: Repository, repo: str) -> list[dict[str, Any]]:
    """Read this repo's non-terminal ``runs`` rows (full row) for reconcile.

    Reads through the repository's public WAL read seam
    (:meth:`Repository.read_connection`) so the orchestrator never opens its own
    DB connection or issues a write off the single-writer path (INV-6). The full
    row (incl. ``engine_run_id``) is needed so the :class:`RunKiller` can resolve
    the engine handle to stop the container.
    """
    placeholders = ", ".join("?" for _ in ACTIVE_RUN_STATUSES)
    statuses = sorted(ACTIVE_RUN_STATUSES)
    async with repository.read_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT * FROM runs "  # noqa: S608 — placeholders only, statuses bound
            f"WHERE repo = ? AND status IN ({placeholders}) ORDER BY started_at",
            (repo, *statuses),
        )
        return [dict(r) for r in rows]


async def _active_run_rows_by_issue(repository: Repository, repo: str) -> dict[int, dict[str, Any]]:
    """Map ``issue_num → active run row`` for the terminal-move kill path."""
    rows = await _read_active_run_rows(repository, repo)
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        num = _as_int(row.get("issue_num"))
        if num is not None and num not in out:
            out[num] = row
    return out


async def _read_terminal_run_rows_with_container(
    repository: Repository, repo: str
) -> list[dict[str, Any]]:
    """Read terminal ``runs`` rows that still carry an ``engine_run_id`` (orphans).

    An orphan candidate is a run whose status is terminal but which still has an
    ``engine_run_id`` (so a container may linger). The :class:`RunKiller` decides
    whether a live container actually exists (it returns ``False`` when no live
    handle/container remains), so this read is intentionally broad — the kill seam
    is the authority on "is there a container to stop". Read through the public WAL
    seam (INV-6).
    """
    placeholders = ", ".join("?" for _ in TERMINAL_RUN_STATUSES)
    statuses = sorted(TERMINAL_RUN_STATUSES)
    async with repository.read_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT * FROM runs "  # noqa: S608 — placeholders only, statuses bound
            f"WHERE repo = ? AND engine_run_id IS NOT NULL AND status IN ({placeholders})",
            (repo, *statuses),
        )
        return [dict(r) for r in rows]


async def _latest_event_ts(repository: Repository, run_ids: Sequence[str]) -> dict[str, str]:
    """Map ``run_id → latest event UTC ts`` for the stall check (one query).

    The stall measure is "seconds since this run's last event" (liveness from the
    **event stream**, not a container busy-poll — §8.2). One grouped read over the
    append-only ``events`` table returns the MAX(``ts``) per run; a run with no
    events is absent (the caller treats it as "no stall ts yet"). Through the
    public WAL read seam (INV-6).
    """
    ids = list(dict.fromkeys(run_ids))
    if not ids:
        return {}
    placeholders = ", ".join("?" for _ in ids)
    async with repository.read_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT run_id, MAX(ts) AS last_ts FROM events "  # noqa: S608 — placeholders only
            f"WHERE run_id IN ({placeholders}) GROUP BY run_id",
            tuple(ids),
        )
        return {str(r["run_id"]): str(r["last_ts"]) for r in rows if r["last_ts"] is not None}


def _decode_labels(labels_json: Any) -> list[str]:
    """Decode the issues cache ``labels_json`` column to a label-name list."""
    import json

    if not labels_json:
        return []
    try:
        value = json.loads(labels_json)
    except (TypeError, ValueError):
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


def _as_int(value: Any) -> int | None:
    """Coerce a possibly-``None`` DB cell to ``int | None``."""
    return int(value) if value is not None else None


#: The container-kill callable shape the tick binds to the in-process engine.
KillFn = Callable[[dict[str, Any]], Awaitable[bool]]


__all__ = [
    "HUMAN_TERMINAL_REASON",
    "ORPHAN_REASON",
    "STALL_REASON",
    "TERMINAL_RUN_STATUSES",
    "KillFn",
    "ReconcileDeps",
    "ReconcileResult",
    "RunKiller",
    "StallSignal",
    "detect_stalls",
    "drive_retries",
    "reconcile_once",
    "refresh_labels",
    "sweep_orphans",
    "sweep_pause_timeouts",
]
