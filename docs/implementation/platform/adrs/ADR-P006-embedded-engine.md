# ADR-P006: Consume `EmbeddedRuntime` in-process; platform owns the DB index

## Status

Accepted

## Context

DKMV ships a clean embedded API (`dkmv/runtime/`: `EmbeddedRuntime`, `RunHandle`, `EventObserver`, `PauseRequest/Response`, introspection, artifacts, reconcile). The platform must drive runs without shelling the CLI, and the engine's contracts must not change for v1 (N6).

## Decision

The backend imports `dkmv.runtime` **in-process** and calls `EmbeddedRuntime` directly via a thin `RunService`. Credentials/config are injected through `RuntimeConfig` (note: it hardcodes `auth_method="api_key"`, so v1 requires API keys — OAuth is an engine ask). The engine's on-disk `runs/{run_id}/` is the **artifact/blob store** and is authoritative for a run's **terminal totals**; the platform DB is authoritative for live state + queryable aggregates and mirrors run metadata with a **platform UUID PK** (engine run-id is collision-weak). Engine changes are out of scope for v1 and tracked as **engine asks** (PRD §11): OAuth, surface `"paused"`, pluggable deployment, run-id uniqueness, **live-run re-attach**, component checkpointing, Codex cost signal.

## Consequences

- + Reuses the hardest-won engine capabilities (isolation, adapters, streaming, pause callback, run persistence); no CLI scraping.
- − Inherits engine constraints: no live-run re-attach (ADR-P007), Codex `$0` cost (ADR-P009), `auth_method=api_key` only, collision-weak engine run-id.
- Implication: the platform mirrors/indexes engine data rather than depending on the engine's O(N) `list_runs`/`get_stats`; reconcile back-fills `run_totals` from engine `result.json`.

## PRD Reference

§6.2, §6.5 (reconciliation rule), §11 (engine asks), N6, R-6/R-8.
