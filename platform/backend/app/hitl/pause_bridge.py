"""The ``on_pause`` bridge — durable, best-effort HITL interrupt (INV-9 / §8.5).

The platform passes ``on_pause: Callable[[PauseRequest], Awaitable[PauseResponse]]``
to ``EmbeddedRuntime.start`` (slice 2.1 wires it through; this module is the real
bridge that replaces the 2.1 pass-through placeholder). The engine genuinely
``await``\\s this callback at a workflow's pause point — with the container held
open and the run coroutine suspended — and resumes only when the callback returns
a :class:`~dkmv.tasks.pause.PauseResponse` (verified in ``ComponentRunner.run``).

When the engine calls the bridge (§8.5 step 1) it:

1. **Writes a ``pause_decisions`` row** (``status='pending'``, the engine
   ``PauseRequest`` payload, a UTC ``timeout_at`` — 60 min default) through the
   single writer (INV-6) BEFORE awaiting, so the *decision* is durable.
2. **Sets the issue ``agent:paused``** via ``set_agent_state`` on the Phase-1
   serialized write-queue (INV-11) → the board's "Needs You" column.
3. **Releases the run's concurrency slot** (T086) — a paused run is genuinely
   idle (no agent process running), so it must not occupy a ``max_concurrent_runs``
   slot while a human is away. This is the accounting primitive Phase 5's
   admission semaphore consumes (Phase 2 does not enforce the cap).
4. **Emits ``pause_requested`` over SSE** by injecting a synthetic
   :class:`~dkmv.runtime.RuntimeEvent` into the run's stream hub → the UI renders
   the decision card; a reconnecting client rehydrates it from the
   ``pause_decisions`` row (slice 2.3 rehydration source).
5. **Awaits an ``asyncio.Future`` keyed by ``decision_id``** (§8.5 step 2). The
   answer endpoint / timeout sweep resolve the DB row exactly-once and — only on
   the winning ``rowcount==1`` — fire that future. The bridge then emits a
   ``decision`` event ("You chose: '{label}'"), **re-acquires the slot**, and
   returns the :class:`PauseResponse` → the engine resumes (§8.5 step 3).

**Honest scope (INV-9 / §8.5.5).** Only the *decision row* is durable. The
suspended run coroutine + live container do NOT survive a backend restart — there
is no engine API to re-enter a half-finished ``ComponentRunner.run``. So the
honest claim is "the decision is durable; on restart the run is re-launchable from
the last pushed task boundary via ``start_task``, else ``interrupted``" — never
"the suspended run survives" and never an in-place-resume promise. No copy here
over-claims that.

Nothing here edits ``dkmv/``; the only engine touch is the in-process
``RuntimeEvent`` / ``PauseRequest`` / ``PauseResponse`` types (INV-13).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from dkmv.runtime import RuntimeEvent
from dkmv.tasks.pause import PauseRequest, PauseResponse

from app.hitl.registry import DecisionRegistry
from app.hitl.slots import ConcurrencySlots

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.db.repository import Repository
    from app.github.client import GitHubClient
    from app.github.graphql import BoardPage
    from app.github.hash_cache import HashCache
    from app.github.write_queue import WriteQueue
    from app.sse.observer_bridge import StreamRegistry

_log = logging.getLogger(__name__)

#: Default pause timeout — 60 minutes (§8.5 step 4 / PRD ``PAUSE_TIMEOUT_S``).
#: NOT 24 h: a held 8 GB container under a 3-slot cap is too costly to park for a
#: day. On expiry the sweep auto-resolves (default auto-abort — INV-9 / T085).
DEFAULT_PAUSE_TIMEOUT_MINUTES = 60

#: Synthetic ``RuntimeEvent.event_type`` values the bridge injects. They are in
#: the never-drop spine (:data:`app.sse.observer_bridge.CRITICAL_EVENT_TYPES`) so
#: the slow-consumer policy never coalesces a pause/decision frame (§8.3 / INV-7).
PAUSE_REQUESTED = "pause_requested"
DECISION = "decision"


def compute_timeout_at(*, minutes: int = DEFAULT_PAUSE_TIMEOUT_MINUTES) -> str:
    """UTC ``timeout_at`` = now + ``minutes`` as an ISO-8601 string (§8.5).

    Stored UTC (binding — INV-9): the sweep re-evaluates ``now() >= timeout_at``
    in UTC each tick, so a DST/local-time skew can never make a pause expire early
    or hang forever. ISO-8601 sorts lexicographically in chronological order, so
    the ``timeout_at <= :now`` sweep query is a correct comparison.
    """
    return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()


def _label_for_choice(request: PauseRequest, answers: dict[str, str]) -> str:
    """Render the human-readable choice label for the ``decision`` event text.

    The engine stores ``answers[question_id]`` verbatim as the chosen option's
    **value** (§6.1). For the "You chose: '{label}'" event we map that value back
    to the option's ``label`` (the engine-authoritative ``{value, label}`` shape)
    so the feed shows the human-friendly label, not the raw value. Falls back to
    the value itself when no option matches (a skip / free-form answer).
    """
    for question in request.questions:
        chosen = answers.get(question.id)
        if chosen is None:
            continue
        for option in question.options:
            if option.get("value") == chosen:
                return str(option.get("label") or chosen)
        return str(chosen)
    return "skip"


@dataclass(slots=True)
class PauseBridgeDeps:
    """Per-run dependencies the pause bridge closes over (composed at launch).

    Bundled so the launch path builds **one** bridge per run carrying the run's
    identity + the shared singletons (repository, write-queue, GitHub client,
    stream registry, decision registry, slot accounting). All are lifespan-owned;
    the bridge never builds a per-call connection.
    """

    run_id: str
    repo: str
    issue_num: int
    repository: Repository
    github_client: GitHubClient
    write_queue: WriteQueue
    stream_registry: StreamRegistry
    decisions: DecisionRegistry
    slots: ConcurrencySlots
    cache: HashCache[BoardPage] | None = None
    current_labels: Sequence[str] = ()
    timeout_minutes: int = DEFAULT_PAUSE_TIMEOUT_MINUTES


def _emit_stream_event(
    deps: PauseBridgeDeps,
    *,
    event_type: str,
    task_name: str,
    data: dict[str, Any],
    content: str = "",
) -> None:
    """Inject a synthetic spine :class:`RuntimeEvent` into the run's stream hub.

    The pump drains the hub's inbound queue, persists each event to the
    append-only ``events`` table, and fans it out to SSE subscribers — so a
    platform-originated ``pause_requested`` / ``decision`` frame reaches the same
    durable log + live stream as an engine frame (and replays on reconnect). The
    event is enqueued directly on the loop thread (the bridge runs on the serving
    loop, unlike the engine's worker-thread observer which needs
    ``call_soon_threadsafe`` — INV-12). A no-op when no hub exists yet (a run with
    no live stream, e.g. a direct unit test): the durable ``pause_decisions`` row
    is the source of truth, so the UI still rehydrates from ``GET /runs/{id}``.
    """
    hub = deps.stream_registry.get(deps.run_id)
    if hub is None:
        return
    event = RuntimeEvent(
        timestamp=datetime.now(UTC),
        run_id=deps.run_id,
        task_name=task_name,
        event_type=event_type,
        data=data,
        content=content,
    )
    # On the loop thread already (the bridge is awaited on the serving loop), and
    # the hub's inbound queue is a plain asyncio.Queue → a direct put is safe here.
    # If full, drop the oldest (recoverable via replay) rather than block the loop.
    queue = hub.queue
    if queue.full():
        try:
            queue.get_nowait()
        except Exception:  # noqa: BLE001 - racey full→empty, best-effort
            pass
    queue.put_nowait(event)


async def _set_paused_label(deps: PauseBridgeDeps) -> None:
    """Move the issue to ``agent:paused`` via the write-queue (INV-11).

    Routed through ``set_agent_state`` (replace-all ``PUT``, single-occupancy) on
    the Phase-1 serialized write-queue — never a fictional single-label ``PATCH``.
    A best-effort step: a GitHub hiccup must not strand the run un-paused (the
    decision row is already durable + the SSE card already rendered), so a failure
    is logged, not raised into the engine's await.
    """
    from app.github.state_machine import set_agent_state

    try:
        await set_agent_state(
            deps.github_client,
            deps.repo,
            deps.issue_num,
            "paused",
            current_labels=deps.current_labels,
            write_queue=deps.write_queue,
            cache=deps.cache,
        )
    except Exception:  # noqa: BLE001 - label move is best-effort; never wedge the pause
        _log.warning("set agent:paused failed for %s#%s", deps.repo, deps.issue_num)


async def run_pause_bridge(deps: PauseBridgeDeps, request: PauseRequest) -> PauseResponse:
    """The ``on_pause`` callback body: write → label → release → emit → await (§8.5).

    Invoked by the engine at a workflow pause point (container held open, run
    coroutine suspended). Performs the §8.5 step-1 side effects, awaits the keyed
    future the answer endpoint / timeout sweep fires (only after winning the INV-9
    exactly-once DB guard), then emits the ``decision`` event, re-acquires the
    slot, and returns the :class:`PauseResponse` so the engine resumes. **Never
    promises in-place recovery of the suspended run** — only the decision is durable
    (§8.5.5).
    """
    timeout_at = compute_timeout_at(minutes=deps.timeout_minutes)
    request_json = request.model_dump_json()

    # (§8.5 step 1a) Durable decision row FIRST — it survives a restart even though
    # the suspended run does not. The decision_id keys the in-memory future below.
    decision_id = await deps.repository.create_pause_decision(
        run_id=deps.run_id,
        request_json=request_json,
        task_name=request.task_name,
        timeout_at=timeout_at,
    )

    # (§8.5 step 1d) Register the await rendezvous BEFORE the slow side effects so
    # an answer that races in cannot fire before the waiter exists.
    future = deps.decisions.register(decision_id)

    # (§8.5 step 1b) Issue → agent:paused (write-queue, INV-11) → "Needs You".
    await _set_paused_label(deps)

    # (§8.5 step 1c) Release the slot — the paused container is genuinely idle (T086).
    deps.slots.release()

    # (§8.5 step 1e) Emit pause_requested over SSE → the UI decision card. Carries
    # the decision_id + the engine request so a live client renders without a refetch.
    _emit_stream_event(
        deps,
        event_type=PAUSE_REQUESTED,
        task_name=request.task_name,
        data={
            "decision_id": decision_id,
            "timeout_at": timeout_at,
            "request": json.loads(request_json),
        },
        content="This run needs your decision to continue",
    )

    try:
        # (§8.5 step 2) Await the human (or the timeout sweep). The future resolves
        # with {answers, skip_remaining} only after the resolver won the DB guard.
        payload = await future
    finally:
        deps.decisions.discard(decision_id)

    answers_raw = payload.get("answers", {})
    answers: dict[str, str] = (
        {str(k): str(v) for k, v in answers_raw.items()} if isinstance(answers_raw, dict) else {}
    )
    skip_remaining = bool(payload.get("skip_remaining", False))
    resolved_by = str(payload.get("resolved_by", "human"))

    # (§8.5 step 3) Re-acquire the slot the run releases on pause — it is active
    # again (Phase 5's semaphore would await a permit here; Phase 2 just accounts).
    deps.slots.acquire()

    # Emit the decision event ("You chose: '{label}'") so the feed records the
    # resolution; a timeout auto-resolve is labelled distinctly.
    chosen_label = _label_for_choice(request, answers)
    decision_text = (
        f"Auto-resolved on timeout ({chosen_label})"
        if resolved_by == "timeout"
        else f"You chose: '{chosen_label}'"
    )
    _emit_stream_event(
        deps,
        event_type=DECISION,
        task_name=request.task_name,
        data={
            "decision_id": decision_id,
            "answers": answers,
            "skip_remaining": skip_remaining,
            "resolved_by": resolved_by,
        },
        content=decision_text,
    )

    return PauseResponse(answers=answers, skip_remaining=skip_remaining)


def build_pause_bridge(deps: PauseBridgeDeps) -> Callable[[PauseRequest], Awaitable[PauseResponse]]:
    """Bind a per-run ``on_pause`` callable the launch path passes to ``start``.

    Closes over the run's :class:`PauseBridgeDeps` so the engine calls a zero-extra-
    arg ``Callable[[PauseRequest], Awaitable[PauseResponse]]`` (the exact engine
    signature). One bridge per launched run; replaces slice 2.1's
    ``_passthrough_on_pause`` placeholder.
    """

    async def _on_pause(request: PauseRequest) -> PauseResponse:
        return await run_pause_bridge(deps, request)

    return _on_pause
