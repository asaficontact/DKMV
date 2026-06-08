# Phase 2 — Run Launch + Live Run + Human-in-the-Loop

> **Phase brief** for the DKMV Platform. Source of truth is the PRD (`docs/design_docs/platform/PRD_dkmv_platform_v1.md`); shared rules are in `docs/implementation/platform/_conventions.md` (INV-1..15). This brief is **locked** during implementation (`lock-prd.sh`). Read the PRD §citations inline — do not implement from this brief alone where it points at the PRD.

**PRD version:** v1.1
**PRD milestone:** M2 (Launch + Live run + HITL)
**Features:** F7 (Run Launch), F8 (Live Run Streaming & Observability), F9 (Human-in-the-Loop)
**User stories:** US-12, US-13, US-14 (F7); US-15, US-16, US-17 (F8); US-18, US-19, US-24 (F9)
**Tasks:** T059–T087 (`tasks.md`)
**Timing:** Weeks 6–10
**ADRs:** ADR-P003 (SSE + sync→async bridge + HttpOnly-cookie auth), ADR-P007 (best-effort-durable HITL, no live-run re-attach), ADR-P009 (capability-aware cost; Codex = timeout-only)

---

## 1. Phase goal

Turn an assigned issue into a watched run that opens a PR. After Phase 2 a solo dev can: open an issue, pick a workflow + agent + guardrails, press **Run with {Claude|Codex}**, and watch the run live — streaming events (Friendly/Raw), real-time **segment-sum** cost/turn/token meters, a stage tracker, run-config/sandbox/artifacts rail, and an always-reachable **Stop** — and, when a workflow pauses, answer a **decision card** to steer the run, with a platform-injected **approval gate before the PR push**. This is the load-bearing happy path of PRD §8.11 (`POST /runs` → claim-lock → `EmbeddedRuntime.start(on_pause=bridge)` → observer→queue→pump→SSE → pause→answer→resume → completion).

The load-bearing technical commitments of this phase:

- **Claim-locked launch** (INV-5): `POST /runs` validates (§8.10), inserts under `UNIQUE(idempotency_key)` + `INSERT … ON CONFLICT DO NOTHING` inside `BEGIN IMMEDIATE` (never `SKIP LOCKED`), then calls `EmbeddedRuntime.start(...)` and returns the **platform UUID**.
- **Capability-aware validation** (INV-8): reject `max_budget_usd`/`max_turns` for Codex (`400 unsupported_for_agent`); the UI hides those fields for Codex and shows "time-bounded, not cost-bounded."
- **Sync→async observer bridge** (INV-12): the engine's sync `EventObserver.on_event` hands off with `loop.call_soon_threadsafe(queue.put_nowait, event)` — never bare `put_nowait`/`create_task`/per-event `run_coroutine_threadsafe`.
- **SSE with cookie auth + resumable replay** (INV-2): `GET /runs/{id}/events` via `sse-starlette`, ~15 s heartbeat, anti-buffering headers, HttpOnly `SameSite=Strict` cookie (token **never** in a URL), `Last-Event-ID` subscribe-before-read dedup-by-id replay + PauseCard rehydration.
- **Segment-sum meters** (INV-7): run cost = Σ(final `cost_usd` of completed tasks) + latest within the active task, **deduped by `task_index`**; `task_completed`/`task_failed` are meter-critical (never coalesced); Codex contributes `$0` and renders "—".
- **Best-effort-durable HITL** (INV-9): `on_pause` writes `pause_decisions`, sets `agent:paused`, **releases the concurrency slot**, awaits a keyed event; `POST /runs/{id}/answer` resolves **exactly once** (rowcount-guard); UTC `timeout_at` (60 min default); code/UI never claim "resumes exactly where it left off."
- **Prompt-injection PR-push gate** (NFR-SEC-5): a platform-injected approval checkpoint on the irreversible PR/branch push, reusing the pause primitive.

---

## 2. Prerequisites (must be green before starting)

Phase 2 consumes Phase 0 (M0), Phase 1 (M1), and one early Phase 4 slice. Do not begin a slice until its prerequisites exist and pass:

- **Phase 0 — `RunService`/`EmbeddedRuntime` bridge (T014), `Executor`/`LocalDockerExecutor` (T026), `SecretStore` + repo-scoped ≤1 hr token (T030), egress allowlist (T029), gVisor + brokered socket (T027/T028).** Launch (2.1) calls `EmbeddedRuntime.start(...)` through `RunService`/the executor; do not shell the CLI (INV-13).
- **Phase 0 — Persistence + event log (T018–T024):** SQLite WAL pragmas + single serialized writer + `BEGIN IMMEDIATE`; Alembic tables `runs/run_stages/events/pause_decisions/run_totals`; the **idempotency-key claim helper** (T024); the append-only event log with monotonic `events.id` (T021); the `spend` projection (Codex-excluded, T023). 2.1's claim-lock and 2.3's pump write **through the repository layer**, never raw SQL.
- **Phase 0 — App access-control middleware (T016):** `127.0.0.1` bind + local token + `Host`/`Origin` validation + CSRF on state-changing POSTs. Every Phase 2 endpoint inherits this; the SSE cookie auth (2.3) is layered on top, not instead.
- **Phase 1 — F4 GitHub state machine (`set_agent_state`, T040) + write-queue (T043).** Launch moves the issue to `agent:in-progress`; pause sets `agent:paused`; both go through `set_agent_state` (replace-all, single-occupancy) on the serialized write-queue (INV-11). Phase 1's authority rule (active-run DB row > label) now has live runs to be authoritative for.
- **Phase 1 — App shell + chrome (T049–T058):** router, ported `tokens.css`, EventSource client primitive, shared `StateBadge`. The issue-detail/run screens mount inside this shell.
- **Phase 4 slice 4.1 — `GET /workflows` / `GET /workflows/{id}` (T106).** Build this early (it only needs Phase-0 `T014`); the run panel's workflow picker (2.2) reads it. Do **not** hardcode the built-in list in the frontend.

If any prerequisite is missing, stop and finish it first (per `CLAUDE.md` phase discipline).

---

## 3. Scope

### IN scope (this phase)

