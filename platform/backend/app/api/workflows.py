"""``GET /workflows`` + ``GET /workflows/{id}`` — read-only Workflows viewer (4.1).

The two **read-only** endpoints behind Screen 07 (F12 / PRD §5.8 FR-07-1v, §6.2).
They surface every built-in + registered component's **pipeline summary** (ordered
stages, per-stage budget, pause points, est. total) and — on the detail route — the
``component.yaml`` + task YAML text for the "compiles to YAML" peek.

All component data comes from the locked DKMV engine, consumed **in-process** via
:class:`~app.runtime.RunService` (INV-13, ADR-P006): the backend never shells the
``dkmv`` CLI and never edits ``dkmv/``. The viewer is strictly **read-only**
(ADR-P010, N7): only the two GET routes below exist — there is no write/update route
and no edit/save path. The service mutates nothing on disk.

Both routes inherit the Phase-0 app access-control middleware (loopback bind + local
token + Host/Origin + CSRF; INV-1) — neither opts out, so neither is unauthenticated.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

from app.api.errors import ApiError
from app.workflows import WorkflowDetail, WorkflowService, WorkflowSummary
from app.workflows.service import WorkflowNotFoundError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.runtime import RunService

# No prefix here: the ``/api/v1`` version prefix is owned by the single parent
# router in :mod:`app.api`, which this router attaches to.
router = APIRouter(tags=["workflows"])


def workflow_not_found(workflow_id: str) -> ApiError:
    """404 — no built-in/registered component matches ``workflow_id`` (§8.9).

    Carries the **semantic top-level code** ``workflow_not_found`` plus a
    ``details.resource: workflow`` discriminator (consistent with the §8.9 domain
    404s in :mod:`app.api.errors`).
    """
    return ApiError(
        404,
        "workflow_not_found",
        f"Workflow {workflow_id} not found",
        details={"resource": "workflow"},
    )


def _connected_project_root(request: Request) -> Path | None:
    """Resolve the connected project's on-disk root, or ``None`` (read-only).

    The engine's ``list_components(project_root=…)`` only surfaces **registered**
    on-disk custom components when it is handed the project root that owns the
    ``.dkmv/components.json`` registry; built-ins resolve without one. Without this
    wiring only the five built-ins ever appear and a ``register``'d custom workflow
    (FR-07-1v / AC-8) is invisible in the viewer.

    The connected project is the same single project the orchestrator tick polls
    at lifespan startup (``app.state.orchestrator_repo`` — v1 connects one project,
    §8.8). Its local root is published on ``app.state.project_root`` by the same
    lifespan seam; we read it here (a plain ``app.state`` read — no DB write, no
    engine call) and fall back to ``None`` when no project is connected yet (a
    fresh install before ``POST /connect``), in which case only built-ins list.

    This is strictly a **read**: resolving the root performs no mutation, no
    registry write, and no file write — the viewer stays read-only (ADR-P010,
    AC-2). Only a ``Path`` (or ``None``) is returned to the introspection adapter.
    """
    root = getattr(request.app.state, "project_root", None)
    if root is None:
        return None
    return root if isinstance(root, Path) else Path(root)


def _service(request: Request) -> WorkflowService:
    """Build the read-only :class:`WorkflowService` over the app's ``RunService``.

    Reuses the single lifespan-owned ``app.state.run_service`` (the configured
    in-process ``EmbeddedRuntime``); the service itself is a stateless adapter, so
    constructing one per request is cheap and holds no engine resources. The
    connected project's root is passed through (when known) so registered on-disk
    custom components resolve — built-ins do not need one (AC-5 / AC-8).
    """
    run_service: RunService = request.app.state.run_service
    return WorkflowService(run_service, project_root=_connected_project_root(request))


@router.get("/workflows", response_model=list[WorkflowSummary])
def list_workflows(request: Request) -> list[WorkflowSummary]:
    """List the pipeline summary for every built-in + registered component (AC-1).

    Backed by the engine's ``list_components()`` so on-disk + registered custom
    components appear. Each entry carries the ordered stages, per-stage budget,
    pause points, and est. total (AC-4). Read-only.
    """
    return _service(request).list_workflows()


@router.get("/workflows/{workflow_id}", response_model=WorkflowDetail)
def get_workflow(request: Request, workflow_id: str) -> WorkflowDetail:
    """Return one component's summary + ``component.yaml`` + task YAML text (AC-1).

    Unknown id → ``404 { "error": { "code": "workflow_not_found" } }`` (§8.9).
    Read-only — no edit/save path exists (ADR-P010).
    """
    try:
        return _service(request).get_workflow(workflow_id)
    except WorkflowNotFoundError as exc:
        raise workflow_not_found(exc.workflow_id) from exc
