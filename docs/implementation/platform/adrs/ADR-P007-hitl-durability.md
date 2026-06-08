# ADR-P007: Best-effort-durable HITL (no live-run re-attach)

## Status

Accepted

## Context

When a workflow pauses, the engine `await`s an `on_pause` callback with the **container held open** and the run coroutine suspended mid-`ComponentRunner.run`, holding in-memory `task_results`. The engine exposes **no API to re-enter a half-finished run or re-attach to a container started by a prior process**. The platform must bridge the pause to a web decision that may arrive much later and survive restarts, without orphaning a money-spending container.

## Decision

- **Pause bridge:** on pause, persist a `pause_decisions` row, set `agent:paused`, **release the run's concurrency slot** (the container is idle during the pause), emit `pause_requested`, and `await` an `asyncio.Event` keyed by `decision_id`. `POST /runs/{id}/answer` resolves **exactly once** (`UPDATE … WHERE status='pending'`, fire on rowcount=1) and returns the `PauseResponse`. A UTC `timeout_at` (default 60 min) auto-resolves via the reconcile tick (default auto-abort).
- **Durability scope (honest):** only the **decision** is durable. On restart the suspended run is **not** resumed in place — it is re-launchable from the **last *pushed* task boundary** via `start_task` (the engine reconstructs prior stage outputs from the repo), else marked `interrupted`. Therefore **any `pause_after` task MUST commit/push its outputs**. UI/copy never promises "resumes exactly where it left off."
- **Stop during pause** uses `RunHandle.stop(force=True)` (cancel is only checked between tasks).
- **Crash recovery** (ADR-P001): kill orphan + mark `interrupted` + offer `start_task` retry; never bare-cancel a task without stopping its container.

## Consequences

- + No orphaned containers; decisions survive restart; idle pauses don't hold slots or hang forever.
- − A mid-task/mid-pause crash loses in-flight work back to the last pushed boundary (acceptable for v1; true durability is engine ask §11.6).
- Implication: graceful drain on SIGTERM is mandatory; reconcile owns deadline evaluation in UTC.

## PRD Reference

§8.5, §8.2 (drain/recovery), NFR-REL-1, R-7/R-15.
