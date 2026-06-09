"""SSE streaming backbone (slice 2.3) — observer bridge → pump → endpoint (§8.3).

The observer→queue→pump→SSE backbone the live-run view (slice 2.4) consumes:

* :mod:`app.sse.observer_bridge` — the INV-12 sync→async hand-off
  (``call_soon_threadsafe``), the per-run :class:`RunStreamHub` + bounded
  :class:`Subscriber` (slow-consumer policy), and the process-wide
  :class:`StreamRegistry`.
* :mod:`app.sse.pump` — the single per-run :class:`EventPump`: batch-append to the
  append-only ``events`` table through the repository, project ``run_stages``, and
  fan out :class:`StreamFrame`-s.
* :mod:`app.sse.auth` — the HttpOnly ``SameSite=Strict`` SSE cookie auth (INV-2).
* :mod:`app.sse.replay` — ``Last-Event-ID`` subscribe-before-read + dedup-by-id.
* :mod:`app.sse.endpoint` — ``GET /runs/{id}/events`` (heartbeat + anti-buffering).
"""

from __future__ import annotations

from app.sse.observer_bridge import (
    PlatformEventObserver,
    RunStreamHub,
    StreamRegistry,
    Subscriber,
)
from app.sse.pump import EventPump, StreamFrame

__all__ = [
    "EventPump",
    "PlatformEventObserver",
    "RunStreamHub",
    "StreamFrame",
    "StreamRegistry",
    "Subscriber",
]
