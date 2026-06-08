# ADR-P003: SSE for live streaming; HttpOnly-cookie auth

## Status

Accepted

## Context

The live run view needs server→client streaming of agent events + meters, with reconnect/replay, for potentially several concurrent runs. The engine emits events via a **synchronous** `EventObserver.on_event(RuntimeEvent)` callback whose thread is not guaranteed to be the event-loop thread. The app binds loopback + requires a local auth token (ADR-P005), but browser `EventSource` cannot set an `Authorization` header.

## Decision

Use **SSE** (`sse-starlette`) for `GET /runs/{id}/events` — the data flow is one-way; the client→server actions (answer/stop/retry) are plain POSTs. Bridge the sync observer to async with **`loop.call_soon_threadsafe(queue.put_nowait, event)`** (never bare `put_nowait`/`create_task`/per-event `run_coroutine_threadsafe`). Resumable replay via `Last-Event-ID`: **subscribe to the live queue first, then read `events WHERE id>last AND run_id` and dedup by `id`**. Heartbeat ~15 s; `Cache-Control: no-cache` + `X-Accel-Buffering: no`. Carry the auth token in an **HttpOnly `SameSite=Strict` cookie** (never in the URL — the `events` table must hold no secrets). Board/chip use polling, not N per-card SSE streams. Multi-process later: Redis pub/sub for live fan-out **only** (replay stays DB-backed).

## Consequences

- + Free browser reconnect; simple; matches the AG-UI direction; replay is exact because it's event-sourced.
- − SSE has no native backpressure → coalesce meter frames (≤4 Hz, keep-latest) but never drop lifecycle/decision/`task_completed`; disconnect persistently-slow consumers.
- Implication: per-run bounded queue + a single event pump per run that batch-appends to `events` and fans out.

## PRD Reference

§8.3, §6.4, NFR-SEC-2.
