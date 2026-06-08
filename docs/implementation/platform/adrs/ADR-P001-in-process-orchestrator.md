# ADR-P001: In-process FastAPI + asyncio orchestrator (no Celery/Temporal for v1)

## Status

Accepted

## Context

The platform launches long-running (10–45 min), expensive, autonomous coding-agent runs and must dispatch, bound concurrency, retry, reconcile, and recover from crashes. The unit of durable work is a **Docker container**, which no workflow engine can replay or resume. The target user is a solo dev self-hosting via `docker compose up`.

## Decision

Run a single **FastAPI** process containing an **in-process asyncio orchestrator** (Symphony-style poll → dispatch → reconcile tick). Each run is a tracked `asyncio.Task` wrapping `EmbeddedRuntime.start(...)`. Bounded concurrency via `asyncio.Semaphore` + aggregate-resource admission. Defer Celery/RQ/Arq/Temporal. If durability is ever needed, the escalation path is **DBOS** (embedded, same DB), *not* Temporal (separate fleet + workflow rewrite).

## Consequences

- + Zero extra infra; trivial to self-host; full control over the loop; matches the proven Symphony model while adding a durable DB.
- − Single point of failure / no horizontal scale (acceptable for solo v1); crash recovery is reconcile-from-Docker + DB, not workflow replay.
- Implication: keep job acquisition behind a `dispatch(run)` boundary so a future queue/DBOS swap is additive. Keep the event loop non-blocking (DB writes off-loop).

## PRD Reference

§8.2 (orchestrator), §8 headline, NFR-PORT-1.
