# DKMV Platform — User Stories

## Summary

28 user stories across 7 categories, derived from the PRD (`docs/design_docs/platform/PRD_dkmv_platform_v1.md`) and the design prototype. Personas: **Solo dev** (the only v1 user persona, PRD §3) and **Implementer** (the developer building the platform — for infrastructure stories). Acceptance criteria are written as observable checks (commands, outputs, tests) per guide H9; for AI agents they are mandates, not suggestions (H-"mandate, don't suggest").

## Traceability Matrix

| US ID | Title | Feature | Task(s) | Status |
|-------|-------|---------|---------|--------|
| US-01 | Scaffold the platform repo | F1 | T010–T013 | [ ] |
| US-02 | Drive the engine programmatically | F1 | T014–T017 | [ ] |
| US-03 | Durable, queryable run state | F2 | T018–T025 | [ ] |
| US-04 | Isolate & secure agent execution | F3 | T026–T032 | [ ] |
| US-05 | Connect GitHub with a PAT | F4 | T033–T035 | [ ] |
| US-06 | Import a repo's issues | F4 | T036–T039 | [ ] |
| US-07 | Track work via `agent:*` labels | F4 | T040–T042 | [ ] |
| US-08 | Stay within GitHub rate limits | F4 | T043–T044 | [ ] |
| US-09 | Onboard & pick a project | F5 | T045–T049 | [ ] |
| US-10 | See issues on a board | F6 | T050–T055 | [ ] |
| US-11 | Navigate the app | F6 | T056–T058 | [ ] |
| US-12 | Read an issue | F7 | T059–T061 | [ ] |
| US-13 | Assign a workflow + agent | F7 | T062–T064 | [ ] |
| US-14 | Launch a run safely | F7 | T065–T067 | [ ] |
| US-15 | Stream live run events | F8 | T068–T072 | [ ] |
| US-16 | See correct live cost/turns | F8 | T073–T075 | [ ] |
| US-17 | Watch & control a run | F8 | T076–T079 | [ ] |
| US-18 | Approve a paused decision | F9 | T080–T084 | [ ] |
| US-19 | Never lose money to a hung pause | F9 | T085–T086 | [ ] |
| US-20 | Review run history | F10 | T088–T091 | [ ] |
| US-21 | Understand spend | F10 | T092–T095 | [ ] |
| US-22 | Recover cleanly after a crash | F11 | T100–T103 | [ ] |
| US-23 | Trust the security posture | F3, F14 | T029–T032, T123 | [ ] |
| US-24 | Gate irreversible actions | F9 | T087 | [ ] |
| US-25 | Retry failed runs without duplicates | F11 | T096–T099 | [ ] |
| US-26 | Browse workflows | F12 | T106–T110 | [ ] |
| US-27 | Run several issues at once within budget | F13 | T111–T115 | [ ] |
| US-28 | Keep Codex runs from running away | F13 | T116–T118 | [ ] |

---

## Stories by Category

### Foundation (US-01 through US-04)

#### US-01: Scaffold the platform repo

> As an implementer, I want a runnable `platform/` repo skeleton so I can build the backend and frontend in one place.

**Acceptance Criteria:**
- [ ] `platform/` contains `backend/` (FastAPI app), `frontend/` (Vite), `docker-compose.yml`, `Dockerfile.backend`, `Dockerfile.frontend`, `pyproject.toml`, `alembic/`.
- [ ] `pip install -e ../dkmv` succeeds; `python -c "import dkmv.runtime"` works in the backend env (Python ≥ 3.12).
- [ ] `docker build -t dkmv-sandbox:latest dkmv/images/` step is documented in the README and runs.
- [ ] `docker compose up` starts backend + frontend; the API responds on `127.0.0.1`.

**Feature:** F1 | **Tasks:** T010–T013 | **Priority:** Must-have

#### US-02: Drive the engine programmatically

> As an implementer, I want a `RunService` that wraps `EmbeddedRuntime` so the API never shells the CLI.

