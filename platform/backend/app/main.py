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

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import api_router
from app.api.errors import install_error_handlers
from app.config import Settings, get_settings
from app.db import Repository
from app.github.provider import aclose_github_client, build_pat_github_client
from app.github.write_queue import WriteQueue
from app.runtime import RunService
from app.secrets import Redactor, SecretStore, SecretStoreError, install_log_redaction
from app.security import AccessControlMiddleware

_log = logging.getLogger(__name__)


def _resolve_secret_key(settings: Settings) -> str:
    """Resolve the Fernet host key for the lifespan-owned :class:`SecretStore`.

    Prefers ``DKMV_SECRET_KEY`` (prod: OS keychain / sealed secret, §8.6). When
    unset (dev / tests) a fresh key is generated and cached on ``settings`` so
    the same process reuses it — encryption is **never** silently disabled, and a
    new key per call would make stored ciphertext undecryptable on read-back.
    """
    import os

    env_key = os.environ.get("DKMV_SECRET_KEY")
    if env_key:
        return env_key
    cached: str | None = getattr(settings, "_dkmv_dev_secret_key", None)
    if cached is None:
        cached = SecretStore.generate_key()
        object.__setattr__(settings, "_dkmv_dev_secret_key", cached)
    return cached


def _build_secret_store(repository: Repository, settings: Settings) -> SecretStore:
    """Build the single lifespan-owned :class:`SecretStore` over the repository.

    Persists ciphertext through the shared :class:`Repository` (the encrypted
    ``secrets`` table) so the PAT survives restarts; falls back to an env key or
    a generated dev key (:func:`_resolve_secret_key`) so encryption is always on
    (INV-4). One store per process replaces the slice-1.4 lazy per-request build.
    """
    try:
        return SecretStore(repository, key=_resolve_secret_key(settings))
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

    try:
        yield
    finally:
        write_queue = getattr(app.state, "github_write_queue", None)
        if isinstance(write_queue, WriteQueue):
            await write_queue.stop()
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
