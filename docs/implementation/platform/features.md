# DKMV Platform — Feature Registry

## Overview

14 features organized across 6 phases (Phase 0 → Phase 5). Features must be built in dependency order. Each feature traces to the PRD (`docs/design_docs/platform/PRD_dkmv_platform_v1.md`, "PRD" below) and to the design prototype (`docs/design_docs/platform/`).

Phases map 1:1 to the PRD §12 milestones:

| Phase | PRD milestone | Theme |
|---|---|---|
| Phase 0 | M0 | Skeleton, persistence, engine bridge, sandbox/security baseline |
| Phase 1 | M1 | GitHub integration + Connect + Board |
| Phase 2 | M2 | Run launch + live run + HITL |
| Phase 3 | M3 | History, analytics, retries, crash recovery |
| Phase 4 | M4 | Workflows viewer (read-only) |
| Phase 5 | M5 | Concurrency, cost governance, hardening, release |

## Dependency Diagram

```
PHASE 0 — Foundation
  F1 Skeleton & Engine Bridge ──┬──► F2 Persistence & Event Log
       │                        └──► F3 Sandbox Security & Execution
       │                                   │
       ▼                                   ▼
PHASE 1 — GitHub + UI shell
  F4 GitHub Integration ──► F5 Connect & Onboarding ──► F6 Board & Navigation
       │                                                      │
       ▼                                                      ▼
PHASE 2 — Run lifecycle
  F7 Run Launch ──► F8 Live Run Streaming & Observability ──► F9 Human-in-the-Loop
       (F7 needs F1,F2,F3,F4)        (F8 needs F2 event log)       (F9 needs F8)
       │
       ▼
PHASE 3 — Durability
  F10 Runs History & Analytics ──► F11 Orchestrator: Retry/Reconcile/Recovery
       (F10 needs F2,F8)               (F11 needs F7,F8,F9 + drain)
       │
       ▼
PHASE 4 — Authoring (read-only)
  F12 Workflows Viewer  (needs F1 engine introspection, F6 chrome)
       │
       ▼
PHASE 5 — Scale & ship
  F13 Concurrency & Cost Governance ──► F14 Hardening & Release
       (F13 needs F11)                      (F14 cross-cutting)
```

Forward-only edges; no cycles.

## Feature List

### F1: Platform Skeleton & Engine Bridge

- **Priority:** 1
- **Phase:** 0 — Foundation
- **Status:** [ ] Not started
- **Depends on:** None
- **Blocks:** F2, F3, F4, F7, F12
- **User Stories:** US-01, US-02
- **Tasks:** T010–T017
- **PRD Reference:** §8 (architecture), §8.8 (repo/dev-env/config), §6.2 (engine embedded API), §0/N6 (consume `dkmv/runtime/` as-is)
- **Key Deliverables:**
  - `platform/` repo scaffold (FastAPI backend + Vite frontend skeleton; `pyproject.toml`; `docker-compose.yml`; `Dockerfile.backend`/`Dockerfile.frontend`).
  - Editable install of the `dkmv` engine; Python ≥ 3.12 pin; documented `docker build -t dkmv-sandbox:latest` step.
  - `RunService` thin wrapper around `EmbeddedRuntime` (start/stop/observe/introspect), constructed from `RuntimeConfig`.
  - Consolidated config/env surface (§8.8) loaded via a typed settings object.
  - App boots, `GET /api/v1/preflight` returns `get_capabilities()` results.

### F2: Persistence & Event Log

- **Priority:** 2
- **Phase:** 0 — Foundation
- **Status:** [ ] Not started
- **Depends on:** F1
- **Blocks:** F4, F7, F8, F10, F11
- **User Stories:** US-03
- **Tasks:** T018–T025
- **PRD Reference:** §6.5 (DB schema, pragmas, indexes/FK, spend projection, reconciliation rule), §6.4 (event shape), §8.2 (idempotency key)
- **Key Deliverables:**
  - SQLite (WAL) schema for `projects, issues, runs, run_stages, events, pause_decisions, run_totals, settings, secrets` with indexes + `ON DELETE CASCADE` + `foreign_keys=ON`.
  - Mandatory concurrency contract: WAL, `synchronous=NORMAL`, `busy_timeout≥5000`, `BEGIN IMMEDIATE` writes, **single serialized writer task**.
  - Alembic migrations; backup story (`VACUUM INTO`).
  - Append-only event log + monotonic `events.id`; `run_totals` snapshot at completion.
  - Repository layer (all DB access behind it; SQLite→Postgres seam).
  - `spend` as a materialized projection (last-cumulative-per-`(run_id, task_index)`, Codex excluded).

