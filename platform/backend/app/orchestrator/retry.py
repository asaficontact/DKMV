"""Retry scheduler — capped backoff + idempotent re-dispatch (PRD §8.2 — AC-14/15/16).

The retry half of the in-process orchestrator (3.4). It owns three load-bearing,
binding behaviors:

**(1) Capped exponential backoff (AC-14).** On a transient failure — a
``task_failed`` the run can retry, or a :class:`~app.orchestrator.reconcile.StallSignal`
from 3.3 — the scheduler schedules a retry with
``delay = min(10s · 2^(attempt-1), 5min)`` (:func:`compute_backoff` — 10s, 20s,
40s, 80s, 160s, 300s, 300s, …). **Max 3 attempts;** the 4th failure parks the run
in the **retry queue** (FR-06-3) for a manual *Retry now*. The backoff ``due_at``
is a **UTC persisted deadline** (in the ``settings`` KV — no schema migration in
this slice) **re-evaluated by 3.3's tick** via :func:`app.orchestrator.deadlines.is_due`,
so it survives a laptop suspend (AC-13) — there is **no** in-memory ``asyncio.sleep``
backoff timer here.

**(2) Idempotent re-dispatch (AC-15, INV-5 / R-15 — binding).** Before
re-dispatching, the scheduler **detects an existing branch/PR for the issue**
(via ``runs.pr_num`` and/or the deterministic branch name) and **resumes/skips
rather than duplicating** — a blind retry would re-push commits or re-open a PR.
A retry **reuses the same ``runs`` row** (the §8.2 ``idempotency_key`` =
``issue_num + workflow_id + base_branch``, *not* a body hash), never colliding
into a second dispatch, and re-dispatches **through the existing
:func:`app.runs.launch.launch_run` boundary** (ADR-P001 — there is exactly ONE
launch path) with ``start_task=<last completed stage>`` so the engine reconstructs
prior stage outputs from the pushed branch.

**(3) The retry-queue projection (AC-4 / FR-06-3).** :func:`read_retry_queue`
renders the parked runs as ``RetryEntry`` rows ``{id, issue, attempt, dueIn,
lastError}`` (PRD §6.1) that 3.1's ``GET /retry-queue`` surfaces.

State lives in the ``settings`` KV (key ``retry::<run_id>`` → a JSON
:class:`RetryState`, plus an index key) through the single writer (INV-6), so this
slice adds **no** schema migration and the persisted backoff ``due_at`` is a
plain re-evaluated UTC timestamp. Nothing here edits ``dkmv/`` — re-dispatch goes
through the in-process launch boundary, never the CLI.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from app.orchestrator.deadlines import Clock, due_at_from_now, is_due, parse_iso, utc_now

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.db.repository import Repository
    from app.github.client import GitHubClient
    from app.orchestrator.reconcile import StallSignal

_log = logging.getLogger(__name__)

#: Base backoff unit (§8.2): ``10s · 2^(attempt-1)``.
BACKOFF_BASE_S = 10.0

#: Backoff cap (§8.2): 5 minutes. ``min(10s·2^(attempt-1), 5min)`` never exceeds it.
BACKOFF_CAP_S = 5 * 60.0  # 300s

#: Max automatic retry attempts (§8.2 / FR-06-3): after the 3rd attempt's failure
#: the run lands in the retry queue (attempt 4 is the parked, manual-retry state).
MAX_ATTEMPTS = 3

#: ``settings`` key prefix for one run's persisted :class:`RetryState`.
_RETRY_KEY_PREFIX = "retry::"

#: ``settings`` key holding the JSON list of run_ids that have retry state (the
#: retry-queue index) — so :func:`read_retry_queue` / :func:`due_retries` enumerate
#: without a ``LIKE`` scan over the KV table.
_RETRY_INDEX_KEY = "retry_index"


def compute_backoff(attempt: int) -> float:
    """``delay = min(10s · 2^(attempt-1), 5min)`` for a 1-based ``attempt`` (AC-14).

    The capped exponential backoff (§8.2): attempt 1 → 10s, 2 → 20s, 3 → 40s, …,
    capped at 300s (5 min). ``attempt <= 0`` is clamped to 1 (the first retry) so a
    miscount never yields a zero/negative delay. This is pure math — the resulting
    delay is turned into a **persisted** UTC ``due_at`` by :meth:`RetryScheduler.schedule`,
    re-evaluated each tick (never slept on).
    """
    n = max(1, attempt)
    delay: float = BACKOFF_BASE_S * float(2 ** (n - 1))
    return min(delay, BACKOFF_CAP_S)


def _retry_key(run_id: str) -> str:
    """``settings`` key for one run's persisted retry state."""
    return f"{_RETRY_KEY_PREFIX}{run_id}"


