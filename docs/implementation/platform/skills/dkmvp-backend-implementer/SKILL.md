---
name: dkmvp-backend-implementer
description: FastAPI + SQLite + asyncio + EmbeddedRuntime conventions for the DKMV Platform backend. Use when implementing or reviewing any platform/backend slice (orchestrator, GitHub, SSE, persistence, executor, secrets). Returns the conventions to follow; does not write code itself.
allowed-tools: Read, Grep, Glob
---

DKMV Platform backend playbook. Stack: Python 3.12, FastAPI, SQLite(WAL)+Alembic+aiosqlite, sse-starlette, in-process asyncio orchestrator wrapping `dkmv.runtime.EmbeddedRuntime`. Package layout `platform/backend/app/{api,orchestrator,github,executor,db,sse,secrets,security}`.

**Engine bridge (INV-13).** Construct one `EmbeddedRuntime(RuntimeConfig(...), output_dir=<platform volume>)` behind a `RunService`. Call it in-process — never shell the `dkmv` CLI, never edit `dkmv/`. Key calls: `start(component, source, ..., on_pause=, ...) -> RunHandle`; `RunHandle.add_observer/stop(force=)/wait`; `get_capabilities()`, `preflight_check()`, `list_components()`, `inspect_component()`, `preview_execution_plan()`, `get_artifact()`, `replay_events()`. The sync `EventObserver.on_event` must bridge via `loop.call_soon_threadsafe(queue.put_nowait, event)` (INV-12). `RuntimeConfig` hardcodes `auth_method="api_key"` — v1 requires API keys.

**Persistence (INV-5/6).** One connection module sets `PRAGMA journal_mode=WAL; synchronous=NORMAL; busy_timeout=5000; foreign_keys=ON`. ALL writes go through a single serialized writer task using `BEGIN IMMEDIATE`; reads use separate connections. Dispatch idempotency = `UNIQUE(idempotency_key)` + `INSERT … ON CONFLICT DO NOTHING`. Never `SKIP LOCKED`/`FOR UPDATE`. Repository layer wraps every table; no raw SQL in handlers. `runs.id` = platform UUID; `engine_run_id` separate. `events` append-only, monotonic id; `spend` is a projection (last-cumulative per `(run_id, task_index)`, Codex excluded); `run_totals` snapshot at completion.

**API (INV-1).** Base `/api/v1`. Error envelope `{error:{code,message,details?}}`. Status codes per PRD §8.9 (409 `duplicate_dispatch`/`pause_already_resolved`, 400 `validation_error`/`unsupported_for_agent`, 403 Host/CSRF). Cursor pagination. Every state-changing route binds loopback + token + Host/Origin validation + CSRF.

**Async discipline.** No blocking calls on the event loop; DB writes off-loop via the writer task; SSE per-run bounded queues. Orchestrator deadlines are UTC, persisted, re-evaluated each tick (survive suspend).

**Quality gate (run before reporting):** `cd platform/backend && ruff check . && mypy app && pytest -q`. No `# type: ignore` without `# DKMVP-ESCAPE: <reason>`.