**Acceptance Criteria:**
- [ ] `RunService` constructs `EmbeddedRuntime(RuntimeConfig(...), output_dir=<platform-owned>)`.
- [ ] `RunService.start(...)` returns a `RunHandle`; `get_capabilities()`/`preflight_check(...)` are exposed.
- [ ] `GET /api/v1/preflight` returns the `get_capabilities()` checks (GitHub/Anthropic/Docker image).
- [ ] No code path invokes the `dkmv` CLI; integration test asserts a run completes via the embedded API against a throwaway repo.

**Feature:** F1 | **Tasks:** T014–T017 | **Priority:** Must-have

#### US-03: Durable, queryable run state

> As an implementer, I want an event-sourced SQLite store so run state survives restarts and dashboards are queryable.

**Acceptance Criteria:**
- [ ] Schema (`projects, issues, runs, run_stages, events, pause_decisions, run_totals, settings, secrets`) created via Alembic with indexes, `ON DELETE CASCADE`, `foreign_keys=ON`.
- [ ] Connections set `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout≥5000`; all writes use `BEGIN IMMEDIATE` through a single serialized writer task.
- [ ] `runs.id` is a platform UUID; `engine_run_id` is a separate non-unique column; `idempotency_key` is UNIQUE.
- [ ] `events` is append-only with a monotonic id; `spend` is computed as a projection (last-cumulative per `(run_id, task_index)`, Codex excluded), not a hand-maintained table.
- [ ] A load test of 5 concurrent writers × ~4 Hz appends produces **zero** `database is locked` errors.

**Feature:** F2 | **Tasks:** T018–T025 | **Priority:** Must-have

#### US-04: Isolate & secure agent execution

> As a solo dev, I want every agent run sandboxed and network-restricted so an injected prompt can't exfiltrate my credentials.

**Acceptance Criteria:**
- [ ] Runs execute under the `runsc` (gVisor) runtime by default; a documented opt-in + warning exists if `runsc` is unavailable (OQ-6).
- [ ] The sandbox cannot reach a non-allowlisted domain (egress denied + logged); only GitHub + model APIs are reachable.
- [ ] The injected GitHub token is repo-scoped (cannot push to a different repo) with ≤1 hr TTL.
- [ ] The backend reaches Docker through a brokered socket (proxy/rootless/Sysbox), not a raw mount.
- [ ] No secret value appears in logs or the `events` table.

**Feature:** F3, F14 | **Tasks:** T026–T032 | **Priority:** Must-have

### GitHub Integration (US-05 through US-08)

#### US-05: Connect GitHub with a PAT

> As a solo dev, I want to paste a fine-grained PAT so the platform can read my issues and manage `agent:*` labels.

**Acceptance Criteria:**
- [ ] The connect screen lists the four required permissions (`issues:write`, `pull_requests:write`, `contents:write`, `metadata:read`) scoped to one repo.
- [ ] `GET /repos` lists the token's repos with `{org, name, lang, langColor, private, updated, issues}`.
- [ ] Preflight verifies **effective write permission** on the selected repo, not just token presence.
- [ ] No GitHub App registration, private key, or webhook endpoint is required (PAT-only, poll-only).

**Feature:** F4 | **Tasks:** T033–T035 | **Priority:** Must-have

#### US-06: Import a repo's issues

> As a solo dev, I want my repo's issues imported onto the board so I can act on them.

**Acceptance Criteria:**
- [ ] `POST /projects/{repo}/sync` imports issues via a paginated GraphQL board read (issues + labels + linked PRs).
- [ ] A `since`/cursor is persisted for incremental polls; the Done column is bounded to a window.
- [ ] Issues map to the six board columns per §5.3.1; the four `agent:*` labels are created on connect if absent.
- [ ] `GET /repos/{repo}/issues` returns the `ISSUES` shape with the derived `state`.

