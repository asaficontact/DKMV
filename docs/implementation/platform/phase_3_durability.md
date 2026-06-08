# Phase 3 — Durability: Runs History, Analytics & Orchestrator Recovery

> **Phase brief** for the DKMV Platform. Source of truth is the PRD (`docs/design_docs/platform/PRD_dkmv_platform_v1.md`); shared rules are in `docs/implementation/platform/_conventions.md` (INV-1..15). This brief is **locked** during implementation (`lock-prd.sh`). Read the PRD §citations inline — do not implement from this brief alone where it points at the PRD.

**PRD version:** v1.1
**PRD milestone:** M3 (History, analytics, retries, recovery)
**Features:** F10 (Runs History & Analytics), F11 (Orchestrator — Retry/Reconcile/Recovery)
**User stories:** US-20, US-21 (F10); US-22, US-25 (F11)
**Tasks:** T088–T105 (`tasks.md`)
**Timing:** Weeks 10–13
**ADRs:** ADR-P001 (in-process asyncio orchestrator; reconcile-from-Docker + DB, not workflow replay), ADR-P007 (best-effort-durable HITL; **no live-run re-attach** — kill+interrupt+`start_task` retry)

---

## 1. Phase goal

Turn the platform from "you can launch and watch one run" into "you can see every run you ever did, understand your spend, and trust that a laptop sleep or a `docker compose restart` will not orphan a money-spending container." After Phase 3 a solo dev can: open the Runs screen and see a sortable/filterable history table + a read-only view of any finished run; read aggregate cards (total runs, success rate, spend, tokens, agent-hours), a daily spend chart, and a rate-limit health row; see a retry queue with `attempt N/3 · backoff`; and — the load-bearing durability story — **kill the backend mid-run and mid-pause and have boot recovery kill the orphan container, mark the run `interrupted`, and offer a `start_task` retry, with idempotent retries that never open a duplicate PR.**

The load-bearing technical commitments of this phase:

- A **read** API over the Phase 0 `events`/`run_totals`/`spend` projection: `GET /runs` (filters + cursor pagination), `GET /runs/{id}` full detail (§8.9), `GET /stats` (Codex-excluded spend, FR-06-1a), `GET /retry-queue`.
- The history UI built to `history.jsx` + the §7.3 palette, with the **status palette mapping** that maps `timed_out`→failed palette and `interrupted`→cancel palette (INV-14, §6.5).
- The **orchestrator tick loop** (poll candidate issues → dispatch) with **UTC-persisted deadlines** (`backoff`/`timeout_at`/stall) re-evaluated each tick so they survive a laptop suspend, plus reconciliation under the **authority rule** (INV-11) and an orphan-container sweep.
- A **retry scheduler** (capped exponential backoff, ≤3 attempts → retry queue) that is **idempotent against side effects** (detect existing branch/PR via `runs.pr_num`/branch before re-dispatch — INV-5/§8.2, R-15).
- **Graceful drain** on SIGTERM and **boot crash recovery** that honors INV-10 / ADR-P007 / NFR-REL-1: **no re-attach**; kill orphan + mark `interrupted` + offer `start_task` retry; never bare-cancel a task without stopping its container.

---

## 2. Prerequisites (from Phase 2 — must be green before starting)

Phase 3 consumes the Phase 2 (M2) run lifecycle. Do not begin a slice until its prerequisites exist and pass:

- **Runs exist end-to-end** (F7, T059–T067): `POST /runs` claim-lock insert (UNIQUE idempotency key, INV-5), `EmbeddedRuntime.start(...)`, the `runs`/`run_stages` read model, and the baseline `GET /runs`/`GET /runs/{id}`. 3.1 extends these; it does not re-create the launch path.
- **Event log + `run_totals` + spend projection** (F2/F8, T018–T024, T068–T078): the append-only `events` table with monotonic `events.id`, the segment-sum meter (dedup by `task_index`, INV-7), the `run_totals` snapshot written at completion, and the `spend` **materialized projection** (last-cumulative-per-`(run_id, task_index)`, **Codex excluded**, INV-8). `GET /stats` and the spend chart read these — they NEVER run off the engine's O(N) `list_runs`/`get_stats` directory scans (§6.5 reconciliation rule).
- **Dispatch path + EmbeddedRuntime bridge** (F7/F8): each run is a tracked `asyncio.Task` wrapping `EmbeddedRuntime.start(...)` with the sync→async observer bridge (INV-12). The Phase-3 tick loop dispatches **through this existing path** (the `dispatch(run)` boundary, ADR-P001) — it does not introduce a second launch mechanism.
- **Pause bridge** (F9, T080–T087): `pause_decisions` rows with UTC `timeout_at`, resolve-exactly-once guard (INV-9), slot-release on pause, and `RunHandle.stop(force=True)` for stop-during-pause. 3.4 wires the existing pause-timeout auto-resolve (T085) into the new reconcile tick.
- **Write-queue + `set_agent_state`** (F4, T040–T044): the single serialized, token-bucket-paced GitHub write-queue and the `PUT .../labels` replace-all primitive (INV-11). Reconcile's label refresh (3.3) routes **every** label change through this queue — it does not call GitHub directly.

If any prerequisite is missing, stop and finish Phase 2 first (per `CLAUDE.md` phase discipline).

---

## 3. Scope

### IN scope (this phase)

