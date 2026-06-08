# DKMV Platform — Master Task List

## How to Use This Document

- Tasks are numbered `T010`–`T126` sequentially, grouped by phase (gaps left at phase boundaries for inserts).
- `[P]` = parallelizable with other `[P]` tasks in the same group (no shared files / no ordering dependency).
- Check off tasks as completed: `- [x] T010 …`.
- Dependencies noted as `(depends: T0NN, T0MM)`; `nothing` = no prerequisite within the build.
- Each phase has a detailed spec in `phaseN_*.md`. **Read the phase doc before implementing.**
- Source of truth: `docs/design_docs/platform/PRD_dkmv_platform_v1.md` (read-only). Design prototype: `docs/design_docs/platform/`.

## Progress Summary

- **Total tasks:** 117
- **Completed:** 0
- **In progress:** 0
- **Blocked:** 0
- **Remaining:** 117

| Phase | Tasks | Range | Feature(s) |
|---|---|---|---|
| 0 — Foundation | 23 | T010–T032 | F1, F2, F3 |
| 1 — GitHub + UI shell | 26 | T033–T058 | F4, F5, F6 |
| 2 — Run lifecycle | 29 | T059–T087 | F7, F8, F9 |
| 3 — Durability | 18 | T088–T105 | F10, F11 |
| 4 — Workflows viewer | 5 | T106–T110 | F12 |
| 5 — Scale & ship | 16 | T111–T126 | F13, F14 |

---

## Phase 0 — Foundation (depends: nothing)

> Detailed specs: [phase0_foundation.md](phase0_foundation.md)

### Task 0.1: Skeleton & Engine Bridge (F1)

- [ ] T010 Scaffold `platform/` repo (backend/frontend/compose/Dockerfiles/pyproject/alembic) (depends: nothing)
- [ ] T011 FastAPI app skeleton + typed settings/config surface (§8.8 env table) (depends: T010)
- [ ] T012 [P] Vite frontend skeleton + router + design-token port + theme + EventSource client (depends: T010)
- [ ] T013 docker-compose + Dockerfiles + `dkmv` editable install + documented `dkmv-sandbox` build (depends: T010, T011)
- [ ] T014 `RunService` wrapper over `EmbeddedRuntime` (construct from `RuntimeConfig`, platform `output_dir`) (depends: T011)
- [ ] T015 `GET /preflight` via `get_capabilities()` + API error-envelope/status conventions (§8.9) (depends: T014)
- [ ] T016 App access-control middleware: `127.0.0.1` bind + local token + `Host`/`Origin` validation + CSRF (depends: T011)
- [ ] T017 Integration test: a component runs end-to-end via `RunService` against a throwaway repo (depends: T014)

### Task 0.2: Persistence & Event Log (F2)

- [ ] T018 SQLite connection mgmt: WAL/`synchronous`/`busy_timeout`/`foreign_keys` pragmas + single serialized writer task (depends: T011)
- [ ] T019 Alembic setup + initial migration: all tables + indexes + FK `ON DELETE CASCADE` (depends: T018)
- [ ] T020 Repository layer for all tables (DB access seam, SQLite→Postgres) (depends: T019)
- [ ] T021 Event-log model + append API (monotonic `id`, append-only, batched) (depends: T020)
- [ ] T022 `run_totals` snapshot on completion + backup (`VACUUM INTO`) command (depends: T020)
- [ ] T023 `spend` projection (last-cumulative per `(run_id, task_index)`, Codex excluded) + daily/total views (depends: T021)
- [ ] T024 Idempotency-key claim insert helper (`INSERT … ON CONFLICT DO NOTHING` under `BEGIN IMMEDIATE`) (depends: T020)
- [ ] T025 Concurrency load test: 5 writers × ~4 Hz → zero `database is locked` (depends: T018, T021)

### Task 0.3: Sandbox Security & Execution (F3)

- [ ] T026 `Executor` interface + `LocalDockerExecutor` (wrap `RunService`/`EmbeddedRuntime` + local Docker) (depends: T014)
- [ ] T027 gVisor (`runsc`) default runtime + documented weaker-isolation opt-in/warning (OQ-6) (depends: T026)
- [ ] T028 Brokered Docker socket (proxy/rootless/Sysbox) wiring (depends: T026)
- [ ] T029 Egress allowlist enforcement (network-layer, pinned DNS, GitHub+model only) (depends: T026)
- [ ] T030 Encrypted `SecretStore` + file-mount injection + repo-scoped ≤1 hr token (depends: T011)
- [ ] T031 Redact-before-persist in the event/log pipeline (secret patterns) (depends: T021, T030)
- [ ] T032 Security baseline tests (egress denial, no-secret-in-log, Host/CSRF reject, token scope) (depends: T027, T028, T029, T030, T031)