**Feature:** F4 | **Tasks:** T036–T039 | **Priority:** Must-have

#### US-07: Track work via `agent:*` labels

> As a solo dev, I want board state reflected as `agent:*` labels so it's visible on GitHub too.

**Acceptance Criteria:**
- [ ] `set_agent_state(repo, num, target|none)` uses `PUT .../labels` replace-all and guarantees at most one `agent:*` label (single-occupancy).
- [ ] Dragging Backlog↔Queued calls `POST /issues/{num}/agent-state` and the label changes on GitHub.
- [ ] For an issue with an active run, the DB run row is authoritative (the authority rule); label→column derivation governs only issues without an active run.
- [ ] State transitions are complete: In Review→Done on PR merge; closed/reopened handled; a failed run is demoted off `agent:in-progress`.

**Feature:** F4 | **Tasks:** T040–T042 | **Priority:** Must-have

#### US-08: Stay within GitHub rate limits

> As a solo dev, I want the platform to respect GitHub limits so my automation doesn't get throttled or 403'd.

**Acceptance Criteria:**
- [ ] All mutating GitHub calls go through a single serialized, token-bucket-paced write-queue.
- [ ] Secondary-limit 403 + `Retry-After` is handled distinctly from primary limits; `X-RateLimit-*` headroom is surfaced.
- [ ] Board reads use GraphQL with self-hashed caching (GraphQL has no ETag); REST polls use conditional requests.
- [ ] A simulated 403-secondary with `Retry-After` causes a backoff, not a crash or a storm.

**Feature:** F4 | **Tasks:** T043–T044 | **Priority:** Must-have

### Onboarding & Board (US-09 through US-11)

#### US-09: Onboard & pick a project

> As a solo dev, I want a guided connect→pick-repo→sync flow so I land on a populated board.

**Acceptance Criteria:**
- [ ] The flow advances `disconnected → connecting → picker → syncing → board`.
- [ ] The preflight box shows GitHub/Anthropic-key/Docker-image status from `get_capabilities()`.
- [ ] The app shell uses the ported design tokens, dark/indigo default theme, and a working router + EventSource client.
- [ ] Selecting a repo and "Open project" imports issues and routes to the board.

**Feature:** F5 | **Tasks:** T045–T049 | **Priority:** Must-have

#### US-10: See issues on a board

> As a solo dev, I want my issues as cards in columns by agent state so I have a control-plane home.

**Acceptance Criteria:**
- [ ] Six columns (Backlog/Queued/In Progress/Needs You/In Review/Done) render per §5.3.1 with counts.
- [ ] Issue cards show number, title, ~2 labels, workflow/agent chips if assigned, a live mini-meter if running, and a "⋯" menu.
- [ ] The aggregate strip shows in-progress / needs-you / spent-today / tokens (poll-driven, Codex-excluded spend).
- [ ] Empty, Populated, and Syncing states render.

**Feature:** F6 | **Tasks:** T050–T055 | **Priority:** Must-have

#### US-11: Navigate the app

> As a solo dev, I want a persistent sidebar and status so I can move between views and jump back to active runs.

**Acceptance Criteria:**
- [ ] Sidebar shows project switcher, "+ New run", nav (Board/Runs/Workflows/Settings), and a live status chip ("N running · $X · M needs you").
- [ ] The top bar shows a refresh affordance with "last synced" and a theme toggle.
- [ ] A paused run is unmistakable (amber dot + count) and clickable from any screen.
- [ ] State badges use one consistent palette everywhere (P5).

**Feature:** F6 | **Tasks:** T056–T058 | **Priority:** Must-have

### Run Lifecycle (US-12 through US-19)

#### US-12: Read an issue

> As a solo dev, I want to read the full issue so I can decide how to work it.

**Acceptance Criteria:**
- [ ] The issue detail renders title, number, author, markdown body, labels, and comments.
- [ ] If a run exists, an alert card (paused=amber / running=blue) links to the live run.
- [ ] "Open on GitHub" links out.

