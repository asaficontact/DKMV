"""Run endpoints — ``POST /runs``, ``GET /runs``, ``GET /runs/{id}`` (§8.4/§8.9).

The launch contract + the run reads (PRD §8.4, §8.9, §8.10, §8.11), all behind the
app-wide :class:`~app.security.AccessControlMiddleware` (INV-1 — loopback ``Host`` +
local token + ``Origin``/CSRF; ``POST /runs`` is a state-changing POST and inherits
the CSRF gate). The launch logic itself lives in :mod:`app.runs.launch` (validation,
``auto → workflow.agent`` resolution, the INV-5 claim-lock, the engine start); the
read projections live in :mod:`app.runs.service`.

* ``POST /runs`` → validate (§8.10) → claim-lock (INV-5) → ``EmbeddedRuntime.start``
  → ``201 { run_id }`` (the **platform UUID** — §8.4); ``409 duplicate_dispatch`` on
  a duplicate claim; ``400 unsupported_for_agent`` for a Codex budget/turns body
  (INV-8).
* ``GET /runs`` → the §8.9 list baseline (the live-view spine; history filters/sort
  are Phase 3).
* ``GET /runs/{id}`` → the §8.9 detail baseline (``stages``/``config``/``sandbox``/
  ``artifacts``/``pr``/``error``); Codex ``cost_usd`` is ``null``/"—".

The repository / write-queue / GitHub client / run-service are resolved from the
slice-2.0 ``app.state`` seam (:mod:`app.api.deps`) — never a per-request build.
Nothing here reaches into ``dkmv/`` except through the in-process
:class:`~app.runtime.RunService` (INV-13).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.deps import get_board_cache, get_repository, get_write_queue
from app.api.errors import ApiError, run_not_found
from app.db.repository import Repository
from app.github.client import GitHubAuthError, GitHubError
from app.github.provider import get_github_client
from app.hitl import ConcurrencySlots, DecisionRegistry, PauseBridgeDeps, build_pause_bridge
from app.runs.launch import LaunchRequest, launch_run
from app.runs.service import build_run_detail, build_run_summaries
from app.runtime import RunService
from app.sse.auth import set_sse_cookie
from app.sse.observer_bridge import StreamRegistry
from app.sse.run_stream import RUN_STREAM_TASKS_ATTR, attach_run_stream

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dkmv.runtime._handle import RunHandle

# No prefix here: the ``/api/v1`` version prefix is owned by the single parent
# router in :mod:`app.api`, which this router attaches to.
router = APIRouter(tags=["runs"])

#: Cap on a ``GET /runs`` page (cursor pagination contract, §8.9). The history
#: page with full filters/sort is Phase 3; Phase 2 ships a bounded list spine.
_MAX_LIMIT = 100


class CreateRunRequest(BaseModel):
    """The ``POST /runs`` body (PRD §8.4).

    Pydantic enforces the structural contract (types + required fields); the
    binding §8.10 rules (branch regex, slug, workflow/agent/model resolution, the
    INV-8 capability rejection) are applied in :mod:`app.runs.launch` so the engine
    resolution + capability branch live in one place.
    """

    issue_num: int = Field(..., description="The GitHub issue number to run.")
    repo: str = Field(..., description="owner/name — must be the connected project's repo.")
    workflow_id: str = Field(..., description="The workflow/component id (validate_component).")
    agent: str = Field("auto", description="claude | codex | auto (auto → workflow.agent).")
    branch: str = Field(..., description="Target branch (^[\\w./-]{1,200}$, no .., no leading -).")
    feature_name: str = Field(..., description="Slugified feature name ([a-z0-9-], ≤30).")
    model: str | None = Field(default=None, description="Override model (validate_agent_model).")
    max_turns: int | None = Field(default=None, description="Hard turn cap (Claude only — INV-8).")
    timeout_minutes: int | None = Field(default=None, description="Run timeout in minutes.")
    max_budget_usd: float | None = Field(
        default=None, description="Hard USD budget (Claude only — INV-8)."
    )
    memory: str | None = Field(default=None, description="Container memory (e.g. '8g').")
    context: list[str] = Field(
        default_factory=list, description="Extra project-internal context paths."
    )
    keep_alive: bool = Field(default=False, description="Keep the container alive after the run.")
    start_task: str | None = Field(
        default=None, description="Resume from a named stage (retry path)."
    )


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


async def _stream_repository(request: Request) -> Repository:
    """Return the long-lived :class:`Repository` the per-run pump/supervisor hold.

    The event pump + completion supervisor (slice 2.3) outlive the ``POST /runs``
    request — they run for the run's whole lifetime — so they must write through
    the **lifespan-owned** ``app.state.repository`` (the single per-process writer,
    INV-6), never a per-request Repository that ``get_repository`` would ``close``
    when the request ends. **Test fallback only** (no lifespan): the per-request
    resolver builds + starts one on the serving loop; the pump shares it for the
    (short-lived) test run. Mirrors ``app.sse.endpoint._stream_repository``.
    """
    repo = getattr(request.app.state, "repository", None)
    if isinstance(repo, Repository):
        return repo
    async with get_repository(request) as fallback:
        return fallback


def _stream_registry(request: Request) -> StreamRegistry:
    """Resolve (composing on first use) the process-wide :class:`StreamRegistry`.

    The app-lifespan composes ONE registry on ``app.state.stream_registry`` so the
    launch path's pump publishes into the same hub the SSE endpoint subscribes to;
    a no-lifespan test gets one lazily here.
    """
    existing = getattr(request.app.state, "stream_registry", None)
    if isinstance(existing, StreamRegistry):
        return existing
    registry = StreamRegistry()
    request.app.state.stream_registry = registry
    return registry


def _stream_tasks(request: Request) -> set[asyncio.Task[Any]]:
    """The process-wide set of live per-run pump/supervisor tasks (``app.state``).

    Tracked so the lifespan can cancel them on shutdown (and a test can await
    them); each task removes itself when it completes (no unbounded growth).
    """
    existing = getattr(request.app.state, RUN_STREAM_TASKS_ATTR, None)
    if isinstance(existing, set):
        return existing
    tasks: set[asyncio.Task[Any]] = set()
    setattr(request.app.state, RUN_STREAM_TASKS_ATTR, tasks)
    return tasks


def _decision_registry(request: Request) -> DecisionRegistry:
    """Resolve the process-wide HITL :class:`DecisionRegistry` (composing if absent).

    The pause bridge built per run registers its awaited future here; the answer
    endpoint / timeout sweep fire it after winning the exactly-once DB guard. The
    lifespan composes ONE on ``app.state.decision_registry`` so the bridge's awaited
    future and the answer route's resolve share one rendezvous; a no-lifespan test
    gets one lazily.
    """
    existing = getattr(request.app.state, "decision_registry", None)
    if isinstance(existing, DecisionRegistry):
        return existing
    registry = DecisionRegistry()
    request.app.state.decision_registry = registry
    return registry


def _concurrency_slots(request: Request) -> ConcurrencySlots:
    """Resolve the process-wide :class:`ConcurrencySlots` accounting (T086).

    The slot-release-on-pause / reacquire-on-resume primitive the pause bridge
    drives. Phase 2 does not enforce a cap (Phase 5 does); the lifespan composes ONE
    on ``app.state.concurrency_slots`` so all runs share the same accounting; a
    no-lifespan test gets one lazily.
    """
    existing = getattr(request.app.state, "concurrency_slots", None)
    if isinstance(existing, ConcurrencySlots):
        return existing
    slots = ConcurrencySlots()
    request.app.state.concurrency_slots = slots
    return slots


def _run_service(request: Request) -> RunService:
    """Resolve the single lifespan-owned :class:`RunService` from ``app.state``.

    The only seam to the in-process DKMV engine (INV-13); composed once in
    ``app.main`` and reused per request (never rebuilt — it owns a configured
    ``EmbeddedRuntime``).
    """
    service = getattr(request.app.state, "run_service", None)
    assert isinstance(service, RunService)
    return service


def _connected_repo(request: Request, body_repo: str) -> str:
    """Resolve the connected project's repo for the §8.10 ``repo`` check.

    Phase 1 connects a single project; the connected repo is the body's ``repo``
    in v1 (there is one project). When a future ``projects`` row pins a canonical
    repo this returns it instead — the §8.10 check then rejects a foreign repo. For
    now it echoes the body so the structural validation path is exercised without a
    false reject of the (single) connected repo.
    """
    return body_repo


@router.post("/runs")
async def create_run(body: CreateRunRequest, request: Request) -> JSONResponse:
    """Launch a run for an issue → ``201 { run_id }`` (the platform UUID) (§8.4, §8.11).

    Validates (§8.10), resolves the agent (``auto → workflow.agent``), **rejects**
    a Codex budget/turns body with ``400 unsupported_for_agent`` (INV-8), claims the
    run row via ``INSERT … ON CONFLICT DO NOTHING`` under ``BEGIN IMMEDIATE``
    (``409 duplicate_dispatch`` on a duplicate — INV-5), starts the engine through
    :class:`RunService` (with the slice-2.5 ``on_pause`` pass-through), moves the
    issue to ``agent:in-progress`` via the write-queue (INV-11), and returns the
    **platform UUID** (the engine id back-fills via the event stream). A
    state-changing POST behind the access-control middleware (INV-1).
    """
    settings = request.app.state.settings
    client = await get_github_client(request.app, settings)
    write_queue = get_write_queue(request)
    cache = get_board_cache(request)
    run_service = _run_service(request)

    # The per-run pump/supervisor + the HITL pause bridge outlive this request, so
    # they hold the lifespan-owned (long-lived) Repository — not the per-request one.
    stream_repository = await _stream_repository(request)
    registry = _stream_registry(request)
    tasks = _stream_tasks(request)
    decisions = _decision_registry(request)
    slots = _concurrency_slots(request)
    # Resolved inside the launch try-block (below) before ``launch_run`` runs, so
    # it is bound before the per-run ``_build_on_pause`` closure could ever be
    # invoked (the bridge is only called by the engine at a pause point, long after
    # launch returns). Initialized here so the closure has a definite binding.
    current_labels: list[str] = []

    def _attach_stream(run_id: str, handle: RunHandle) -> None:
        """Register the run's observer + spawn its pump/supervisor (F8 / §8.3)."""
        attach_run_stream(
            run_id=run_id,
            handle=handle,
            registry=registry,
            repository=stream_repository,
            tasks=tasks,
        )

    def _build_on_pause(run_id: str) -> Any:
        """Build the per-run HITL ``on_pause`` bridge once the UUID exists (slice 2.5).

        Bound to the claimed platform UUID + the lifespan-owned singletons
        (long-lived Repository, write-queue, GitHub client, stream registry,
        decision rendezvous, slot accounting). On pause the bridge writes
        ``pause_decisions``, sets ``agent:paused`` (write-queue, INV-11), releases
        the slot (T086), emits ``pause_requested`` over SSE, and awaits the keyed
        event resolved exactly-once by ``POST /runs/{id}/answer`` (INV-9 / §8.5).
        """
        deps = PauseBridgeDeps(
            run_id=run_id,
            repo=body.repo,
            issue_num=body.issue_num,
            repository=stream_repository,
            github_client=client,
            write_queue=write_queue,
            stream_registry=registry,
            decisions=decisions,
            slots=slots,
            cache=cache,
            current_labels=tuple(current_labels),
        )
        return build_pause_bridge(deps)

    req = LaunchRequest(
        issue_num=body.issue_num,
        repo=body.repo,
        workflow_id=body.workflow_id,
        agent=body.agent,
        branch=body.branch,
        feature_name=body.feature_name,
        model=body.model,
        max_turns=body.max_turns,
        timeout_minutes=body.timeout_minutes,
        max_budget_usd=body.max_budget_usd,
        memory=body.memory,
        context=list(body.context),
        keep_alive=body.keep_alive,
        start_task=body.start_task,
    )

    try:
        async with get_repository(request) as repository:
            current_labels = await _issue_labels(repository, body.repo, body.issue_num)
            result = await launch_run(
                req,
                repository=repository,
                run_service=run_service,
                github_client=client,
                write_queue=write_queue,
                cache=cache,
                connected_repo=_connected_repo(request, body.repo),
                project_root=None,
                default_memory=_default_memory(settings),
                current_labels=current_labels,
                build_on_pause=_build_on_pause,
                attach_stream=_attach_stream,
            )
    except (GitHubAuthError, GitHubError) as exc:
        raise _map_github_error(exc) from exc

    # INV-2: install the HttpOnly SameSite=Strict SSE cookie on this authenticated
    # POST /runs response so the browser holds it BEFORE opening the EventSource for
    # the new run — the SSE handler then 200s with the cookie (and still 401s
    # without it). The cookie carries the SAME loopback control-plane token; it is
    # never put in the SSE URL (a URL token would leak into the append-only events
    # table). ``secure`` follows the deployment's TLS posture (off for loopback dev).
    response = JSONResponse(status_code=201, content={"run_id": result.run_id})
    set_sse_cookie(
        response,
        settings.DKMV_PLATFORM_TOKEN.get_secret_value(),
        secure=_cookie_secure(settings),
    )
    return response


