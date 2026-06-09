"""The orchestrator tick loop — reconcile → poll → dispatch (PRD §8.2 — AC-10).

A single long-lived :class:`asyncio.Task` runs a fixed-cadence tick
(``settings.TICK_INTERVAL_S``, default 10 s — §8.8). Each tick:

1. **reconcile** running runs (:mod:`app.orchestrator.reconcile`) — stall
   detection, the authority-rule label refresh, the orphan-container sweep;
2. **validate preflight** — a cheap engine capability probe so the loop does not
   dispatch into a broken environment;
3. **fetch candidate issues** — **one** GraphQL board read (reusing the Phase-1
   client + hash-cache) to refresh the cache, then the candidates are read from
   the **issues DB cache**: ``agent:queued`` issues with an assigned
   ``workflow_id`` (§8.2 / FR-05);
4. **sort** — priority ascending, then oldest first;
5. **dispatch** — through the **existing** :func:`app.runs.launch.launch_run`
   boundary (ADR-P001 — there is exactly ONE launch path; the tick does **not**
   introduce a second). Launch params are built from the issue's stored
   ``workflow_id`` + the config defaults.

The **cap** (``asyncio.Semaphore(max_concurrent_runs)`` + aggregate admission) is
**Phase 5** (the §3 OUT list). Phase 3 dispatches **serially within the existing
single-PR-at-a-time / serialized-writer constraints** — one candidate per tick —
so it honors the serialized model without yet enforcing the concurrency cap.

Liveness comes from the **event stream**, not a per-container busy-poll; the basic
tick gauges (:mod:`app.orchestrator.gauges`) record tick duration +
time-since-last-successful-tick + a heartbeat so a wedged loop is detectable
(AC-10).

The loop is started as a **tracked task** in the app lifespan
(:func:`app.main._lifespan`) and **cancelled on shutdown**. Container kills go
through the in-process engine handle (``RunHandle.stop(force=True)`` → the engine
``finally`` stops the container — INV-10-adjacent); the orchestrator never bare-
cancels a run task without stopping its container, and never re-attaches to a
container started by a dead process (INV-10; that is 3.5's boot recovery).

Nothing here shells the ``dkmv`` CLI or edits ``dkmv/`` (INV-13) — the engine is
consumed in-process via the lifespan-owned :class:`~app.runtime.RunService`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.orchestrator.deadlines import Clock, utc_now
from app.orchestrator.loop_metrics import LoopMetrics
from app.orchestrator.reconcile import ReconcileDeps, ReconcileResult, RunKiller, reconcile_once

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path

    from app.config import Settings
    from app.db.repository import Repository
    from app.github.client import GitHubClient
    from app.github.graphql import BoardPage
    from app.github.hash_cache import HashCache
    from app.github.write_queue import WriteQueue
    from app.hitl.registry import DecisionRegistry
    from app.orchestrator.dispatch import BoundedDispatcher
    from app.orchestrator.retry import RetryScheduler
    from app.runs.launch import LaunchResult
    from app.runtime import RunService

_log = logging.getLogger(__name__)

#: The ``agent:*`` label that marks an issue as a dispatch candidate (§5.3.1 /
#: §8.2): an ``agent:queued`` issue with an assigned workflow is ready to run.
QUEUED_LABEL = "agent:queued"


class EngineRunKiller:
    """:class:`RunKiller` bound to the in-process engine (INV-10-adjacent).

    Resolves a run row's engine handle (by ``engine_run_id``) and calls
    ``stop(force=True)`` so the engine's ``finally`` **stops the container** — the
    only correct kill (a bare task-cancel would orphan a money-spending container,
    INV-10). Returns ``True`` iff a live handle existed in **this** process and was
    stopped; a run started by a now-dead process has no live handle → ``False`` (its
    container is reaped by 3.5's boot ``docker kill``, **never** re-attached here).
    """

    def __init__(self, run_service: RunService) -> None:
        self._run_service = run_service

    async def kill(self, run_row: dict[str, Any]) -> bool:
        engine_run_id = run_row.get("engine_run_id")
        if not engine_run_id:
            return False
        handle = self._run_service.runtime.get_handle(str(engine_run_id))
        if handle is None:
            # No live handle in this process — do NOT re-attach (INV-10). 3.5's
            # boot recovery docker-kills such an orphan; reconcile only signals it.
            return False
        await handle.stop(force=True)
        return True


@dataclass(slots=True)
class TickDeps:
    """Everything the tick loop needs, resolved from the app-state seam (deps.py).

    The lifespan composes this from its singletons (the single-writer
    :class:`Repository`, the GitHub client + serialized :class:`WriteQueue` + board
    hash-cache, the engine :class:`RunService`, the typed :class:`Settings`) and a
    ``dispatch`` callable that routes through the **existing** ``launch_run``
    boundary (ADR-P001). ``now`` is injectable so a frozen-clock test drives the
    UTC-persisted stall/timeout deadlines deterministically (AC-13).
    """

    repository: Repository
    github_client: GitHubClient
    write_queue: WriteQueue
    run_service: RunService
    settings: Settings
    dispatch: DispatchFn
    repo: str
    cache: HashCache[BoardPage] | None = None
    gauges: LoopMetrics = field(default_factory=LoopMetrics)
    now: Clock = field(default=utc_now)
    #: The Phase-5 bounded-dispatch gate (semaphore + per-state caps + aggregate
    #: admission — AC-1/2/3). Production wires it via :func:`build_tick_deps`; a bare
    #: unit test may leave it ``None``, in which case the tick falls back to the
    #: Phase-3 single-serial-dispatch behaviour (so legacy tick tests still pass).
    bounded_dispatcher: BoundedDispatcher | None = None
    #: The lifespan-composed HITL :class:`DecisionRegistry` (slice 2.5). Threaded
    #: into :class:`ReconcileDeps` so the production reconcile pass runs the
    #: pause-timeout auto-resolve sweep through the SAME exactly-once guard the
    #: human answer path uses (T104 / AC-17 — INV-9). ``None`` only in a bare test
    #: that drives ``run_tick`` without the registry; production always wires it.
    decisions: DecisionRegistry | None = None
    #: The lifespan-composed :class:`RetryScheduler` (slice 3.4 — the SAME singleton
    #: ``POST /runs/{id}/retry`` enqueues onto). Threaded into :class:`ReconcileDeps`
    #: so the production reconcile pass drives the stall→retry schedule + fires due
    #: backoffs through the idempotent re-dispatch (AC-14/15). ``None`` only in a
    #: bare test; production always wires it so the retry queue actually drains.
    retry_scheduler: RetryScheduler | None = None


#: A dispatch callable: given a built candidate, launch it through the existing
#: ``launch_run`` boundary and return the :class:`LaunchResult` (or ``None`` if it
#: could not be dispatched — e.g. it lost the claim-lock race). Bound by the
#: lifespan so the loop has exactly ONE launch path (ADR-P001); a test injects a
#: recording fake to assert "exactly one dispatch through the launch boundary".
DispatchFn = Any  # see _build_dispatch; typed loosely to keep the seam test-friendly


@dataclass(frozen=True, slots=True)
class Candidate:
    """One dispatchable queued issue (the issues-cache projection §8.2 needs).

    Built from an ``agent:queued`` issue with an assigned ``workflow_id``. The
    launch params flow from the issue's stored ``workflow_id`` + config defaults;
    ``priority``/``num`` drive the sort (priority asc, then oldest — lowest issue
    number is oldest, since GitHub issue numbers are monotonic).
    """

    repo: str
    num: int
    workflow_id: str
    agent: str | None = None
    priority: int = 0
    labels: tuple[str, ...] = ()
    #: The container memory the launch will request (admission input — AC-3). The
    #: candidate carries it so :class:`~app.orchestrator.admission.AdmissionController`
    #: sizes ``Σ memory + this run`` against ``HOST_MEMORY_BUDGET`` BEFORE the launch.
    #: ``None`` → the platform default memory is assumed (never treated as free).
    memory: str | None = None


@dataclass(frozen=True, slots=True)
class TickOutcome:
    """Outcome of one :func:`run_tick` pass (for tests + the heartbeat log).

    ``reconcile`` is the pass's reconcile result; ``dispatched`` is the list of
    candidates launched this tick (Phase 3 dispatches serially — at most one per
    tick within the existing constraints); ``preflight_ok`` records whether the
    environment probe passed (the loop skips dispatch when it does not).
    """

    reconcile: ReconcileResult
    dispatched: tuple[LaunchResult, ...] = ()
    preflight_ok: bool = True


async def run_tick(deps: TickDeps) -> TickOutcome:
    """Run ONE tick: reconcile → preflight → poll → sort → dispatch (AC-10).

    The single unit a test drives directly (and the loop body repeats on cadence).
    It reconciles first (so a stalled/orphaned run is reaped before new work is
    admitted), validates preflight, does **one** board read (reusing the Phase-1
    client + cache), reads the queued candidates from the issues cache, sorts them
    (priority asc, then oldest), and **dispatches through the existing
    ``launch_run`` boundary** (ADR-P001). Phase 3 dispatches **one** candidate per
    tick (serial, within the existing constraints — the concurrency *cap* is Phase
    5). Records the basic tick gauges (duration + heartbeat) on success.
    """
    started = time.monotonic()

    # 1. reconcile running runs (stall / authority-rule labels / orphan sweep).
    killer: RunKiller = EngineRunKiller(deps.run_service)
    reconcile_result = await reconcile_once(
        ReconcileDeps(
            repository=deps.repository,
            github_client=deps.github_client,
            write_queue=deps.write_queue,
            killer=killer,
            settings=deps.settings,
            cache=deps.cache,
            now=deps.now,
            # Wire the pause-timeout sweep + retry machinery into the LIVE tick
            # (slice 3.4): the lifespan-composed registry + scheduler drive the
            # exactly-once pause auto-resolve (AC-17 / INV-9) and the stall→retry +
            # due-backoff re-dispatch (AC-14/15). Without these the reconcile pass
            # defaults them to None and the machinery is dead code in production.
            decisions=deps.decisions,
            retry_scheduler=deps.retry_scheduler,
        ),
        deps.repo,
    )

    # 2. validate preflight — do not dispatch into a broken environment.
    preflight_ok = _preflight_ok(deps.run_service)

    dispatched: list[LaunchResult] = []
    queue_depth = 0
    dispatch_latency_s: float | None = None
    if preflight_ok:
        # 3. fetch candidates: ONE board read (refresh the cache), then read the
        #    queued candidates from the issues DB cache.
        await _refresh_board(deps)
        candidates = await _read_candidates(deps)
        # 4. sort: priority ascending, then oldest (lowest issue number) first.
        candidates.sort(key=lambda c: (c.priority, c.num))
        queue_depth = len(candidates)
        # 5. dispatch through the EXISTING launch boundary (ADR-P001). Phase 5 layers
        #    the cap (semaphore + per-state caps + aggregate admission) INTO this
        #    path: the bounded dispatcher dispatches UP TO ``available`` admitted
        #    candidates per tick, re-queuing the rest. Falls back to Phase-3 serial
        #    dispatch only when no bounded dispatcher is wired (a bare unit test).
        dispatch_started = time.monotonic()
        if deps.bounded_dispatcher is not None:
            result = await deps.bounded_dispatcher.dispatch_candidates(deps.repo, candidates)
            dispatched.extend(result.dispatched)
            deps.gauges.record_loop(
                slots_in_use=deps.bounded_dispatcher.slots.held,
                slots_capacity=deps.bounded_dispatcher.slots.capacity,
                queue_depth=queue_depth,
                reconcile_actions=reconcile_result.action_count,
                dispatch_latency_s=time.monotonic() - dispatch_started,
            )
        else:
            for candidate in candidates:
                launched = await deps.dispatch(candidate)
                if launched is not None:
                    dispatched.append(launched)
                    break  # serial dispatch fallback (no cap wired)
        dispatch_latency_s = time.monotonic() - dispatch_started

    deps.gauges.record_tick(duration_s=time.monotonic() - started)
    if deps.bounded_dispatcher is None:
        # Keep the workload gauges fresh even on the serial-fallback path so the
        # queue-depth / dispatch-latency gauges are populated for the heartbeat.
        deps.gauges.record_loop(
            slots_in_use=deps.gauges.slots_in_use,
            slots_capacity=deps.gauges.slots_capacity,
            queue_depth=queue_depth,
            reconcile_actions=reconcile_result.action_count,
            dispatch_latency_s=dispatch_latency_s,
        )
    deps.gauges.heartbeat()
    return TickOutcome(
        reconcile=reconcile_result,
        dispatched=tuple(dispatched),
        preflight_ok=preflight_ok,
    )


async def tick_loop(deps: TickDeps, *, stop: asyncio.Event) -> None:
    """The long-lived tick loop: run a tick every ``TICK_INTERVAL_S`` until stopped.

    The body of the tracked :class:`asyncio.Task` the lifespan starts. It runs
    :func:`run_tick` on the fixed cadence, swallowing per-tick exceptions (a single
    bad tick — a transient GitHub error — must not kill the whole loop; it is
    logged and the next tick retries) so the orchestrator stays live. The interval
    wait is interruptible by ``stop`` so shutdown cancels promptly. This is the
    loop's *cadence* sleep (between whole ticks), **not** a deadline timer — every
    deadline (stall/backoff/timeout) is a UTC-persisted comparison re-evaluated
    inside :func:`run_tick` (AC-13), never an ``asyncio.sleep`` until-due.
    """
    interval = deps.settings.TICK_INTERVAL_S
    _log.info("orchestrator.tick loop started repo=%s interval_s=%d", deps.repo, interval)
    while not stop.is_set():
        try:
            await run_tick(deps)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a bad tick must not kill the loop
            _log.exception("orchestrator.tick pass failed; continuing")
        # Cadence wait between whole ticks, interruptible by shutdown. NOT a
        # deadline timer (AC-13): deadlines are re-evaluated inside run_tick.
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
    _log.info("orchestrator.tick loop stopped repo=%s", deps.repo)


# ── candidate polling (one board read + the issues-cache projection) ──────────


async def _refresh_board(deps: TickDeps) -> None:
    """Do ONE GraphQL board read for the repo, reusing the Phase-1 client + cache.

    Refreshes the issues cache so the candidate read below sees current labels.
    Reuses :func:`app.github.sync.sync_issues` (the Phase-1 read+upsert path) so
    there is exactly one board-read implementation; a transient GitHub failure is
    logged and the tick proceeds against the last-known cache (the next tick
    re-reads). One read per tick (§8.2), never one stream per card.
    """
    from app.github.sync import sync_issues

    try:
        await sync_issues(
            deps.github_client,
            deps.repo,
            writer=deps.repository,
            cache=deps.cache,
        )
    except Exception:  # noqa: BLE001 - a transient board-read error must not kill the tick
        _log.warning("orchestrator.tick board read failed; using cached issues", exc_info=True)


async def _read_candidates(deps: TickDeps) -> list[Candidate]:
    """Read ``agent:queued`` issues with an assigned workflow from the cache (§8.2).

    A candidate is an issue carrying the ``agent:queued`` label **and** an assigned
    ``workflow_id`` (no workflow → nothing to dispatch). An issue that already has
    an active run is excluded (it is in progress, not queued) so a re-poll does not
    re-dispatch a live run — the claim-lock would reject it anyway (INV-5), but
    skipping it here avoids a wasted launch attempt. Read through the repository
    seam; the launch params are built from the stored ``workflow_id`` + config
    defaults.
    """
    from app.github.sync import ACTIVE_RUN_STATUSES

    issues = await deps.repository.read_issues(deps.repo)
    active_rows = await deps.repository.read_active_runs(deps.repo, sorted(ACTIVE_RUN_STATUSES))
    active_issue_nums = {int(r["issue_num"]) for r in active_rows if r.get("issue_num") is not None}
    candidates: list[Candidate] = []
    for issue in issues:
        num = int(issue["num"])
        if num in active_issue_nums:
            continue
        labels = _decode_labels(issue.get("labels_json"))
        if QUEUED_LABEL not in labels:
            continue
        workflow_id = issue.get("workflow_id")
        if not workflow_id:
            continue
        candidates.append(
            Candidate(
                repo=deps.repo,
                num=num,
                workflow_id=str(workflow_id),
                agent=issue.get("agent"),
                labels=tuple(labels),
            )
        )
    return candidates


#: Default base branch a tick-dispatched run targets when the project pins none.
#: The candidate carries only the issue + workflow; the branch/feature_name the
#: §8.4 launch contract requires are derived here (config default branch +
#: ``issue-<num>`` feature slug) so the tick dispatches through the SAME
#: ``launch_run`` boundary a manual ``POST /runs`` uses (ADR-P001).
DEFAULT_BASE_BRANCH = "main"


def build_dispatch(
    deps_factory: TickDepsFactory,
) -> DispatchFn:
    """Build the ``dispatch`` callable that routes a candidate through ``launch_run``.

    The single dispatch seam (ADR-P001): given a :class:`Candidate`, construct the
    §8.4 :class:`~app.runs.launch.LaunchRequest` from the issue's stored
    ``workflow_id`` + config defaults (agent ``auto`` resolves to the workflow's
    agent; branch = the project default; ``feature_name = issue-<num>``) and call
    the **existing** :func:`app.runs.launch.launch_run` — the very same boundary
    ``POST /runs`` uses. The tick introduces **no** second launch mechanism. A
    duplicate dispatch (the claim-lock lost — INV-5) is swallowed to ``None`` so a
    re-poll of a now-running issue is a no-op rather than a tick-killing 409.
    """
    import app.runs.launch as launch_mod
    from app.api.errors import ApiError
    from app.runs.launch import LaunchRequest

    async def _dispatch(candidate: Candidate) -> LaunchResult | None:
        ctx = deps_factory()
        feature_name = f"issue-{candidate.num}"
        current_labels = list(candidate.labels)
        req = LaunchRequest(
            issue_num=candidate.num,
            repo=candidate.repo,
            workflow_id=candidate.workflow_id,
            agent=candidate.agent or "auto",
            branch=ctx.base_branch,
            feature_name=feature_name,
            memory=ctx.default_memory,
        )
        try:
            return await launch_mod.launch_run(
                req,
                repository=ctx.repository,
                run_service=ctx.run_service,
                github_client=ctx.github_client,
                write_queue=ctx.write_queue,
                cache=ctx.cache,
                connected_repo=candidate.repo,
                project_root=ctx.project_root,
                default_memory=ctx.default_memory,
                current_labels=current_labels,
                attach_stream=ctx.attach_stream,
            )
        except ApiError as exc:
            # A duplicate dispatch (409 — the claim-lock was lost) or a transient
            # validation failure must not kill the tick; log + skip this candidate.
            if exc.status_code == 409:
                _log.debug(
                    "orchestrator.dispatch issue=%s already claimed; skipping", candidate.num
                )
            else:
                _log.warning("orchestrator.dispatch issue=%s rejected: %s", candidate.num, exc.code)
            return None

    return _dispatch


@dataclass(frozen=True, slots=True)
class DispatchContext:
    """The per-dispatch dependencies ``build_dispatch`` resolves from the lifespan.

    Carries the singletons ``launch_run`` needs (single-writer :class:`Repository`,
    engine :class:`RunService`, GitHub client + serialized :class:`WriteQueue` +
    board cache, the ``attach_stream`` SSE hook) plus the launch defaults (base
    branch + container memory). A factory returns a fresh context per dispatch so a
    test can inject its own.
    """

    repository: Repository
    run_service: RunService
    github_client: GitHubClient
    write_queue: WriteQueue
    base_branch: str = DEFAULT_BASE_BRANCH
    default_memory: str = "8g"
    cache: HashCache[BoardPage] | None = None
    attach_stream: Any | None = None
    project_root: Path | None = None


#: A zero-arg factory returning a fresh :class:`DispatchContext` per dispatch.
TickDepsFactory = Any


def _preflight_ok(run_service: RunService) -> bool:
    """Validate the standing environment before dispatching (§8.2 step 2).

    A cheap engine capability probe (``get_capabilities().ready``) so the loop does
    not launch into a broken environment (missing image / Docker down). A probe
    failure is treated as "not ready" — the tick reconciles + skips dispatch and
    retries next tick. Consumed in-process (INV-13).
    """
    try:
        report = run_service.get_capabilities()
    except Exception:  # noqa: BLE001 - a probe error means "not ready", skip dispatch
        _log.warning("orchestrator.tick preflight probe failed; skipping dispatch", exc_info=True)
        return False
    return bool(getattr(report, "ready", False))


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


# ── lifespan wiring (started as a tracked task; cancelled on shutdown — AC-10) ─


@dataclass(slots=True)
class OrchestratorHandle:
    """The running tick loop's handle (the lifespan holds it, cancels on shutdown).

    Pairs the tracked loop :class:`asyncio.Task` with its ``stop`` event so the
    lifespan can request a graceful stop (set the event → the cadence wait wakes)
    and then cancel/await the task. Composed by :func:`start_orchestrator`.
    """

    task: asyncio.Task[None]
    stop: asyncio.Event
    deps: TickDeps

    async def shutdown(self) -> None:
        """Stop + cancel + await the tick loop (idempotent) on lifespan shutdown."""
        self.stop.set()
        if not self.task.done():
            self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self.task


def build_tick_deps(app: Any, repo: str) -> TickDeps:
    """Compose :class:`TickDeps` from the lifespan-owned ``app.state`` singletons.

    Resolves the single-writer :class:`Repository`, the GitHub client + serialized
    :class:`WriteQueue` + board hash-cache, and the engine :class:`RunService`
    from the same ``app.state`` seam the serving handlers use (``deps.py``), and
    binds a ``dispatch`` callable routing through the **existing** ``launch_run``
    boundary (ADR-P001) via :func:`build_dispatch`. The dispatch context's
    ``attach_stream`` is bound to the slice-2.3 run-stream wiring so a tick-launched
    run streams + persists events exactly like a ``POST /runs`` one.
    """
    from app.api.deps import (
        CONCURRENCY_SLOTS_ATTR,
        DECISION_REGISTRY_ATTR,
        project_root_from_state,
    )
    from app.hitl.slots import ConcurrencySlots
    from app.orchestrator.admission import AdmissionController
    from app.orchestrator.dispatch import BoundedDispatcher, build_policy_from_settings
    from app.orchestrator.retry_deps import RETRY_SCHEDULER_ATTR, build_retry_scheduler
    from app.runs.service import DEFAULT_MEMORY
    from app.sse.run_stream import attach_run_stream

    state = app.state
    repository: Repository = state.repository
    github_client: GitHubClient = state.github_client
    write_queue: WriteQueue = state.github_write_queue
    run_service: RunService = state.run_service
    settings: Settings = state.settings
    cache: HashCache[BoardPage] | None = getattr(state, "github_hash_cache", None)
    registry = state.stream_registry

    # The lifespan-composed HITL registry + retry scheduler (the SAME singletons the
    # serving handlers resolve). The tick threads them into ReconcileDeps so the LIVE
    # reconcile pass drives the pause-timeout sweep (AC-17) + the stall→retry / due-
    # backoff re-dispatch (AC-14/15). The retry scheduler is resolved through the
    # cached app.state attr (composing it on first use via build_retry_scheduler) so
    # the tick and ``POST /runs/{id}/retry`` share ONE instance over ONE queue — a
    # manual enqueue is actually drained by the tick.
    decisions: DecisionRegistry | None = getattr(state, DECISION_REGISTRY_ATTR, None)
    retry_scheduler: RetryScheduler | None = getattr(state, RETRY_SCHEDULER_ATTR, None)
    if retry_scheduler is None:
        retry_scheduler = build_retry_scheduler(app)
    stream_tasks = getattr(state, "run_stream_tasks", None)
    if stream_tasks is None:
        stream_tasks = set()
        state.run_stream_tasks = stream_tasks

    def _attach_stream(run_id: str, handle: Any) -> None:
        attach_run_stream(
            run_id=run_id,
            handle=handle,
            registry=registry,
            repository=repository,
            tasks=stream_tasks,
        )

    # The lifespan-published local project root (slice 4.2 / DKMV_PROJECT_ROOT) so a
    # tick-dispatched candidate whose ``workflow_id`` is a registry NAME resolves
    # exactly like a ``POST /runs`` one (FIX-3). ``None`` when no local root is
    # configured (built-ins / absolute paths only). Read through the canonical
    # deps.py seam (consistent Path coercion — FIX-2) rather than a bare getattr.
    project_root = project_root_from_state(state)

    def _dispatch_context() -> DispatchContext:
        return DispatchContext(
            repository=repository,
            run_service=run_service,
            github_client=github_client,
            write_queue=write_queue,
            base_branch=DEFAULT_BASE_BRANCH,
            default_memory=DEFAULT_MEMORY,
            cache=cache,
            attach_stream=_attach_stream,
            project_root=project_root,
        )

    dispatch_fn = build_dispatch(_dispatch_context)

    # Phase-5 bounded dispatch (AC-1/2/3): gate the SAME ``launch_run`` boundary with
    # the shared concurrency semaphore (the one the pause bridge releases/reacquires —
    # INV-9), per-state caps, and the aggregate memory/spend admission. Composed from
    # the lifespan-owned ``concurrency_slots`` singleton so the cap, the pause
    # release, and the admission all share ONE permit pool + ONE settings object.
    slots: ConcurrencySlots = getattr(state, CONCURRENCY_SLOTS_ATTR, None) or ConcurrencySlots(
        capacity=settings.MAX_CONCURRENT_RUNS
    )
    setattr(state, CONCURRENCY_SLOTS_ATTR, slots)
    bounded_dispatcher = BoundedDispatcher(
        dispatch=dispatch_fn,
        slots=slots,
        admission=AdmissionController(repository=repository, settings=settings),
        repository=repository,
        policy=build_policy_from_settings(settings),
    )

    return TickDeps(
        repository=repository,
        github_client=github_client,
        write_queue=write_queue,
        run_service=run_service,
        settings=settings,
        dispatch=dispatch_fn,
        repo=repo,
        cache=cache,
        decisions=decisions,
        retry_scheduler=retry_scheduler,
        bounded_dispatcher=bounded_dispatcher,
    )


def start_orchestrator(app: Any, repo: str) -> OrchestratorHandle:
    """Start the tick loop as a tracked :class:`asyncio.Task` (lifespan startup).

    Composes :class:`TickDeps` from ``app.state`` and launches :func:`tick_loop`
    on the serving event loop, returning an :class:`OrchestratorHandle` the
    lifespan stores on ``app.state.orchestrator`` and ``shutdown()``s on teardown
    (cancel-on-shutdown — AC-10). One orchestrator per process.
    """
    deps = build_tick_deps(app, repo)
    stop = asyncio.Event()
    task = asyncio.create_task(tick_loop(deps, stop=stop), name=f"orchestrator-tick:{repo}")
    return OrchestratorHandle(task=task, stop=stop, deps=deps)


__all__ = [
    "DEFAULT_BASE_BRANCH",
    "QUEUED_LABEL",
    "Candidate",
    "DispatchContext",
    "DispatchFn",
    "EngineRunKiller",
    "OrchestratorHandle",
    "TickDeps",
    "TickOutcome",
    "build_dispatch",
    "build_tick_deps",
    "run_tick",
    "start_orchestrator",
    "tick_loop",
]