- **History read API** (F10 / §8.9, §5.7): `GET /runs` (filters `workflow`/`agent`/`status` + cursor pagination), `GET /runs/{id}` full detail (config/sandbox/artifacts/pr/stages), `GET /stats` (aggregates from `run_totals` + active runs, **Codex excluded** from spend), `GET /retry-queue`.
- **History UI** (F10 / §5.7, FR-06): runs table (sortable/filterable) + read-only finished-run view; aggregate cards + spend chart (Codex-excluded) + rate-limit health row + retry-queue card; empty state; the **status palette mapping** including `timed_out`→failed and `interrupted`→cancel.
- **Orchestrator tick loop** (F11 / §8.2): the fixed-cadence poll → dispatch tick + basic tick gauges; reconciliation (stall detection, GitHub-label refresh under the authority rule, orphan-container sweep); **UTC-persisted deadlines** re-evaluated each tick.
- **Retry** (F11 / §8.2): retry scheduler (capped exponential backoff, ≤3 attempts → retry queue); **idempotent retry** (detect existing branch/PR before re-dispatch); `POST /runs/{id}/retry`; wire pause-timeout auto-resolve into reconcile.
- **Recovery** (F11 / §8.2, NFR-REL-1, R-15): **graceful drain** on SIGTERM; **boot crash recovery** (kill orphan + mark `interrupted` + offer `start_task` retry; **no re-attach**; jittered + semaphore-bounded); resilience tests.

### OUT of scope (explicitly deferred)

- **Bounded concurrency, aggregate admission control, cost governance** (`asyncio.Semaphore(max_concurrent_runs)`, per-state caps, summed-memory + daily-spend admission, capability-aware budget/timeout enforcement, full loop self-observability gauges + heartbeat, non-blocking-loop off-loop DB writes) → **Phase 5** (F13, T111–T118). Phase 3's tick loop dispatches **serially within the existing single-PR-at-a-time / serialized-writer constraints**; it adds only *basic* tick gauges (tick duration, slots-in-use placeholder), not the full observability suite. Phase 3 honors the pause **slot-release** built in Phase 2 but does not introduce the concurrency *cap* logic — that is Phase 5.
- **Workflows viewer** (Screen 07, `GET /workflows`, pipeline summary, read-only YAML) → **Phase 4** (F12, T106–T110). Phase 3 does not build any `/workflows` endpoint or screen.
- **GitHub App + webhooks** (bot identity, HMAC-verified delivery, `expected_label_events` echo-suppression) → deferred / post-v1 (ADR-P004, §8.1). Reconcile's label refresh is **poll-mode** under the authority rule; do not add a webhook receiver.
- **True crash *resumption*** (re-attach an observer to a live container; component-level checkpointing to resume the suspended coroutine) → **engine asks** §11.5/§11.6, explicitly NOT in v1 (INV-10, R-15). Recovery is kill+interrupt+`start_task`-retry only.
- **Rate-limit *enforcement* / token-bucket internals** → already shipped in Phase 1 (F4 write-queue, T044). Phase 3 only **surfaces** the `X-RateLimit-*` / secondary-limit accounting in the FR-06-2 health row (read-only display).

---

## 4. Slices

Slice IDs are `3.k-name`. Each maps to a feature and PRD §. "Files" lists the primary edit surface used by the wave plan (no two same-wave slices share a file). Backend lives under `platform/backend/`, frontend under `platform/frontend/src/`.

### 3.1 — `3.1-history-api` (F10 / §8.9, §5.7)

**What:** the read-only history/analytics API over the Phase 0 event log + projections.

- `GET /runs` — paginated `RunSummary` rows (FR-06-4 columns: Run id, Issue, Workflow, Agent+model, Status, Cost, Turns, Duration, Started, PR) with filters `?workflow=&agent=&status=` and **cursor pagination** (`?limit<=100&cursor=` → `{ items, next_cursor }`, §8.9 / `_conventions.md`). Reads the `runs` read model, never the engine `list_runs` directory scan (§6.5).
- `GET /runs/{id}` — **full detail** per §8.9: `{ id (uuid), engine_run_id, repo, issue:{num,title}, workflow_id, agent, model, status (§6.3), branch, cost_usd|null, tokens_in, tokens_out, turns, duration_s|null, started_at, finished_at|null, pr:{num,title,checks}|null, error|null, stages:[RunStage], config:{...FR-04-5 keys}, sandbox:{image,mem,vcpu,health}, artifacts:[{name,size,live?}] }`. **Codex `cost_usd` = `null`** (rendered "—", FR-06-1a). This is the read-only finished-run source for 3.2's run view.
- `GET /stats` — `{ total_runs, success_rate, total_spend_usd, tokens, agent_hours, spend_series:[{date,usd}], rate_limits:{github,anthropic,openai} }` computed from `run_totals` + active runs via the SQL spend views (§6.5). **Codex `$0`-cost runs are excluded from `total_spend_usd` and `spend_series`** while their tokens/agent-hours count normally (FR-06-1a, INV-8). Success rate = `completed/(completed+failed)`.
- `GET /retry-queue` — `RetryEntry` rows `{id, issue, attempt, dueIn, lastError}` (PRD §6.1, `data.jsx RETRY_QUEUE`) sourced from the retry scheduler state (3.4). Until 3.4 lands, returns an empty list (the endpoint and shape ship here; the data is populated by 3.4).
- All endpoints inherit the app access-control middleware (INV-1) and emit the standard error envelope + status codes (§8.9: `404 run_not_found`, `400 validation_error`, cursor `next_cursor`).
- **Files:** `platform/backend/app/api/history.py` (`GET /runs`, `GET /runs/{id}`), `platform/backend/app/api/stats.py` (`GET /stats`), `platform/backend/app/api/retry_queue.py` (`GET /retry-queue`), `platform/backend/app/db/queries_history.py` (read queries over the repository layer).
- **Tasks:** T088, T089, T092 (and the endpoint half of T095).