**Feature:** F7 | **Tasks:** T059–T061 | **Priority:** Must-have

#### US-13: Assign a workflow + agent

> As a solo dev, I want to pick a workflow and agent with sane defaults so launching is one decision.

**Acceptance Criteria:**
- [ ] The workflow picker lists built-ins (plan/dev/qa/docs/ship) with stages, pauses badge, est. cost/time.
- [ ] Agent is `auto|claude|codex`; "auto" resolves to the workflow default; model populated from engine adapter defaults.
- [ ] For Codex the budget/turn fields are hidden and the UI shows "time-bounded, not cost-bounded."
- [ ] Branch prefills `dkmv/issue-{num}-{slug}` and is editable.

**Feature:** F7 | **Tasks:** T062–T064 | **Priority:** Must-have

#### US-14: Launch a run safely

> As a solo dev, I want launching a run to be validated and idempotent so I don't double-spend.

**Acceptance Criteria:**
- [ ] `POST /runs` validates inputs (§8.10): branch regex, repo match, `validate_component`, `validate_agent_model`, and **rejects budget/turns for Codex** (400 `unsupported_for_agent`).
- [ ] The run row is inserted with a `UNIQUE` idempotency key (`issue+workflow+base_branch`) via `INSERT … ON CONFLICT DO NOTHING` under `BEGIN IMMEDIATE`; a duplicate returns 409.
- [ ] `POST /runs` returns `{run_id}` = the **platform UUID**; the issue moves to `agent:in-progress`.
- [ ] `EmbeddedRuntime.start(...)` is called with `on_pause` wired.

**Feature:** F7 | **Tasks:** T065–T067 | **Priority:** Must-have

#### US-15: Stream live run events

> As a solo dev, I want a live event feed so I can see what the agent is doing.

**Acceptance Criteria:**
- [ ] The sync `EventObserver.on_event` pushes via `loop.call_soon_threadsafe(queue.put_nowait, …)` (never bare/`create_task`/per-event `run_coroutine_threadsafe`).
- [ ] `GET /runs/{id}/events` streams SSE with a ~15 s heartbeat and `Cache-Control: no-cache` + `X-Accel-Buffering: no`.
- [ ] Reconnect with `Last-Event-ID` replays `id > last AND run_id` with **no gaps and no duplicates** (subscribe-before-read).
- [ ] The SSE request carries the auth token in an HttpOnly `SameSite=Strict` cookie — never in the URL.
- [ ] The Friendly/Raw toggle works; Raw renders `RuntimeEvent.data`.

**Feature:** F8 | **Tasks:** T068–T072 | **Priority:** Must-have

#### US-16: See correct live cost/turns

> As a solo dev, I want the cost meter to be accurate across multi-stage runs so I trust the number.

**Acceptance Criteria:**
- [ ] Run cost = sum of completed tasks' final `cost_usd` + latest within the active task, **deduped by `task_index`** (segment-sum, §8.3/§6.4).
- [ ] On a multi-stage `plan` run the meter climbs across stage boundaries to ~$12 and **never resets toward $0**.
- [ ] `task_completed`/`task_failed` events are never coalesced/dropped (meter-critical).
- [ ] Codex cost renders "—" (not $0.00) and is excluded from aggregates while tokens still count.

**Feature:** F8 | **Tasks:** T073–T075 | **Priority:** Must-have

#### US-17: Watch & control a run

> As a solo dev, I want meters, a stage tracker, and a Stop button so I stay in control.

**Acceptance Criteria:**
- [ ] Meters (elapsed, cost, tokens in/out, turns, progress) and a per-stage tracker render and update live.
- [ ] The run-config/sandbox/artifacts rail renders; artifacts appear as produced; a linked PR shows when present.
- [ ] Stop transitions the run (and uses `stop(force=True)` when paused).
- [ ] "Run a command in the container" performs a one-shot `execute_in_container` (not a PTY).

