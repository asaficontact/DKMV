"""Run control endpoints — ``POST /runs/{id}/stop`` + one-shot container exec (§8.5).

The two live-run control actions the run view drives (slice 2.4, FR-04-1):

* ``POST /runs/{id}/stop`` — stop a running **or paused** run. **A paused run is
  stopped with ``RunHandle.stop(force=True)``** (§8.5, R-7): the engine only checks
  ``cancel_event`` *between* tasks, so a cooperative stop never fires while the run
  is parked at ``await on_pause`` — ``force=True`` cancels the run task, and the
  engine's ``finally`` stops the container. A *running* run uses the cooperative
  ``stop()`` (it will observe the cancel at the next task boundary). The platform
  marks the run ``stopping`` and lets the completion supervisor record the terminal
  status off the handle.
* ``POST /runs/{id}/exec`` — **one-shot** "run a command in the container", via the
  engine's ``execute_in_container`` (a single ``docker exec``). This is deliberately
  a single bounded command, **not** a streaming shell session — no stdin attach,
  no persistent session: one command in, captured stdout out. The §8.5 "attach
  terminal" affordance in the prototype maps to this bounded exec.

The engine is consumed **in-process** through the lifespan-owned
:class:`~app.runtime.RunService` (INV-13) — never the ``dkmv`` CLI. Both endpoints
are state-changing POSTs behind the app-wide :class:`~app.security` access-control
middleware (INV-1 — loopback ``Host`` + local token + ``Origin``/CSRF). Container
control addresses the **engine** ``run_id`` (the engine's container registry is
keyed by it); the platform resolves it from the run row's ``engine_run_id``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.deps import get_repository
from app.api.errors import ApiError, run_not_found
from app.runtime import RunService

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dkmv.runtime._handle import RunHandle

# No prefix here: the ``/api/v1`` version prefix is owned by the single parent
# router in :mod:`app.api`, which this router attaches to.
router = APIRouter(tags=["runs"])

#: Run statuses that are still controllable (the handle is live, the container may
#: be up). A terminal run (``completed``/``failed``/``cancelled``/…) rejects stop.
_STOPPABLE_STATUSES: frozenset[str] = frozenset({"running", "pending", "paused", "stopping"})


class ExecRequest(BaseModel):
    """The ``POST /runs/{id}/exec`` body — ONE command to run once in the container.

    This is a single command string for a one-shot ``docker exec`` (not a
    persistent shell session). The engine wraps it as ``bash -c <command>`` and
    returns its captured stdout.
    """

    command: str = Field(..., min_length=1, description="One command to run once in the container.")


class StopResponse(BaseModel):
    """The ``POST /runs/{id}/stop`` 202 body."""

    run_id: str
    status: str
    forced: bool


class ExecResponse(BaseModel):
    """The ``POST /runs/{id}/exec`` 200 body — the one-shot command's stdout."""

    run_id: str
    output: str


def _run_service(request: Request) -> RunService:
    """Resolve the single lifespan-owned :class:`RunService` from ``app.state``.

    The only seam to the in-process DKMV engine (INV-13); composed once in
    ``app.main`` and reused per request. A no-lifespan unit test that injected one
    on ``app.state`` is served the same way.
    """
    service = getattr(request.app.state, "run_service", None)
    assert isinstance(service, RunService)
    return service


def _resolve_handle(request: Request, engine_run_id: str | None) -> RunHandle | None:
    """Resolve the engine ``RunHandle`` for a run, or ``None`` if not addressable.

    The engine registers each handle in its in-process registry keyed by the
    **engine** ``run_id`` (which back-fills onto ``runs.engine_run_id`` off the
    event stream). A run that hasn't surfaced its engine id yet — or whose handle
    is gone (the engine reclaimed a finished run) — resolves to ``None``. We never
    re-attach to a container started by a dead process (INV-10): this only reaches
    handles this process started and still holds.
    """
    if not engine_run_id:
        return None
    service = _run_service(request)
    return service.runtime.get_handle(engine_run_id)


@router.post("/runs/{run_id}/stop", status_code=202)
async def stop_run(run_id: str, request: Request) -> StopResponse:
    """Stop a running or paused run → ``202`` (§8.5, FR-04-1).

    A **paused** run is stopped with ``RunHandle.stop(force=True)`` (R-7: the
    engine checks ``cancel_event`` only between tasks, so a cooperative stop won't
    fire while it is parked at ``await on_pause``; ``force=True`` cancels the task
    and the engine's ``finally`` stops the container). A **running** run uses the
    cooperative ``stop()``. The run is marked ``stopping``; the completion
    supervisor records the terminal status off the handle. ``404`` for an unknown
    run; ``409`` for a run that is already terminal.
    """
    async with get_repository(request) as repository:
        row = await repository.get_run(run_id)
        if row is None:
            raise run_not_found(run_id)
        status = str(row.get("status") or "")
        if status not in _STOPPABLE_STATUSES:
            raise ApiError(
                status_code=409,
                code="run_not_stoppable",
                message=f"Run is {status or 'terminal'} and cannot be stopped.",
            )

        # A paused run requires force (the cooperative cancel never fires while
        # parked at await on_pause — R-7). A running run can stop cooperatively.
        force = status == "paused"
        handle = _resolve_handle(request, row.get("engine_run_id"))
        if handle is not None:
            await handle.stop(force=force)

        # Reflect the in-flight stop in the read model; the supervisor finalizes
        # the terminal status when the handle settles.
        await repository.update_run_fields(run_id, status="stopping")

    return StopResponse(run_id=run_id, status="stopping", forced=force)


@router.post("/runs/{run_id}/exec")
async def exec_in_run(run_id: str, body: ExecRequest, request: Request) -> ExecResponse:
    """Run ONE command in the run's container (one-shot exec) — §8.5.

    Delegates to the engine's ``execute_in_container`` (a single ``docker exec
    … bash -c <command>``) through the in-process :class:`RunService` (INV-13).
    There is no stdin attach and no streaming shell session — one command in, its
    captured stdout out. ``404`` for an unknown run; ``409`` when
    the container is not running (a finished/keep-alive-off run); ``400`` when the
    command fails.
    """
    async with get_repository(request) as repository:
        row = await repository.get_run(run_id)
        if row is None:
            raise run_not_found(run_id)
        engine_run_id = row.get("engine_run_id")

    if not engine_run_id:
        raise ApiError(
            status_code=409,
            code="container_unavailable",
            message="The run has no live container to exec into.",
        )

    service = _run_service(request)
    try:
        output = service.runtime.execute_in_container(str(engine_run_id), body.command)
    except RuntimeError as exc:
        # The engine raises RuntimeError both when the container is not running and
        # when the command itself fails; surface as a 409 (no container) is the
        # common case for the live view, but a failed command is a 400.
        message = str(exc)
        if "not running" in message:
            raise ApiError(
                status_code=409,
                code="container_unavailable",
                message="The container is not running.",
            ) from exc
        raise ApiError(
            status_code=400,
            code="exec_failed",
            message="The command failed in the container.",
            details={"reason": _safe_reason(message)},
        ) from exc

    return ExecResponse(run_id=run_id, output=output)


def _safe_reason(message: str) -> Any:
    """Trim an engine error message for the §8.9 ``details`` (never a secret value).

    The engine's exec error carries the command's stderr; we cap its length so a
    noisy failure doesn't bloat the envelope. It is operator-facing diagnostic
    text, not a credential (the run token never appears in a shell command's
    stderr).
    """
    return message[:500]
