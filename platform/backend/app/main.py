"""FastAPI application factory + ASGI entrypoint.

Slice 0.2 wires the working control-plane skeleton:

* the :class:`~app.security.AccessControlMiddleware` access-control stack
  (loopback ``Host`` + local token + ``Origin``/``Referer`` validation + CSRF on
  state-changing POSTs — INV-1 / NFR-SEC-2);
* the §8.9 error-envelope exception handlers;
* the liveness probe (token-exempt) + the engine-backed
  ``GET /api/v1/preflight`` (``get_capabilities()`` → ``{ready,checks,blockers}``);
* a single configured :class:`~app.runtime.RunService` on ``app.state`` — the
  only seam to the in-process DKMV engine (INV-13).

Run locally::

    uvicorn app.main:app --host 127.0.0.1 --port 8787

The container entrypoint reads ``Settings.DKMV_PLATFORM_BIND`` (default
``127.0.0.1:8787``) for the loopback bind address.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.api import api_router
from app.api.deps import resolve_secret_key
from app.api.errors import install_error_handlers
from app.config import Settings, get_settings
from app.db import Repository
from app.github.provider import aclose_github_client, build_pat_github_client
from app.github.write_queue import DEFAULT_DRAIN_GRACE_SECONDS, WriteQueue
from app.hitl import ConcurrencySlots, DecisionRegistry
from app.observability import install_structured_logging
from app.orchestrator.recovery import DockerOrphanReaper, RecoveryDeps, recover_orphans
from app.orchestrator.retry_deps import RETRY_SCHEDULER_ATTR, build_retry_scheduler
from app.orchestrator.tick import EngineRunKiller, OrchestratorHandle, start_orchestrator
from app.runtime import RunService
from app.secrets import Redactor, SecretStore, SecretStoreError, install_log_redaction
from app.security import AccessControlMiddleware, AuditLog
from app.sse import StreamRegistry
from app.sse.run_stream import RUN_STREAM_TASKS_ATTR

_log = logging.getLogger(__name__)


async def _cancel_stream_tasks(tasks: set[asyncio.Task[Any]]) -> None:
    """Cancel + await every live per-run pump/supervisor task on shutdown (FIX-1).

    Snapshots the set (tasks remove themselves via a done-callback), cancels each,
    and awaits them swallowing ``CancelledError`` so a draining process tears the
    streams down cleanly instead of leaking a pump blocked on its hub queue.
    """
    pending = list(tasks)
    for task in pending:
        if not task.done():
            task.cancel()
    for task in pending:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


def _resolve_project_root(settings: Settings) -> Path | None:
    """Resolve + validate the optional local project root, or ``None`` (slice 4.2).

    ``DKMV_PROJECT_ROOT`` is the LOCAL on-disk working copy of the connected project
    (the directory holding ``.dkmv/`` — the ``components.json`` registry + any custom
    components authored on disk). It is published once on ``app.state.project_root``
    and read **read-only** by both the Workflows viewer (so a registry-registered
    custom component appears in ``GET /workflows``) and the launch path (so a
    registry-NAME ``workflow_id`` resolves in ``POST /runs``).

    Unset → ``None`` (the viewer lists built-ins only; only built-ins / absolute
    paths are dispatchable — graceful, no error). When set but the path does not
    exist (or is not a directory), we **log and treat as None** rather than crash —
    a misconfigured local root must never wedge boot (the viewer degrades to
    built-ins; the operator fixes the path and restarts). This is independent of
    ``orchestrator_repo`` (the GitHub repo slug) — a connected project is not
    required for a local checkout to exist, and vice-versa.
    """
    root = settings.DKMV_PROJECT_ROOT
    if root is None:
        return None
    resolved = Path(root).expanduser()
    if not resolved.is_dir():
        _log.warning(
            "DKMV_PROJECT_ROOT %s is not an existing directory; "
            "treating as unset (Workflows viewer lists built-ins only)",
            resolved,
        )
        return None
    return resolved.resolve()


async def _resolve_orchestrator_repo(repository: Repository) -> str | None:
    """Resolve the connected project's repo for the tick loop, or ``None`` (slice 3.3).

    The orchestrator polls **one** project's board (v1 connects a single project,
    §8.8). The repo is resolved from the first ``projects`` row through the
    repository's public WAL read seam (INV-6 — no second connection, no write). When
    no project is connected yet (a fresh install before ``POST /connect``), this
    returns ``None`` and the lifespan skips starting the loop — there is nothing to
    poll; the loop is started on the next boot once a project exists. A read failure
    (e.g. a partially-migrated DB) is swallowed to ``None`` so a boot is never wedged
    by orchestrator startup.
    """
    try:
        async with repository.read_connection() as conn:
            rows = await conn.execute_fetchall(
                "SELECT repo FROM projects ORDER BY created_at LIMIT 1"
            )
    except Exception:  # noqa: BLE001 - never wedge boot on orchestrator repo resolution
        _log.warning("orchestrator repo resolution failed; tick loop not started", exc_info=True)
        return None
    row = next(iter(rows), None)
    return str(row["repo"]) if row is not None else None


async def _run_boot_recovery(app: FastAPI, repo: str) -> None:
    """Boot crash-recovery scan — runs at startup BEFORE the tick dispatches (3.5).

    Honors INV-10 / ADR-P007 / R-15: for each non-terminal ``runs`` row the dead
    process left in-flight, ``docker kill`` the orphaned (budget-burning) container
    via the :class:`DockerOrphanReaper` seam, mark the run ``interrupted``, and offer
    a jittered + semaphore-bounded ``start_task`` retry through **3.4's existing**
    scheduler (no second launch path). It does **not** re-attach to any container
    started by the dead process — the engine has no such API. Composed from the same
    lifespan singletons the tick uses; a recovery failure is swallowed so a boot is
    never wedged by the orphan sweep (the next boot retries). Called **before**
    :func:`start_orchestrator` so no new run is dispatched while orphans are reaped.
    """
    state = app.state
    settings: Settings = state.settings
    repository: Repository = state.repository
    run_service: RunService = state.run_service
    scheduler = getattr(state, RETRY_SCHEDULER_ATTR, None)
    # Anti-thundering-herd (AC-19): bound the boot recovery retry offers by the
    # configured concurrency so N orphans never re-dispatch onto Docker + GitHub all
    # at once. The Phase-3 tick dispatches serially (the admission *cap* is Phase 5);
    # this dedicated semaphore caps only the recovery fan-out, jittered per orphan.
    semaphore = asyncio.Semaphore(max(1, settings.MAX_CONCURRENT_RUNS))
    try:
        await recover_orphans(
            RecoveryDeps(
                repository=repository,
                reaper=DockerOrphanReaper(run_service),
                repo=repo,
                retry_scheduler=scheduler,
                concurrency=semaphore,
            )
        )
    except Exception:  # noqa: BLE001 - never wedge boot on the orphan-recovery sweep
        _log.warning("orchestrator boot recovery failed; continuing startup", exc_info=True)


def _register_sigterm_drain(app: FastAPI, repo: str) -> Any | None:
    """Register a SIGTERM handler that gracefully drains live runs (3.5 — AC-18).

    A ``docker compose restart`` delivers SIGTERM. The handler schedules
    :func:`app.orchestrator.drain.drain_with_stop` on the serving loop so it (1)
    stops the tick dispatching new runs and (2) calls ``RunHandle.stop(force=True)``
    on every live run — stopping its container (INV-10; **never** a bare task-cancel
    that would orphan a money-spending container) — within the drain deadline,
    marking any it could not cleanly stop ``interrupted`` for the next boot sweep.

    Registered via ``loop.add_signal_handler`` when the running loop supports it
    (POSIX). On a platform without signal-handler support (or when no orchestrator is
    running), this is a no-op and the lifespan ``finally`` drain is the backstop.
    Returns the previously-registered handler reference (currently unused) or
    ``None``.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover - lifespan always has a running loop
        return None

    def _on_sigterm() -> None:
        _log.info("SIGTERM received; starting graceful drain")
        loop.create_task(_drain_orchestrator(app))  # noqa: RUF006 - fire-and-forget drain on shutdown

    try:
        loop.add_signal_handler(signal.SIGTERM, _on_sigterm)
    except (NotImplementedError, ValueError, RuntimeError):
        # Non-POSIX / no main thread: no signal handler. The shutdown drain backstops.
        _log.info("SIGTERM handler unavailable on this platform; relying on shutdown drain")
        return None
    return _on_sigterm


