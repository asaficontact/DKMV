"""Shared ``app.state`` access seam for the serving path (slice 2.0 — FIX-1).

The control-plane singletons — the single-writer :class:`Repository` (INV-6), the
encrypted :class:`SecretStore` (INV-4), the serialized GitHub :class:`WriteQueue`
(INV-11), and the GraphQL board hash-cache (§8.1) — are composed **once** by the
app-lifespan (``app.main._lifespan``) on ``app.state``. Every serving handler must
**reuse** those singletons, never build its own (a per-request Repository would
spawn a second writer task and break the SQLite single-writer contract; a
per-request WriteQueue would let two label PUTs race GitHub's secondary budget).

Before this module the ``getattr(app.state, X, ...)`` + per-request build/start/
close fallback was duplicated verbatim across ``issues.py``, ``board.py``,
``agent_state.py`` and (for the secret store) ``connect.py``. That duplication is
the seam Phase 2's 2.1 (claim-lock), 2.3 (SSE pump) and 2.5 (HITL bridge) all
consume, so it lives here in exactly ONE place.

**Resolution contract (identical for every resolver):**

1. If the lifespan-owned singleton is present on ``app.state`` (production, or a
   test that injected one), return it as-is and do **not** tear it down — its
   owner (the lifespan) manages its lifecycle.
2. **Test fallback only** (a bare :class:`~fastapi.testclient.TestClient` that did
   not enter the lifespan): build the component on the serving loop and — for the
   :class:`Repository` — ``start()``/``close()`` it per request so the writer task
   is created and torn down on the live loop (a cached cross-request writer would
   be bound to a stale, closed loop).

This module constructs no GitHub URL and never touches ``dkmv/`` — it only wires
the app-state seam.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import Request

from app.db.repository import Repository
from app.github.graphql import BoardPage
from app.github.hash_cache import HashCache
from app.github.write_queue import WriteQueue
from app.secrets import SecretStore

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.config import Settings

#: ``app.state`` attribute names. Centralized here so every slice agrees on the
#: seam (the names are unchanged from the per-router constants they replace).
REPO_ATTR = "repository"
WRITE_QUEUE_ATTR = "github_write_queue"
SECRET_STORE_ATTR = "secret_store"
BOARD_CACHE_ATTR = "github_hash_cache"


def resolve_secret_key(settings: Settings) -> str:
    """Resolve the Fernet host key for a **test-fallback** :class:`SecretStore`.

    In production the lifespan-owned store is reused and this is never reached;
    only the no-lifespan test fallback resolves a key here. ``DKMV_SECRET_KEY``
    (prod: OS keychain / sealed secret, §8.6) wins; otherwise a generated dev key
    is cached on ``settings`` so encryption is **never** silently disabled (INV-4)
    and the same process reuses one key (a new key per call would make stored
    ciphertext undecryptable on read-back).
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


@asynccontextmanager
async def get_repository(request: Request) -> AsyncIterator[Repository]:
    """Yield the platform :class:`Repository` for this request (INV-6 writer).

    Reuses the lifespan-owned ``app.state.repository`` (slice 2.0 — the single
    per-process writer task) without closing it; **as a test fallback only** (no
    lifespan), build + ``start()`` a request-scoped Repository on the serving loop
    and ``close()`` it on exit. The single shared resolver every read/write path
    routes through (replaces the verbatim ``_repository`` copies in ``issues.py`` /
    ``board.py`` / ``agent_state.py``).
    """
    injected = getattr(request.app.state, REPO_ATTR, None)
    if injected is not None:
        assert isinstance(injected, Repository)
        yield injected
        return
    settings: Settings = request.app.state.settings
    repository = Repository(settings.DATABASE_URL)
    await repository.start()
    try:
        yield repository
    finally:
        await repository.close()


def get_write_queue(request: Request) -> WriteQueue:
    """Return the single process-wide GitHub :class:`WriteQueue` from ``app.state``.

    The app-lifespan composes ONE serialized, token-bucket-paced queue on
    ``app.state.github_write_queue`` (§8.1, INV-11) every mutating GitHub call
    shares, and drains it on shutdown. The serving path reuses it; **as a test
    fallback only** (no lifespan) a queue is built and cached on first use. Tests
    may also inject their own before the first request.
    """
    existing = getattr(request.app.state, WRITE_QUEUE_ATTR, None)
    if existing is not None:
        assert isinstance(existing, WriteQueue)
        return existing
    queue = WriteQueue()
    setattr(request.app.state, WRITE_QUEUE_ATTR, queue)
    return queue


def get_secret_store(request: Request) -> SecretStore:
    """Return the single lifespan-owned :class:`SecretStore` from ``app.state``.

    The app-lifespan composes exactly ONE :class:`SecretStore` on
    ``app.state.secret_store`` at startup (real host key, persisted through the
    shared :class:`Repository` — INV-4), so handlers **reuse** it rather than
    building an ephemeral per-request store. **As a test fallback only** (a
    :class:`~fastapi.testclient.TestClient` that did not enter the lifespan), build
    an in-memory store from the env/dev key once and cache it on ``app.state`` —
    the store always encrypts at rest (INV-4); only the persistence backend
    (DB vs. in-memory) varies.
    """
    existing: SecretStore | None = getattr(request.app.state, SECRET_STORE_ATTR, None)
    if existing is not None:
        return existing
    settings: Settings = request.app.state.settings
    repository = getattr(request.app.state, REPO_ATTR, None)
    store = SecretStore(repository, key=resolve_secret_key(settings))
    setattr(request.app.state, SECRET_STORE_ATTR, store)
    return store


def get_board_cache(request: Request) -> HashCache[BoardPage]:
    """Return (building+caching once) the shared GraphQL board hash-cache (§8.1).

    GraphQL has no ETag, so we self-hash ``(query, variables)`` to coalesce
    identical reads; the cache is process-wide (one event loop) and shared between
    slice 1.2's read path and slice 1.3's label-write invalidation, so a write
    invalidating it makes the next board read reflect the change (no stale page).
    """
    existing = getattr(request.app.state, BOARD_CACHE_ATTR, None)
    if existing is not None:
        assert isinstance(existing, HashCache)
        return existing
    cache: HashCache[BoardPage] = HashCache()
    setattr(request.app.state, BOARD_CACHE_ATTR, cache)
    return cache
