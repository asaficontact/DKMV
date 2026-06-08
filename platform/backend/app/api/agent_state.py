"""``POST /issues/{num}/agent-state`` — the Backlog↔Queued drag (PRD §8.1, FR-02-3).

The board's only user-driven label transition: dragging a card between **Backlog**
and **Queued** posts ``{target: queued|none}`` here, which calls
:func:`app.github.state_machine.set_agent_state` — the replace-all ``PUT .../labels``
primitive (INV-11), **routed through the serialized write-queue** (§8.1). Cards are
draggable *only* between Backlog and Queued; the other columns are run-driven and
not user-draggable (FR-02-3), so this endpoint accepts only ``queued`` (set
``agent:queued`` → Queued) and ``none`` (clear it → Backlog).

Like every Phase-1 route, this is a state-changing ``POST`` behind the app-wide
:class:`~app.security.AccessControlMiddleware` (INV-1 — loopback ``Host`` + local
token + ``Origin``/CSRF); it declares **no** auth opt-out.

The write path:

1. Read the issue's **current labels** from the ``issues`` cache through the
   repository seam (so non-agent labels are preserved on the replace-all ``PUT``).
2. Call ``set_agent_state`` through the single ``WriteQueue`` (held on
   ``app.state`` so every mutating GitHub call in the process shares one paced,
   serialized queue — §8.1).
3. ``set_agent_state`` invalidates the GraphQL hash-cache so the next board read
   reflects the change.

The ``GitHubClient`` (PAT backend in v1; the App backend slots behind the same
interface, ADR-P004) and the hash-cache are resolved from ``app.state``, shared
with slice 1.2's read path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.errors import ApiError, validation_error
from app.db.repository import Repository
from app.github.client import GitHubAuthError, GitHubError
from app.github.graphql import BoardPage
from app.github.hash_cache import HashCache
from app.github.provider import get_github_client
from app.github.state_machine import set_agent_state
from app.github.write_queue import WriteQueue

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.config import Settings

# No prefix here: the ``/api/v1`` version prefix is owned by the single parent
# router in :mod:`app.api`, which this router attaches to.
router = APIRouter(tags=["github"])

#: ``app.state`` attribute names so concurrent slices agree on the seam (the cache
#: name matches :mod:`app.api.issues` so the read + write share one hash-cache).
_CACHE_ATTR = "github_hash_cache"
_REPO_ATTR = "repository"
_WRITE_QUEUE_ATTR = "github_write_queue"

#: The only targets the Backlog↔Queued drag may post (FR-02-3): ``queued`` sets
#: ``agent:queued`` (→ Queued); ``none`` clears it (→ Backlog). The other columns
#: are run-driven and not user-draggable, so their states are rejected here.
_ALLOWED_TARGETS: frozenset[str] = frozenset({"queued", "none"})


class AgentStateRequest(BaseModel):
    """Body for ``POST /issues/{num}/agent-state``: the drag target (§8.1).

    ``target`` is ``"queued"`` (drag into Queued) or ``"none"`` (drag back to
    Backlog). Any other value is rejected at the validation layer — the drag is
    only ever between those two columns (FR-02-3).
    """

    target: str = Field(..., description="queued | none — the Backlog↔Queued drag target.")


class AgentStateResponse(BaseModel):
    """Response after a successful transition — the post-write occupancy."""

    repo: str
    num: int
    #: The single surviving ``agent:*`` label (``"agent:queued"`` or ``None`` for
    #: Backlog) — the single-occupancy result the board renders.
    agent_label: str | None
    #: The issue's full label set after the replace-all ``PUT`` (non-agent labels
    #: preserved), echoed from GitHub.
    labels: list[str]


def _board_cache(request: Request) -> HashCache[BoardPage]:
    """Return (building+caching once) the shared GraphQL board hash-cache (§8.1).

    The same cache slice 1.2 reads through, so invalidating it here makes the next
    board read reflect the label write (no stale page).
    """
    existing = getattr(request.app.state, _CACHE_ATTR, None)
    if existing is not None:
        assert isinstance(existing, HashCache)
        return existing
    cache: HashCache[BoardPage] = HashCache()
    setattr(request.app.state, _CACHE_ATTR, cache)
    return cache


def _write_queue(request: Request) -> WriteQueue:
    """Return (building+caching once) the single process-wide GitHub write-queue.

    All mutating GitHub calls route through this one serialized, token-bucket-paced
    queue (§8.1, INV-11), so it is a singleton on ``app.state``. Tests may inject
    their own via ``app.state.github_write_queue`` before the first request.
    """
    existing = getattr(request.app.state, _WRITE_QUEUE_ATTR, None)
    if existing is not None:
        assert isinstance(existing, WriteQueue)
        return existing
    queue = WriteQueue()
    setattr(request.app.state, _WRITE_QUEUE_ATTR, queue)
    return queue


@asynccontextmanager
async def _repository(request: Request) -> AsyncIterator[Repository]:
    """Yield the platform :class:`Repository` for this request (INV-6 writer).

    Mirrors :mod:`app.api.issues`: reuse an injected ``app.state.repository``
    (Phase-2 lifespan / a test) without closing it, else build + ``start()`` a
    request-scoped Repository from ``settings.DATABASE_URL`` on the serving loop and
    ``close()`` it on exit (keeping the single-writer contract correct here until
    Phase 2's lifespan-scoped writer lands).
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
    """Map a GitHub failure to the §8.9 error envelope (matches issues.py)."""
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


async def _read_issue_row(repository: Repository, repo: str, num: int) -> dict[str, Any] | None:
    """Return the cached ``issues`` row for ``(repo, num)``, or ``None`` if absent.

    A targeted single-issue point read (``Repository.read_issue``, served by the
    ``issues`` PK/index on ``(repo, num)``) — the drag hot path reads exactly one
    row, not the whole board (no full-repo ``read_issues`` scan + Python filter).
    """
    return await repository.read_issue(repo, num)


def _current_labels(row: dict[str, Any] | None) -> list[str]:
    """Decode the issue's current labels (preserve non-agent labels on the PUT).

    The replace-all ``PUT`` needs the full desired label set, so we start from the
    cached labels (imported by slice 1.2's sync) and let
    :func:`app.github.state_machine.compute_desired_labels` strip/replace only the
    ``agent:*`` plane — preserving every GitHub label the card renders. An uncached
    issue (not yet synced) is treated as having no labels.
    """
    if row is None:
        return []
    return _decode_labels(row.get("labels_json"))


def _decode_labels(labels_json: Any) -> list[str]:
    """Decode the cache's ``labels_json`` column to a list of label names."""
    import json

    if not labels_json:
        return []
    try:
        value = json.loads(labels_json)
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [str(v) for v in value]


@router.post("/issues/{owner}/{name}/{num}/agent-state", response_model=AgentStateResponse)
async def post_agent_state(
    owner: str, name: str, num: int, body: AgentStateRequest, request: Request
) -> AgentStateResponse:
    """Drive the Backlog↔Queued drag through ``set_agent_state`` (FR-02-3, AC-9).

    ``target: queued`` sets ``agent:queued`` (→ Queued); ``target: none`` clears it
    (→ Backlog). The transition goes through the replace-all ``PUT .../labels``
    primitive (INV-11) on the single serialized write-queue (§8.1), preserving the
    issue's non-agent labels and the single-occupancy invariant; the GraphQL
    hash-cache is invalidated so the next board read reflects the change. A
    state-changing ``POST`` behind the access-control middleware (INV-1).
    """
    target = body.target.strip().lower()
    if target not in _ALLOWED_TARGETS:
        raise validation_error(
            "agent-state target must be 'queued' or 'none' (the Backlog↔Queued drag)",
            details={"allowed": sorted(_ALLOWED_TARGETS)},
        )

    repo = f"{owner}/{name}"
    settings = request.app.state.settings
    client = await get_github_client(request.app, settings)
    cache = _board_cache(request)
    queue = _write_queue(request)
    state_target: str | None = None if target == "none" else target

    try:
        async with _repository(request) as repository:
            row = await _read_issue_row(repository, repo, num)
            current = _current_labels(row)
            result = await set_agent_state(
                client,
                repo,
                num,
                state_target,
                current_labels=current,
                write_queue=queue,
                cache=cache,
            )
            # Persist the new label set + derived state into the cache so the next
            # board read is consistent before the next full sync (the issues row's
            # ``state`` column is re-derived at read time, but the labels must be
            # current). Reuse the repository upsert seam (never raw SQL), carrying
            # the existing row's title/workflow/agent/pr so the upsert does not
            # blank them.
            await _persist_labels(repository, repo, num, list(result.labels), row)
    except (GitHubAuthError, GitHubError) as exc:
        raise _map_github_error(exc) from exc

    return AgentStateResponse(
        repo=repo,
        num=num,
        agent_label=result.agent_label,
        labels=list(result.labels),
    )


async def _persist_labels(
    repository: Repository,
    repo: str,
    num: int,
    labels: list[str],
    row: dict[str, Any] | None,
) -> None:
    """Write the post-transition labels back into the issues cache (best-effort).

    Keeps the cache consistent with the just-written GitHub state until the next
    full sync. Reuses the repository upsert seam (never raw SQL). The existing
    row's ``title``/``workflow_id``/``agent``/``pr_num`` are carried through so the
    replace-all upsert does not blank them; the ``state`` is re-derived from the new
    labels (closed/Done is preserved when the cached row was already Done). If the
    issue is not yet cached (no prior sync) this still upserts the row with its
    labels so a drag on a freshly-imported board is not lost.
    """
    from app.db.repository import IssueRow
    from app.github.sync import derive_state

    pr_num = row.get("pr_num") if row else None
    cached_done = bool(row) and str((row or {}).get("state") or "") == "done"
    state = derive_state(
        labels=labels,
        is_closed=cached_done,
        merged_pr_num=(int(pr_num) if pr_num is not None else None),
    )
    await repository.upsert_issues(
        [
            IssueRow(
                repo=repo,
                num=num,
                title=str((row or {}).get("title", "")),
                state=state,
                labels=labels,
                workflow_id=(row or {}).get("workflow_id"),
                agent=(row or {}).get("agent"),
                pr_num=(int(pr_num) if pr_num is not None else None),
            )
        ]
    )