- **F7 Run Launch:** `GET /issues/{num}` detail; issue-detail UI (markdown body, labels, comments, existing-run alert); run panel (workflow picker from `GET /workflows`; agent/model resolution `auto→workflow.agent` via `validate_agent_model`; Codex hides budget/turn fields; branch prefill; advanced guardrails); `POST /runs` validation (§8.10) → claim-lock insert → `EmbeddedRuntime.start(... on_pause=bridge)` → return platform UUID → move issue `agent:in-progress`; `GET /runs` + `GET /runs/{id}` baseline (§8.4, §8.9, §8.10, §8.11).
- **F8 Live Run Streaming & Observability:** sync→async observer bridge; per-run bounded queue + slow-consumer policy; event pump (batch-append to `events` + update `run_stages` + fan-out); SSE endpoint with heartbeats + anti-buffering headers + HttpOnly-cookie auth + `Last-Event-ID` replay + PauseCard rehydration; **segment-sum** cost/turn meters (+ Codex "—"/exclusion); live-run UI (header, meters row, stage tracker, Friendly/Raw event feed, run-config/sandbox/artifacts rail, Stop, one-shot exec via `execute_in_container`) (§5.5, §6.4, §8.3, FR-04).
- **F9 Human-in-the-Loop:** `on_pause` bridge (write `pause_decisions`, set `agent:paused`, release slot, emit `pause_requested`, await keyed event); `POST /runs/{id}/answer` resolve-exactly-once + resume + `decision` event; decision card UI (engine-authoritative `{value,label,description?}` options; recommended = `value==default`; send chosen **value**; Ship-as-is/Abort set `skip_remaining`); UTC `timeout_at` (60 min) minimal auto-resolve hook; platform-injected **PR-push approval gate** (NFR-SEC-5) (§5.6, §8.5, NFR-SEC-5, FR-05).

### OUT of scope (explicitly deferred)

- **Runs history, analytics, `/stats`, retry queue, spend chart** → **Phase 3** (F10). Phase 2 ships the `GET /runs` + `GET /runs/{id}` **baseline** shape (§8.9) for the live view and the run list spine; sortable/filterable history, aggregate cards, the SpendChart, and the rate-limit health row are Phase 3. The live meters compute spend from the Phase-0 segment-sum/`spend` projection, not from a `/stats` endpoint.
- **Full orchestrator tick / dispatch loop / reconciliation / retry / crash recovery / graceful drain** → **Phase 3** (F11). Phase 2 **may launch runs directly** from `POST /runs` (no tick loop required). The **minimal** pause-timeout auto-resolve hook (T085) is built here but is *wired into the reconcile tick in Phase 3* (T104); in Phase 2 it is exercised by a directly-invoked sweep in tests. Stall detection, orphan sweep, idempotent re-dispatch, and boot recovery are Phase 3.
- **Bounded concurrency / aggregate admission control** → **Phase 5** (F13). Phase 2 launches runs without a global `Semaphore` cap (a solo dev launching one or two runs is fine). The HITL **slot release** (T086) is still built — it is the slot-accounting primitive Phase 5's semaphore consumes — but the admission gate that *enforces* `max_concurrent_runs`/memory/daily-spend is Phase 5.
- **Capability-aware *enforcement*** (hard budget/turn caps actually applied to the running engine) → **Phase 5** (F13, T116/T117). Phase 2 does the capability-aware **validation/rejection** at the API boundary (Codex `400`, §8.10) and the **display** ("—", "time-bounded") — it does **not** implement the runtime cap-enforcement loop.
- **Board/sidebar live-status chip streaming.** The chip and board aggregate strip stay **poll-driven** (Phase 1, §8.3 "Board/chip use polling"); only the single open run view holds an SSE stream. Do not open N per-card SSE streams.
- **Interactive PTY / "attach terminal".** The "Run a command in the container" affordance is a **one-shot** `execute_in_container` exec (the engine exposes no interactive PTY) — build the one-shot exec only (§5.5 FR-04-1).
- **True coroutine-level resume across restart.** Out of scope by engine reality (ADR-P007 / R-15) — Phase 2 honors "decision durable; run resumes from last pushed boundary, else `interrupted`" and must never promise otherwise. Boot recovery itself is Phase 3.

---

## 4. Slices

Slice IDs are `2.k-name`. Each maps to a feature and PRD §. "Files" lists the primary edit surface used by the wave plan (no two same-wave slices share a file: API vs UI vs streaming vs hitl live in separate modules).

### 2.1 — `2.1-launch-api` (F7 / §8.4, §8.9, §8.10, §8.11)

**What:** the launch contract — issue detail read, validation, claim-lock, engine start, run reads.

- `GET /issues/{num}` returns the issue detail (markdown body, labels, comments) for the issue-detail screen (T059, §5.4, §8.1 endpoints). Distinct from Phase 1's `GET /repos/{repo}/issues` board-list shape.
- `POST /runs` (body §8.4: `{issue_num, repo, workflow_id, agent, branch, feature_name, model?, max_turns?, timeout_minutes?, max_budget_usd?, memory?, context[]?, keep_alive?, start_task?}`):
  - **Validation (§8.10):** `branch` matches `^[\w./-]{1,200}$` (no `..`, no leading `-`); `feature_name` slugified (`[a-z0-9-]`, ≤30); `repo` is the connected project's; `workflow_id` resolves via `validate_component`; `agent`/`model` via `validate_agent_model`; `timeout_minutes`/`memory` within bounds; `context` paths exist inside the project. **`max_budget_usd`/`max_turns` are rejected `400 unsupported_for_agent` when the resolved agent's `supports_budget()`/`supports_max_turns()` is false (Codex)** — INV-8 (do not silently ignore).
  - **Agent resolution:** `resolvedAgent = agent == "auto" ? workflow.agent : agent` (FR-03-3); `idempotency_key = issue_num + workflow_id + base_branch` (not a hash of mutable issue body, §8.2).
  - **Claim-lock (INV-5):** insert the `runs` row via the Phase-0 idempotency helper — `INSERT … ON CONFLICT(idempotency_key) DO NOTHING` inside `BEGIN IMMEDIATE`; act only if the insert won the row, else `409 duplicate_dispatch`. **No `SKIP LOCKED`/`FOR UPDATE` anywhere** (SQLite has neither).
  - Build `ExecutionSource(type=remote, repo, branch)`, call `EmbeddedRuntime.start(..., on_pause=bridge)` (the bridge object is provided by 2.5; in 2.1 it is wired through but may be a thin pass-through until 2.5 lands), and **return `{ run_id }` = the platform UUID** (the engine `YYMMDD-HHMM-…` id is *not* available synchronously — it back-fills as `engine_run_id` via the event stream; address all run endpoints by the platform UUID) (§8.4, §8.11).
  - On successful start, move the issue to `agent:in-progress` via `set_agent_state` (Phase 1 write-queue, INV-11).