### 3.2 — `3.2-history-ui` (F10 / §5.7, FR-06)

**What:** the Runs history & analytics screen, built to `history.jsx`.

- **Runs table** (`RunsHistory` in `history.jsx`): sortable on `id/status/cost/turns/dur/started` and filterable by `workflow/agent/status`; columns per FR-06-4; row click → the run view, **read-only for finished runs** (renders from `GET /runs/{id}`, no Stop/Retry controls beyond the failed-run "Retry now"). Reuses the Phase-1 `StateBadge`, `WfChip`, `AgentChip`.
- **Status palette mapping** (FR-06-5, §6.5, INV-14): map the engine `RunStatus` (`running|paused|completed|failed|cancelled|timed_out`) plus the platform-only `interrupted` to the §7.3 palette via `STATE_OF` (`components.jsx`): `timed_out` → **failed** palette + a "Timed out" label; **`interrupted` → cancel palette** + an "Interrupted" label (the prototype `STATE_OF` does not include `interrupted` — it is platform-only per §6.5 and MUST be added). State is conveyed by **icon + label**, never color alone.
- **Aggregate cards** (`StatCard` × 5, FR-06-1): Total runs, Success rate (`{completed} completed` sub, `--st-done` accent), Total spend (`--accent`), Tokens (`…k`), Agent-hours — all from `GET /stats`.
- **SpendChart** (daily bars, last bar `--accent`, total label, FR-06-1) — **Codex-excluded** spend with a small "excludes Codex (cost not reported)" footnote on the spend cards (FR-06-1a). Do **not** build spend math from the `data.jsx RUNS` Codex mock values (illustrative only, non-representative — §6.1/FR-06-1a note).
- **Rate-limit health row** (FR-06-2): "Rate limits healthy · Anthropic 38% · OpenAI 12% used this hour" + usage bar, from `GET /stats` `rate_limits` (the Phase-1 write-queue `X-RateLimit-*` accounting).
- **Retry-queue card** (`RetryQueue`, collapsible, amber/`--st-paused`, FR-06-3): rows `{id, issue, attempt N/3, dueIn, lastError}` from `GET /retry-queue`; a **Retry now** action posts `POST /runs/{id}/retry` (the endpoint ships in 3.4).
- **Empty state** (`RunsEmpty`, FR-06-5): "No runs yet · Run your first issue".
- **Files:** `platform/frontend/src/screens/History.tsx`, `platform/frontend/src/screens/RunDetail.tsx` (read-only finished-run view), `platform/frontend/src/components/StatCard.tsx`, `platform/frontend/src/components/SpendChart.tsx`, `platform/frontend/src/components/RetryQueue.tsx`, `platform/frontend/src/components/RunsTable.tsx`, `platform/frontend/src/components/StateBadge.tsx` (extend the palette map with `interrupted`→cancel), `platform/frontend/src/api/history.ts`.
- **Tasks:** T090, T091, T093, T094 (and the card half of T095).

### 3.3 — `3.3-orchestrator-tick` (F11 / §8.2)

**What:** the orchestrator core — tick loop + reconciliation + UTC-persisted deadlines.

- **Tick loop:** a long-lived `asyncio.Task` on a fixed cadence (`TICK_INTERVAL_S`, default 10s, §8.8): reconcile running runs → validate preflight → fetch candidate issues (one GraphQL board read, reusing the Phase-1 client) → sort (priority asc, then oldest `created_at`) → **dispatch through the existing `dispatch(run)` boundary** while slots remain (the *cap* itself is Phase 5; Phase 3 dispatches within the serialized constraints). Liveness comes from the **event stream**, not a per-container busy-poll; `get_container_status` is consulted only on suspected stall (§8.2).
- **Basic tick gauges:** emit tick duration + time-since-last-successful-tick + a loop heartbeat (the *full* self-observability suite — queue depth, dispatch latency, reconcile-action counters — is Phase 5 / T114; ship the minimal heartbeat here so a wedged loop is detectable).
- **Reconciliation (every tick), §8.2:**
  - **(a) Stall detection:** if no events for `STALL_TIMEOUT_S` (default 300s) → kill the container + schedule a retry (the retry *scheduler* is 3.4; 3.3 emits the stall signal and the kill).
  - **(b) GitHub-label refresh under the authority rule (INV-11):** for an issue with an **active run the DB `runs` row is authoritative** — a stray human label edit does not move the board; if a human moved the issue to a **terminal/non-active** state, stop the run (terminal → also clean workspace). All label changes route through the **Phase-1 serialized write-queue** (`set_agent_state` / `PUT .../labels` replace-all) — never a direct GitHub call, never `PATCH .../label`.
  - **(c) Orphan-container sweep:** containers labeled with a `run_id` whose `runs` row is terminal are killed.