**Feature:** F8 | **Tasks:** T076–T079 | **Priority:** Must-have

#### US-18: Approve a paused decision

> As a solo dev, when a workflow pauses I want a clear decision card so I can steer it.

**Acceptance Criteria:**
- [ ] On pause, the platform writes a `pause_decisions` row, sets `agent:paused`, releases the run's concurrency slot, and emits `pause_requested`.
- [ ] The card renders the engine-authoritative options `{value, label, description?}`; the option whose `value == default` is marked "recommended."
- [ ] `POST /runs/{id}/answer` sends the chosen option **value**, resolves the decision **exactly once** (`UPDATE … WHERE status='pending'`), and the run resumes.
- [ ] A double-submit or a racing timeout cannot double-resolve (rowcount-guarded).

**Feature:** F9 | **Tasks:** T080–T084 | **Priority:** Must-have

#### US-19: Never lose money to a hung pause

> As a solo dev, I want a paused run to time out so an idle container never burns budget indefinitely.

**Acceptance Criteria:**
- [ ] Each pause has a UTC `timeout_at` (default 60 min) re-evaluated each reconcile tick (not an in-memory timer).
- [ ] On expiry the decision auto-resolves per policy (default auto-abort) with the same exactly-once guard, `resolved_by='timeout'`.
- [ ] While paused, the run does **not** occupy a `max_concurrent_runs` slot.
- [ ] UI copy never promises "resumes exactly where it left off."

**Feature:** F9 | **Tasks:** T085–T086 | **Priority:** Must-have

### History, Recovery & Authoring (US-20 through US-26)

#### US-20: Review run history

> As a solo dev, I want a sortable, filterable runs table so I can look back at past work.

**Acceptance Criteria:**
- [ ] `GET /runs` returns cursor-paginated rows filterable by workflow/agent/status; the table sorts on id/status/cost/turns/dur/started.
- [ ] A finished run opens read-only in the run view; `timed_out`→failed palette, `interrupted`→cancel palette.
- [ ] `GET /runs/{id}` returns the full detail shape (§8.9).
- [ ] The empty state renders ("No runs yet").

**Feature:** F10 | **Tasks:** T088–T091 | **Priority:** Must-have

#### US-21: Understand spend

> As a solo dev, I want accurate aggregate spend and a chart so I understand cost.

**Acceptance Criteria:**
- [ ] `GET /stats` returns total runs, success rate, total spend, tokens, agent-hours, daily spend series, rate-limit usage.
- [ ] Spend aggregates **exclude** $0-cost Codex runs (count their tokens) with a footnote.
- [ ] The spend chart and cards render from `run_totals`/active runs (not engine directory scans).
- [ ] The retry queue card shows attempt N/3 + backoff.

**Feature:** F10 | **Tasks:** T092–T095 | **Priority:** Must-have

#### US-22: Recover cleanly after a crash

> As a solo dev, I want the platform to recover after a restart without orphaning a money-spending container.

**Acceptance Criteria:**
- [ ] On SIGTERM the orchestrator drains: stops dispatch, `stop(force=True)`s live runs (containers stopped), marks the rest `interrupted`.
- [ ] On boot, non-terminal runs' orphan containers are **killed**, runs marked `interrupted`, and offered for retry (optionally `start_task=` last pushed stage).
- [ ] Boot recovery dispatch is jittered and semaphore-bounded.
- [ ] After a mid-run and a mid-pause restart, **no orphaned running container survives** (verified by `docker ps`).

**Feature:** F11 | **Tasks:** T100–T103 | **Priority:** Must-have

#### US-23: Trust the security posture

> As a solo dev, I want the web app itself locked down so a malicious page can't drive it.

**Acceptance Criteria:**
- [ ] The API/SSE bind to `127.0.0.1` and reject requests lacking the local token (401) and with a bad `Host`/`Origin` (403).
- [ ] State-changing POSTs require CSRF protection.
- [ ] The sandbox image is digest-pinned and SBOM-scanned.
- [ ] An audit log records run launches, token use, egress denials, and decision resolutions.