async def _drain_orchestrator(app: FastAPI) -> None:
    """Stop dispatch + stop every live run's container (the SIGTERM/shutdown drain).

    The shared drain body the SIGTERM handler and the lifespan ``finally`` both call
    (idempotent — a second drain over already-stopped runs is a no-op). It binds the
    **same** :class:`EngineRunKiller` the tick uses (``RunHandle.stop(force=True)`` —
    INV-10) and the orchestrator's ``stop`` event so dispatch halts first, then
    drains live runs within the deadline, marking any undrained run ``interrupted``.
    Swallows errors so a drain never crashes shutdown.
    """
    from app.orchestrator.drain import DrainDeps, drain, drain_with_stop

    orchestrator = getattr(app.state, "orchestrator", None)
    repo = getattr(orchestrator, "deps", None)
    repo_name = getattr(repo, "repo", None)
    if repo_name is None:
        repo_name = getattr(app.state, "orchestrator_repo", None)
    if repo_name is None:
        return
    deps = DrainDeps(
        repository=app.state.repository,
        killer=EngineRunKiller(app.state.run_service),
        repo=str(repo_name),
    )
    try:
        if isinstance(orchestrator, OrchestratorHandle):
            await drain_with_stop(deps, stop=orchestrator.stop)
        else:
            await drain(deps)
    except Exception:  # noqa: BLE001 - a drain must never crash shutdown
        _log.warning("orchestrator graceful drain failed", exc_info=True)