- **UTC-persisted deadlines:** all deadlines (`backoff`, `timeout_at`, stall) are **UTC timestamps persisted in the DB and re-evaluated against `now()` each tick** — never in-memory `asyncio.sleep` timers — so they **survive a laptop sleep/suspend** (§8.2). 3.4's backoff and 3.5's drain deadline reuse this same evaluation.
- **Files:** `platform/backend/app/orchestrator/tick.py` (loop + dispatch call), `platform/backend/app/orchestrator/reconcile.py` (stall, label refresh, orphan sweep), `platform/backend/app/orchestrator/deadlines.py` (UTC persisted-deadline evaluation), `platform/backend/app/orchestrator/gauges.py` (basic tick gauges + heartbeat).
- **Tasks:** T096, T102, T103.

### 3.4 — `3.4-retry` (F11 / §8.2)

**What:** the retry scheduler + idempotent re-dispatch + the retry endpoint.

- **Retry scheduler:** on a transient failure (or a stall signal from 3.3), schedule a retry with **capped exponential backoff `delay = min(10s · 2^(attempt-1), 5min)`**; **max 3 attempts**, after which the run lands in the **retry queue** (FR-06-3, surfaced by 3.1's `GET /retry-queue`). Backoff `due_at` is a UTC persisted deadline re-evaluated by 3.3's tick (`deadlines.py`), so it survives suspend.
- **Idempotent retry (INV-5, R-15, §8.2 — binding):** **before re-dispatching, detect an existing branch/PR for the issue** (via `runs.pr_num` and/or the deterministic branch name) and **resume/skip rather than duplicate** — a blind retry would re-push commits or re-open a PR. A *retry* reuses the same `runs` row (same `idempotency_key = issue_num + workflow_id + base_branch`, not a body hash), never colliding into a second dispatch. Optionally retry with `start_task=<last completed stage>` (the engine reconstructs prior stage outputs from the pushed branch).
- `POST /runs/{id}/retry` (FR-06-3): enqueues a retry for a failed/`interrupted` run, returns `202`; idempotent (a second call while a retry is pending is a no-op, not a duplicate dispatch). On a run whose issue already has an **open PR**, the retry **resumes/skips and creates NO duplicate PR** (the AT-Recovery / §13 resilience bar).
- **Wire pause-timeout auto-resolve into reconcile (T104):** the Phase-2 pause `timeout_at` (default 60 min → auto-abort, INV-9) is evaluated by 3.3's reconcile tick using the same UTC-deadline path; on expiry it auto-resolves the `pause_decisions` row via the **exactly-once** guard (`UPDATE … WHERE status='pending'`, `resolved_by='timeout'`).
- **Files:** `platform/backend/app/orchestrator/retry.py` (scheduler + idempotent re-dispatch + branch/PR detection), `platform/backend/app/api/runs_retry.py` (`POST /runs/{id}/retry`), and a wire-in to `platform/backend/app/orchestrator/reconcile.py` for the pause-timeout auto-resolve (3.3's file — sequenced in a later wave, no same-wave collision).
- **Tasks:** T097, T098, T099, T104 (and the data half of T095).

### 3.5 — `3.5-recovery` (F11 / §8.2, NFR-REL-1, R-15 — INV-10)

**What:** graceful drain on SIGTERM + boot crash recovery + the resilience suite.

- **Graceful drain (SIGTERM), §8.2 — INV-10:** a `docker compose restart` is routine, and cancelling a run's `asyncio.Task` does **NOT** stop its container (it would be orphaned and keep spending). On SIGTERM the orchestrator: (1) **stops dispatching** new runs; (2) for each live run, calls **`RunHandle.stop(force=True)`** (cancels the task → the engine's `finally` stops the container) within a drain deadline; (3) marks any run it couldn't cleanly stop **`interrupted`** and records its container id for the boot sweep. **Never bare-cancel a run task without stopping its container.**
- **Boot crash recovery, §8.2 — INV-10, ADR-P007:** on boot, for each **non-terminal `runs` row**: **`docker kill` the orphaned container** (it is unfinishable and budget-burning), mark the run **`interrupted`**, and **offer retry** — optionally re-launching with `start_task=<last completed stage>` (only recovers stages whose outputs were committed/pushed; otherwise stays `interrupted`). **The code MUST NOT attempt to re-attach an observer to, or resume, a container started by a dead process** (the engine has no such API — R-15; `reconcile_stale_runs` only writes `cancelled` for dead containers; `replay_events` only reads persisted `stream.jsonl`). Recovery dispatch is **jittered and routed through the same semaphore** (reusing 3.4's retry path) to avoid a boot thundering-herd on Docker + the GitHub API.
- **Resilience tests (T105, §13 / AT-Recovery):**
  - Kill the backend **mid-run** and (separately) **mid-pause** → on boot the orphan container is killed (asserted via **`docker ps`** showing no surviving `run_id`-labeled container), the run is marked `interrupted`, and retry re-launches via `start_task` from the last pushed stage. **No orphaned money-spending container survives.**
  - **Idempotent retry → no duplicate PR:** a retry of an issue that already has an open PR does **NOT** create a second PR (uses 3.4's branch/PR detection).
- **Files:** `platform/backend/app/orchestrator/drain.py` (SIGTERM handler + drain loop), `platform/backend/app/orchestrator/recovery.py` (boot scan + kill-orphan + interrupt + offer-retry), a signal-handler registration in `platform/backend/app/main.py` (startup/shutdown hooks), and the resilience suite under `platform/backend/tests/`.
- **Tasks:** T100, T101, T105.

---

## 5. Wave plan

No two slices in the same wave edit the same file. Backend `app/api/*`, `app/orchestrator/*`, and frontend `src/*` are split per slice; the only cross-slice file (`orchestrator/reconcile.py`, created in 3.3, wired by 3.4) is touched in **different waves**.

| Wave | Slices | Rationale / dependency |
|---|---|---|
| **A** | `3.1-history-api` | First. Needs Phase-0/2 `events`/`run_totals`/`spend` + the baseline `runs` read model. Establishes the read endpoints (incl. the empty `GET /retry-queue` shape) that 3.2 renders and 3.4 populates. |
| **B** | `3.2-history-ui` **+** `3.3-orchestrator-tick` | Both depend on 3.1 and run **in parallel** — disjoint surfaces: 3.2 is frontend-only (`src/screens`, `src/components`, `src/api/history.ts`), 3.3 is backend-orchestrator-only (`app/orchestrator/*`). No shared file. |
| **C** | `3.4-retry` | After 3.3 (the tick loop + `deadlines.py` + `reconcile.py` must exist before the retry scheduler hooks backoff into the deadline path and the pause-timeout auto-resolve into reconcile). Note **T098 (idempotent re-dispatch) reuses T042** (the Phase-1 branch/PR/label state). |
| **D** | `3.5-recovery` | After 3.3 (orchestrator core) **and** 3.4 — boot recovery's `start_task` retry reuses 3.4's scheduler (**T101 depends on T097**), and the no-duplicate-PR resilience test exercises 3.4's idempotent re-dispatch (T098). |

Critical path: A → 3.3 (B) → 3.4 (C) → 3.5 (D). 3.2 (B) runs alongside 3.3–3.5 and only gates the F10 UI exit. Within Wave B the two slices never share a file (frontend vs. backend orchestrator).

---

## 6. Acceptance criteria (greppable, with PRD §citations)

Each criterion is verifiable by a grep/command + a test. Backend greps run under `platform/backend/`, frontend under `platform/frontend/src/`.

### F10 — Runs History & Analytics

- **AC-1 (3.1, §8.9 / §5.7).** `GET /runs` supports filters `workflow`/`agent`/`status` **and cursor pagination** (`?limit<=100&cursor=` → `{ items, next_cursor }`). `grep -rni "next_cursor\|cursor" platform/backend/app/api/history.py` non-empty; a test asserts a `limit`-bounded page returns a `next_cursor` and that each filter narrows the result set.
- **AC-2 (3.1, §8.9).** `GET /runs/{id}` returns the full detail shape (config/sandbox/artifacts/pr/stages); an unknown id returns `404 run_not_found` in the error envelope. `grep -rni "stages\|sandbox\|artifacts\|run_not_found" platform/backend/app/api/history.py` non-empty; a test asserts the detail body keys and the 404 code.
- **AC-3 (3.1, FR-06-1a — INV-8, binding).** `GET /stats` computes spend from `run_totals` + active runs and **excludes $0-cost Codex runs** from `total_spend_usd` and `spend_series` while counting their tokens/agent-hours. `grep -rni "codex" platform/backend/app/api/stats.py platform/backend/app/db/queries_history.py` shows the exclusion; a test with one Claude + one Codex completed run asserts `total_spend_usd` = Claude-only and `tokens` = both. Stats are NOT computed via the engine `list_runs`/`get_stats` directory scan: `grep -rn "list_runs\|get_stats" platform/backend/app/api/stats.py` is **empty** (§6.5).
- **AC-4 (3.1, FR-06-3 / FR-06-6).** `GET /retry-queue` returns `RetryEntry` rows `{id, issue, attempt, dueIn, lastError}` (PRD §6.1). A test asserts the shape; before 3.4 populates it the endpoint returns `{items: []}`.
- **AC-5 (3.2, §5.7 FR-06-4/5).** The runs table is sortable on `id/status/cost/turns/dur/started` and filterable by `workflow/agent/status`; row click opens the **read-only** finished-run view (no Stop control on a completed run). A render test asserts a sort toggles order and a filter narrows rows.
- **AC-6 (3.2, FR-06-5 / §6.5 — INV-14, binding).** The status palette maps **`timed_out` → failed palette** ("Timed out" label) and **`interrupted` → cancel palette** ("Interrupted" label). `grep -rni "timed_out\|interrupted" platform/frontend/src/components/StateBadge.tsx` non-empty; a test asserts `timed_out` renders the `s-failed`/failed class and `interrupted` renders the `s-cancel`/cancel class, each with an **icon + label** (not color alone).
- **AC-7 (3.2, FR-06-1 / FR-06-1a — INV-8).** Aggregate cards (Total runs / Success rate / Total spend / Tokens / Agent-hours) + the SpendChart render from `GET /stats`; the **spend card + chart exclude Codex** and show the "excludes Codex (cost not reported)" footnote. `grep -rni "excludes Codex\|cost not reported" platform/frontend/src` non-empty; the chart's last bar uses `--accent` (DESIGN_FIDELITY).
- **AC-8 (3.2, FR-06-2 / FR-06-3).** The rate-limit health row renders Anthropic/OpenAI usage from `GET /stats.rate_limits`; the retry-queue card renders `attempt N/3 · due in {dueIn} · {lastError}` and its **Retry now** posts `POST /runs/{id}/retry`. A render test asserts both.
- **AC-9 (3.2, FR-06-5).** The empty state renders "No runs yet" + "Run your first issue". `grep -rn "No runs yet\|Run your first issue" platform/frontend/src` non-empty.

### F11 — Orchestrator: Retry / Reconcile / Recovery

- **AC-10 (3.3, §8.2).** A single fixed-cadence tick loop (`TICK_INTERVAL_S`, default 10s) polls candidate issues and dispatches **through the existing `dispatch(run)` boundary** (ADR-P001) — it does not introduce a second launch path. `grep -rni "TICK_INTERVAL\|async def tick\|while " platform/backend/app/orchestrator/tick.py` non-empty; a test runs one tick against a seeded candidate and asserts exactly one dispatch.
- **AC-11 (3.3, §8.2 — INV-11, binding).** Reconcile's label refresh honors the **authority rule** (active-run DB row > label) and routes **every** label change through the Phase-1 serialized write-queue (`set_agent_state` / `PUT .../labels` replace-all). `grep -rn "set_agent_state\|write_queue" platform/backend/app/orchestrator/reconcile.py` non-empty; `grep -rni "PATCH.*/label" platform` is **empty**. A test feeds a running issue with a stray human label edit and asserts the DB row wins (board state unchanged); a separate test asserts a human move to a terminal state stops the run.
- **AC-12 (3.3, §8.2).** Reconcile detects a stall (no events for `STALL_TIMEOUT_S`, default 300s) → kills the container + signals a retry; and sweeps orphan containers whose `run_id`'s `runs` row is terminal. `grep -rni "STALL_TIMEOUT\|stall\|orphan" platform/backend/app/orchestrator/reconcile.py` non-empty; tests cover both paths.
- **AC-13 (3.3, §8.2 — binding).** Deadlines (`backoff`, `timeout_at`, stall) are **UTC timestamps persisted in the DB and re-evaluated against `now()` each tick**, NOT in-memory `asyncio.sleep` timers — so they survive a laptop suspend. `grep -rni "sleep(" platform/backend/app/orchestrator/deadlines.py` is **empty** (no deadline is implemented as a sleep timer); a test advances a frozen clock past a persisted `due_at` and asserts the tick fires the deadline (simulating a suspend gap).
- **AC-14 (3.4, §8.2).** The retry scheduler uses capped exponential backoff **`min(10s·2^(attempt-1), 5min)`**, **max 3 attempts → retry queue**. `grep -rniE "2 ?\*\*|2\^|min\(.*300|5 ?\* ?60|max_attempts|attempt" platform/backend/app/orchestrator/retry.py` non-empty; a test asserts the backoff sequence `10s, 20s, 40s…` capped at 300s and that the 4th failure lands in the retry queue.
- **AC-15 (3.4, §8.2 — INV-5, R-15, binding).** **Idempotent retry:** before re-dispatch the scheduler detects an existing branch/PR (via `runs.pr_num` / branch) and resumes/skips rather than duplicating; a retry reuses the same `runs` row (same `idempotency_key`). `grep -rni "pr_num\|existing.*branch\|idempotenc" platform/backend/app/orchestrator/retry.py` non-empty. **A test retries an issue that already has an open PR and asserts NO duplicate PR is created** (the §13 resilience bar).
- **AC-16 (3.4, FR-06-3 / §8.9).** `POST /runs/{id}/retry` enqueues a retry (`202`) and is itself idempotent (a second call while a retry is pending is a no-op, not a second dispatch). A test asserts the `202` and that a double-call yields one queued retry.
- **AC-17 (3.4, §8.5 — INV-9).** The pause `timeout_at` (default 60 min → auto-abort) is re-evaluated by the reconcile tick and auto-resolved via the **exactly-once** guard (`resolved_by='timeout'`). `grep -rni "timeout_at\|resolved_by\|timeout" platform/backend/app/orchestrator/reconcile.py platform/backend/app/orchestrator/retry.py` non-empty; a test expires a pause and asserts a single `resolved_by='timeout'` transition (no double-resolve).
- **AC-18 (3.5, §8.2 / NFR-REL-1 — INV-10, binding).** **Graceful drain on SIGTERM stops containers:** the handler stops dispatch, calls `RunHandle.stop(force=True)` on live runs (containers stopped), and marks the rest `interrupted`. `grep -rni "SIGTERM\|stop(force=True\|force=True\|drain" platform/backend/app/orchestrator/drain.py platform/backend/app/main.py` non-empty; a test simulates SIGTERM and asserts every live run's container is stopped (none left running) and undrained runs are `interrupted`.
- **AC-19 (3.5, §8.2 / R-15 — INV-10, binding).** **Boot recovery = kill orphan + `interrupted` + `start_task` retry; NO re-attach.** For each non-terminal `runs` row on boot, the orphan container is `docker kill`ed, the run is marked `interrupted`, and a `start_task` retry is offered (jittered + semaphore-bounded). `grep -rni "interrupted\|start_task\|kill" platform/backend/app/orchestrator/recovery.py` non-empty; **`grep -rni "re-attach\|reattach" platform/backend`** appears **only in comments noting it is unsupported** (or is empty). A test asserts the boot scan kills the orphan, sets `interrupted`, and offers retry, and that no `re_attach`/`reattach` function is defined.
- **AC-20 (3.5, §13 — resilience, binding).** Killing the backend **mid-run** and **mid-pause** leaves **no orphaned money-spending container** (asserted via **`docker ps`** showing no surviving `run_id`-labeled container after recovery), and an idempotent retry creates **no duplicate PR**. The resilience suite (T105) covers both.

---

## 7. SECURITY_CHECKS

Concrete greps/tests from the applicable INVs (`_conventions.md`). All must hold at phase exit. The defining security property of this phase is **"a restart never leaves an orphaned money-spending container"** (INV-10) and **"reconcile never bypasses the GitHub write-queue"** (INV-11).

- **INV-10 — No live-run re-attach; recovery = kill+interrupt+retry; drain stops containers (§8.2, R-15, ADR-P007).** Boot recovery kills the orphan container, marks the run `interrupted`, and offers a `start_task` retry; graceful drain on SIGTERM stops containers (`RunHandle.stop(force=True)`), never bare-cancels a task. The code **MUST NOT** re-attach an observer to a container started by a dead process. *Verify:* `grep -rni "interrupted\|start_task\|kill\|force=True\|SIGTERM" platform/backend/app/orchestrator` non-empty across `recovery.py`/`drain.py`; **`grep -rni "re-attach\|reattach" platform/backend`** is empty **or only in comments** explaining it is unsupported; the AC-20 resilience test asserts **`docker ps`** shows no surviving `run_id`-labeled container after a mid-run and mid-pause restart. *Failure mode guarded:* an orphaned 8 GB container keeps spending after a `docker compose restart`.
- **INV-11 — GitHub label write-queue still used by reconcile (§8.1, ADR-P004).** Reconcile's label refresh (active-run authority rule) routes **all** `agent:*` transitions through the **single serialized write-queue** via `set_agent_state` (`PUT .../labels` replace-all, single-occupancy); the fictional `PATCH .../label` MUST NOT appear; reconcile does not call GitHub directly. *Verify:* `grep -rn "set_agent_state\|write_queue" platform/backend/app/orchestrator/reconcile.py` non-empty; `grep -rni "PATCH.*/label" platform` empty; no `requests`/`httpx` GitHub mutation is issued from `orchestrator/` outside the write-queue. *Failure mode guarded:* a reconcile-driven label storm or a second `agent:*` label.

> Out-of-phase security INVs (INV-1 app access control, INV-3 egress allowlist, INV-4 secret hygiene, INV-12 observer bridge) are exercised by Phase 0/2 and inherited here (every Phase-3 endpoint sits behind the access-control middleware; the read endpoints persist no secrets). Phase 3 must not regress them — e.g. do not add a `GET /runs/{id}` field that surfaces a raw token, and do not add an orchestrator GitHub call that bypasses the write-queue.

## 8. DESIGN_FIDELITY (UI slice 3.2)

- **No hardcoded hex in `platform/frontend/src`** outside the tokens file (INV-14). `grep -rnE "#[0-9a-fA-F]{3,8}\b" platform/frontend/src --include=*.tsx --include=*.ts` excluding `styles/tokens.css` is **empty**. All color comes from CSS variables ported from `styles.css` (`--accent`, `--st-queued/-running/-paused/-review/-done/-failed/-cancel`) — these literals live **only** in `tokens.css`.
- **History table / cards / spend-chart match `history.jsx`.** The runs table matches `RunsHistory` (column set + `Th` sortable headers + `WfChip`/`AgentChip`/`StateBadge` cells + the `#issue title` cell + the PR badge / chevron trailing cell); the five `StatCard`s + `SpendChart` match the `repeat(5,1fr) 1.6fr` grid; the SpendChart's **last bar uses `--accent`**, earlier bars `color-mix(--accent 45% --surface-3)`, with the total label; the `RetryQueue` card uses the `--st-paused` amber border/badges; the `RunsEmpty` state matches.
- **Status badges convey state by icon + label** (never color alone), pulsing on running/paused, matching `StateBadge`/`STATE_OF`/`STATE_LABEL` in `components.jsx` and the §7.3 palette + `.state.s-*` classes — AA contrast in dark and light (NFR-A11Y-1). **The mapping is complete for the history enum incl. `timed_out` (→ failed palette, "Timed out") and the platform-only `interrupted` (→ cancel palette, "Interrupted")** — the latter is added beyond the prototype `STATE_OF` per §6.5.
- **Type/numbers** per §7.5: run ids, costs, turns, durations, and meters use `JetBrains Mono` with `tnum`; UI text uses `Plus Jakarta Sans` — sourced from the ported tokens, not re-declared.

## 9. Independent verification commands

The evaluator runs these; all must pass (exit 0 / empty where noted).

```bash
# ---- Backend: lint, type, test ----
cd platform/backend && ruff check . && mypy app && pytest -q

# ---- Frontend: type, test ----
cd platform/frontend && npx tsc --noEmit && npx vitest run

# ---- INV-10: no live-run re-attach; recovery kills orphan + interrupts; drain stops containers ----
grep -rni "re-attach\|reattach" platform/backend          # expect: empty OR only in comments noting it's unsupported
grep -rni "interrupted\|start_task\|force=True\|SIGTERM" platform/backend/app/orchestrator   # expect: non-empty
# resilience suite: kill mid-run + mid-pause → no orphan via docker ps; idempotent retry → no duplicate PR
cd platform/backend && pytest -q tests/test_resilience.py   # asserts `docker ps` shows no run_id-labeled container; no dup PR

# ---- INV-11: reconcile uses the write-queue + the real label primitive; the fictional PATCH MUST NOT appear ----
grep -rn  "set_agent_state\|write_queue" platform/backend/app/orchestrator/reconcile.py   # expect: non-empty
grep -rni "PATCH.*/label" platform                        # expect: empty

# ---- INV-8 / FR-06-1a: Codex excluded from /stats spend and the spend chart ----
grep -rni "codex" platform/backend/app/api/stats.py platform/backend/app/db/queries_history.py   # expect: non-empty (exclusion)
grep -rni "excludes Codex\|cost not reported" platform/frontend/src   # expect: non-empty (footnote)
grep -rn  "list_runs\|get_stats" platform/backend/app/api/stats.py    # expect: empty (no engine directory scan)

# ---- INV-14: status palette mapping present (timed_out → failed, interrupted → cancel); no hardcoded hex ----
grep -rni "timed_out\|interrupted" platform/frontend/src/components/StateBadge.tsx   # expect: non-empty
grep -rnE "#[0-9a-fA-F]{3,8}\b" platform/frontend/src --include=*.tsx --include=*.ts \
  | grep -v "styles/tokens.css"               # expect: empty
bash scripts/hooks/post-edit-no-hardcoded-hex.sh           # convention hook, expect: empty/pass

# ---- SQLite-lock guard (must stay clean — reconcile/retry add no Postgres-only locking) ----
grep -rn "SKIP LOCKED\|FOR UPDATE" platform/backend         # expect: empty

# ---- Engine untouched (INV-13) ----
git diff --name-only main..HEAD -- dkmv/      # expect: empty
```

## 10. Test plan

**Backend (pytest):**
- `test_history_api`: `GET /runs` filters (`workflow`/`agent`/`status`) + cursor pagination (`limit`/`next_cursor`); `GET /runs/{id}` full-detail keys + `404 run_not_found`; no engine `list_runs` scan (AC-1, AC-2).
- `test_stats`: spend from `run_totals` + active; **Codex excluded** from `total_spend_usd`/`spend_series`, tokens counted; success-rate math; rate-limit fields present (AC-3, INV-8).
- `test_retry_queue_api`: `GET /retry-queue` shape; empty before 3.4 populates it (AC-4).
- `test_tick`: one tick dispatches one seeded candidate through the `dispatch(run)` boundary; no second launch path (AC-10).
- `test_reconcile`: authority rule (active-run DB row > stray label edit; board unchanged); human terminal move stops the run; stall detection kills + signals retry; orphan-container sweep; **all label changes via the write-queue, no direct GitHub call, no `PATCH .../label`** (AC-11, AC-12, INV-11).
- `test_deadlines`: persisted UTC `due_at` re-evaluated each tick; a frozen-clock jump past `due_at` (simulating suspend) fires the deadline; no `asyncio.sleep` deadline timer (AC-13).
- `test_retry`: backoff sequence `min(10s·2^(n-1), 300s)`; ≤3 attempts → retry queue; **idempotent re-dispatch detects existing branch/PR and reuses the `runs` row** (AC-14, AC-15); `POST /runs/{id}/retry` `202` + double-call no-op (AC-16).
- `test_pause_timeout`: pause `timeout_at` auto-resolved by reconcile via the exactly-once guard, `resolved_by='timeout'`, no double-resolve (AC-17, INV-9).
- `test_drain`: SIGTERM stops dispatch, `RunHandle.stop(force=True)` stops every live container, undrained runs → `interrupted`; never bare-cancel (AC-18, INV-10).
- `test_recovery`: boot scan kills orphan + marks `interrupted` + offers `start_task` retry; jittered + semaphore-bounded; **no `re_attach`/`reattach` symbol defined** (AC-19, INV-10).
- `test_resilience` (the §13 bar): kill mid-run **and** mid-pause → on boot **`docker ps` shows no surviving `run_id`-labeled container**; idempotent retry of an issue with an open PR → **no duplicate PR** (AC-20).

**Frontend (vitest + render):**
- `History.test`: runs table renders FR-06-4 columns; sort toggles order; `workflow`/`agent`/`status` filters narrow rows; row click opens the **read-only** finished-run view (AC-5).
- `StateBadge.test`: `timed_out` → `s-failed`/"Timed out"; **`interrupted` → `s-cancel`/"Interrupted"**; each renders icon + label, not color alone (AC-6, INV-14).
- `Stats.test`: aggregate cards + SpendChart from `GET /stats`; **Codex-excluded** spend + the "excludes Codex (cost not reported)" footnote; SpendChart last bar `--accent` (AC-7, INV-8).
- `RateLimit_Retry.test`: rate-limit health row from `rate_limits`; retry-queue card `attempt N/3 · due in · lastError`; **Retry now** posts `POST /runs/{id}/retry` (AC-8).
- `Empty.test`: "No runs yet" / "Run your first issue" (AC-9).
- A repo-wide no-hardcoded-hex assertion mirrors the INV-14 grep.

**Phase exit gate (per `CLAUDE.md`):** all AC checked off, every command in §9 passes (incl. the INV-10 `re-attach` grep, the INV-11 `PATCH`/`set_agent_state` greps, the resilience `docker ps` orphan check, and the no-duplicate-PR test), the §10 suites are green, and `ruff`/`mypy`/`tsc`/`vitest` are clean. Then update `progress.md` and proceed to Phase 4.

---

**PRD version:** v1.1 · **Phase:** 3 (M3) · **Features:** F10, F11 · **Tasks:** T088–T105 · **ADRs:** ADR-P001, ADR-P007 · Generated against `_conventions.md` INV-1..15.