- `GET /runs` + `GET /runs/{id}` **baseline** shape (§8.9): the live-view detail (`id, engine_run_id, repo, issue, workflow_id, agent, model, status, branch, cost_usd|null, tokens_*, turns, stages, config, sandbox, artifacts, pr|null, error|null`). Codex `cost_usd = null`/"—". (History filters/sort = Phase 3.)
- **Files:** `platform/backend/app/api/issue_detail.py` (`GET /issues/{num}`), `platform/backend/app/api/runs.py` (`POST /runs`, `GET /runs`, `GET /runs/{id}`), `platform/backend/app/runs/launch.py` (validation + agent resolution + claim-lock + start), `platform/backend/app/runs/service.py` (run read model).
- **Tasks:** T059, T065, T066, T067.

### 2.2 — `2.2-launch-ui` (F7 / §5.4, FR-03)

**What:** the issue-detail screen + the "Run this issue" panel (build to `issue.jsx`).

- **Issue detail (left pane, `minmax(0,1fr) 408px`)** built to `issue.jsx`: `#num` + `StateBadge`; branch caption + "Open on GitHub" when a run exists; H1 title; author row + GitHub label pills; markdown body (the `MD`/`Inline` renderer — `###`, ordered/unordered lists, `` `code` ``, `**bold**`); comments thread (§5.4 FR-03-1).
- **Existing-run alert card** (FR-03-1, FR-03-4): paused variant (amber, "This run is paused and needs your decision", **Review decision**) / running variant (blue, "A run is in progress", **Watch live**), showing the run id and linking to the live run (T061).
- **Run panel (right):** **Workflow** picker — cards from **`GET /workflows`** (4.1), showing emoji, name, purpose, stage chain (chevrons), a **"pauses"** badge, and "Est. {budget} · {estTime}" (FR-03-2). Do **not** hardcode `WORKFLOWS`; the prototype mock is illustrative.
- **Agent/model resolution** (T063, FR-03-3): `auto | claude | codex`; Auto shows "→ {model}" resolving to `workflow.agent`; resolution validated via the engine's `validate_agent_model` (reject incompatible explicit pairs — surfaced from the API). **For Codex, hide the Max-budget and Max-turns fields entirely and show "Codex runs are time-bounded, not cost-bounded"** (NFR-COST-1, INV-8, R-10). Populate the model picker from engine adapter defaults, not the prototype labels (§6.1 drift note: Codex default is `gpt-5.4`, not `gpt-5.1-codex`).
- **Branch** prefilled `dkmv/issue-{num}-{slug}`, editable, mono; **Advanced guardrails** (collapsed): Max budget / Max turns (Claude only) / Timeout / Memory (default "8g") / Extra context files; sticky footer est. line + **Queue for later** + **Run with {Claude|Codex}** → `POST /runs` → navigate to the live run (T064, FR-03-2/3).
- **Files:** `platform/frontend/src/screens/IssueDetail.tsx`, `platform/frontend/src/components/Markdown.tsx`, `platform/frontend/src/components/ExistingRunAlert.tsx`, `platform/frontend/src/components/RunPanel.tsx`, `platform/frontend/src/components/WorkflowPicker.tsx`, `platform/frontend/src/api/runs.ts`.
- **Tasks:** T060, T061, T062, T063, T064.

### 2.3 — `2.3-streaming-core` (F8 / §8.3, §6.4)

**What:** the observer→queue→pump→SSE backbone with cookie auth + resumable replay (no UI).

- **Sync→async bridge (INV-12, ADR-P003):** the platform's `EventObserver` captures the loop at startup and hands off each `RuntimeEvent` with **`loop.call_soon_threadsafe(queue.put_nowait, event)`** — **never** bare `queue.put_nowait`, `loop.create_task`, or per-event `run_coroutine_threadsafe` from the observer (the observer thread is not guaranteed to be the loop thread) (§8.3).
- **Per-run bounded queue + slow-consumer policy:** each subscriber gets a bounded queue; on overflow **coalesce/drop meter frames (≤4 Hz, keep-latest)** but **never** lifecycle/decision/`task_completed`/`task_failed` events; disconnect a persistently-slow consumer (it will reconnect and replay) (§8.3, ADR-P003).
- **Event pump:** a single pump task per run **batch-appends** `RuntimeEvent`s to the append-only `events` table (monotonic `events.id` = the SSE cursor), updates `run_stages` (and the meter projection — segment-sum lives in 2.4), and **fans out** to SSE subscribers (T069). The SSE message body carries the **outer** `RuntimeEvent` (`sequence, timestamp, run_id, task_name, task_index, event_type, data{}, content, cost_usd, turns`, §6.4); each message `id = events.id`.
- **SSE endpoint `GET /runs/{id}/events`** (`sse-starlette` `EventSourceResponse`, T070): **~15 s `:`-comment heartbeat**; `Cache-Control: no-cache` + `X-Accel-Buffering: no` (proxy-safety).
- **Auth (INV-2, ADR-P003, T071):** the SSE token rides an **HttpOnly `SameSite=Strict` cookie** (auto-sent by `EventSource`, unreadable by JS); the handler validates the cookie + `Origin`/`Host`. **The token MUST NOT appear in any URL.** Browser `EventSource` cannot set `Authorization`, and a query-string token would leak into logs and the append-only `events` table.
- **Resumable replay (INV-2 contract, T072):** on reconnect with `Last-Event-ID`, (1) **subscribe to the live per-run queue first**, then (2) read the backlog `WHERE run_id = ? AND id > :last ORDER BY id`, flush it, then (3) tail live — **de-duplicating by `id`** across the replay→live handoff (subscribe-before-read closes the gap/dup window). The platform `events` table is the primary replay log; the engine's `replay_events` is a fallback only.
- **PauseCard rehydration hook:** if the socket drops while paused, replay only reaches `pause_requested`; expose the decision state on `GET /runs/{id}` (the `pause_decisions` row) so the client rehydrates the card from state, not the live push (§8.3). (The card itself is 2.5; this slice provides the rehydration source.)
- **Files:** `platform/backend/app/sse/observer_bridge.py` (`call_soon_threadsafe` handoff + bounded queue), `platform/backend/app/sse/pump.py` (batch-append + fan-out + run_stages), `platform/backend/app/sse/endpoint.py` (`GET /runs/{id}/events` + heartbeat + anti-buffering), `platform/backend/app/sse/auth.py` (HttpOnly cookie + Origin/Host), `platform/backend/app/sse/replay.py` (`Last-Event-ID` subscribe-before-read + dedup).
- **Tasks:** T068, T069, T070, T071, T072.