def _build_secret_store(repository: Repository, settings: Settings) -> SecretStore:
    """Build the single lifespan-owned :class:`SecretStore` over the repository.

    Persists ciphertext through the shared :class:`Repository` (the encrypted
    ``secrets`` table) so the PAT survives restarts; falls back to an env key or
    a generated dev key (:func:`app.api.deps.resolve_secret_key`) so encryption is
    always on (INV-4). One store per process replaces the slice-1.4 lazy
    per-request build.
    """
    try:
        return SecretStore(repository, key=resolve_secret_key(settings))
    except SecretStoreError:  # pragma: no cover - defensive; key is always resolvable
        return SecretStore(repository, key=SecretStore.generate_key())


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Compose + tear down the process-wide singletons on ``app.state`` (slice 2.0).

    On **startup**, build exactly ONE of each long-lived component on the serving
    event loop so Phase 2's per-run SSE pump (2.3) writes through ONE shared
    :class:`Repository` and the SQLite single-writer contract holds (INV-6 — one
    writer task per process):

    * ``app.state.repository`` — one :class:`Repository` seeded with
      ``Redactor.from_settings`` so the **events** path scrubs the platform's own
      concrete secret VALUES (not just shapes), the INV-4 backstop slice 0.5
      deferred to here;
    * ``app.state.secret_store`` — one encrypted :class:`SecretStore` (real host
      key, not a per-request ephemeral one);
    * ``app.state.github_client`` — the cached :class:`PatGitHubClient` (built
      once unless a test already injected a client) whose owned ``httpx`` client
      is ``aclose()``-d on shutdown (the 1.1 seam);
    * ``app.state.github_write_queue`` — one serialized :class:`WriteQueue`
      (INV-11) every mutating GitHub call shares.

    On **shutdown**, tear them down cleanly (drain the write-queue, aclose the
    GitHub client, close the Repository → stop the single writer task).
    """
    settings: Settings = app.state.settings

    # The local on-disk project root (slice 4.2 / FR-07-1v). Published ONCE here from
    # ``DKMV_PROJECT_ROOT`` (resolved + existence-validated; a missing path degrades
    # to ``None`` rather than crashing boot) and consumed read-only by BOTH the
    # Workflows viewer (``GET /workflows`` → ``list_components(project_root)`` surfaces
    # registered custom components — AC-5) and the launch path (``POST /runs`` resolves
    # a registry-NAME ``workflow_id`` — AC-8). Independent of ``orchestrator_repo``: a
    # local checkout can exist with no connected GitHub project, and vice-versa. A test
    # that pre-injects ``app.state.project_root`` keeps its injection (the settings
    # value is authoritative only when no override is present).
    if getattr(app.state, "project_root", None) is None:
        app.state.project_root = _resolve_project_root(settings)

    repository = Repository(settings.DATABASE_URL, redactor=Redactor.from_settings(settings))
    await repository.start()
    app.state.repository = repository

    # The durable §8.6 audit log (slice 5.3 / AC-12). Composed ONCE here, co-located
    # with the single SQLite file (the spend + audit source of truth, §6.5), and
    # seeded with ``Redactor.from_settings`` so every audit line is scrubbed of the
    # platform's OWN concrete secret VALUES (not just shapes) before persistence
    # (INV-4 — a leak into the audit trail is as permanent as one into ``events``).
    # Published on ``app.state.audit`` so the run-launch / token-mint-use / egress-
    # denial / decision-resolution call sites record their evidence line through one
    # shared sink. A test may pre-inject ``app.state.audit`` (e.g. a MemoryAuditSink)
    # — that injection is authoritative; the file sink is the production default.
    if getattr(app.state, "audit", None) is None:
        app.state.audit = AuditLog.from_database_url(
            settings.DATABASE_URL,
            redactor=Redactor.from_settings(settings),
        )

    secret_store = _build_secret_store(repository, settings)
    app.state.secret_store = secret_store

    # Bind the run-token minter + audit sink onto the (app-creation-time) RunService
    # now that the encrypted SecretStore and the audit log exist (slice 5.3 / AC-12).
    # This is what makes the ``token_mint`` + ``token_use`` §8.6 audit kinds actually
    # recorded IN PRODUCTION: the launch path's ``RunService.start`` mints a repo-
    # scoped, ≤1 hr token (INV-4) and authorizes the push, passing this audit sink —
    # previously those two kinds were exercised only by tests (dormant hooks).
    app.state.run_service.bind_run_token_minting(
        secret_store=secret_store,
        audit=getattr(app.state, "audit", None),
    )

    # Build the GitHub client once unless a test/connect already injected one.
    if getattr(app.state, "github_client", None) is None:
        app.state.github_client = await build_pat_github_client(secret_store, settings)

    if getattr(app.state, "github_write_queue", None) is None:
        app.state.github_write_queue = WriteQueue()

    # The process-wide per-run SSE fan-out registry (slice 2.3). One registry per
    # process / event loop: the launch path registers a run's observer + pump on a
    # hub here, and the SSE endpoint attaches subscribers to the same hub so the
    # pump's publish target and the live connections share one fan-out point.
    if getattr(app.state, "stream_registry", None) is None:
        app.state.stream_registry = StreamRegistry()

    # The HITL await/resume rendezvous + the concurrency-slot accounting (slice
    # 2.5). The pause bridge registers a keyed future per decision here and awaits
    # it; ``POST /runs/{id}/answer`` (and the timeout sweep) fire it after winning
    # the exactly-once DB guard (INV-9). ``slots`` is the slot-release-on-pause /
    # reacquire-on-resume primitive (T086) Phase 5's admission semaphore consumes;
    # Phase 2 does not enforce the cap (it accounts only).
    if getattr(app.state, "decision_registry", None) is None:
        app.state.decision_registry = DecisionRegistry()
    if getattr(app.state, "concurrency_slots", None) is None:
        app.state.concurrency_slots = ConcurrencySlots(
            capacity=settings.MAX_CONCURRENT_RUNS,
        )

    # The process-wide retry scheduler (slice 3.4 / §8.2 — AC-14/15/16). Composed
    # ONCE here from the lifespan-owned singletons (single-writer Repository,
    # GitHub client, the existing ``launch_run`` re-dispatch boundary — ADR-P001)
    # and cached on ``app.state.retry_scheduler`` so the orchestrator tick (firing
    # due backoffs + scheduling stall→retry — reconcile.drive_retries), ``POST
    # /runs/{id}/retry`` (enqueuing a manual retry), and ``GET /retry-queue``
    # (projecting) all share the SAME instance over ONE persisted queue. Without
    # composing it here the tick would default ``retry_scheduler=None`` and the
    # retry machinery would be dead code in production (a manual retry would enqueue
    # but never drain). ``build_retry_scheduler`` is idempotent — it sets the
    # cached attr; the API resolver returns this same singleton.
    if getattr(app.state, RETRY_SCHEDULER_ATTR, None) is None:
        build_retry_scheduler(app)

    # The set of live per-run pump/supervisor tasks (slice 2.3 / FIX-1). Each
    # launched run spawns one EventPump + one completion supervisor here; the set
    # is tracked so shutdown can cancel any still-running stream (a task removes
    # itself from the set when it finishes — no unbounded growth).
    if getattr(app.state, RUN_STREAM_TASKS_ATTR, None) is None:
        setattr(app.state, RUN_STREAM_TASKS_ATTR, set())

    # The in-process orchestrator tick loop (slice 3.3 / §8.2 — AC-10). Started as
    # a tracked asyncio.Task on the serving loop ONCE a project repo is known
    # (resolved from the connected ``projects`` row), and cancelled on shutdown.
    # It reconciles running runs (stall / authority-rule labels / orphan sweep),
    # polls candidate ``agent:queued`` issues, and dispatches through the EXISTING
    # ``launch_run`` boundary (ADR-P001 — no second launch path). Skipped when no
    # project is connected yet (nothing to poll); the loop is also driven directly
    # in tests via ``run_tick`` without entering the lifespan.
    app.state.orchestrator = None
    orchestrator_repo = await _resolve_orchestrator_repo(repository)
    app.state.orchestrator_repo = orchestrator_repo
    if orchestrator_repo is not None:
        # Boot crash recovery FIRST (slice 3.5 / §8.2 — INV-10, ADR-P007): before
        # the tick dispatches any new run, ``docker kill`` every orphan container the
        # dead process left alive, mark those runs ``interrupted``, and offer a
        # jittered + semaphore-bounded ``start_task`` retry through 3.4's scheduler.
        # NO re-attach (the engine has no such API — R-15). Run before the tick so a
        # reaped orphan's slot is free and a recovery retry races no fresh dispatch.
        await _run_boot_recovery(app, orchestrator_repo)
        # Register the SIGTERM graceful-drain handler (slice 3.5 — AC-18): on a
        # ``docker compose restart`` it stops dispatch + ``RunHandle.stop(force=True)``s
        # every live run (stopping its container — INV-10), marking the undrained
        # ``interrupted`` for the next boot sweep. The lifespan ``finally`` drain is
        # the backstop on a platform without signal-handler support.
        _register_sigterm_drain(app, orchestrator_repo)
        app.state.orchestrator = start_orchestrator(app, orchestrator_repo)

    try:
        yield
    finally:
        # Graceful drain on shutdown (slice 3.5 — AC-18 / INV-10): stop every live
        # run's container BEFORE cancelling the tick + tearing down singletons, so a
        # ``docker compose restart`` never leaves an orphaned money-spending
        # container. Idempotent with the SIGTERM handler (a second drain is a no-op).
        if getattr(app.state, "orchestrator_repo", None) is not None:
            await _drain_orchestrator(app)
        # Stop + cancel + await the tick loop first so it stops dispatching new
        # runs and reconciling before the singletons it depends on are torn down.
        orchestrator = getattr(app.state, "orchestrator", None)
        if isinstance(orchestrator, OrchestratorHandle):
            await orchestrator.shutdown()
        # Cancel any in-flight per-run pump/supervisor tasks (slice 2.3 / FIX-1) so
        # a draining process doesn't leak a pump blocked on its hub. This is the
        # graceful-shutdown path; orphan-container recovery on a HARD crash is
        # Phase 3 (INV-10 — no re-attach, kill+interrupt+retry).
        stream_tasks = getattr(app.state, RUN_STREAM_TASKS_ATTR, None)
        if isinstance(stream_tasks, set):
            await _cancel_stream_tasks(stream_tasks)
        write_queue = getattr(app.state, "github_write_queue", None)
        if isinstance(write_queue, WriteQueue):
            # Graceful, BOUNDED drain (INV-11): flush any in-flight / queued
            # ``agent:*`` label PUT so the GitHub label and the DB row stay
            # consistent, but cancel any remainder after the grace window so a
            # token-bucket-paced backlog cannot wedge shutdown forever.
            await write_queue.stop(grace=DEFAULT_DRAIN_GRACE_SECONDS)
        await aclose_github_client(app)
        await repository.close()


def create_app(
    settings: Settings | None = None,
    run_service: RunService | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    Args:
        settings: Optional settings override (tests inject a throwaway one);
            defaults to the process-wide cached settings.
        run_service: Optional pre-built run service (tests inject one whose
            engine is a fast in-process fake so they don't require Docker);
            defaults to one constructed from ``settings`` with the
            platform-owned ``output_dir`` bound to ``settings.OUTPUT_DIR``.
    """
    settings = settings or get_settings()

    # NFR-OBS-1 / INV-4 (slice 5.3): configure the ROOT logger for STRUCTURED,
    # OTel-compatible logs at boot — a JSON line per record carrying the active
    # ``run_id``/``issue``/``session`` correlation block (the schema the deferred
    # GenAI tracer, N8, upgrades onto additively) — AND install the
    # redact-before-persist filter on it. The redactor is seeded from settings
    # (``Redactor.from_settings``) so it scrubs BOTH the known credential *shapes*
    # AND the platform's OWN concrete secret VALUES, catching a leak even when the
    # value's shape is non-standard; ``install_structured_logging`` attaches the
    # RedactingLogFilter to the structured handler so no log line — message OR
    # assembled JSON — can carry a secret (the "no secret reaches logs" guarantee).
    redactor = Redactor.from_settings(settings)
    install_structured_logging(redactor)
    # Belt-and-braces: also attach the message-level redaction filter directly to
    # the root logger (idempotent) so a record handled before the structured
    # handler — or by a handler a test adds — is still scrubbed (INV-4).
    install_log_redaction(redactor)

    app = FastAPI(
        title="DKMV Platform",
        version="0.1.0",
        description="Self-hostable control plane wrapping the DKMV engine.",
        lifespan=_lifespan,
    )
    app.state.settings = settings
    app.state.run_service = run_service or RunService(settings)

    # The DB / SecretStore / GitHub-client / write-queue singletons are composed
    # on ``app.state`` by ``_lifespan`` at startup (and torn down at shutdown) —
    # see slice 2.0. The lifespan seeds the Repository with
    # ``Redactor.from_settings(settings)`` so the append-only ``events`` path
    # scrubs the platform's OWN concrete secret VALUES, not just their shapes
    # (the INV-4 events-path backstop slice 0.5 deferred here).

    # INV-1: the access-control stack wraps the whole app. Added last so it is
    # the outermost middleware (it runs before routing on every request).
    app.add_middleware(AccessControlMiddleware, settings=settings)

    install_error_handlers(app)
    # Single versioned parent router (owns the /api/v1 prefix); feature routers
    # attach to it in app.api, not here.
    app.include_router(api_router)
    return app


app = create_app()