def _cookie_secure(settings: Any) -> bool:
    """Whether the SSE cookie gets the ``Secure`` attribute (TLS deployments).

    Defaults off for loopback ``http://127.0.0.1`` dev (a ``Secure`` cookie would
    not be sent over plain http, breaking the local stream); a TLS-terminated
    deployment opts in via ``DKMV_COOKIE_SECURE``.
    """
    return bool(getattr(settings, "DKMV_COOKIE_SECURE", False))


def _default_memory(settings: Any) -> str:
    """The default container memory limit (FR-04-5 default '8g')."""
    return "8g"


async def _issue_labels(repository: Any, repo: str, num: int) -> list[str]:
    """Read the issue's current labels from the cache (for the replace-all PUT).

    ``set_agent_state`` needs the full desired label set so non-agent labels are
    preserved on the replace-all ``PUT`` (INV-11). An uncached issue (not yet
    synced) is treated as having no labels.
    """
    import json

    row = await repository.read_issue(repo, num)
    if not row:
        return []
    raw = row.get("labels_json")
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


@router.get("/runs")
async def list_runs(request: Request) -> dict[str, Any]:
    """Return the §8.9 run-list baseline (the live-view spine).

    Cursor-paginated (``?limit&cursor``); ``?repo=`` scopes to one project. The
    sortable/filterable history with the FR-06-4 columns is Phase 3 — Phase 2 ships
    the baseline list spine. Codex ``cost_usd`` is ``null``/"—".
    """
    limit = _parse_limit(request)
    offset = _parse_offset(request)
    repo = request.query_params.get("repo")

    async with get_repository(request) as repository:
        rows = await repository.list_runs(repo=repo, limit=limit + 1, offset=offset)
        has_more = len(rows) > limit
        page = rows[:limit]
        # One bulk spend query for the whole page (not one run_spend per row —
        # the N+1 the per-row path otherwise serializes through the read pool).
        items = await build_run_summaries(repository, page)

    next_cursor = str(offset + limit) if has_more else None
    return {"items": items, "next_cursor": next_cursor}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> dict[str, Any]:
    """Return the §8.9 ``GET /runs/{id}`` detail baseline for the live view.

    Carries ``stages``, the FR-04-5 ``config`` snapshot, ``sandbox``, ``artifacts``,
    and the linked ``pr``/``error``; Codex ``cost_usd`` is ``null``/"—" (INV-8). A
    ``404 run_not_found`` for an unknown platform UUID. All run endpoints address
    the platform UUID (§8.4).
    """
    settings = request.app.state.settings
    async with get_repository(request) as repository:
        row = await repository.get_run(run_id)
        if row is None:
            raise run_not_found(run_id)
        return await build_run_detail(
            repository,
            row,
            sandbox_image=settings.DKMV_IMAGE,
            default_memory=_default_memory(settings),
        )


def _parse_limit(request: Request) -> int:
    """Parse ``?limit`` (1..100; default 100) for the run list (§8.9)."""
    raw = request.query_params.get("limit")
    if raw is None:
        return _MAX_LIMIT
    try:
        value = int(raw)
    except ValueError:
        return _MAX_LIMIT
    return max(1, min(value, _MAX_LIMIT))


def _parse_offset(request: Request) -> int:
    """Parse the opaque ``?cursor`` (an integer offset) for the run list (§8.9)."""
    raw = request.query_params.get("cursor")
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0
