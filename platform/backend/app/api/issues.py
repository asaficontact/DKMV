"""Issue sync + board list endpoints (PRD §8.1, §5.3.1 — slice 1.2).

Two routes, both behind the app-wide :class:`~app.security.AccessControlMiddleware`
(INV-1 — loopback + token + Host/Origin + CSRF), like every Phase-1 endpoint:

* ``POST /projects/{repo}/sync`` — the Connect "Open project" action (FR-01-5).
  Ensures the four ``agent:*`` control-plane labels exist on the repo (created on
  connect if absent; idempotent — §8.1, AC-4), then imports the repo's issues into
  the platform ``issues`` cache **through the repository layer** (never raw SQL)
  via :func:`app.github.sync.sync_issues` over the paginated GraphQL board read.

* ``GET /repos/{repo}/issues`` — the board list (FR-02-7). Returns each cached
  issue with its board ``state`` **derived per §5.3.1** (label→column) and the
  **authority rule** applied (active-run DB row > label, §8.1).

The GraphQL hash-cache (GraphQL has no ETag — §8.1) is held on ``app.state`` and
shared across syncs (and, in 1.3, the write-queue's reads). The
:class:`~app.github.client.GitHubClient` is resolved from ``app.state`` (the PAT
backend in v1; the App backend slots behind the same interface, ADR-P004).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request

from app.api.errors import ApiError
from app.db.repository import Repository
from app.github.client import GitHubAuthError, GitHubError
from app.github.graphql import BoardPage
from app.github.hash_cache import HashCache
from app.github.labels import AGENT_LABEL_NAMES, EnsureLabelsResult, ensure_agent_labels
from app.github.provider import get_github_client
from app.github.sync import (
    build_board_list,
    read_board_via_repository,
    sync_issues,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.config import Settings

# No prefix here: the ``/api/v1`` version prefix is owned by the single parent
# router in :mod:`app.api`, which this router attaches to.
router = APIRouter(tags=["github"])

#: ``app.state`` attribute names so concurrent slices agree on the seam.
_CACHE_ATTR = "github_hash_cache"
_REPO_ATTR = "repository"


def _board_cache(request: Request) -> HashCache[BoardPage]:
    """Return (building+caching once) the shared GraphQL board hash-cache (§8.1).

    GraphQL has no ETag, so we self-hash ``(query, variables)`` to coalesce
    identical reads; the cache is process-wide (one event loop) and shared with
    slice 1.3's rate-limit work.
    """
    existing = getattr(request.app.state, _CACHE_ATTR, None)
    if existing is not None:
        assert isinstance(existing, HashCache)
        return existing
    cache: HashCache[BoardPage] = HashCache()
    setattr(request.app.state, _CACHE_ATTR, cache)
    return cache


@asynccontextmanager
async def _repository(request: Request) -> AsyncIterator[Repository]:
    """Yield the platform :class:`Repository` for this request (INV-6 writer).

    The app-lifespan (slice 2.0) composes ONE long-lived, app-loop-bound
    :class:`Repository` on ``app.state.repository`` (the single writer task per
    process, INV-6), so the serving path **reuses** it. Resolution:

    * if ``app.state.repository`` is present (the lifespan wiring, or a test that
      injected one), use it as-is and do **not** close it — its owner (the
      lifespan) manages its lifecycle;
    * **test fallback only** (a ``TestClient`` that did not enter the lifespan):
      build + ``start()`` a Repository scoped to this request and ``close()`` it
      on exit, so the writer task is created and torn down on the serving loop
      (a cached cross-request writer would be bound to a stale loop).
    """
    injected = getattr(request.app.state, _REPO_ATTR, None)
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


def _map_github_error(exc: Exception) -> ApiError:
    """Map a GitHub failure to the §8.9 error envelope."""
    if isinstance(exc, GitHubAuthError):
        return ApiError(
            status_code=401,
            code="github_unauthorized",
            message="GitHub rejected the credential. Reconnect with a valid token.",
        )
    return ApiError(
        status_code=502,
        code="github_upstream_error",
        message="GitHub could not be reached.",
    )


def _query_flag(request: Request, name: str) -> bool:
    """Read a truthy boolean query flag (``?<name>=true|1|yes``)."""
    raw = request.query_params.get(name)
    return raw is not None and raw.strip().lower() in {"1", "true", "yes", "on"}


async def _ensure_labels_once(
    repository: Repository,
    client: object,
    repo: str,
    *,
    force: bool,
) -> EnsureLabelsResult:
    """Ensure the four ``agent:*`` labels at most once per repo (FIX-2 / AC-4).

    On the first sync (no ``labels_ensured::<repo>`` flag) — or when ``force`` is
    set (the explicit re-ensure path) — call :func:`ensure_agent_labels` (the four
    idempotent GitHub ``POST /labels`` creates) and record the flag on success, so
    routine re-syncs skip the create calls and stop spending GitHub's
    secondary-rate-limit budget on a no-op. AC-4 is preserved: the labels are still
    created on first connect/sync if absent. When already ensured and not forced,
    return an all-``existing`` result without touching GitHub.
    """
    if not force and await repository.labels_ensured(repo):
        return EnsureLabelsResult(created=(), existing=tuple(sorted(AGENT_LABEL_NAMES)))
    result = await ensure_agent_labels(client, repo)
    await repository.mark_labels_ensured(repo)
    return result


@router.post("/projects/{owner}/{name}/sync")
async def sync_project(owner: str, name: str, request: Request) -> dict[str, Any]:
    """Import a repo's issues into the cache + ensure the ``agent:*`` labels (T037).

    The Connect "Open project" action (FR-01-5): a state-changing ``POST`` behind
    the access-control middleware (INV-1). On the **first** sync for a repo it
    **ensures the four ``agent:*`` labels exist** (created on connect if absent,
    idempotently — §8.1, AC-4) and records a ``labels_ensured::<repo>`` flag;
    subsequent incremental polls **skip** the four GitHub ``POST /labels`` create
    calls (they spend secondary-rate-limit budget for no effect once the labels
    exist — FIX-2). A ``?ensure_labels=true`` query forces a re-ensure. It then
    reads the board (paginated GraphQL, Done-bounded, incremental from the
    persisted ``since`` cursor) and upserts the page **through the repository
    layer** in one writer transaction (never raw SQL — AC-3). Returns the import
    count + the new ``since`` cursor.
    """
    repo = f"{owner}/{name}"
    settings = request.app.state.settings
    client = await get_github_client(request.app, settings)
    cache = _board_cache(request)
    force_ensure = _query_flag(request, "ensure_labels")

    try:
        async with _repository(request) as repository:
            labels_result = await _ensure_labels_once(repository, client, repo, force=force_ensure)
            sync_result = await sync_issues(client, repo, writer=repository, cache=cache)
    except (GitHubAuthError, GitHubError) as exc:
        raise _map_github_error(exc) from exc

    return {
        "repo": repo,
        "imported": sync_result.imported,
        "since_cursor": sync_result.since_cursor,
        "from_cache": sync_result.from_cache,
        "labels": {
            "created": list(labels_result.created),
            "existing": list(labels_result.existing),
        },
    }


@router.get("/repos/{owner}/{name}/issues")
async def list_issues(owner: str, name: str, request: Request) -> dict[str, Any]:
    """Return the board list with ``state`` derived per §5.3.1 + authority (FR-02-7).

    Reads the cached issues and the repo's active runs, then derives each issue's
    board ``state`` with the authority rule applied (active-run DB row > label,
    §8.1) — so a stale ``agent:*`` label on an issue that has a live run does not
    win over the run's state. The persisted ``state``/Done signal is honored so a
    closed (or merged-PR) issue renders in **Done** (§5.3.1 row 6). Returns the
    ``data.jsx ISSUES`` list shape.

    Both inputs flow through the :class:`Repository` read seam (NFR-PORT-1), the
    same single DB boundary the writes use, so the SQLite→Postgres swap stays an
    additive change rather than a rewrite.
    """
    repo = f"{owner}/{name}"
    async with _repository(request) as repository:
        cached, active = await read_board_via_repository(repository, repo)
    items = build_board_list(cached, active)
    return {"items": items, "next_cursor": None}