---

## Phase 1 — GitHub + UI shell (depends: Phase 0)

> Detailed specs: [phase1_github_board.md](phase1_github_board.md)

### Task 1.1: GitHub Integration (F4)

- [ ] T033 `GitHubClient` interface + fine-grained PAT auth + secret storage (depends: T030)
- [ ] T034 `GET /repos` (list the token's repos) (depends: T033)
- [ ] T035 Effective-write-permission preflight on the selected repo (depends: T033)
- [ ] T036 GraphQL board read (issues+labels+linked PRs) + pagination + `since`/cursor + Done window (depends: T033)
- [ ] T037 `POST /projects/{repo}/sync` (import issues into DB cache) (depends: T036, T020)
- [ ] T038 `GET /repos/{repo}/issues` (derived `state` per §5.3.1) (depends: T037)
- [ ] T039 Create the four `agent:*` labels on connect (depends: T033)
- [ ] T040 `set_agent_state` (PUT replace-all, single-occupancy, precedence) + `POST /issues/{num}/agent-state` (depends: T043)
- [ ] T041 Label→column derivation + authority rule (active-run DB row > label) (depends: T038, T040)
- [ ] T042 State-machine completeness: In Review→Done (PR merged), closed/reopened, failed-run demotion (depends: T041)
- [ ] T043 Serialized token-bucket write-queue for all mutating GitHub calls (depends: T033)
- [ ] T044 Secondary-limit (80/min) + `Retry-After` handling; `X-RateLimit-*` surfacing; GraphQL hash-cache (depends: T043, T036)

### Task 1.2: Connect & Onboarding (F5)

- [ ] T045 Connect flow state machine UI (`disconnected→connecting→picker→syncing`) (depends: T012)
- [ ] T046 PAT entry screen (lists the 4 permissions) + `POST /connect/github` (depends: T045, T033)
- [ ] T047 Repo picker UI + "What we'll do" card + Open project → sync (depends: T046, T034, T037)
- [ ] T048 [P] Preflight box UI from `GET /preflight` (depends: T045, T015)
- [ ] T049 App shell finalize: nav routes, EventSource client, theme persistence (depends: T012)

### Task 1.3: Board & Navigation (F6)

- [ ] T050 Global chrome: sidebar (project switcher, +New run, nav, live status chip) (depends: T049)
- [ ] T051 [P] Top bar (refresh/last-synced, theme toggle, avatar) + breadcrumbs (depends: T049)
- [ ] T052 Board columns + label→column rendering (§5.3.1) (depends: T050, T038)
- [ ] T053 [P] Issue card component (labels, chips, live mini-meter, ⋯ menu) (depends: T052, T058)
- [ ] T054 [P] Aggregate strip (poll-driven; Codex-excluded spend) (depends: T052)
- [ ] T055 Drag Backlog↔Queued → `POST /issues/{num}/agent-state` (depends: T052, T040)
- [ ] T056 Board states (Populated/Empty/Syncing) + filter bar (depends: T052)
- [ ] T057 Live status chip wiring (poll active runs; paused amber count) (depends: T050)
- [ ] T058 [P] Shared state-badge palette component (consistent everywhere) (depends: T049)

---

## Phase 2 — Run lifecycle (depends: Phase 1)

> Detailed specs: [phase2_run_lifecycle.md](phase2_run_lifecycle.md)

### Task 2.1: Run Launch (F7)

- [ ] T059 `GET /issues/{num}` detail (body markdown, labels, comments) (depends: T038)
- [ ] T060 Issue detail UI (markdown renderer, labels, comments) (depends: T059, T049)
- [ ] T061 [P] Existing-run alert card (paused/running variants) (depends: T060)
- [ ] T062 Run panel UI: workflow picker (built-ins) + stages/pauses/est (depends: T060, T106)
- [ ] T063 Agent/model resolution (auto→workflow.agent; `validate_agent_model`; Codex hides budget/turns) (depends: T062)
- [ ] T064 [P] Branch field + advanced guardrails (collapsed) + est line (depends: T062)
- [ ] T065 `POST /runs` validation (§8.10) incl. reject budget/turns for Codex (depends: T024, T063)
- [ ] T066 `POST /runs` claim-lock insert + `EmbeddedRuntime.start` + return platform UUID; move issue→`in-progress` (depends: T065, T026, T040)
- [ ] T067 `GET /runs` + `GET /runs/{id}` baseline shape (§8.9) (depends: T020)

### Task 2.2: Live Run Streaming & Observability (F8)

- [ ] T068 Sync→async observer bridge (`call_soon_threadsafe`) + per-run bounded queue + slow-consumer policy (depends: T066, T021)
- [ ] T069 Event pump: batch-append to `events` + update `run_stages`/meters + fan-out (depends: T068, T023)
- [ ] T070 SSE endpoint `GET /runs/{id}/events` (sse-starlette, heartbeat, anti-buffering headers) (depends: T069)
- [ ] T071 SSE auth via HttpOnly `SameSite=Strict` cookie (token never in URL) (depends: T070, T016)
- [ ] T072 Resumable replay (`Last-Event-ID`: subscribe-before-read, `id>last AND run_id`, dedup) + PauseCard rehydration (depends: T070)
- [ ] T073 Segment-sum meter computation (dedup by `task_index`; `task_completed` meter-critical) (depends: T069)
- [ ] T074 [P] Codex cost "—"/exclusion in the live meter (depends: T073)
- [ ] T075 Live-run meters row UI (elapsed/cost/tokens/turns/progress) (depends: T070, T073)
- [ ] T076 [P] Stage tracker UI (per-stage status/cost/turns/dur) (depends: T070)
- [ ] T077 [P] Event feed UI (Friendly/Raw toggle, search) (depends: T070)
- [ ] T078 [P] Run-config/sandbox/artifacts rail + linked PR (depends: T067)
- [ ] T079 Stop control (force when paused) + one-shot exec (`execute_in_container`) (depends: T075)

### Task 2.3: Human-in-the-Loop (F9)

- [ ] T080 `on_pause` bridge: write `pause_decisions`, set `agent:paused`, release slot, emit `pause_requested`, await keyed event (depends: T066, T020)
- [ ] T081 `POST /runs/{id}/answer` resolve-exactly-once (`UPDATE … WHERE status='pending'`) + resume engine + `decision` event (depends: T080)
- [ ] T082 Decision card UI (engine-authoritative options `{value,label,description?}`; recommended=`default`) (depends: T075, T080)
- [ ] T083 Send chosen option **value**; Ship-as-is/Abort set `skip_remaining` (depends: T082, T081)
- [ ] T084 [P] Needs-You board treatment + "Review decision" CTA wiring (depends: T080)
- [ ] T085 Pause timeout: UTC `timeout_at` + minimal reconcile auto-resolve hook (default auto-abort) (depends: T080)
- [ ] T086 Slot release/reacquire accounting around pause (depends: T080)
- [ ] T087 PR-push approval gate (NFR-SEC-5) reusing the pause primitive (depends: T080)

---

## Phase 3 — Durability (depends: Phase 2)

> Detailed specs: [phase3_durability.md](phase3_durability.md)

### Task 3.1: Runs History & Analytics (F10)

- [ ] T088 `GET /runs` filters + cursor pagination (depends: T067)
- [ ] T089 `GET /runs/{id}` full detail (config/sandbox/artifacts/pr/stages) (depends: T067, T078)
- [ ] T090 Runs table UI (sortable/filterable) + read-only finished-run view (depends: T088, T075)
- [ ] T091 [P] Status palette mapping incl. `timed_out`/`interrupted`; empty state (depends: T090, T058)
- [ ] T092 `GET /stats` (aggregates from `run_totals` + active; Codex-excluded) (depends: T023)
- [ ] T093 [P] Aggregate cards + spend-chart UI (depends: T092)
- [ ] T094 [P] Rate-limit health row UI (depends: T044, T092)
- [ ] T095 `GET /retry-queue` + retry-queue card UI (depends: T097)

### Task 3.2: Orchestrator — Retry/Reconcile/Recovery (F11)

- [ ] T096 Orchestrator tick loop skeleton (poll candidates → dispatch) + basic tick gauges (depends: T066)
- [ ] T097 Retry scheduler: capped exponential backoff, ≤3 attempts → retry queue (depends: T096)
- [ ] T098 Idempotent retry: detect existing branch/PR before re-dispatch (depends: T097, T042)
- [ ] T099 [P] `POST /runs/{id}/retry` (depends: T097)
- [ ] T100 Graceful drain on SIGTERM (stop containers, mark `interrupted`) (depends: T066)
- [ ] T101 Boot crash recovery: kill orphan + mark `interrupted` + `start_task` retry; jittered + semaphore-bounded (depends: T100, T097)
- [ ] T102 Reconciliation: stall detection + label refresh (authority rule) + orphan-container sweep (depends: T096, T041)
- [ ] T103 UTC-persisted deadlines (backoff/`timeout_at`/stall) re-evaluated per tick (survive suspend) (depends: T096)
- [ ] T104 Wire pause-timeout auto-resolve into reconcile (from T085) (depends: T102, T085)
- [ ] T105 Resilience tests (kill mid-run + mid-pause → no orphan; idempotent retry → no dup PR) (depends: T101, T098, T104)

---

## Phase 4 — Workflows viewer (depends: Phase 0; UI depends: Phase 1)

> Detailed specs: [phase4_workflows_viewer.md](phase4_workflows_viewer.md)

### Task 4.1: Workflows Viewer (F12)

- [ ] T106 `GET /workflows` + `GET /workflows/{id}` (`list_components`/`inspect_component`/`preview_execution_plan`) (depends: T014)
- [ ] T107 Workflows list UI (depends: T106, T049)
- [ ] T108 [P] Pipeline-summary component (stages/pauses/budget/est) (depends: T107)
- [ ] T109 [P] Read-only YAML view + "authoring coming in v1.1" note (depends: T107)
- [ ] T110 Registered-custom-component appears + runnable test (depends: T106, T066)

> Note: T106 is also a dependency of T062 (run panel needs the workflow list). Build T106 early (it only needs T014); the rest of Phase 4 UI can follow Phase 1.

---

## Phase 5 — Scale & ship (depends: Phase 3)

> Detailed specs: [phase5_scale_ship.md](phase5_scale_ship.md)

### Task 5.1: Concurrency & Cost Governance (F13)

- [ ] T111 Bounded concurrency: `Semaphore(max_concurrent_runs)` + per-state caps in dispatch (depends: T096)
- [ ] T112 Aggregate-resource admission (summed memory + daily-spend caps) (depends: T111, T023)
- [ ] T113 [P] Non-blocking loop: DB writes off-loop/executor + batched appends (depends: T096, T018)
- [ ] T114 [P] Loop self-observability gauges + heartbeat (full) (depends: T096)
- [ ] T115 Concurrency tests (>3 issues → only N at once; admission enforced) (depends: T111, T112)
- [ ] T116 Capability-aware enforcement: hard caps for Claude (budget+turns+timeout) (depends: T066)
- [ ] T117 Codex timeout-only enforcement + tighter default Codex timeout + launch-UI copy (depends: T116, T063)
- [ ] T118 Cost-governance tests (Codex timeout-bounded; Claude budget-capped) (depends: T116, T117)

### Task 5.2: Hardening & Release (F14)

- [ ] T119 [P] Accessibility pass (icon+label state, AA contrast, keyboard nav) (depends: T090)
- [ ] T120 [P] Structured logging (OTel-compatible schema) across the backend (depends: T096)
- [ ] T121 [P] Image digest pinning + SBOM scan in the build (depends: T013)
- [ ] T122 [P] Backup verification + restore doc (depends: T022)
- [ ] T123 Audit log (launches, token use, egress denials, decisions) (depends: T031, T080)
- [ ] T124 End-to-end happy-path test suite (PRD §13 acceptance tests) (depends: T105, T115, T118)
- [ ] T125 [P] `docker compose up` docs + platform README + setup guide (depends: T013)
- [ ] T126 Final integration verification + acceptance-matrix sign-off (depends: T124, T119, T123)

---

## Dependency sanity

- All edges point backward to earlier or same-phase tasks. The two cross-phase pulls are intentional and noted: **T062 (P2) depends on T106 (P4)** — build T106 during Phase 0/early (it only needs T014); and **T040 depends on T043** (write-queue before the label primitive), both within Phase 1.
- No task touches more than ~1–3 files' worth of coherent change; larger items (e.g., F4 GitHub) are split across T033–T044.
- Every task traces to a feature (F1–F14) and, via the feature, to user stories and PRD sections (see `features.md` / `user_stories.md`).
