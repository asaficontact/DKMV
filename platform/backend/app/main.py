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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
from app.orchestrator.retry_deps import RETRY_SCHEDULER_ATTR, build_retry_scheduler
from app.orchestrator.tick import OrchestratorHandle, start_orchestrator
from app.runtime import RunService
from app.secrets import Redactor, SecretStore, SecretStoreError, install_log_redaction
from app.security import AccessControlMiddleware
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

    repository = Repository(settings.DATABASE_URL, redactor=Redactor.from_settings(settings))
    await repository.start()
    app.state.repository = repository

    secret_store = _build_secret_store(repository, settings)
    app.state.secret_store = secret_store

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
    if orchestrator_repo is not None:
        app.state.orchestrator = start_orchestrator(app, orchestrator_repo)

    try:
        yield
    finally:
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

    # INV-4 / NFR-OBS-1 ("never logged"): attach the RedactingLogFilter to the
    # ROOT logger at boot so no structured-log line emitted by any handler can
    # carry a secret. Seed it from settings (Redactor.from_settings) so it scrubs
    # BOTH the known credential *shapes* (the structural patterns in
    # app.secrets.redaction) AND the platform's OWN concrete secret VALUES (the
    # SecretStr fields on Settings) — catching a leak even when the value's shape
    # is non-standard. Without this wiring the redactor is dead code and the
    # "no secret reaches logs" guarantee is unenforced at runtime.
    install_log_redaction(Redactor.from_settings(settings))

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
