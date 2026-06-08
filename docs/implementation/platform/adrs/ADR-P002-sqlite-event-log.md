# ADR-P002: SQLite (WAL, single-writer, event log) → Postgres later

## Status

Accepted

## Context

The platform needs queryable run state, dashboard aggregates, claim-locking for dispatch idempotency, and a durable event log that powers SSE replay + audit + meters. The engine's file-per-run JSON/JSONL store does O(N) directory scans and isn't safe for concurrent writers or queries. Target: solo self-host now, multi-tenant Postgres later.

## Decision

Use **SQLite in WAL mode** as the source of truth for queryable state, with an **append-only `events` table** + plain materialized projections (`runs`, `run_stages`, `run_totals`, `spend`). SQLite is **single-writer**: all writes go through one serialized writer task using `BEGIN IMMEDIATE`, with `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout≥5000`, `foreign_keys=ON`. Dispatch idempotency is a `UNIQUE(idempotency_key)` + `INSERT … ON CONFLICT DO NOTHING` — **not** `SELECT FOR UPDATE`/`SKIP LOCKED` (SQLite has neither and doesn't need them single-process). `runs.id` is a platform UUID; the engine's run-id is a separate `engine_run_id`. Migrations via Alembic. The engine's `runs/{run_id}/` stays the artifact/blob store (authoritative for terminal totals).

## Consequences

- + Zero-ops, single-file, fast enough; event sourcing earns its keep via SSE replay + audit; backup is `VACUUM INTO`.
- − Storage ports to Postgres cleanly, but the **dispatch concurrency model does not**: Postgres needs `FOR UPDATE SKIP LOCKED` + leader election (NFR-PORT-1). The in-memory HITL `asyncio.Event` also becomes a DB-poll/Redis-signal at multi-process.
- Implication: all DB access behind a repository layer; `spend` is a projection (last-cumulative per `(run_id, task_index)`, Codex excluded), never a hand-maintained table.

## PRD Reference

§6.5, §6.4, §8.2 (idempotency), R-5, R-8, NFR-PORT-1.