### 2.4 — `2.4-meters-liveui` (F8 / §5.5, §6.4, §8.3)

**What:** segment-sum meter computation + the full live-run UI (build to `run.jsx`).

- **Segment-sum meters (INV-7, §8.3/§6.4, T073):** `run_cost = Σ(final cost_usd of each completed task) + (latest cost_usd within the active task)`, **de-duplicated by `(run_id, task_index)`** — **never** a naive `SUM(cost_usd)` over all events (double-counts) and **never** plain keep-latest (would reset toward $0 at every stage boundary and never reach the run total). The outer `RuntimeEvent.cost_usd`/`turns` are cumulative *per task*; `task_completed`/`task_failed` carry a completed segment's final and are **meter-critical** (never coalesced/dropped). Turns aggregate identically.
- **Codex cost handling (INV-8, FR-06-1a, T074):** Codex segments contribute `$0`; render the cost meter as **"—" not "$0.00"** and exclude the run from spend (tokens still count); the run is bounded by timeout, not budget.
- **Meters row UI** (T075, FR-04-2, mono/`tnum`): **elapsed** (`{m}m {ss}s`), **cost** (`$x.xx`, accent when live; from the segment-sum value — *not* a raw `cost_usd` field), **tokens (in · out)**, **turns**, and **overall progress** bar with %.
- **Stage tracker** (T076, FR-04-3): a stepper of the workflow's stages with per-stage status (done ✓ / running ● / paused ⏸ / pending ○) and `${cost} · {turns}t · {dur}`; clickable to expand when not pending (build to `run.jsx StageTracker`).
- **Event feed** (T077, FR-04-4): live auto-scrolling feed with a **Friendly | Raw** toggle + search. Friendly derives `kind/icon/text/tool` from `event_type` + `data`; **Raw renders the inner `RuntimeEvent.data` dict** (`type/subtype/content/tool_name?/total_cost_usd?/num_turns` JSON line, §6.4) — not the outer wrapper.
- **Right rail** (T078, FR-04-5): **Run config** snapshot (verbatim keys `repo, branch, feature_name, model, max_turns, timeout_minutes, max_budget_usd, memory_limit`), **Sandbox** (`dkmv-sandbox:latest`, "8g · 2 vCPU · healthy"), **Artifacts** (e.g. `analysis.json`, `qa_evaluation.json`, `GUIDE.md`, live `session.log`), **Pull request** when present.
- **Stop + one-shot exec** (T079, FR-04-1): **Stop** (danger) when running/paused — uses `RunHandle.stop(force=True)` when paused (the engine checks `cancel_event` only between tasks, so a cooperative stop won't fire at `await on_pause`; force cancels the task → the engine `finally` stops the container) (§8.5, R-7); "Run a command in the container" is a **one-shot** `execute_in_container` exec, **not** a PTY.
- **Files:** `platform/backend/app/runs/meters.py` (segment-sum, dedup by `task_index`), `platform/backend/app/api/run_actions.py` (`POST /runs/{id}/stop`, one-shot exec endpoint), `platform/frontend/src/screens/LiveRun.tsx` (owns the layout + a slot for the decision card built in 2.5), `platform/frontend/src/components/MetersRow.tsx`, `platform/frontend/src/components/StageTracker.tsx`, `platform/frontend/src/components/EventFeed.tsx`, `platform/frontend/src/components/RunRail.tsx`, `platform/frontend/src/api/sse.ts` (EventSource consumer).
- **Tasks:** T073, T074, T075, T076, T077, T078, T079.

### 2.5 — `2.5-hitl` (F9 / §5.6, §8.5, NFR-SEC-5)

**What:** the pause bridge + answer + decision card + timeout + PR-push approval gate.

- **`on_pause` bridge (INV-9, ADR-P007, T080):** the platform passes `on_pause: Callable[[PauseRequest], Awaitable[PauseResponse]]` to `EmbeddedRuntime.start` (the engine genuinely `await`s it at the pause point with the container held open). On pause: write a `pause_decisions` row (`status=pending`, request payload, UTC `timeout_at`); set the issue `agent:paused` (via the Phase-1 write-queue); **release the run's concurrency slot** (the container is genuinely idle during the pause — T086); emit `pause_requested` over SSE; then `await` an `asyncio.Event`/`Future` keyed by `decision_id`.
- **`POST /runs/{id}/answer` resolve-exactly-once (INV-9, T081):** guarded transition `UPDATE pause_decisions SET status='answered', answer_json=…, resolved_by='human' WHERE id=? AND status='pending'`; **fire the in-memory keyed event only on rowcount=1** (so a double-click / two tabs / a racing timeout can't double-resolve) → the callback returns `PauseResponse(answers, skip_remaining)` → the engine resumes (re-acquiring a slot); append a `decision` event ("You chose: '{label}'"). Returns `200 {resolved:true}` or `409 pause_already_resolved` (§8.9).
- **Decision card UI (T082, T083, FR-05):** render the amber card from `run.jsx PauseCard`, mapping to the engine `PauseRequest`: badge `PAUSED · after {task_name}`; the `PauseQuestion.question`; the `context.summary`; **options** as radio rows. **Use the engine-authoritative option shape `{value, label, description?}`** — display `label` (bold) + optional `description`; the **recommended** option is the one whose **`value` equals `default`** (NOT label-matching). On **Approve & continue** → `POST /runs/{id}/answer` with `{answers:{question_id: <chosen option value>}, skip_remaining:false}` — **send the chosen `value`, not the label**; **Ship as-is** and **Abort** set `skip_remaining:true`. (The `data.jsx PAUSE_REQUEST` mock omits `value` and uses `{label, description}` — that is a prototype simplification; build to the engine shape per §6.1.)
- **Pause timeout (INV-9, T085):** each pause carries a UTC `timeout_at` (**default 60 min**); a **minimal auto-resolve hook** re-evaluates `now() >= timeout_at` and auto-resolves via the same exactly-once guard (`resolved_by='timeout'`; default **auto-abort**, configurable). In Phase 2 this hook is exercised by a directly-invoked sweep in tests; *wiring it into the reconcile tick is Phase 3 (T104)*.
- **Needs-You wiring (T084):** the issue goes to `agent:paused` → "Needs You" column; the board card's "Review decision" CTA (Phase 1) targets the live run's decision card.
- **PR-push approval gate (NFR-SEC-5, INV-9 primitive reuse, T087):** a **platform-injected** approval checkpoint on the irreversible high-blast-radius action — the PR/branch push — implemented via the **same pause primitive** (independent of workflow-authored pauses). An injected prompt in an issue body still requires human approval before the PR push. Document that this is defense-in-depth, not prevention.
- **Slot accounting (T086):** model the slot release on pause + reacquire on resume as the accounting primitive Phase 5's `Semaphore` will consume (the enforcement cap itself is Phase 5).
- **Files:** `platform/backend/app/hitl/pause_bridge.py` (`on_pause`, write row, set label, release slot, emit, await), `platform/backend/app/hitl/answer.py` (resolve-exactly-once + resume + decision event), `platform/backend/app/hitl/timeout.py` (UTC `timeout_at` + auto-resolve sweep), `platform/backend/app/hitl/pr_gate.py` (platform-injected PR-push approval), `platform/backend/app/api/answer.py` (`POST /runs/{id}/answer`), `platform/frontend/src/components/PauseCard.tsx`.
- **Tasks:** T080, T081, T082, T083, T084, T085, T086, T087.

---

## 5. Wave plan

No two slices in the same wave edit the same file — API (`app/api/*`, `app/runs/*`), streaming (`app/sse/*`), and hitl (`app/hitl/*`) are split backend modules; UI screens/components are split frontend files. `LiveRun.tsx` is owned by **2.4** (it renders a slot for the decision card); `PauseCard.tsx` is owned by **2.5**; the rehydration *source* is in **2.3** — so the three never edit the same file.

| Wave | Slices | Rationale / dependency |
|---|---|---|
| **A** | `2.1-launch-api` | First. Needs Phase-0 persistence/idempotency helper + `RunService`/executor and Phase-1 `set_agent_state`. Establishes `POST /runs` + run reads + the `run_id` everything else addresses. |
| **B** | `2.2-launch-ui`, `2.3-streaming-core` | Both after 2.1. **2.2** additionally needs **Phase-4 slice 4.1** (`GET /workflows`) for the workflow picker. **2.3** needs 2.1's launched run + Phase-0 event log. Disjoint files (frontend `screens/IssueDetail`+`components/RunPanel` + `api/runs.ts` vs backend `app/sse/*`) → parallel. |
| **C** | `2.4-meters-liveui`, `2.5-hitl` | Both after 2.3 (they consume the SSE stream + the pump's `events`/`run_stages`). Disjoint files (frontend `LiveRun`/`MetersRow`/`StageTracker`/`EventFeed`/`RunRail` + backend `runs/meters.py`/`api/run_actions.py` vs backend `app/hitl/*`/`api/answer.py` + frontend `PauseCard.tsx`) → parallel. The `on_pause` object 2.5 builds is wired into 2.1's `start(...)` call as a pass-through until 2.5 lands. |

Critical path: **A → 2.3 (B) → {2.4, 2.5} (C)**. 2.2 (B) gates only the launch UX and 4.1.

---

## 6. Acceptance criteria (greppable, with PRD §citations)

Each criterion is verifiable by a grep/command + a test. Backend greps run under `platform/backend/`, frontend under `platform/frontend/src/`.

### F7 — Run Launch

- **AC-1 (2.1, §8.10 — INV-8, binding).** `POST /runs` **rejects `max_budget_usd`/`max_turns` for a resolved Codex agent** with `400 unsupported_for_agent` (not silently ignored), branching on `supports_budget()`/`supports_max_turns()`. `grep -rn "supports_budget\|supports_max_turns" platform/backend/app/runs` is **non-empty**; `grep -rn "unsupported_for_agent" platform/backend/app` is non-empty; a test asserts the 400 for a Codex budget/turns body and a 201 for the same body on Claude.
- **AC-2 (2.1, §8.2/§8.11 — INV-5, binding).** Launch claims the run via `UNIQUE(idempotency_key)` + `INSERT … ON CONFLICT DO NOTHING` under `BEGIN IMMEDIATE`; a duplicate dispatch returns `409 duplicate_dispatch`. `grep -rn "ON CONFLICT\|INSERT OR IGNORE" platform/backend/app` is non-empty (the Phase-0 claim helper, reached from `runs/launch.py`); **`grep -rn "SKIP LOCKED\|FOR UPDATE" platform/backend` is empty**. A test fires two concurrent identical `POST /runs` and asserts exactly one run row + one `409`.
- **AC-3 (2.1, §8.4/§8.11).** `POST /runs` returns the **platform UUID** (not the engine `YYMMDD-HHMM-…` id) and moves the issue to `agent:in-progress` via `set_agent_state`. A test asserts the returned `run_id` is a UUID, `runs.engine_run_id` is null at return time and back-fills from the event stream, and the label transition went through the write-queue (INV-11).
- **AC-4 (2.1, §8.10).** Validation enforces `branch ^[\w./-]{1,200}$` (no `..`/leading `-`), slugified `feature_name`, `validate_component(workflow_id)`, `validate_agent_model(agent, model)`, and project-internal `context` paths. A test table asserts each invalid input → `400 validation_error` with field details.
- **AC-5 (2.1, §8.9).** `GET /issues/{num}`, `GET /runs`, and `GET /runs/{id}` return the §8.9 baseline shapes; Codex `cost_usd` is `null`/"—". A test asserts the `GET /runs/{id}` body carries `stages`, `config` (the FR-04-5 keys), `sandbox`, `artifacts`, `pr|null`.
- **AC-6 (2.2, §5.4/FR-03-2).** The run panel's workflow picker is populated from **`GET /workflows`** (not a hardcoded list); the Codex selection **hides the Max-budget and Max-turns fields** and shows "time-bounded, not cost-bounded." `grep -rni "time-bounded" platform/frontend/src` non-empty; `grep -rn "WORKFLOWS\s*=" platform/frontend/src` is **empty** (no inlined workflow constant). A render test asserts budget/turn inputs are absent for Codex and present for Claude.
- **AC-7 (2.2, FR-03-1/3).** The issue-detail markdown renderer supports `###`, ordered/unordered lists, `` `code` ``, `**bold**`; the existing-run alert shows paused (amber/Review decision) vs running (blue/Watch live) variants; **Run with {Claude|Codex}** posts `POST /runs` with `resolvedAgent = agent=="auto" ? workflow.agent : agent`. Render tests cover all three.

### F8 — Live Run Streaming & Observability

- **AC-8 (2.3, §8.3 — INV-12, binding).** The observer hands off with `loop.call_soon_threadsafe(queue.put_nowait, event)`. `grep -rn "call_soon_threadsafe" platform/backend/app/sse` is **non-empty**; `grep -rn "create_task\|run_coroutine_threadsafe" platform/backend/app/sse/observer_bridge.py` is **empty** (the observer never schedules coroutines). A test drives `on_event` from a non-loop thread and asserts the event arrives on the queue with no loop error.
- **AC-9 (2.3, §8.3 — INV-2, binding).** SSE auth rides an HttpOnly `SameSite=Strict` cookie; **the token never appears in a URL.** `grep -rnE "token=|\?.*token" platform/frontend/src | grep -i eventsource` is **empty**; `grep -rni "HttpOnly\|SameSite" platform/backend/app/sse` non-empty. A test asserts the SSE handler 401s without the cookie and 200s with it, and that an `Origin`/`Host`-mismatched request is rejected.
- **AC-10 (2.3, §8.3).** The SSE endpoint emits a ~15 s heartbeat and sets `Cache-Control: no-cache` + `X-Accel-Buffering: no`. `grep -rni "X-Accel-Buffering\|no-cache" platform/backend/app/sse` non-empty; a test asserts both headers and a heartbeat comment within the interval.
- **AC-11 (2.3, §8.3 — INV-2 replay).** `Last-Event-ID` replay **subscribes to the live queue before reading** `events WHERE id > :last AND run_id = ?` and **dedups by `id`**. `grep -rni "Last-Event-ID\|last_event_id" platform/backend/app/sse` non-empty. A test reconnects mid-stream and asserts **no gaps and no duplicates** across the replay→live handoff; a paused-run reconnect rehydrates the decision card from `GET /runs/{id}` (not the live push).
- **AC-12 (2.4, §8.3/§6.4 — INV-7, binding).** The meter computes **segment-sum**: Σ(completed-task finals) + latest-within-active, **deduped by `task_index`** — never `SUM(cost_usd)` over events, never keep-latest. `grep -rni "task_index" platform/backend/app/runs/meters.py` non-empty; `grep -rni "task_completed\|task_failed" platform/backend/app` shows them treated meter-critical. **A multi-stage test (e.g. a `plan` run) asserts the displayed cost climbs across stage boundaries toward the run total (~$12) and NEVER resets toward $0.**
- **AC-13 (2.4, FR-04-2/FR-06-1a — INV-8).** A Codex run's live cost renders **"—" not "$0.00"** and is excluded from spend (tokens still count). `grep -rni "codex" platform/backend/app/runs/meters.py platform/frontend/src/components/MetersRow.tsx` shows the exclusion/"—"; a test with mixed Claude+Codex segments asserts spend = Claude-only, tokens = both.
- **AC-14 (2.4, FR-04-4).** The event feed Friendly/Raw toggle: **Raw renders the inner `RuntimeEvent.data`** (`type/subtype/content/tool_name?/num_turns`), not the outer wrapper. A render test asserts the Raw line keys match the inner dict shape (§6.4).
- **AC-15 (2.4, FR-04-1/§8.5).** **Stop** uses `RunHandle.stop(force=True)` for a paused run; the in-container command is a **one-shot `execute_in_container`**, not a PTY. `grep -rni "stop(force=True)\|force=True" platform/backend/app` non-empty (for the paused path); `grep -rni "execute_in_container" platform/backend/app` non-empty; `grep -rni "pty\|interactive.*terminal" platform/backend/app/api/run_actions.py` is **empty**.
- **AC-16 (2.4, FR-04-3/5).** Stage tracker renders per-stage status + `${cost} · {turns}t · {dur}`; the rail shows the verbatim run-config keys (`repo, branch, feature_name, model, max_turns, timeout_minutes, max_budget_usd, memory_limit`), sandbox health, artifacts, and the linked PR when present. Render tests cover each.

### F9 — Human-in-the-Loop

- **AC-17 (2.5, §8.5 — INV-9, binding).** `POST /runs/{id}/answer` resolves **exactly once**: `UPDATE pause_decisions SET status='answered' … WHERE id=? AND status='pending'` and fires the keyed event **only on rowcount=1**. `grep -rni "status='pending'\|status=\"pending\"" platform/backend/app/hitl/answer.py` non-empty; a **double-submit/timeout race test** asserts the decision resolves once (second call → `409 pause_already_resolved`).
- **AC-18 (2.5, §8.5 — INV-9).** The pause bridge **releases the concurrency slot** and never claims in-place resume. `grep -rni "release" platform/backend/app/hitl/pause_bridge.py` shows the slot release; **`grep -rni "resumes exactly\|resume in place" platform` is empty** (no over-claim, in code or UI copy). A test asserts the slot is released on pause and re-acquired on resume.
- **AC-19 (2.5, §6.1/FR-05 — DESIGN_FIDELITY).** The decision card uses the **engine-authoritative option shape `{value, label, description?}`**; **recommended = the option whose `value == default`**; Approve sends `{answers:{question_id: <chosen value>}}` (the **value**, not the label); Ship-as-is/Abort set `skip_remaining:true`. `grep -rn "value" platform/frontend/src/components/PauseCard.tsx` shows the value is sent; a render+submit test asserts the recommended marker tracks `value==default` and the posted body carries the chosen `value`.
- **AC-20 (2.5, §8.5 — INV-9).** Each pause carries a UTC `timeout_at` (default 60 min) re-evaluated by an auto-resolve sweep (default auto-abort) using the same exactly-once guard. `grep -rni "timeout_at" platform/backend/app/hitl" non-empty; a test fast-forwards `now()` past `timeout_at` and asserts a single `resolved_by='timeout'` transition.
- **AC-21 (2.5, NFR-SEC-5 — binding).** A platform-injected **PR-push approval gate** fires before the irreversible push, reusing the pause primitive, independent of workflow-authored pauses. `grep -rni "pr.push\|pr_push\|push.*approval\|approval.*gate" platform/backend/app/hitl/pr_gate.py` non-empty. **An AT-PromptInjection-style test** (a run whose issue body contains an injected instruction) asserts the run pauses for human approval before the PR push.

---

## 7. SECURITY_CHECKS

Concrete greps/tests from the applicable INVs (`_conventions.md`). All must hold at phase exit.

- **INV-2 — SSE auth via cookie, token never in URL (§8.3).** The SSE token rides an HttpOnly `SameSite=Strict` cookie; the handler validates cookie + `Origin`/`Host`. `grep -rnE "token=|\?.*token" platform/frontend/src | grep -i eventsource` is **empty**; `grep -rni "HttpOnly\|SameSite" platform/backend/app/sse` non-empty. A query-string token never appears (a leak into the append-only `events` table would be permanent). (AC-9.)
- **INV-5 — Dispatch idempotency, SQLite-correct (§8.2).** Launch uses `ON CONFLICT DO NOTHING` under `BEGIN IMMEDIATE`; **`grep -rn "SKIP LOCKED\|FOR UPDATE" platform/backend` is empty.** A concurrent double-`POST /runs` yields one row + one `409`. (AC-2.)
- **INV-9 — HITL correctness (§8.5, ADR-P007).** `answer` is rowcount-guarded (`WHERE status='pending'`, fire on rowcount=1); pause **releases the slot**; `timeout_at` is UTC; Stop-during-pause uses `stop(force=True)`. **`grep -rni "resumes exactly\|resume in place" platform` is empty.** (AC-17, AC-18, AC-20.)
- **INV-12 — Sync→async observer bridge (§8.3).** `grep -rn "call_soon_threadsafe" platform/backend/app/sse` non-empty; the observer does **not** call `create_task`/`run_coroutine_threadsafe`. (AC-8.)
- **NFR-SEC-5 — Prompt-injection PR-push gate.** The platform-injected approval gate fires on the PR push (issue body + repo content are untrusted, OWASP LLM01, R-14). A test proves the gate fires before any push. (AC-21.)
- **INV-4 (no regression) — secret hygiene.** The redact-before-persist pipeline (Phase 0) must still cover the new event-pump writes: `grep -rnE "sk-ant-|ghp_|github_pat_" platform/backend/app | grep -i "event\|log"` shows no secret persisted (only redaction). Phase 2 must not append a raw secret to `events`.

> Out-of-phase security INVs (INV-1 app access control, INV-3 egress allowlist, INV-11 label write-queue) are owned by Phase 0/1 and inherited here — every Phase 2 endpoint stays behind the loopback+token+Host/CSRF middleware and every label mutation goes through the write-queue. Do not add a route or a GitHub call that bypasses them.

## 8. DESIGN_FIDELITY (UI slices 2.2, 2.4, 2.5)

- **No hardcoded hex in `platform/frontend/src`** outside the tokens file (INV-14). `grep -rnE "#[0-9a-fA-F]{3,8}\b" platform/frontend/src --include=*.tsx --include=*.ts` excluding `styles/tokens.css` is **empty**. All color comes from the CSS variables ported from `styles.css` (`--accent` indigo `#7b7bf5`; state palette `--st-queued #94a3b8 · --st-running #4f8cff · --st-paused #f5a623 · --st-review #a78bfa · --st-done #34c98a · --st-failed #f2666b · --st-cancel #7c7a82`; §7.3) — these literals live **only** in `tokens.css`.
- **Live run matches `run.jsx`.** The meters row (elapsed/cost/tokens/turns/progress, mono + `tnum`, cost accent when live), the `StageTracker` stepper (done ✓ / running ● / paused ⏸ / pending ○ with `${cost} · {turns}t · {dur}`), the Friendly/Raw `EventFeed`, and the `RunRail` (Run config / Sandbox / Artifacts / Pull request sections) match the prototype layout and the §7.3 palette. State is conveyed by **icon + label**, not color alone; running/paused dots pulse (NFR-A11Y-1).
- **Issue detail matches `issue.jsx`.** Two-pane `minmax(0,1fr) 408px`; the `MD`/`Inline` markdown renderer; author row + `GhLabel` pills; the paused/running existing-run alert; the run panel (workflow cards with stage chevrons + "pauses" badge, agent segmented control, branch mono input, collapsed advanced guardrails, sticky est. footer).
- **Decision card matches `run.jsx PauseCard` BUT uses the engine option shape.** Amber card, `PAUSED · after {task_name}` badge, question + `context.summary`, radio option rows, Approve & continue / Ship as-is / Abort footer. **Critically:** options are the **engine-authoritative `{value, label, description?}`** (NOT the `data.jsx PAUSE_REQUEST` `{label, description}` mock); the **recommended** marker tracks `value == default`; the posted answer carries the chosen **value**. (§6.1, FR-05-2/3.)
- **State badges** (`StateBadge`, shared from Phase 1) reused in the run header (Running / Paused · needs you / Completed / Failed) — icon + label, pulsing on running/paused, AA contrast in dark and light (§7.3, components.jsx `STATE_OF`).
- **Type/radii/motion** per §7.5 (`Plus Jakarta Sans` UI, `JetBrains Mono` for run ids / numbers / meters with `tnum`; radii/easing tokens) — sourced from the ported tokens, not re-declared.

## 9. Independent verification commands

The evaluator runs these; all must pass (exit 0 / empty where noted).

```bash
# ---- Backend: lint, type, test ----
cd platform/backend && ruff check . && mypy app && pytest -q

# ---- Frontend: type, test ----
cd platform/frontend && npx tsc --noEmit && npx vitest run

# ---- INV-5: SQLite-correct idempotency; SKIP LOCKED / FOR UPDATE MUST NOT appear ----
grep -rn "SKIP LOCKED\|FOR UPDATE" platform/backend            # expect: empty
grep -rn "ON CONFLICT\|INSERT OR IGNORE" platform/backend/app  # expect: non-empty (claim-lock)

# ---- INV-8: Codex budget/turns rejected; capability branch present ----
grep -rn "supports_budget\|supports_max_turns" platform/backend/app   # expect: non-empty
grep -rn "unsupported_for_agent" platform/backend/app                 # expect: non-empty

# ---- INV-12: observer bridges via call_soon_threadsafe; never schedules coroutines ----
grep -rn "call_soon_threadsafe" platform/backend/app/sse                       # expect: non-empty
grep -rn "create_task\|run_coroutine_threadsafe" platform/backend/app/sse/observer_bridge.py   # expect: empty

# ---- INV-2: SSE cookie auth; token NEVER in an EventSource URL ----
grep -rnE "token=|\?.*token" platform/frontend/src | grep -i eventsource   # expect: empty
grep -rni "HttpOnly\|SameSite" platform/backend/app/sse                     # expect: non-empty

# ---- INV-9: resolve-exactly-once guard; no in-place-resume over-claim ----
grep -rni "status='pending'\|status=\"pending\"" platform/backend/app/hitl/answer.py   # expect: non-empty
grep -rni "resumes exactly\|resume in place" platform                                   # expect: empty

# ---- INV-7: segment-sum dedups by task_index ----
grep -rni "task_index" platform/backend/app/runs/meters.py    # expect: non-empty

# ---- NFR-SEC-5: PR-push approval gate exists ----
grep -rni "pr.push\|pr_push\|approval.*gate\|push.*approval" platform/backend/app/hitl/pr_gate.py   # expect: non-empty

# ---- INV-14: no hardcoded hex outside the tokens file ----
grep -rnE "#[0-9a-fA-F]{3,8}\b" platform/frontend/src --include=*.tsx --include=*.ts \
  | grep -v "styles/tokens.css"               # expect: empty
bash scripts/hooks/post-edit-no-hardcoded-hex.sh   # convention hook, expect: empty/pass

# ---- Engine untouched (INV-13) ----
git diff --name-only main..HEAD -- dkmv/      # expect: empty
```

## 10. Test plan

**Backend (pytest):**
- `test_runs_launch`: §8.10 validation table (branch/feature_name/workflow/agent/context); **Codex budget/turns → `400 unsupported_for_agent`**, Claude same body → `201`; agent resolution `auto→workflow.agent` (AC-1, AC-4, AC-6).
- `test_launch_idempotency`: concurrent double-`POST /runs` → one row + one `409 duplicate_dispatch`; **no `SKIP LOCKED`** anywhere; returns the platform UUID; issue → `agent:in-progress` via the write-queue (AC-2, AC-3, INV-5).
- `test_run_reads`: `GET /issues/{num}`, `GET /runs`, `GET /runs/{id}` baseline shapes; Codex `cost_usd=null` (AC-5).
- `test_observer_bridge`: `on_event` from a non-loop thread → event on the queue via `call_soon_threadsafe`; observer never calls `create_task`/`run_coroutine_threadsafe`; slow-consumer drops meter frames but never `task_completed`/decision/lifecycle (AC-8, INV-12).
- `test_sse_endpoint`: heartbeat ≤15 s; `Cache-Control`/`X-Accel-Buffering` headers; cookie auth 401-without/200-with; Origin/Host mismatch rejected; **no token in URL** (AC-9, AC-10, INV-2).
- `test_sse_replay`: `Last-Event-ID` subscribe-before-read → **no gaps, no duplicates**; paused-run reconnect rehydrates from `GET /runs/{id}` (AC-11).
- `test_segment_sum_meter`: **multi-stage run cost climbs across stage boundaries to the run total and never resets toward $0**; dedup by `task_index`; `task_completed`/`task_failed` meter-critical; mixed Claude+Codex → Codex "—"/excluded, tokens counted (AC-12, AC-13, INV-7, INV-8).
- `test_run_actions`: Stop-during-pause → `stop(force=True)`; one-shot `execute_in_container` (no PTY) (AC-15).
- `test_hitl_bridge`: pause writes `pause_decisions`, sets `agent:paused`, **releases the slot**, emits `pause_requested`, awaits the keyed event (AC-18, INV-9).
- `test_answer_resolve_once`: **double-submit / racing-timeout → exactly one resolution** (second → `409 pause_already_resolved`); resume returns `PauseResponse(value, skip_remaining)`; `decision` event appended (AC-17, INV-9).
- `test_pause_timeout`: `now() >= timeout_at` → single `resolved_by='timeout'` auto-abort via the exactly-once guard (AC-20).
- `test_pr_push_gate`: an injected-instruction issue body still pauses for human approval before the PR push (AC-21, NFR-SEC-5).
- `test_secret_hygiene` (no regression): the event-pump never persists a raw secret to `events` (INV-4).

**Frontend (vitest + render):**
- `IssueDetail.test`: markdown renderer (`###`/lists/`code`/`**bold**`); paused vs running existing-run alert; **Run with {Claude|Codex}** posts `resolvedAgent` (AC-7).
- `RunPanel.test`: workflow picker from `GET /workflows` (no inlined `WORKFLOWS`); **Codex hides budget/turn fields + shows "time-bounded, not cost-bounded"**; Claude shows them (AC-6).
- `LiveRun.test`: meters row + stage tracker + Friendly/Raw feed (**Raw renders inner `RuntimeEvent.data`**) + rail render; cost accent when live; Codex cost "—" (AC-13, AC-14, AC-16).
- `PauseCard.test`: engine option shape `{value,label,description?}`; **recommended tracks `value==default`**; Approve posts the chosen **value**; Ship-as-is/Abort set `skip_remaining` (AC-19).
- A repo-wide no-hardcoded-hex assertion mirrors the INV-14 grep.

**Phase exit gate (per `CLAUDE.md`):** all AC checked off, every command in §9 passes, the §10 suites are green, and `ruff`/`mypy`/`tsc`/`vitest` are clean. Then update `progress.md` and proceed to Phase 3.

---

**PRD version:** v1.1 · **Phase:** 2 (M2) · **Features:** F7, F8, F9 · **Tasks:** T059–T087 · **ADRs:** ADR-P003, ADR-P007, ADR-P009 · Generated against `_conventions.md` INV-1..15.