### F3: Sandbox Security & Execution

- **Priority:** 3
- **Phase:** 0 — Foundation
- **Status:** [ ] Not started
- **Depends on:** F1
- **Blocks:** F7, F13
- **User Stories:** US-04, US-23
- **Tasks:** T026–T032
- **PRD Reference:** §8.6 (secrets/exfiltration containment), §8.7 (Executor seam), §8.8 (gVisor, brokered socket), NFR-SEC-1/2/3/4
- **Key Deliverables:**
  - `Executor` interface + `LocalDockerExecutor` (wraps `RunService`/`EmbeddedRuntime` + local Docker).
  - gVisor (`runsc`) default runtime; documented weaker-isolation opt-in + warning (OQ-6).
  - Brokered Docker socket (method-allowlisted proxy / rootless / Sysbox) — not raw mount.
  - Default-on network-enforced **egress allowlist** (GitHub + model APIs, pinned DNS).
  - Encrypted SecretStore; file-mount injection; repo-scoped ≤1 hr GitHub token; redact-before-persist.
  - App access control: `127.0.0.1` bind + local token + `Host`/`Origin` validation + CSRF.

### F4: GitHub Integration

- **Priority:** 4
- **Phase:** 1 — GitHub + UI shell
- **Status:** [ ] Not started
- **Depends on:** F1, F2, F3
- **Blocks:** F5, F7, F11
- **User Stories:** US-05, US-06, US-07, US-08
- **Tasks:** T033–T044
- **PRD Reference:** §8.1 (PAT-first, set_agent_state, state machine, write-queue, poll sync), §5.3.1 (board state machine), FR-02-3/7
- **Key Deliverables:**
  - `GitHubClient` with fine-grained PAT auth (App deferred); `GET /repos`; effective-write-permission preflight.
  - Issue import via paginated GraphQL board read (issues + labels + linked PRs) + `since`/cursor; Done window.
  - `set_agent_state(repo, num, target|none)` via `PUT .../labels` replace-all (single-occupancy invariant + precedence).
  - Create the four `agent:*` labels on connect.
  - Serialized, token-bucket-paced **write-queue** for all mutating calls (80/min secondary-limit handling, `Retry-After`).
  - Label→column derivation (§5.3.1) + authority rule (active run's DB row > label).
  - State-machine completeness: In Review→Done (PR merged), closed/reopened, failed-run demotion.

### F5: Connect & Onboarding

- **Priority:** 5
- **Phase:** 1 — GitHub + UI shell
- **Status:** [ ] Not started
- **Depends on:** F4
- **Blocks:** F6
- **User Stories:** US-09
- **Tasks:** T045–T049
- **PRD Reference:** §5.2 (Screen 01 `connect.jsx`), FR-01-1..6
- **Key Deliverables:**
  - Connect flow `disconnected → connecting → picker → syncing` (PAT entry screen listing the four permissions).
  - Repo picker (`GET /repos`), "What we'll do" card, `POST /projects/{repo}/sync`.
  - Preflight box from `get_capabilities()` (GitHub / Anthropic key / Docker image).
  - Vite app shell, router, design tokens ported from `styles.css`, EventSource client, theme (dark/indigo default).

### F6: Board & Navigation

- **Priority:** 6
- **Phase:** 1 — GitHub + UI shell
- **Status:** [ ] Not started
- **Depends on:** F5
- **Blocks:** F7
- **User Stories:** US-10, US-11
- **Tasks:** T050–T058
- **PRD Reference:** §5.1 (chrome, build to `dkmv_dashboard_design_prompt.md` §5), §5.3 (Screen 02), §5.3.1
- **Key Deliverables:**
  - Global chrome (sidebar nav, project switcher, "+ New run", live status chip, top-bar refresh/last-synced, theme toggle).
  - Board: six columns by `agent:*` state, issue cards, aggregate strip (poll-driven), filter bar.
  - Drag Backlog↔Queued → `POST /issues/{num}/agent-state`.
  - Empty/Populated/Syncing states.

### F7: Run Launch

- **Priority:** 7
- **Phase:** 2 — Run lifecycle
- **Status:** [ ] Not started
- **Depends on:** F1, F2, F3, F4
- **Blocks:** F8
- **User Stories:** US-12, US-13, US-14
- **Tasks:** T059–T067
- **PRD Reference:** §5.4 (Screen 03), §8.4 (launch contract), §8.9 (API contracts), §8.10 (validation), §8.11 (sequence), FR-03
- **Key Deliverables:**
  - Issue detail screen (markdown body, labels, comments, existing-run alert).
  - Run panel (workflow picker, agent/model resolution incl. `validate_agent_model`, branch, advanced guardrails; Codex hides budget/turns).
  - `POST /runs`: validation (§8.10) → claim-lock insert (UNIQUE idempotency key) → `EmbeddedRuntime.start(...)` → returns platform UUID.
  - `on_pause` callback wired (handed to engine; bridge implemented in F9).
  - `GET /runs`, `GET /runs/{id}` baseline.

### F8: Live Run Streaming & Observability

- **Priority:** 8
- **Phase:** 2 — Run lifecycle
- **Status:** [ ] Not started
- **Depends on:** F2, F7
- **Blocks:** F9, F10
- **User Stories:** US-15, US-16, US-17
- **Tasks:** T068–T079
- **PRD Reference:** §5.5 (Screen 04), §8.3 (SSE, bridge, replay, meters), §6.4 (event layers + segment-sum), FR-04
- **Key Deliverables:**
  - Sync→async observer bridge (`loop.call_soon_threadsafe`), per-run bounded queue, event pump → DB append + fan-out.
  - SSE endpoint (`GET /runs/{id}/events`) with heartbeats, anti-buffering headers, HttpOnly-cookie auth.
  - `Last-Event-ID` resumable replay (subscribe-before-read, dedup by id) + PauseCard rehydration.
  - **Segment-sum** cost/turn meters (dedup by `task_index`; `task_completed` meter-critical).
  - Live run UI: header, meters, stage tracker, event feed (Friendly/Raw), run-config/sandbox/artifacts rail, Stop, one-shot exec.

### F9: Human-in-the-Loop

- **Priority:** 9
- **Phase:** 2 — Run lifecycle
- **Status:** [ ] Not started
- **Depends on:** F8
- **Blocks:** F11
- **User Stories:** US-18, US-19, US-24
- **Tasks:** T080–T087
- **PRD Reference:** §5.6 (Screen 05), §8.5 (HITL bridge), §6.1 (PauseRequest shape), NFR-SEC-5 (PR-push approval)
- **Key Deliverables:**
  - `on_pause` bridge: write `pause_decisions`, set `agent:paused`, **release concurrency slot**, emit `pause_requested`, await keyed event.
  - `POST /runs/{id}/answer` with **resolve-exactly-once** guard; resumes engine; appends `decision` event.
  - Decision card UI (engine-authoritative `{value,label,description?}` options, recommended = `default`).
  - UTC `timeout_at` (60 min default → auto-abort) auto-resolved by reconcile; `Stop` during pause → `stop(force=True)`.
  - Platform-injected **PR-push approval gate** (NFR-SEC-5) reusing the pause primitive.

### F10: Runs History & Analytics

- **Priority:** 10
- **Phase:** 3 — Durability
- **Status:** [ ] Not started
- **Depends on:** F2, F8
- **Blocks:** None
- **User Stories:** US-20, US-21
- **Tasks:** T088–T095
- **PRD Reference:** §5.7 (Screen 06), §8.9 (`GET /stats`), FR-06, FR-06-1a (Codex spend exclusion)
- **Key Deliverables:**
  - `GET /runs` (filters + cursor pagination), `GET /runs/{id}` full detail, `GET /stats`, `GET /retry-queue`.
  - Aggregate cards + spend chart (Codex-excluded), rate-limit health row, retry queue.
  - Runs table (sortable/filterable) + read-only finished-run view; `timed_out`/`interrupted` palette mapping.

### F11: Orchestrator — Retry, Reconcile, Recovery

- **Priority:** 11
- **Phase:** 3 — Durability
- **Status:** [ ] Not started
- **Depends on:** F7, F8, F9
- **Blocks:** F13
- **User Stories:** US-22, US-25
- **Tasks:** T096–T105
- **PRD Reference:** §8.2 (tick, reconcile, drain, crash recovery, idempotency), NFR-REL-1, R-15
- **Key Deliverables:**
  - Orchestrator tick loop (poll candidate issues → dispatch); UTC-persisted deadlines re-evaluated per tick.
  - Reconciliation: stall detection, label refresh under authority rule, orphan-container sweep.
  - **Idempotent retries** (detect existing branch/PR; capped exponential backoff; ≤3 attempts → retry queue).
  - **Graceful drain** on SIGTERM (stop containers, never bare-cancel).
  - **Boot crash recovery**: kill orphan + mark `interrupted` + `start_task` retry (no re-attach); jittered + semaphore-bounded.

### F12: Workflows Viewer (read-only)

- **Priority:** 12
- **Phase:** 4 — Authoring (read-only)
- **Status:** [ ] Not started
- **Depends on:** F1, F6
- **Blocks:** None
- **User Stories:** US-26
- **Tasks:** T106–T110
- **PRD Reference:** §5.8 / FR-07-1v (read-only viewer), N7 (full authoring deferred)
- **Key Deliverables:**
  - `GET /workflows`, `GET /workflows/{id}` via `list_components`/`inspect_component`/`preview_execution_plan`.
  - Viewer UI: list built-in + registered components, pipeline summary (stages/pauses/budget), read-only YAML view.
  - Editing disabled with a "coming in v1.1" note; on-disk + registered custom components appear and are runnable.

### F13: Concurrency & Cost Governance

- **Priority:** 13
- **Phase:** 5 — Scale & ship
- **Status:** [ ] Not started
- **Depends on:** F11
- **Blocks:** F14
- **User Stories:** US-27, US-28
- **Tasks:** T111–T118
- **PRD Reference:** §8.2 (bounded concurrency + aggregate admission + loop observability), NFR-SCALE-1, NFR-COST-1 (capability-aware), §7.2 (Codex timeout-only)
- **Key Deliverables:**
  - Bounded concurrency (`asyncio.Semaphore(max_concurrent_runs)`) + optional per-state caps.
  - Aggregate-resource admission (summed memory + daily spend caps).
  - Capability-aware enforcement: hard budget+turns+timeout for Claude; **timeout-only for Codex** (branch on `supports_budget`/`supports_max_turns`), surfaced in launch UI.
  - Loop self-observability gauges + heartbeat; non-blocking loop (DB writes off-loop, batched).

### F14: Hardening & Release

- **Priority:** 14
- **Phase:** 5 — Scale & ship
- **Status:** [ ] Not started
- **Depends on:** F13
- **Blocks:** None
- **User Stories:** US-23 (security verification), plus cross-cutting
- **Tasks:** T119–T126
- **PRD Reference:** NFR-A11Y-1, NFR-OBS-1 (structured logs + audit), §8.6 (audit log, image digest/scan), §13 (acceptance/test matrix), §8.8 (`docker compose up`)
- **Key Deliverables:**
  - Accessibility pass (icon+label state, AA contrast, keyboard nav).
  - Structured logs (OTel-compatible schema; full OTel deferred) + audit log.
  - Image digest pinning + SBOM scan; backup verified.
  - End-to-end happy-path + resilience + security test suites (PRD §13 acceptance tests); `docker compose up` docs; README.

## Feature → PRD coverage check

Every PRD goal G1–G9 and screen 01–07 + Settings maps to a feature: G1→F5; G2→F6; G3→F7; G4→F8; G5→F9; G6→F10; G7→F12; G8→F11/F13; G9→F1/F14; Settings→F5/F14. NFR-SEC→F3/F9/F14; NFR-COST→F13; NFR-REL→F11; NFR-PERF/SCALE→F8/F13. No PRD non-goal (N1–N8) is covered by any feature.
