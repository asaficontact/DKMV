# DKMV Platform — Architecture Decision Records

These ADRs capture the **locked** architectural decisions for the DKMV Platform (the web control plane built in `platform/`). They constrain task implementation; phase docs and tasks reference them by ID. They are scoped to the *platform*, separate from the engine ADRs in `docs/adrs/` (which govern `dkmv/`).

Format: MADR (Markdown Any Decision Record). Status one of Proposed / Accepted / Superseded.

| ADR | Title | Status | Drives |
|---|---|---|---|
| [ADR-P001](ADR-P001-in-process-orchestrator.md) | In-process FastAPI + asyncio orchestrator (no Celery/Temporal for v1) | Accepted | F11, F13, all backend |
| [ADR-P002](ADR-P002-sqlite-event-log.md) | SQLite (WAL, single-writer, event log) → Postgres later | Accepted | F2, F10 |
| [ADR-P003](ADR-P003-sse-streaming.md) | SSE for live streaming; HttpOnly-cookie auth | Accepted | F8 |
| [ADR-P004](ADR-P004-github-pat-labels.md) | Fine-grained PAT + poll-only + labels-as-control-plane (App/webhooks deferred) | Accepted | F4, F5, F6 |
| [ADR-P005](ADR-P005-sandbox-isolation.md) | gVisor runtime + egress allowlist + brokered socket | Accepted | F3 |
| [ADR-P006](ADR-P006-embedded-engine.md) | Consume `EmbeddedRuntime` in-process; platform owns the DB index | Accepted | F1, F2 |
| [ADR-P007](ADR-P007-hitl-durability.md) | Best-effort-durable HITL (no live-run re-attach) | Accepted | F9, F11 |
| [ADR-P008](ADR-P008-executor-seam.md) | `Executor` interface (LocalDocker now, remote later) | Accepted | F3, F11 |
| [ADR-P009](ADR-P009-capability-aware-cost.md) | Capability-aware cost enforcement (Codex = timeout-only) | Accepted | F13 |
| [ADR-P010](ADR-P010-workflows-readonly-v1.md) | Workflows screen read-only in v1 (authoring → v1.1) | Accepted | F12 |

Quick-reference one-liners are duplicated in the implementation `CLAUDE.md`.