@dataclass(slots=True)
class RetryState:
    """One run's persisted retry state (the unit the ``settings`` KV stores).

    ``attempt`` is the number of retries **scheduled so far** (1 after the first
    transient failure). ``due_at`` is the **UTC persisted backoff deadline** the
    tick re-evaluates (:func:`app.orchestrator.deadlines.is_due`) — ``None`` once a
    due retry has fired (the run is back in flight) or once the run is parked.
    ``last_error`` is the most recent failure reason (the ``RetryEntry.lastError``).
    ``parked`` is set when ``attempt`` exhausted :data:`MAX_ATTEMPTS` — the run sits
    in the retry queue awaiting a manual *Retry now* (which clears it via
    :meth:`RetryScheduler.enqueue_manual`). ``issue_num`` is cached for the
    ``RetryEntry`` projection without a second run read.
    """

    run_id: str
    issue_num: int | None = None
    attempt: int = 0
    due_at: str | None = None
    last_error: str | None = None
    parked: bool = False

    @property
    def exhausted(self) -> bool:
        """``True`` once the automatic attempts are spent (→ the retry queue)."""
        return self.attempt >= MAX_ATTEMPTS


@dataclass(frozen=True, slots=True)
class RetryEntry:
    """A ``GET /retry-queue`` row (PRD §6.1 / FR-06-3) — ``data.jsx RETRY_QUEUE``.

    ``id`` is the platform run UUID; ``issue`` the issue number; ``attempt`` the
    ``attempt N/3`` count; ``dueIn`` the seconds until the backoff ``due_at`` (``0``
    when already due / parked); ``lastError`` the last failure reason the card shows.
    """

    id: str
    issue: int | None
    attempt: int
    dueIn: int  # noqa: N815 — the UI/data.jsx contract field name (camelCase)
    lastError: str | None  # noqa: N815 — the UI/data.jsx contract field name


#: A re-dispatch callable: given a run row + an optional ``start_task``, re-launch
#: the run through the EXISTING ``launch_run`` boundary (ADR-P001) and return the
#: platform run id iff a (re-)dispatch actually happened, else ``None`` (the
#: claim-lock reused the row / a duplicate was skipped). Bound by the lifespan to
#: the real launch path; a test injects a recording fake.
RedispatchFn = Callable[[dict[str, Any], str | None], Awaitable[str | None]]