**Feature:** F3, F14 | **Tasks:** T029–T032, T123 | **Priority:** Must-have

#### US-24: Gate irreversible actions

> As a solo dev, I want to approve the PR push so an injected prompt can't silently open a PR.

**Acceptance Criteria:**
- [ ] A platform-injected approval checkpoint fires before the irreversible PR/branch push (reusing the HITL pause primitive, NFR-SEC-5).
- [ ] A run whose issue body contains an injected instruction still requires human approval before the push.
- [ ] The gate is documented as defense-in-depth, not prevention.

**Feature:** F9 | **Tasks:** T087 | **Priority:** Must-have

#### US-25: Retry failed runs without duplicates

> As a solo dev, I want retries to not open duplicate PRs so my repo stays clean.

**Acceptance Criteria:**
- [ ] Before a retry, the orchestrator detects an existing branch/PR for the issue (via `runs.pr_num`/branch) and resumes/skips rather than duplicates.
- [ ] Retries use capped exponential backoff (`min(10s·2^(n-1), 5 min)`), max 3 attempts, then the retry queue.
- [ ] A retry of an issue that already has an open PR creates **no** duplicate PR (test-verified).

**Feature:** F11 | **Tasks:** T096–T099 | **Priority:** Must-have

#### US-26: Browse workflows

> As a solo dev, I want to see the available workflows and what they do so I can choose well.

**Acceptance Criteria:**
- [ ] The Workflows viewer lists built-in + registered components (via `list_components`).
- [ ] Each shows a pipeline summary (ordered stages, per-stage budget, pause points, est. total) and a read-only YAML view.
- [ ] The qa example shows 3 stages / 1 pause / $2.00.
- [ ] Editing is disabled with a "coming in v1.1" note; a component authored on disk + registered appears and is runnable.

**Feature:** F12 | **Tasks:** T106–T110 | **Priority:** Must-have

### Scale & Governance (US-27, US-28)

#### US-27: Run several issues at once within budget

> As a solo dev, I want bounded concurrency so I can clear the backlog without OOMing my machine or overspending.

**Acceptance Criteria:**
- [ ] Dispatch is gated by `asyncio.Semaphore(max_concurrent_runs)` (default 3) + optional per-state caps.
- [ ] A run is admitted only if summed container memory ≤ `HOST_MEMORY_BUDGET` and summed daily spend ≤ `DAILY_SPEND_CAP`.
- [ ] Launching >3 issues runs only `max_concurrent_runs` at once; the rest queue and eventually complete.
- [ ] Loop self-observability gauges (tick duration, slots-in-use, queue depth) are emitted.

**Feature:** F13 | **Tasks:** T111–T115 | **Priority:** Must-have

#### US-28: Keep Codex runs from running away

> As a solo dev, I want Codex runs bounded even though they have no cost cap so they can't run forever.

**Acceptance Criteria:**
- [ ] Enforcement branches on the adapter's `supports_budget()`/`supports_max_turns()`.
- [ ] For Codex (both false), `timeout_minutes` is enforced as the sole guardrail and the launch UI says so.
- [ ] Codex workflows default to a tighter timeout than their nominal value.
- [ ] For Claude, budget + turns + timeout are all enforced as hard caps.

**Feature:** F13 | **Tasks:** T116–T118 | **Priority:** Must-have

---

## Coverage notes

- Every feature F1–F14 has ≥1 story. Every story has 3–7 acceptance criteria and traces to a feature + task range.
- Infrastructure-heavy features (F1, F2, F3, F11, F13) are covered by "implementer" stories per guide H6/H-infrastructure.
- No story covers a PRD non-goal (N1–N8): no multi-tenant/RBAC, no cloud execution, no full workflow-authoring UI (US-26 is read-only), no webhooks/App (US-05 is PAT-only), no OTel tracing.
