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
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.db.repository import Repository, RunTotals
from app.github.state_machine import set_agent_state
from app.sse.observer_bridge import RunStreamHub, StreamRegistry
from app.sse.pump import EventPump, drain_pump

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dkmv.runtime._handle import RunHandle

    from app.github.client import GitHubClient
    from app.github.graphql import BoardPage
    from app.github.hash_cache import HashCache
    from app.github.write_queue import WriteQueue

_log = logging.getLogger(__name__)

#: ``runs.status`` values that count as a **successful** completion for the G5
#: board lifecycle: the engine-clean terminal where the agent shipped its work →
#: the issue moves to ``agent:review`` and the run's PR is linked. Any other
#: terminal (``failed`` / ``cancelled`` / ``timed_out`` / ``interrupted`` /
#: ``error``) demotes the issue off ``agent:in-progress`` (§5.3.1) so the board
#: never strands a finished issue in "In Progress".
_SUCCESS_STATUSES: frozenset[str] = frozenset({"completed", "succeeded"})

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


@dataclass(slots=True)
class LifecycleDeps:
    """GitHub seam the completion supervisor uses to finish the board lifecycle (G5).

    Resolved by the launch path from the same ``app.state`` singletons the serving
    handlers use (the GitHub client, the **serialized** :class:`WriteQueue`, and the
    board hash-cache). When present, the supervisor — on a run reaching a terminal
    status — resolves the PR the agent opened for the run's branch, persists
    ``runs.pr_num``, and moves the issue to ``agent:review`` (success) or demotes it
    off ``agent:in-progress`` (failure) via :func:`set_agent_state` (INV-11 — every
    ``agent:*`` move is a write-queue-serialized replace-all ``PUT``, never a direct
    GitHub call). ``None`` (the default) skips the board work — a bare test or a path
    with no GitHub wiring still streams + records the terminal status.
    """

    github_client: GitHubClient
    write_queue: WriteQueue
    cache: HashCache[BoardPage] | None = None


def _decode_labels(labels_json: Any) -> list[str]:
    """Decode the cached ``issues.labels_json`` column to a list of label names.

    Mirrors :func:`app.github.sync._decode_labels`: a missing/garbage value yields
    an empty list (Backlog), so the replace-all desired set is computed from a clean
    base even when the issue cache is sparse.
    """
    if not labels_json:
        return []
    try:
        value = json.loads(labels_json)
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [str(v) for v in value]


async def _complete_board_lifecycle(
    *,
    run_id: str,
    status: str,
    repository: Repository,
    lifecycle: LifecycleDeps,
) -> None:
    """Finish the board lifecycle when a run reaches a terminal status (G5 / FR-04-7).

    Best-effort + non-blocking: a GitHub hiccup must never crash the supervisor, so
    every external step is guarded and a failure is logged + swallowed. Idempotent:
    re-running it on an already-transitioned issue is a no-op (the replace-all ``PUT``
    is idempotent; a re-resolved ``pr_num`` writes the same value). On a **successful**
    run it (a) resolves the open PR for the run's branch via the GitHub client and
    persists ``runs.pr_num``, then (b) moves the issue to ``agent:review``; on a
    **failed/errored** run it demotes the issue off ``agent:in-progress`` (per §5.3.1)
    so it leaves "In Progress". Both label moves go through :func:`set_agent_state`
    (the write-queue-serialized replace-all ``PUT`` — INV-11), never a direct call.
    """
    row = await repository.get_run(run_id)
    if row is None:  # pragma: no cover - the supervisor owns a real, claimed row
        return
    repo = row.get("repo")
    issue_num = row.get("issue_num")
    branch = row.get("branch")
    if not repo:
        return

    succeeded = status in _SUCCESS_STATUSES

    # (a) On success, resolve + persist the run's PR so the run-detail PR link is
    # populated (the DB pr_num signal also backs the retry no-duplicate guard).
    if succeeded and branch and row.get("pr_num") is None:
        with contextlib.suppress(Exception):
            pr_num = await lifecycle.github_client.find_open_pr_for_branch(str(repo), str(branch))
            if pr_num is not None:
                await repository.update_run_fields(run_id, pr_num=int(pr_num))

    # (b) Move the issue's agent state: review on success, demote on failure. We
    # need the issue's CURRENT labels to compute the single-occupancy replace-all
    # set (INV-11) — read the cached issue row (a sparse/absent cache degrades to an
    # empty base, still correct for the single agent:* label).
    if issue_num is None:
        return
    issue_n = int(issue_num)
    current_labels = await _current_issue_labels(repository, str(repo), issue_n)

    target = "review" if succeeded else None
    if not succeeded and "agent:in-progress" not in current_labels:
        # Nothing to demote (the issue is not stranded in In Progress).
        return
    if succeeded and current_labels == ["agent:review"]:
        # Already in review (idempotent re-run); skip the redundant write.
        return

    with contextlib.suppress(Exception):
        await set_agent_state(
            lifecycle.github_client,
            str(repo),
            issue_n,
            target,
            current_labels=current_labels,
            write_queue=lifecycle.write_queue,
            cache=lifecycle.cache,
        )


async def _current_issue_labels(repository: Repository, repo: str, issue_num: int) -> list[str]:
    """Read an issue's current label set from the cache (empty on miss/error)."""
    try:
        issue = await repository.read_issue(repo, issue_num)
    except Exception:  # noqa: BLE001 - a cache read failure → empty base (still correct)
        return []
    if issue is None:
        return []
    return _decode_labels(issue.get("labels_json"))


async def _supervise(
    *,
    run_id: str,
    handle: RunHandle,
    hub: RunStreamHub,
    pump_task: asyncio.Task[None],
    registry: StreamRegistry,
    repository: Repository,
    lifecycle: LifecycleDeps | None = None,
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
        terminal_status = _terminal_status(handle)
        with contextlib.suppress(Exception):
            await repository.update_run_fields(run_id, status=terminal_status)
        with contextlib.suppress(Exception):
            await repository.snapshot_run_totals(
                run_id, _run_totals_from_result(getattr(handle, "result", None))
            )
        # G5: finish the board lifecycle — link the PR + move the issue to review
        # (success) or demote it off in-progress (failure) via the write-queue
        # (INV-11). Best-effort: any GitHub failure is swallowed inside the helper
        # so the supervisor still records the terminal status + reclaims the hub.
        if lifecycle is not None:
            with contextlib.suppress(Exception):
                await _complete_board_lifecycle(
                    run_id=run_id,
                    status=terminal_status,
                    repository=repository,
                    lifecycle=lifecycle,
                )
        registry.discard(run_id)


def attach_run_stream(
    *,
    run_id: str,
    handle: RunHandle,
    registry: StreamRegistry,
    repository: Repository,
    tasks: set[asyncio.Task[Any]] | None = None,
    lifecycle: LifecycleDeps | None = None,
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
            lifecycle=lifecycle,
        )
    )

    for task in (pump_task, supervisor):
        track.add(task)
        task.add_done_callback(track.discard)

    return hub