@dataclass(slots=True)
class RetryScheduler:
    """Schedules + fires idempotent retries with capped backoff (§8.2 — 3.4).

    Composed by the lifespan / tick from the single-writer :class:`Repository`
    (INV-6), the GitHub client (for the existing-PR/branch detection seam), and a
    ``redispatch`` callable routing through the **existing** ``launch_run`` boundary
    (ADR-P001). ``now`` is injectable so a frozen-clock test advances past a
    persisted backoff ``due_at`` (simulating a suspend) without sleeping (AC-13/14).
    """

    repository: Repository
    redispatch: RedispatchFn
    github_client: GitHubClient | None = None
    now: Clock = utc_now

    # ── scheduling (AC-14) ────────────────────────────────────────────────────

    async def schedule(
        self, run_id: str, *, issue_num: int | None = None, error: str | None = None
    ) -> RetryState:
        """Schedule the next retry for ``run_id`` with capped backoff (AC-14).

        Increments the run's ``attempt`` and, while attempts remain
        (``attempt <= MAX_ATTEMPTS``), persists a UTC backoff ``due_at`` =
        ``now() + min(10s·2^(attempt-1), 5min)`` the tick re-evaluates. On the
        attempt that **exhausts** :data:`MAX_ATTEMPTS` (the 4th failure — i.e. a
        failure when ``attempt`` already equals ``MAX_ATTEMPTS``) the run is
        **parked** in the retry queue (``parked=True``, no further backoff) for a
        manual *Retry now*. Idempotent in the sense that it persists through the
        single writer; the caller (reconcile/tick) calls it once per observed
        transient failure. Returns the updated :class:`RetryState`.
        """
        state = await self._read_state(run_id) or RetryState(run_id=run_id)
        if issue_num is not None:
            state.issue_num = issue_num
        if error is not None:
            state.last_error = error

        if state.attempt >= MAX_ATTEMPTS:
            # The automatic attempts are spent — park the run in the retry queue
            # (no further auto-backoff; only a manual Retry now revives it).
            state.parked = True
            state.due_at = None
            _log.info(
                "orchestrator.retry parked run=%s attempt=%d (retry queue)",
                run_id,
                state.attempt,
            )
        else:
            state.attempt += 1
            delay = compute_backoff(state.attempt)
            state.due_at = due_at_from_now(delay, now=self.now)
            _log.info(
                "orchestrator.retry scheduled run=%s attempt=%d/%d backoff_s=%.0f due_at=%s",
                run_id,
                state.attempt,
                MAX_ATTEMPTS,
                delay,
                state.due_at,
            )
        await self._write_state(state)
        return state

    async def schedule_from_signal(self, signal: StallSignal) -> RetryState:
        """Schedule a retry for a 3.3 :class:`StallSignal` (the stall→retry bridge).

        3.3's reconcile kills a stalled/orphaned container and emits a
        :class:`StallSignal`; 3.4 consumes it here to schedule a capped-backoff
        retry (AC-12 → AC-14). The signal's ``reason`` becomes the
        ``RetryEntry.lastError`` so the queue card shows *why* the retry exists.
        """
        return await self.schedule(signal.run_id, issue_num=signal.issue_num, error=signal.reason)

    # ── firing due retries (re-evaluated by the tick — AC-13/14) ──────────────

    async def fire_due_retries(self) -> list[str]:
        """Re-dispatch every run whose persisted backoff ``due_at`` is now due (AC-13/14).

        Called from the reconcile tick: enumerate the persisted retry states, and
        for each non-parked one whose ``due_at`` is at-or-before a fresh ``now()``
        (:func:`app.orchestrator.deadlines.is_due` — a re-evaluation that fires
        correctly after a suspend gap, never a slept timer), perform the
        **idempotent** re-dispatch (:meth:`redispatch_run`) and clear its ``due_at``.
        A run with no due backoff (or parked) is skipped. Returns the run_ids
        re-dispatched this tick.
        """
        fired: list[str] = []
        for state in await self._read_all_states():
            if state.parked or state.due_at is None:
                continue
            if not is_due(state.due_at, now=self.now):
                continue
            dispatched = await self.redispatch_run(state.run_id)
            # Clear the fired deadline regardless of whether a NEW dispatch happened
            # (a resume/skip on an existing PR also consumes the backoff window) so
            # the tick does not re-fire the same due_at every cadence.
            state.due_at = None
            await self._write_state(state)
            if dispatched:
                fired.append(state.run_id)
        return fired

    # ── idempotent re-dispatch (AC-15, INV-5 / R-15 — binding) ────────────────

    async def redispatch_run(self, run_id: str) -> bool:
        """Re-dispatch a run idempotently — detect existing branch/PR first (AC-15).

        The binding INV-5 / R-15 path. Before re-launching:

        1. Read the run row (it carries ``pr_num`` / ``branch`` / ``workflow_id``).
        2. **Detect an existing PR/branch** (:meth:`_has_existing_pr`): if the
           issue already has an **open PR** (``runs.pr_num`` set, or the GitHub
           detection seam finds one for the deterministic branch), the retry
           **resumes/skips and creates NO duplicate PR** — it does not re-dispatch a
           fresh run that would re-open the PR. The §13 / AT-Recovery resilience bar.
        3. Otherwise re-dispatch **through the existing ``launch_run`` boundary**
           (ADR-P001) with ``start_task=<last completed stage>`` so the engine
           reconstructs prior stage outputs from the pushed branch — reusing the
           **same ``runs`` row** (same ``idempotency_key`` = issue+workflow+branch),
           never a second claim.

        Returns ``True`` iff a fresh re-dispatch was launched; ``False`` when the
        retry resumed/skipped on an existing PR (no duplicate) or the run row was
        gone. Never raises into the tick (a re-dispatch failure is logged + skipped).
        """
        row = await self.repository.get_run(run_id)
        if row is None:
            _log.warning("orchestrator.retry redispatch run=%s gone; skipping", run_id)
            return False

        if await self._has_existing_pr(row):
            # Idempotent (INV-5 / R-15): the issue already has an open PR. A blind
            # retry would re-open it — instead resume/skip. No duplicate PR.
            _log.info(
                "orchestrator.retry run=%s issue=%s has an open PR (pr_num=%s); "
                "resuming/skipping — NO duplicate PR",
                run_id,
                row.get("issue_num"),
                row.get("pr_num"),
            )
            return False

        start_task = await self._last_completed_stage(run_id)
        try:
            dispatched_id = await self.redispatch(row, start_task)
        except Exception:  # noqa: BLE001 - a re-dispatch failure must not kill the tick
            _log.exception("orchestrator.retry redispatch run=%s failed; will re-evaluate", run_id)
            return False
        if dispatched_id is None:
            # The claim-lock reused the existing row (INV-5) — no second dispatch.
            _log.debug("orchestrator.retry redispatch run=%s reused existing row", run_id)
            return False
        return True

    async def _has_existing_pr(self, row: dict[str, Any]) -> bool:
        """Detect an existing open PR for the run's issue (INV-5 / R-15 — binding).

        First the cheap DB signal: ``runs.pr_num`` set means the run already pushed
        a PR (a retry must not re-open it). Then, if a GitHub detection seam is wired
        and the run carries the deterministic ``branch`` name, ask GitHub whether an
        open PR exists for that head branch (so a PR the DB row hasn't back-filled
        yet is still detected). A missing seam / a transient GitHub error degrades to
        "no PR detected via GitHub" — the DB ``pr_num`` signal still guards the
        common case, and the launch claim-lock (INV-5) is the backstop against a
        genuine second dispatch.
        """
        if row.get("pr_num") is not None:
            return True
        client = self.github_client
        branch = row.get("branch")
        repo = row.get("repo")
        if client is None or not branch or not repo:
            return False
        # Typed idempotency seam (INV-5 / R-15): ask GitHub whether an open PR
        # already exists for the run's deterministic head branch, closing the
        # "PR exists but runs.pr_num not yet back-filled" window. This is a typed
        # method on the GitHubClient ABC (returns the PR number or None) — no more
        # getattr duck-typing. A detection error is NOT a duplicate-PR risk by
        # itself: degrade to "not detected via GitHub" and rely on the launch
        # claim-lock backstop, never on a second dispatch.
        try:
            pr_number = await client.find_open_pr_for_branch(str(repo), str(branch))
        except Exception:  # noqa: BLE001 - a detection error is not a duplicate-PR risk by itself
            _log.warning(
                "orchestrator.retry PR detection failed for %s@%s; relying on DB pr_num",
                repo,
                branch,
                exc_info=True,
            )
            return False
        return pr_number is not None

    async def _last_completed_stage(self, run_id: str) -> str | None:
        """The last **completed** stage name, for an optional ``start_task=`` retry.

        Reads ``run_stages`` and returns the name of the highest-index stage whose
        ``status`` is ``completed`` — the engine reconstructs prior stage outputs
        from the pushed branch, so a retry can resume from there (§8.2). ``None``
        when no stage has completed (retry from the top). A read failure degrades to
        ``None`` (retry from the top) rather than blocking the retry.
        """
        try:
            stages = await self.repository.read_run_stages(run_id)
        except Exception:  # noqa: BLE001 - a stage read failure → retry from the top
            return None
        completed = [s for s in stages if str(s.get("status") or "") == "completed"]
        if not completed:
            return None
        last = max(completed, key=lambda s: int(s.get("idx") or 0))
        name = last.get("name")
        return str(name) if name else None

    # ── manual retry (POST /runs/{id}/retry — AC-16) ──────────────────────────

    async def enqueue_manual(self, run_id: str, *, issue_num: int | None = None) -> RetryState:
        """Enqueue a manual *Retry now* for ``run_id`` — itself idempotent (AC-16).

        Backs ``POST /runs/{id}/retry``. If a retry is **already pending** for this
        run (a non-parked state with a future ``due_at``, or one already due this
        tick), the call is a **no-op** — it returns the existing state without
        scheduling a second one, so a double-click yields **one** queued retry, not
        a duplicate dispatch (the AC-16 bar). Otherwise (no state yet, or a parked
        run) it schedules an **immediate** retry (``due_at = now``) so the next tick
        fires the idempotent re-dispatch. Returns the (possibly pre-existing) state.
        """
        existing = await self._read_state(run_id)
        if existing is not None and not existing.parked and existing.due_at is not None:
            # A retry is already queued for this run — second call is a no-op.
            return existing

        state = existing or RetryState(run_id=run_id)
        if issue_num is not None:
            state.issue_num = issue_num
        # A manual retry revives a parked run and schedules an IMMEDIATE re-dispatch
        # (due now) so the next tick fires it through the idempotent re-dispatch path.
        state.parked = False
        # Count the manual retry as an attempt (so the queue card's attempt N/3 is
        # truthful) but never beyond the cap.
        state.attempt = min(state.attempt + 1, MAX_ATTEMPTS)
        state.due_at = due_at_from_now(0.0, now=self.now)
        await self._write_state(state)
        _log.info("orchestrator.retry manual enqueue run=%s attempt=%d", run_id, state.attempt)
        return state

    async def has_pending_retry(self, run_id: str) -> bool:
        """``True`` iff ``run_id`` already has a queued (non-parked, due_at-set) retry."""
        state = await self._read_state(run_id)
        return state is not None and not state.parked and state.due_at is not None

    # ── retry-queue projection (AC-4 / FR-06-3) ───────────────────────────────

    async def read_retry_queue(self) -> list[RetryEntry]:
        """Project the persisted retry states to ``RetryEntry`` rows (AC-4 / FR-06-3).

        The data half of ``GET /retry-queue`` (3.1 shipped the empty shape; 3.4
        fills it). Returns one row per run with retry state — both parked runs
        (awaiting *Retry now*) and runs in backoff — as ``{id, issue, attempt,
        dueIn, lastError}`` (PRD §6.1). ``dueIn`` is the integer seconds until the
        backoff ``due_at`` (``0`` when due/parked), computed from a fresh ``now()``
        so the card counts down each poll. Ordered by ``dueIn`` (soonest first).
        """
        entries = [self._to_entry(state) for state in await self._read_all_states()]
        entries.sort(key=lambda e: (e.dueIn, e.id))
        return entries

    def _to_entry(self, state: RetryState) -> RetryEntry:
        """Render one :class:`RetryState` as a ``RetryEntry`` (computes ``dueIn``)."""
        due_in = 0
        if state.due_at is not None:
            parsed = parse_iso(state.due_at)
            if parsed is not None:
                remaining = (parsed - self.now()).total_seconds()
                due_in = max(0, int(remaining))
        return RetryEntry(
            id=state.run_id,
            issue=state.issue_num,
            attempt=state.attempt,
            dueIn=due_in,
            lastError=state.last_error,
        )

    # ── persistence (settings KV through the single writer — INV-6) ───────────

    async def clear(self, run_id: str) -> None:
        """Drop a run's retry state (e.g. after a successful re-dispatch completes)."""
        await self.repository.set_setting(_retry_key(run_id), "")
        index = await self._read_index()
        if run_id in index:
            index.discard(run_id)
            await self._write_index(index)

    async def _read_state(self, run_id: str) -> RetryState | None:
        """Read one run's persisted :class:`RetryState` from the ``settings`` KV."""
        raw = await self.repository.get_setting(_retry_key(run_id))
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return _state_from_dict(data)

    async def _read_all_states(self) -> list[RetryState]:
        """Read every persisted :class:`RetryState` (enumerated via the index key)."""
        states: list[RetryState] = []
        for run_id in sorted(await self._read_index()):
            state = await self._read_state(run_id)
            if state is not None:
                states.append(state)
        return states

    async def _write_state(self, state: RetryState) -> None:
        """Persist a :class:`RetryState` + index its run_id (single writer, INV-6)."""
        await self.repository.set_setting(_retry_key(state.run_id), json.dumps(asdict(state)))
        index = await self._read_index()
        if state.run_id not in index:
            index.add(state.run_id)
            await self._write_index(index)

    async def _read_index(self) -> set[str]:
        """Read the JSON-list index of run_ids that have retry state."""
        raw = await self.repository.get_setting(_RETRY_INDEX_KEY)
        if not raw:
            return set()
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return set()
        return {str(v) for v in data} if isinstance(data, list) else set()

    async def _write_index(self, index: set[str]) -> None:
        """Persist the run_id index (single writer, INV-6)."""
        await self.repository.set_setting(_RETRY_INDEX_KEY, json.dumps(sorted(index)))


def _state_from_dict(data: Any) -> RetryState | None:
    """Build a :class:`RetryState` from a persisted JSON dict (tolerant of drift)."""
    if not isinstance(data, dict) or "run_id" not in data:
        return None
    return RetryState(
        run_id=str(data["run_id"]),
        issue_num=data.get("issue_num"),
        attempt=int(data.get("attempt", 0)),
        due_at=data.get("due_at"),
        last_error=data.get("last_error"),
        parked=bool(data.get("parked", False)),
    )


__all__ = [
    "BACKOFF_BASE_S",
    "BACKOFF_CAP_S",
    "MAX_ATTEMPTS",
    "RedispatchFn",
    "RetryEntry",
    "RetryScheduler",
    "RetryState",
    "compute_backoff",
]
