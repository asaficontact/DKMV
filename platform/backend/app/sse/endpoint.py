"""SSE endpoint ``GET /runs/{id}/events`` — heartbeat, anti-buffering, replay (§8.3).

The single live-run stream (the board/chip stay poll-driven — §8.3). One
``EventSource`` connection per open run view holds one stream here. The endpoint:

* authenticates via the **HttpOnly ``SameSite=Strict`` SSE cookie** + ``Origin``/
  ``Host`` (:func:`app.sse.auth.authenticate_sse` — INV-2; the token NEVER rides a
  URL/query), on top of the app-wide INV-1 middleware;
* **subscribes to the live per-run queue first**, then streams the durable
  backlog after ``Last-Event-ID`` and tails live, **dedup-by-id**
  (:func:`app.sse.replay.replay_then_tail` — INV-2 replay contract, AC-11);
* emits a ``:``-comment **heartbeat every ~15 s** (under common 30–60 s proxy idle
  timeouts) and sets ``Cache-Control: no-cache`` + ``X-Accel-Buffering: no`` so a
  reverse proxy never batches or drops the stream (AC-10);
* carries the **outer** ``RuntimeEvent`` as the SSE message body and each message
  ``id`` = the ``events.id`` cursor (§6.4).

The run's :class:`~app.sse.observer_bridge.RunStreamHub` is resolved from the
process-wide :class:`~app.sse.observer_bridge.StreamRegistry` on ``app.state``
(composed by the launch path / lifespan). A request for a run with no live hub but
a persisted run row still replays the durable backlog then closes (the run already
finished); an unknown run is ``404 run_not_found``.

Nothing here writes SQL directly or reaches ``dkmv/``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from app.api.deps import get_repository
from app.api.errors import ApiError, run_not_found
from app.db.repository import Repository
from app.sse.auth import SseAuthError, authenticate_sse
from app.sse.observer_bridge import StreamRegistry, Subscriber
from app.sse.pump import StreamFrame
from app.sse.replay import iter_backlog, parse_last_event_id, replay_then_tail

# No prefix here: the ``/api/v1`` version prefix is owned by the single parent
# router in :mod:`app.api`, which this router attaches to.
router = APIRouter(tags=["runs"])

#: Heartbeat cadence (seconds). A ``:``-comment ping under common 30–60 s proxy
#: idle timeouts keeps the stream from being reaped (§8.3 / AC-10). ``sse-starlette``
#: emits its own ping at this interval.
HEARTBEAT_INTERVAL_S = 15

#: Anti-buffering headers (binding — §8.3 / AC-10): ``no-cache`` so the proxy/browser
#: never serves a cached stream; ``X-Accel-Buffering: no`` so nginx-style proxies
#: don't buffer the chunked response (which would defeat live streaming).
_STREAM_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def _registry(request: Request) -> StreamRegistry:
    """Resolve the process-wide :class:`StreamRegistry` from ``app.state``.

    Composed once by the launch path / lifespan so the pump's publish target and
    the SSE subscribers share one hub per run. Falls back to creating + caching an
    empty registry (a test that streams a finished run from the durable backlog
    only needs the replay path, not a live hub).
    """
    existing = getattr(request.app.state, "stream_registry", None)
    if isinstance(existing, StreamRegistry):
        return existing
    registry = StreamRegistry()
    request.app.state.stream_registry = registry
    return registry


def _frame_to_sse(frame: StreamFrame) -> ServerSentEvent:
    """Wrap a :class:`StreamFrame` as one SSE message (id = ``events.id``, §6.4).

    The ``data`` payload is the JSON-serialized **outer** ``RuntimeEvent`` body;
    ``id`` is the monotonic cursor a reconnecting client echoes as
    ``Last-Event-ID``; ``event`` is the ``event_type`` so a client can branch on
    the message kind without parsing the body.
    """
    return ServerSentEvent(
        data=json.dumps(frame.body),
        id=str(frame.event_id),
        event=frame.event_type or "message",
    )


@router.get("/runs/{run_id}/events")
async def stream_run_events(run_id: str, request: Request) -> EventSourceResponse:
    """Stream a run's events over SSE (cookie auth + replay + heartbeat) — §8.3.

    Authenticates the connection via the HttpOnly ``SameSite=Strict`` cookie +
    ``Origin``/``Host`` (INV-2), resolves the run (``404`` if unknown),
    **subscribes to the live hub before reading** the durable backlog after
    ``Last-Event-ID``, and returns an :class:`EventSourceResponse` that flushes the
    deduped backlog then tails live with a ~15 s heartbeat and anti-buffering
    headers. The token NEVER appears in the URL.
    """
    # INV-2: cookie + Origin/Host auth, layered on the INV-1 middleware.
    try:
        authenticate_sse(request)
    except SseAuthError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message) from exc

    # The SSE generator tails for the run's lifetime — longer than any single
    # ``async with get_repository`` block — so it holds the long-lived,
    # lifespan-owned Repository (never a per-request one that would be closed when
    # its block exits). Resolve it once here; the run-existence read uses it too.
    repository = await _stream_repository(request)

    # Resolve the run (404 for an unknown platform UUID). The durable ``events``
    # backlog is the primary replay source, so a finished run still streams.
    row = await repository.get_run(run_id)
    if row is None:
        raise run_not_found(run_id)

    last_id = parse_last_event_id(
        request.headers.get("last-event-id") or request.query_params.get("lastEventId")
    )

    registry = _registry(request)
    hub = registry.get(run_id)

    # Subscribe-before-read (INV-2 replay): attach to the live hub FIRST so any
    # event the pump persists during the backlog read is also captured live —
    # closing the gap/dup window. A finished run has no hub → backlog-only replay.
    subscriber = Subscriber()
    if hub is not None:
        hub.add_subscriber(subscriber)

    async def event_generator() -> AsyncIterator[ServerSentEvent]:
        """Yield the deduped backlog then tail live, cleaning up the subscriber."""
        try:
            if hub is not None:
                async for frame in replay_then_tail(
                    repository=repository,
                    hub=hub,
                    subscriber=subscriber,
                    last_id=last_id,
                ):
                    if await request.is_disconnected():
                        break
                    yield _frame_to_sse(frame)
            else:
                # No live hub (finished run): stream the durable backlog once, then
                # end — in BOUNDED PAGES (FIX-3) so a reconnect on a long finished
                # run doesn't materialize the whole history into memory at once.
                async for frame in iter_backlog(repository, run_id, last_id):
                    if await request.is_disconnected():
                        break
                    yield _frame_to_sse(frame)
        finally:
            if hub is not None:
                hub.remove_subscriber(subscriber)

    return EventSourceResponse(
        event_generator(),
        headers=_STREAM_HEADERS,
        ping=HEARTBEAT_INTERVAL_S,
    )


async def _stream_repository(request: Request) -> Repository:
    """Return the long-lived :class:`Repository` for the stream's lifetime.

    The SSE generator outlives any single ``async with get_repository`` block (it
    tails for the run duration), so it holds the lifespan-owned
    ``app.state.repository`` — never a per-request one that would be ``close()``-d
    when its block exits. **Test fallback only** (no lifespan): use the per-request
    resolver, which builds + starts a Repository on the serving loop. The test
    fallback Repository is left open for the (short-lived, backlog-only) test
    stream; production reuses the lifespan singleton.
    """
    repo = getattr(request.app.state, "repository", None)
    if isinstance(repo, Repository):
        return repo
    # Test fallback (no lifespan): the per-request resolver builds + starts one.
    async with get_repository(request) as fallback:
        return fallback
