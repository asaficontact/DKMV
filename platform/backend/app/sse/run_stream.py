"""Wire a launched run into the live stream — the seam that makes runs stream.

Slice 2.3 built the observer→queue→pump→SSE machinery; this module is the
**production caller** that connects it to an actually-launched run, so the
"watch a run live" path is functional (not dead code). For each launched run it:

1. **Gets-or-creates** the run's :class:`~app.sse.observer_bridge.RunStreamHub`
   on the process-wide :class:`~app.sse.observer_bridge.StreamRegistry`
   (``app.state.stream_registry``), keyed by the **platform UUID**.
2. **Registers the platform observer with the engine** — ``hub.observer()`` (a
   :class:`~app.sse.observer_bridge.PlatformEventObserver`, which *is* the
   engine's sync ``EventObserver``) is attached to the engine ``RunHandle`` via
   its public ``add_observer`` so every ``RuntimeEvent`` the engine emits is
   handed off to the hub's inbound queue with ``call_soon_threadsafe`` (INV-12).
   The engine drives the run on a freshly-``create_task``-d coroutine, so events
   do not fire until the loop yields — attaching here, synchronously after
   ``start`` returns, never races the first event (INV-13: consume only).
3. **Spawns ONE per-run :class:`~app.sse.pump.EventPump` task** (tracked on
   ``app.state``) that drains the hub queue → persists to ``events`` (through the
   slice-2.0 single-writer :class:`~app.db.repository.Repository`) → projects
   ``run_stages`` → fans out to subscribers.
4. **Spawns a supervisor task** that ``await``\\s the engine handle to
   completion, then marks the hub closed, ``drain_pump``\\s the trailing batch so
   replay is complete, back-fills ``runs.engine_run_id`` from the event stream,
   records the terminal ``runs.status`` + completion snapshot, and
   ``registry.discard``\\s the hub so a finished run's fan-out point does not leak.

This is **not** a live-run re-attach (INV-10): the supervisor owns the handle from
the moment the platform started it, in this same process; it never tries to adopt
a container started by a dead process. The only engine touch is the public
``RunHandle`` surface (``add_observer`` / ``wait`` / ``run_id`` / ``result``) —
nothing here edits ``dkmv/`` (INV-13).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from app.db.repository import Repository, RunTotals
from app.sse.observer_bridge import RunStreamHub, StreamRegistry
from app.sse.pump import EventPump, drain_pump

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dkmv.runtime._handle import RunHandle

_log = logging.getLogger(__name__)

#: ``app.state`` attribute holding the set of live per-run supervisor/pump tasks.
#: Tracked so the lifespan can cancel them on shutdown and so a test can await
#: them; a task removes itself from the set when it finishes (no unbounded growth).
RUN_STREAM_TASKS_ATTR = "run_stream_tasks"


def _terminal_status(handle: RunHandle) -> str:
    """Map the engine ``RunHandle`` terminal state to a platform ``runs.status``.

    The engine ``RunStatus`` (``completed``/``failed``/``cancelled``/``timed_out``…)
    is surfaced verbatim where it is a clean terminal; a handle with no result
    (an exception escaped ``wait``) is recorded ``failed`` so the run never hangs
    in ``running`` in the DB.
    """
    status = getattr(handle, "status", None)
    if isinstance(status, str) and status:
        return status
    return "failed"


def _run_totals_from_result(result: Any) -> RunTotals:
    """Best-effort completion snapshot from the engine ``ComponentResult``.

    The authoritative spend/turn projection is the segment-sum over ``events``
    (slice 2.4 / the repository projection); this snapshot is the §6.5 audit row
    that lets ``events`` be retention-pruned later. Reads the engine result's
    ``total_cost_usd`` / ``duration_seconds`` when present (the
    :class:`~dkmv.tasks.models.ComponentResult` field names), leaving them
    ``None`` otherwise. A Codex result reports ``$0`` — its cost stays excluded
    from the spend projection by the run's ``agent`` regardless of this snapshot.
    """
    cost = getattr(result, "total_cost_usd", None)
    duration = getattr(result, "duration_seconds", None)
    return RunTotals(
        cost_usd=float(cost) if isinstance(cost, int | float) else None,
        duration_s=float(duration) if isinstance(duration, int | float) else None,
    )


async def _backfill_engine_run_id(repository: Repository, run_id: str, hub: RunStreamHub) -> None:
    """Back-fill ``runs.engine_run_id`` from the streamed engine id, once known.

    The engine ``YYMMDD-HHMM-…`` id is **not** available synchronously at
    ``start`` (§8.4) — it arrives via the event stream (each ``RuntimeEvent``
    carries the engine ``run_id``). The pump persists those events under the
    **platform** UUID (``events.run_id`` = the platform id), so it captures the
    engine id off the stream onto :attr:`RunStreamHub.engine_run_id`; we read it
    here and write it to the run row. Idempotent: a no-op when the engine never
    surfaced an id (a run that died before its first stamped frame).
    """
    engine_id = hub.engine_run_id
    if not engine_id:
        return
    with contextlib.suppress(Exception):
        await repository.update_run_fields(run_id, engine_run_id=engine_id)


async def _supervise(
    *,
    run_id: str,
    handle: RunHandle,
    hub: RunStreamHub,
    pump_task: asyncio.Task[None],
    registry: StreamRegistry,
    repository: Repository,
) -> None:
    """Own a launched run end-to-end: await completion → close → drain → record.

    The single supervisor task per run. It ``await``\\s the engine handle (the
    run's background coroutine), then — in a ``finally`` so a crashing run still
    closes the stream — marks the hub closed (so SSE subscriber generators can
    terminate after draining), ``drain_pump``\\s the pump so any trailing
    ``task_completed`` (meter-critical, INV-7) is persisted + replayable,
    back-fills the engine id (§8.4), writes the terminal ``runs.status`` +
    completion snapshot, and ``discard``\\s the hub so a finished run's fan-out
    point is reclaimed. No re-attach (INV-10): we owned this handle from launch.
    """
    try:
        with contextlib.suppress(Exception):
            # The engine runs the work on its own task; await it to completion.
            # A run error/cancel is recorded as the terminal status below — it
            # must never escape and wedge the supervisor.
            await handle.wait()
    finally:
        # Close the live stream first so subscribers drain, then flush the pump.
        hub.mark_closed()
        await drain_pump(pump_task)
        with contextlib.suppress(Exception):
            await _backfill_engine_run_id(repository, run_id, hub)
        with contextlib.suppress(Exception):
            await repository.update_run_fields(run_id, status=_terminal_status(handle))
        with contextlib.suppress(Exception):
            await repository.snapshot_run_totals(
                run_id, _run_totals_from_result(getattr(handle, "result", None))
            )
        registry.discard(run_id)


def attach_run_stream(
    *,
    run_id: str,
    handle: RunHandle,
    registry: StreamRegistry,
    repository: Repository,
    tasks: set[asyncio.Task[Any]] | None = None,
) -> RunStreamHub:
    """Wire a launched run into the live stream and return its hub.

    Called by the launch path **synchronously after** ``EmbeddedRuntime.start``
    returns its ``RunHandle`` (before the engine's run coroutine has had a chance
    to emit — it was just ``create_task``-d). Steps:

    * ``get_or_create`` the run's :class:`RunStreamHub` on ``registry`` (keyed by
      the platform UUID);
    * register ``hub.observer()`` (the engine ``EventObserver``) on the handle via
      ``add_observer`` so every ``RuntimeEvent`` bridges into the hub queue with
      ``call_soon_threadsafe`` (INV-12);
    * spawn ONE :class:`EventPump` task (drain → persist → project → fan out) and a
      supervisor task that closes/drains/records/discards at completion.

    The two tasks are tracked in ``tasks`` (defaulting to a private set) so the
    lifespan can cancel them on shutdown; each removes itself when done. Returns
    the hub so a test can subscribe to it.
    """
    track = tasks if tasks is not None else set()
    hub = registry.get_or_create(run_id)

    # Attach the platform observer to the engine handle (INV-12 hand-off lives in
    # the observer; this is the only place it is registered WITH the engine).
    handle.add_observer(hub.observer())

    pump = EventPump(repository=repository, hub=hub)
    pump_task: asyncio.Task[None] = asyncio.ensure_future(pump.run())

    supervisor: asyncio.Task[None] = asyncio.ensure_future(
        _supervise(
            run_id=run_id,
            handle=handle,
            hub=hub,
            pump_task=pump_task,
            registry=registry,
            repository=repository,
        )
    )

    for task in (pump_task, supervisor):
        track.add(task)
        task.add_done_callback(track.discard)

    return hub
