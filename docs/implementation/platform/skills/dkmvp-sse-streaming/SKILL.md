---
name: dkmvp-sse-streaming
description: The DKMV Platform live-streaming playbook — sync→async observer bridge, SSE endpoint + cookie auth, Last-Event-ID replay, and the segment-sum cost/turn meter. Use for the streaming and meter slices (2.3, 2.4) and any reconnect/meter review.
allowed-tools: Read, Grep, Glob
---

DKMV Platform streaming + meter playbook (PRD §8.3, §6.4; ADR-P003). The three things people get wrong:

**1. Observer bridge (INV-12).** The engine calls `EventObserver.on_event(RuntimeEvent)` **synchronously, inline**, on a thread that is NOT guaranteed to be the event-loop thread. Capture the loop at startup and push with `loop.call_soon_threadsafe(queue.put_nowait, event)`. NEVER bare `queue.put_nowait`, `loop.create_task`, or per-event `run_coroutine_threadsafe` from the observer. Each run has a bounded per-subscriber queue; on overflow, coalesce/drop meter frames but NEVER lifecycle/decision/`task_completed` events; disconnect a persistently-slow consumer (it reconnects + replays).

**2. SSE + resumable replay.** `GET /api/v1/runs/{id}/events` via `sse-starlette`. Auth token rides an **HttpOnly `SameSite=Strict` cookie** — never a URL/query param (INV-2; a token in the URL leaks into the `events` table). Heartbeat ~15 s; set `Cache-Control: no-cache` and `X-Accel-Buffering: no`. On reconnect with `Last-Event-ID`: **subscribe to the live per-run queue FIRST, then read `events WHERE id>:last AND run_id=:id ORDER BY id`, flush, then tail — dedup by `id`** across the handoff (this closes the gap/dup window). Rehydrate the PauseCard from the `pause_decisions` row, not the live push. Board/chip use polling, not N per-card SSE streams.

**3. Segment-sum meter (INV-7).** `RuntimeEvent.cost_usd`/`turns` are **cumulative per task**; the run total is the **sum across tasks**. Compute `run_cost = Σ(final cost_usd of each completed task) + (latest cost_usd within the active task)`, **deduped by `(run_id, task_index)`**. NEVER `SUM(cost_usd)` over all events (double-counts) and NEVER plain keep-latest (resets to ~$0 at each stage boundary and never reaches the run total). `task_completed`/`task_failed` carry a segment's final cost → meter-critical, never coalesced. Codex segments contribute `$0` → render the run cost "—" if the (sole) agent is Codex, and exclude from spend aggregates (tokens still count).

The acceptance test that proves it: a multi-stage `plan` run's displayed cost climbs across stage boundaries toward the ~$12 run total and never drops toward $0.
