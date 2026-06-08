# PRD — DKMV Platform v1 (Agent Control Plane)

**Status:** Draft v1.1 (revised after multi-domain best-practices + engine-fit review; for dev-team handoff)
**Owner:** Tawab (asaficontact)
**Last updated:** 2026-06-07
**Type:** New product — a web platform built in a **separate repo inside the DKMV directory**, wrapping the existing DKMV engine.

> **v1.1 changelog (what changed from v1):** Corrected three engine-reality items — crash recovery cannot re-attach to a live run (§8.2; now kill-orphan + `interrupted` + `start_task` retry), durable-HITL overclaim (§8.5; decision durable, run resumes only from a pushed boundary), and the per-task-cumulative **cost-meter aggregation** (§6.4/§8.3 segment-sum). Reconciled the **Codex no-budget** contradiction (NFR-COST-1: timeout-only for no-budget agents). Resolved the **EventSource-auth vs loopback-token** conflict (§8.3 HttpOnly cookie). Corrected the **SQLite claim-lock** to a `UNIQUE`-key atomic insert + mandated WAL/`busy_timeout`/single-writer pragmas + indexes/FK/Alembic/backup/spend-projection (§6.5). Added **orchestration** completeness (graceful drain, idempotent retries, aggregate admission control, loop observability). Hardened **security** to the minimum-responsible bar (gVisor runtime, default-on egress allowlist, repo-scoped tokens, brokered socket, Host/CSRF, prompt-injection LLM01 + PR-push approval gate). Switched GitHub to **PAT-first + poll-only** (App/webhooks deferred) with a real `set_agent_state` label primitive + state-machine completeness. Added **API contracts (§8.9)**, **validation (§8.10)**, a **happy-path sequence (§8.11)**, and a **dev-env/config (§8.8)**. **Descoped** the Workflow Builder to a read-only viewer (N7) and **deferred** OTel/Redis/Postgres (N8). Updated risks (R-3/5/11/13 + new R-14..R-17), engine asks (+re-attach, checkpointing, Codex cost), open questions (OQ-1/3/4/5 resolved), milestones, and acceptance tests.

---

## 0. How to read this document

This PRD specifies a **web platform ("DKMV Platform")** that turns GitHub Issues into autonomous coding-agent runs. It is grounded in three sources, which it must stay faithful to:

1. **The UI prototype & design docs** at `/Users/tawab/Projects/DKMV/docs/design_docs/platform/` — the 9-page `DKMV — Design Overview (PDF).pdf`, the React/JSX prototype (`data.jsx`, `connect.jsx`, `issue.jsx`, `run.jsx`, `history.jsx`, `settings.jsx`, `components.jsx`, `styles.css`, `DKMV.html`), and the companion spec `/Users/tawab/Projects/DKMV/dkmv_dashboard_design_prompt.md`.
2. **The existing DKMV engine** at `/Users/tawab/Projects/DKMV/dkmv/` — in particular its embedded API `dkmv/runtime/` (`EmbeddedRuntime`, `RunHandle`, `EventObserver`, `PauseRequest`/`PauseResponse`).
3. **Best-practice research** (see §13 References) on orchestrating long-running agent jobs, GitHub integration, streaming, HITL, and secrets.

Where the prototype and the engine disagree on a value, the engine is authoritative for data shapes and the prototype is authoritative for UX. Both are cited inline.

> **Prototype completeness caveat (must read):** The prototype implements Screens 01, 03, 04, 05, 06 and Settings as JSX. **Screen 02 (Board), Screen 07 (Workflows — read-only viewer in v1, §5.8), and the global chrome/navigation are specified only in the PDF + `dkmv_dashboard_design_prompt.md`** — their `board.jsx`, `builder.jsx`, `chrome.jsx`, and `app.jsx` are referenced by `DKMV.html` but are **not present** in the repo. Treat those three as design-spec-only and build them to the written spec.

---

## 1. Overview & problem statement

DKMV (the engine) already runs multi-stage, multi-agent coding workflows ("components") inside isolated Docker sandboxes, driven from a CLI. It has no daemon, no GitHub Issues integration, no concurrency dispatcher, and no UI. Today a developer must invoke each run by hand and watch a terminal.

**DKMV Platform** is the missing control plane: a self-hostable web app where a solo developer **connects a GitHub repo, sees its issues on a Kanban board, assigns each issue a workflow + agent, presses Run, and watches the agent work to a pull request** — with live cost/token meters, human-in-the-loop approval checkpoints, run history, and spend analytics. The product promise from the design overview: **"Assign it and walk away."**

It is explicitly modeled on OpenAI's Symphony (issue-tracker-as-control-plane, poll/dispatch/reconcile orchestrator) but: (a) built on **GitHub Issues** with **labels as the state machine**, (b) running **DKMV's richer multi-stage pipelines** instead of a single prompt, (c) **multi-agent** (Claude Code *and* Codex), and (d) with **stronger Docker isolation** than Symphony's bare per-issue dirs. Execution is **local Docker now**, designed so **dedicated cloud VMs** are a later swap, not a rewrite.

## 2. Goals & non-goals

### 2.1 Goals (v1)

- G1. Connect a GitHub account, pick **one repository** ("project"), and import its issues. (Design Screen 01.)
- G2. Show issues on a **Kanban board** keyed by an `agent:*` label state machine; let the user drag issues between Backlog/Queued. (Screen 02.)
- G3. From an **issue detail** screen, pick a **workflow** (DKMV component) + **agent** (Claude/Codex/Auto) + guardrails (branch, budget, turns, timeout, memory, context), and **launch a run**. (Screen 03.)
- G4. **Watch a run live**: streaming event feed (friendly + raw), real-time meters (elapsed, cost, tokens in/out, turns, progress), a stage tracker, run-config rail, sandbox health, artifacts, linked PR, and a Stop control. (Screen 04.)
- G5. **Human-in-the-loop**: when a workflow pauses, surface a **decision card**; the user approves an option / ships as-is / aborts; the run resumes. (Screen 05.)
- G6. **Runs history & analytics**: aggregate stats (total runs, success rate, total spend, tokens, agent-hours, daily spend chart), rate-limit health, a retry queue, and a sortable/filterable runs table. (Screen 06.)
- G7. **Workflows viewer (v1)**: a read-only Workflows screen listing built-in + registered components with pipeline summary and a YAML view (Screen 07). *Full form-based authoring (create/edit components, pause-question builder, for-each) is deferred to v1.1 — see §5.8 / N7.*
- G8. **Bounded concurrency**: run multiple issues at once with a global (and optional per-state) cap, with retries + reconciliation + crash recovery.
- G9. **Self-hostable by a solo developer** via `docker compose up`, wrapping the DKMV engine's `EmbeddedRuntime`.

### 2.2 Non-goals (v1)

- N1. Multi-tenant SaaS, orgs, roles/RBAC. (Solo, single-user, single active project. Schema must *anticipate* tenancy — see §6.)
- N2. Cloud/remote execution. (Design the `Executor` seam now; ship `LocalDockerExecutor` only.)
- N3. Trackers other than GitHub Issues (no Linear/Jira). GitHub Projects v2 status is a later opt-in; labels are the v1 state machine.
- N4. Editing/authoring issues inside DKMV (issues are authored on GitHub).
- N5. Mobile-native UI (desktop-first web; tablet acceptable).
- N6. Changing the DKMV engine's public contracts. The platform consumes `dkmv/runtime/` as-is; any engine change is a separately-scoped PR (see §11 Engine asks).
- N7. **Full workflow authoring UI** (form→YAML builder, pause-question editor, for-each UX). v1 ships a read-only Workflows viewer; authoring is v1.1 (§5.8).
- N8. **Full OpenTelemetry GenAI tracing, Redis fan-out, and the Postgres repository abstraction** are post-v1 (structured logs + in-process fan-out + direct SQLite for v1); the nullable `tenant_id` hedge stays.

## 3. Personas & top user stories

**Persona — "Solo dev / power user" (primary and only v1 persona).** Runs DKMV on their own repos (e.g. `asaficontact/DKMV`), one project at a time, self-hosted on their machine. Comfortable with GitHub, cost-conscious about agents, wants to "assign and walk away" but retain control at checkpoints.

Top stories (full backlog in §5):
- US1. *As a solo dev, I connect GitHub and pick a repo so my issues appear on a board.*
- US2. *As a solo dev, I assign issue #247 the `dev` workflow with Codex and press Run, so an agent fixes it and opens a PR.*
- US3. *As a solo dev, I watch a run's live cost and events so I trust what's happening and can stop it if it goes wrong.*
- US4. *As a solo dev, when the `plan` workflow pauses after Analyze, I pick "Proceed with all 4 phases" so it continues.*
- US5. *As a solo dev, I review my runs history and daily spend so I understand cost.*
- US6. *As a solo dev, I author a custom `qa` workflow with a pause after Evaluate so future runs follow my process.*
- US7. *As a solo dev, I run several issues concurrently within a budget so I clear the backlog faster.*

## 4. Product principles (from the design docs)

- P1. **Simple first, depth on demand (progressive disclosure).** Default views are uncluttered; raw logs, token breakdowns, retry internals live one click deeper.
- P2. **Always answer "what's happening / what do I do next."** Every screen has one obvious primary action and a clear status.
- P3. **Trust through visibility.** Live progress, running cost, and an always-reachable Stop.
- P4. **Friendly, not corporate.** Warm plain-language microcopy ("Run with Claude", "Approve & continue").
- P5. **Status is sacred.** One consistent state palette + badge style everywhere (board card, run header, history row, sidebar chip).
- P6. **Cost is always visible during runs** and summarized after.

---

## 5. Functional requirements — screen by screen

Each screen lists: the data it reads, the actions, the states, and the backend it requires. Field names and example values are taken verbatim from `data.jsx`/`styles.css` unless noted. The board state machine is in §5.3.1.

### 5.1 Global chrome & navigation (spec-only — build to `dkmv_dashboard_design_prompt.md` §5)

- FR-NAV-1. **Left sidebar (collapsible):** project switcher at top (repo name + avatar, e.g. "DK… · asaficontact"); a global **"+ New run"** button; primary nav **Board / Runs / Workflows / Settings**; a bottom **live status chip** showing active work, e.g. *"2 running · $12.40 · 1 needs you"*, linking to the active/paused run. When a run is **paused**, show an amber dot + count ("1 needs you").
- FR-NAV-2. **Top bar:** breadcrumb / page title; a **Refresh** affordance with a "last synced 12s ago" indicator (board/runs poll for updates); theme toggle (dark default); GitHub account avatar.
- FR-NAV-3. **Theme:** dark is the hero. Active theme is `data-mode="dark" data-theme="indigo"` (persisted to `localStorage` keys `dkmv-mode`, `dkmv-skin`). Six selectable skins exist (ember/indigo/evergreen/graphite/plum/rose); indigo is the v1 default accent (`#7b7bf5`). (See §7 tokens.)
- FR-NAV-4. **Persistent active-runs presence:** from any screen, the user can jump back to a live or paused run.

### 5.2 Screen 01 — Connect & project picker (`connect.jsx`)

- FR-01-1. Local state machine `disconnected → connecting → picker → syncing` (top Segmented tabs Welcome / Pick repo / Syncing).
- FR-01-2. **Disconnected:** hero "Turn your GitHub issues into work that runs itself.", a primary **Connect GitHub** button, and the reassurance line *"Read-only on your code. We only read issues and add `agent:*` labels. Nothing runs until you say so."*
- FR-01-3. **Connect** triggers GitHub auth (see §8.1). On success → **picker**.
- FR-01-4. **Picker:** searchable repo list from `GET /repos` (fields `{org, name, lang, langColor, private, updated, issues, stars?, desc?}`; e.g. `asaficontact/DKMV`, Python, private, 12 issues). Selecting a repo shows a "What we'll do" card (Read issues / Add `agent:*` labels / Nothing runs until Run) and a **Preflight** box (see FR-01-6). Primary: **Open project** → **syncing**.
- FR-01-5. **Syncing:** "Importing your issues…", indeterminate progress; on completion → Board.
- FR-01-6. **Preflight** renders standing environment checks via **`EmbeddedRuntime.get_capabilities()`** (the component-agnostic health call): GitHub connected, Anthropic API key present (`sk-ant-•••••4f2a` masked), Docker available + sandbox image `dkmv-sandbox:latest` present. Each row shows ok/blocker. Backend: `GET /preflight`. *(Note: `preflight_check(component, source)` is **per-launch** and requires a component + source — use it at run-launch time in FR-03-3, not for the standing checklist.)*

### 5.3 Screen 02 — Board (HOME) — issues by agent state (spec-only — build to design prompt §6)

#### 5.3.1 Board state machine (label → column) — **authoritative**

| Column | GitHub condition | engine/run meaning |
|---|---|---|
| **Backlog** | no `agent:*` label | not assigned |
| **Queued** | `agent:queued` | ready to run |
| **In Progress** | `agent:in-progress` | a run is live |
| **Needs You** | `agent:paused` | run paused for a decision |
| **In Review** | `agent:review` | PR open, awaiting human |
| **Done** | issue closed / PR merged | merged |

(Columns + mapping from `data.jsx COLUMNS` and design prompt §8.)

- FR-02-1. Render the six columns left→right with horizontal scroll. Each column header shows a count; **In Progress** also shows aggregate live cost.
- FR-02-2. **Issue card:** number + title; ~2 GitHub labels (color from `LABELS` map, §7.4); if assigned, a **workflow chip** + **agent chip**; if running, a **live mini-meter** (turn count + running cost + thin progress bar with the blue running pulse, from `liveCost/liveTurns/progress`); assignee avatar; a "⋯" menu (Assign workflow, Run, Open on GitHub, Stop). "Needs You" cards get amber treatment + a **Review decision** button.
- FR-02-3. Cards are **draggable** between Backlog ↔ Queued, which sets/clears the `agent:queued` label via `POST /issues/{num}/agent-state` → the `set_agent_state` replace-all primitive (§8.1), preserving single-occupancy. Clicking a card → Issue detail.
- FR-02-4. **Aggregate strip** (Symphony-style, compact): *"{in_progress} in progress · {needs_you} needs you · ${spent_today} spent today · {tokens_today} tokens."* "Spent today" follows the Codex caveat FR-06-1a (Codex runs contribute $0 from the engine and are excluded from the spend figure; their tokens still count).
- FR-02-5. **Filter bar:** by label / workflow / agent / state. **"+ Run an issue"** primary.
- FR-02-6. States: **Populated** (hero), **Empty** (friendly illustration + "Create an issue on GitHub or import"), **Syncing**.
- FR-02-7. Backend: `GET /repos/{repo}/issues` (paginated; returns the `ISSUES` shape with `state` derived per §5.3.1 + the authority rule §8.1), `POST /issues/{num}/agent-state`, and the board aggregate counters.

### 5.4 Screen 03 — Issue detail & launch (`issue.jsx`)

- FR-03-1. Two-pane layout `minmax(0,1fr) 408px`. **Left:** `#num` + state badge; branch caption ("on `feat/codex`") + "Open on GitHub" when a run exists; H1 title; author row + GitHub label pills; **if a run exists**, an alert card — paused variant (amber, "This run is paused and needs your decision", **Review decision**) or running variant (blue, "A run is in progress", **Watch live**) showing the run id; markdown body (renderer supports `###`, ordered/unordered lists, `` `code` ``, `**bold**`); comments thread.
- FR-03-2. **Right "Run this issue" panel:**
  - **Workflow** picker — cards from `WORKFLOWS` showing emoji, name, purpose, stage chain (chevrons), a **"pauses"** badge if `pauses`, and "Est. {budget} · {estTime}". Built-ins: `plan/dev/qa/docs/ship` (table §7.2).
  - **Agent** — `auto | claude | codex`; Auto shows "→ {model}" (resolves to the workflow's default agent).
  - **Branch** — prefilled `dkmv/issue-{num}-{slug}`, editable, mono.
  - **Advanced guardrails** (collapsed): Max budget ($), Max turns, Timeout (min), Memory (default "8g"), Extra context files.
  - **Sticky footer:** est. line "Est. **{budget}** · {estTime} · pauses once for you" (if it pauses); **Queue for later** + **Run with {Claude|Codex}**.
- FR-03-3. **Launch** posts `POST /runs` (body in §8.4) and navigates to the live run. `resolvedAgent = agent === "auto" ? workflow.agent : agent`.
- FR-03-4. If the issue already has a run, show its status inline with links to the live run / history; allow reassigning the workflow.

### 5.5 Screen 04 — Live run (`run.jsx`) — observability

- FR-04-1. Header: run-status badge (Running / Paused · needs you / Completed / Failed); run id (mono); "#{num} {title}"; workflow chip; agent chip + model; branch. Right actions by state: **⋯ menu** (**Run a command in the container** — a one-shot exec via the engine's `execute_in_container`, *not* an interactive PTY, which the engine doesn't expose; Keep alive on finish) when live; **Stop** (danger) when running/paused; **Retry run** when failed; **View PR #{pr}** when completed.
- FR-04-2. **Meters row** (mono, animating): **elapsed** (`{m}m {ss}s`), **cost** (`$x.xx`, accent when live; computed via the **segment-sum** rule §8.3/§6.4 — *not* a single `cost_usd` field), **tokens (in · out)**, **turns** (segment-sum), and **overall progress** bar with %. For Codex runs the engine reports cost `$0.00`; render "—" not "$0.00", and bound by timeout not budget (see R-10, FR-06-1a, NFR-COST-1).
- FR-04-3. **Stage tracker:** a stepper of the workflow's stages with per-stage status (done ✓ / running ● / paused ⏸ / pending ○) and `${cost} · {turns}t · {dur}`. Examples: `dev` → 3 phases (`RUN_STAGES`); `plan` → Analyze → Features & Stories → Phases → Assembly → Evaluate-Fix. Stages are clickable to expand when not pending.
- FR-04-4. **Event feed:** live auto-scrolling feed with a **Friendly | Raw** toggle.
  - Friendly: rows with time, emoji icon, text (with `` `code` `` highlight), optional tool badge; color-coded by kind (`system/assistant/tool/error/ok/decision/result`); a "thinking…" row while live.
  - Raw: each event rendered as the inner `RuntimeEvent.data` stream JSON line `{ "type", "subtype", "content", "tool_name"?, "total_cost_usd"?, "num_turns" }` (see §6.4). A search/filter is present.
- FR-04-5. **Right rail (collapsible):** **Run config** snapshot (`repo, branch, feature_name, model, max_turns, timeout_minutes, max_budget_usd, memory_limit` — verbatim keys), **Sandbox** (`dkmv-sandbox:latest`, "8g · 2 vCPU · healthy"), **Artifacts** (as produced, e.g. `analysis.json`, `qa_evaluation.json`, `GUIDE.md`, live `session.log`), **Pull request** (number, title, checks status) when present.
- FR-04-6. **Live updates** stream over SSE (§8.3). Meter updates are coalesced server-side (≤4 Hz); discrete lifecycle/decision events are never dropped. Reconnect resumes via `Last-Event-ID` (§8.3).
- FR-04-7. **States:** Running (hero) · Paused (decision card, §5.6) · Completed (success banner: Total cost / Tokens / Turns / Duration — Total cost shows "—" for Codex per FR-06-1a; Open PR / Run next stage / Back to board; "Issue moved to In Review") · Failed/Timed-out (clear error from `run.error`, auto-retry "attempt N of 3 · backoff due in …", Retry now / Open logs).

### 5.6 Screen 05 — Human-in-the-loop checkpoint (`PauseCard` in `run.jsx`)

- FR-05-1. When a run pauses, render an **amber decision card** inline (and mark the issue `agent:paused` → "Needs You").
- FR-05-2. Card content maps to the engine's `PauseRequest` (`dkmv/tasks/pause.py`): status badge `PAUSED · after {task_name}` + "This run needs your decision to continue"; the **question** (`PauseQuestion.question`); a **context blurb** (`context.summary`); **options** as radio rows (display `label` bold + optional `description`; the underlying choice value is the option's `value`), with the option whose `value` equals `default` marked **"recommended"**.
- FR-05-3. **Actions:** **Approve & continue** → `POST /runs/{id}/answer` with `{answers:{question_id: <chosen option value>}, skip_remaining:false}`; **Ship as-is** and **Abort** set `skip_remaining:true`. On answer a `decision` event is appended ("You chose: '{label}'") and the run resumes.
- FR-05-4. Example (verbatim from `data.jsx PAUSE_REQUEST`): task `Analyze`; question "I found 4 candidate phases for this implementation. How would you like to proceed?"; options "Proceed with all 4 phases" (recommended) / "Merge phases 3 & 4" / "Let me edit the plan first".
- FR-05-5. **Durability & timeout** (see §8.5): the pause **decision** is persisted (DB) and resolved exactly-once; it carries a UTC `timeout_at` (default 60 min → auto-abort) re-evaluated each tick so a paused run never hangs and an idle container never holds a concurrency slot. **Honest scope:** across a backend restart the *decision* survives but the *suspended run* does not — it is re-launchable from the last pushed task boundary via `start_task`, else marked `interrupted` (§8.5.5). UI copy must not promise "resumes exactly where it left off."

### 5.7 Screen 06 — Runs history & analytics (`history.jsx`)

- FR-06-1. **Aggregate cards:** Total runs (`RUNS.length`); Success rate (`completed/(completed+failed)`, e.g. **88%**, "{completed} completed"); Total spend (Σcost, accent); Tokens (Σ(in+out)/1000 → "…k"); Agent-hours (Σdur/3600); plus a **SpendChart** (daily bars, last bar accent, total label).
- FR-06-1a. **Codex cost caveat (binding).** The engine's Codex adapter reports `total_cost_usd = 0.0` (it cannot price runs). Therefore Total spend, the SpendChart, the board "spent today" (FR-02-4), and each completed run's "Total cost" (FR-04-7) **must not silently sum Codex at $0**. Per OQ-5, render Codex cost as "—" and **exclude $0-cost Codex runs from spend aggregates** (count their tokens/agent-hours normally), with a small "excludes Codex (cost not reported)" footnote on spend cards. **Note:** the prototype `RUNS` mock shows *non-zero* Codex costs (e.g. `$9.86`, `$8.90`) — this is illustrative only and is NOT representative of engine behavior; do not build spend math from those values.
- FR-06-2. **Rate-limit health row:** "Rate limits healthy · Anthropic 38% · OpenAI 12% used this hour" + a usage bar (from GitHub/model `X-RateLimit-*` headers and per-provider accounting).
- FR-06-3. **Retry queue** (collapsible, amber): rows `{id, issue, attempt N/3, dueIn, lastError}` (from `RETRY_QUEUE`). `POST /runs/{id}/retry`.
- FR-06-4. **Filters:** workflow / agent / status. **Runs table** (sortable on id/status/cost/turns/dur/started): columns Run (mono id), Issue (#num + title), Workflow, Agent (+model), Status, Cost, Turns, Duration, Started, PR/chevron. Row click → the run view (read-only for finished runs).
- FR-06-5. Status enum in the table: `running | paused | completed | failed | cancelled | timed_out` (engine `RunStatus`, §6.3; `timed_out` renders with the `failed` palette + a "timed out" label, `interrupted` — platform-only — renders with the `cancel` palette). Empty state: "No runs yet · Run your first issue".
- FR-06-6. Backend: `GET /runs` (filters), `GET /runs/{id}` (detail), `GET /stats`, `GET /retry-queue`.

### 5.8 Screen 07 — Workflows (v1 = read-only viewer; full authoring → v1.1)

> **Scope decision:** full form→YAML authoring (the questions/options sub-builder, `for-each` UX, per-task IO editor) is the highest-drift, lowest-relative-value screen for a solo dev who already has 5 working built-ins, and it's spec-only prose with no `builder.jsx` (R-12). **v1 ships a read-only Workflows viewer**; **full authoring is deferred to v1.1** (gated on a `builder.jsx` design spike). FR-07-1v below is the v1 requirement; FR-07-1..6 are the v1.1 target, retained for reference.

- **FR-07-1v (v1 — read-only viewer).** List built-in + registered components (via `list_components`); for each, show the pipeline summary (ordered stages, per-stage budget, pause points, est. total — the `qa` example: 3 stages / 1 pause / $2.00) and a **read-only "compiles to YAML" view** of `component.yaml` + task files. Editing is disabled with a "Workflow authoring coming in v1.1 — edit the YAML directly for now" note. Custom components authored on disk + `ComponentRegistry.register` still appear and are runnable. Backend (v1): `GET /workflows`, `GET /workflows/{id}` (read-only).

**v1.1 target (full authoring — deferred):**
- FR-07-1. **Workflow (component) editor:** `name`, `description`, **defaults** (`agent`, `model`, `max_turns`, `timeout_minutes`, `max_budget_usd`), **component inputs** (e.g. `impl_docs`, type `file`, src `{{ impl_docs_path }}`, dest `impl_docs/`), **agent instructions** (free text), and an **ordered, drag-reorderable task list** (each row: name, pauses-after?, for-each?, budget).
- FR-07-2. **Pipeline summary** rail: ordered stages with per-stage budget, total **Stages** count, **Pause points** count, **Est. total budget**. Authoritative qa example: 3 stages (Evaluate → Fix → Re-evaluate), **1 pause** (after Evaluate), **$2.00 total** (`max_budget_usd: 2.00`). *(Per-stage $0.80/$0.80/$0.40 in the prototype is an illustrative split; only the $2.00 total is authoritative.)*
- FR-07-3. **Task editor** (drawer/sub-page): name + description; **Prompt** (markdown/code editor + preview); **Instructions/rules**; **Inputs** (type `file|text|env`, src/dest/content/key/value); **Outputs** (`path`, `required?`, `save?`, `required_fields[]`); **commit/push** toggles; per-task overrides (agent/model/max_turns/timeout/max_budget); **pause-after** with a questions+options builder (question text, options `label`+`description`, `default`).
- FR-07-4. **Templates:** start from `plan / dev / qa / docs / blank`. A read-only "compiles to YAML" peek (progressive disclosure); the primary editing experience is form-based.
- FR-07-5. **Persistence:** the platform writes `component.yaml` + task `*.yaml` into a component directory inside the project, then calls the DKMV registry (`ComponentRegistry.register(project_root, name, path)` → `.dkmv/components.json`). Validate before saving with `EmbeddedRuntime.validate_component(...)`; preview ordering with `preview_execution_plan(...)`. Backend: `GET/POST/PUT /workflows`.
- FR-07-6. **"Test run on an issue"** action launches a normal run using the edited component.

### 5.9 Settings (`settings.jsx`)

- FR-SET-1. **Preflight** section (same checks as FR-01-6). **GitHub** ("Connected · read issues, write `agent:*` labels", **Switch repo** → Connect). **Defaults** (default agent, default memory "8g", default timeout "30m", spend alert "$25.00 / day"). Backend: `GET/PUT /settings`, `GET /preflight`.

---

## 6. Data model & engine contracts

The platform maintains **its own DB** (the source of truth for queryable state, §6.5) while treating the engine's on-disk run artifacts as the raw log/blob store. The DB mirrors engine data using the shapes below.

### 6.1 Domain entities (from `data.jsx`, authoritative for the UI contract)

- **Issue:** `num, title, state (backlog|queued|progress|needsyou|review|done), labels[], workflow (id|null), agent (claude|codex|auto|null), assignee, body, liveCost?, liveTurns?, progress? (0–1), phase?, comments[], run?, pr?, prTitle?`.
- **Workflow (component):** `id, name, emoji, purpose, stages[], pausesAfter, pauses, budget, budgetRange, estTime, model, agent, maxTurns, timeout, maxBudget`. (Built-ins table §7.2.)
- **Agent:** `claude {name:"Claude", model:"claude-sonnet-4-6", color:"#ff6b4a", short:"C"}`, `codex {name:"Codex", model:"gpt-5.1-codex", color:"#34c98a", short:"Cx"}`. *(Drift note: the engine's actual Codex default is `gpt-5.4` (`dkmv/adapters/codex.py`); the prototype's `gpt-5.1-codex` is a UI label only — populate the model picker from the engine adapter defaults, not this constant.)*
- **Run:** `id, issue, issueTitle, wf, agent, model, status, cost, tokensIn, tokensOut, turns, dur (sec|null), started, branch, pr (num|null), error?`.
- **RunStage:** `{name, status (done|running|paused|pending), cost, turns, dur}`.
- **RunEvent:** `{kind (system|assistant|tool|error|ok|decision|result), icon, text, t ("MM:SS"), turn, tool?}`.
- **PauseRequest** (engine, `dkmv/tasks/pause.py` + `_build_pause_request`; UI usage §5.6): `{task_name, context{}, questions:[{id, question, options:[{value, label, description?}], default}]}`. **Engine-authoritative shape:** each option MUST carry both `value` and `label` (`description` optional) — the engine *drops* options missing either (`component.py` `clean_options`). `default` matches an option's `value`. **PauseResponse:** `{answers:{question_id → chosen option `value`}, skip_remaining}` (the engine stores `answers[question_id]` verbatim as the question's `user_answer`). *(The `data.jsx PAUSE_REQUEST` mock uses `{label, description}` without `value` — that is a prototype simplification; build to the engine shape.)*
- **RetryEntry:** `{id, issue, attempt, dueIn, lastError}`.
- **Repo:** `{org, name, lang, langColor, private, updated, issues, stars?, desc?}`.
- **Preflight check:** `{id, label, sub, ok}`.

### 6.2 Engine embedded API (the platform's primary integration — `dkmv/runtime/`)

The backend **calls `EmbeddedRuntime` directly; it does not shell the CLI.** Key surface (verbatim signatures):

- `EmbeddedRuntime(config: RuntimeConfig | None, output_dir: Path | None)`.
- `async start(component, source: ExecutionSource, feature_name="", variables=None, agent=None, model=None, max_turns=None, timeout_minutes=None, max_budget_usd=None, memory=None, on_pause=None, context_paths=None, start_task=None, keep_alive=False, docker_socket=False) -> RunHandle` — **non-blocking**; spawns an `asyncio.Task`; `run_id` back-fills once `RunManager.start_run` fires.
- `RunHandle`: `.run_id`, `.status` (engine `RunStatus`), `.result`, `.events`, `add_observer(EventObserver)`, `remove_observer`, `await wait(timeout=None)`, `await stop(force=False)`, `inspect()`.
- `EventObserver` is a **sync** `on_event(event: RuntimeEvent) -> None` callback (the platform's observer must push to an `asyncio.Queue` and not block).
- `RuntimeEvent`: `sequence, timestamp, run_id, task_name, task_index, step_instance, event_type, data{}, content, cost_usd, turns`.
- Introspection: `inspect_component`, `validate_component`, `list_components`, `preview_execution_plan`, `get_capabilities`, `preflight_check`.
- History/artifacts/telemetry: `list_runs`, `get_run`, `list_artifacts`, `get_artifact`, `get_stats`, `replay_events(run_id, offset)` (the reconnect primitive), `get_handle`, `active_runs`.
- Container ops (retained containers): `get_container_status`, `execute_in_container`, `export_workspace`; retention/reconcile: `cleanup_runs`, `reconcile_stale_runs`.
- Config injection: `RuntimeConfig(anthropic_api_key, claude_oauth_token, github_token, codex_api_key, default_model, default_max_turns, image_name, output_dir, timeout_minutes, memory_limit, max_budget_usd, default_agent, docker_socket)`; `ExecutionSource(type: remote|local_snapshot, repo, branch, local_path, include_uncommitted, include_untracked)`.

### 6.3 Run status mapping

Engine `RunStatus = pending | running | paused | stopping | cancelled | completed | failed | timed_out`. UI state palette classes (from `components.jsx STATE_OF`): `progress→running`, `needsyou→paused`, `review→review`, `done|completed→done`, `failed|timed_out→failed`, `cancelled|pending→cancel`. The platform derives a run's "paused" state from the `pause_requested`/`pause_resolved` lifecycle events (the engine `RunHandle.status` does **not** flip to `"paused"` — see §10 R-7).

### 6.4 Event shape (two layers — read carefully)

There are **two nested layers**, and the UI reads different fields from each:

1. **Outer wrapper — engine `RuntimeEvent`** (`dkmv/runtime/_observer.py`), what the platform's `EventObserver` actually receives and what the SSE message body carries: `sequence, timestamp, run_id, task_name, task_index, step_instance, event_type, data{}, content, cost_usd, turns`.
2. **Inner raw stream dict — `RuntimeEvent.data{}`**, the original normalized agent stream line: `type (system|assistant|user|result), subtype (text|tool_use|tool_result), content, tool_name, tool_input, total_cost_usd, duration_ms, num_turns, session_id, is_error`.

**Field-mapping rules (binding):**
- The **live meters** (FR-04-2) read the **outer** `RuntimeEvent.cost_usd`/`RuntimeEvent.turns` — *not* the inner `total_cost_usd`/`num_turns` — **but these are cumulative *per task*, not per run.** Verified in the engine: a `result`/`task_completed` event's `cost_usd = result.total_cost_usd` for that task, and the run total is `sum(r.total_cost_usd for r in task_results)` (`dkmv/tasks/component.py`). **The displayed run cost MUST be the segment-sum** defined in §8.3 (sum of completed tasks' finals + latest-within-active-task, deduped by `task_index`), **not** `RuntimeEvent.cost_usd` directly (that would track only the current task and reset toward $0 at each stage boundary) and **not** `SUM(cost_usd)` over events (double-counts). `task_completed`/`task_failed` are meter-critical.
- The **Raw toggle** (FR-04-4) renders the **inner** `RuntimeEvent.data` dict (the `type/subtype/total_cost_usd/num_turns/...` JSON line).
- The **Friendly feed** derives its `kind/icon/text/tool` from `event_type` + `data`.

The platform wraps each `RuntimeEvent` as one SSE message whose `id` = the DB `events.id` (monotonic), enabling `Last-Event-ID` replay (§8.3).

### 6.5 Platform database (SQLite WAL v1 → Postgres later)

An **append-only event log + plain materialized projections** (not full event-sourcing ceremony — the `runs`/`run_stages` rows are a mutable read model; the `events` table is a durable stream + audit that also powers SSE replay). Tables (minimum):
- `projects(id, repo, default_branch, github_installation_id NULL, created_at, tenant_id NULL)`.
- `issues(repo, num, title, state, labels_json, workflow_id, agent, pr_num, updated_at, sync_cursor)` — cache/index of GitHub issues. PK `(repo, num)`.
- `runs(id PK = platform UUID, engine_run_id, repo, issue_num, workflow_id, agent, model, status, branch, feature_name, cost_usd, tokens_in, tokens_out, turns, duration_s, started_at, finished_at, pr_num, error, idempotency_key UNIQUE, tenant_id NULL)`. **PK is a platform-generated UUID** (the engine's `YYMMDD-HHMM-…-4hex` id is collision-weak under concurrency — R-8 — and is stored as the non-unique human-readable `engine_run_id`, which arrives *after* `start()` via the event stream).
- `run_stages(run_id FK, idx, name, status, cost_usd, turns, duration_s)`.
- `events(id INTEGER PK AUTOINCREMENT, run_id FK, sequence, ts, event_type, payload_json)` — **append-only**; the single source for SSE replay, audit, and meters. `id` is the monotonic SSE cursor.
- `pause_decisions(id, run_id FK, task_name, request_json, status (pending|answered|expired), answer_json, resolved_by (human|timeout), timeout_at, created_at)`.
- `run_totals(run_id PK FK, cost_usd, tokens_in, tokens_out, turns, duration_s)` — a **snapshot written at run completion** so `events` can be retention-pruned without losing spend/audit totals.
- `settings(key, value)` and `secrets` (encrypted, §8.6).
- **`spend` is a materialized projection, not a hand-maintained table** (resolves the prior indecision): computed from `events` as the **last cumulative `cost_usd` per `(run_id, task_index)` summed per run** (never `SUM` over all events — that double-counts), with **Codex runs excluded** from cost (FR-06-1a) while their tokens count. Daily/total rollups are SQL views over `run_totals` + active runs.

**Indexes & integrity (binding):** `UNIQUE(run_id, sequence)` and an index on `events(run_id, id)`; indexes on `runs(status, started_at)` (boot scan + history sort), `runs(issue_num)`, `pause_decisions(status, timeout_at)` (expiry sweep). Foreign keys on `run_stages/events/pause_decisions/run_totals → runs(id)` with `ON DELETE CASCADE`; **`PRAGMA foreign_keys=ON` per connection** (SQLite doesn't enforce FKs otherwise).

**Concurrency contract (binding — or NFR-SCALE-1's 5 runs × ~4 Hz will throw `database is locked`):** `PRAGMA journal_mode=WAL; synchronous=NORMAL; busy_timeout>=5000; foreign_keys=ON`; **all write transactions use `BEGIN IMMEDIATE`** and stay short; **all writes are serialized through a single dedicated writer task/connection** (event appends batched), with reads on separate connections. SQLite is single-writer — this is a feature here (it makes dispatch idempotency a `UNIQUE`-key insert, §8.2, not a lock table), not a limitation.

**Migrations & backup:** use **Alembic** (dialect-portable, supports the SQLite→Postgres path); ship a backup story (`VACUUM INTO` snapshot or litestream-style WAL streaming) since this single file is the source of truth for spend + audit.

**DB-vs-engine-disk reconciliation rule (two stores, one truth each):** the platform DB is authoritative for **live** state, queryable aggregates, and audit; the engine's on-disk `runs/{run_id}/` is the **artifact/blob store** (`analysis.json`, `GUIDE.md`, `session.log`, prompts) and is authoritative for a run's **final terminal totals** (its `result.json` is written in the engine's `finally`). On boot/reconcile, back-fill `run_totals`/`runs` from `result.json` for terminal runs; never run dashboards off the engine's O(N) `list_runs`/`get_stats` directory scans (read them once at ingest). Resolves OQ-4: the engine writes to a **platform-owned `output_dir`** via `RuntimeConfig`.

Rationale: the engine's file-per-run JSON/JSONL store isn't safe/queryable for dashboard aggregates or claim-locking. Keep `runs/{run_id}/` as the artifact store; the DB is the index + event log + cursor source. (See §13 — event sourcing on SQLite.)

---

## 7. Design system & tokens (from `styles.css`)

### 7.1 Theme

- Active: `data-mode="dark" data-theme="indigo"` (persist `dkmv-mode`, `dkmv-skin`). Indigo accent `#7b7bf5` (light `#5b54e0`). Six skins selectable.
- Surfaces computed via `oklch()` per skin (neutral hue/chroma tokens `--nh/--nc/--ncl`).

### 7.2 Built-in workflows (verbatim from `data.jsx WORKFLOWS`)

*(Model names below are UI labels from the prototype; populate the actual model picker from engine adapter defaults — see the drift note in §6.1, e.g. Codex default is `gpt-5.4`, not `gpt-5.1-codex`.)*

| id | emoji | purpose | stages | pausesAfter | pauses | budget | estTime | model | agent | maxTurns | timeout | maxBudget |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| plan | 🧭 | PRD → full implementation docs | Analyze, Features & Stories, Phases, Assembly, Evaluate-Fix | Analyze | true | ~$12 | ~40 min | claude-sonnet-4-6 | claude | 100 | 30 | 12 |
| dev | 🛠️ | Implement each phase from the plan docs | Implement-Phase ×N (for-each) | — | false | $10/phase¹ | ~25 min/phase | gpt-5.1-codex² | codex | 120 | 40³ | 10¹ |
| qa | 🔍 | Evaluate → fix → re-evaluate | Evaluate, Fix, Re-evaluate | Evaluate | true | ~$2 | ~15 min | claude-sonnet-4-6 | claude | 80 | 25 | 2 |
| docs | 📝 | Update docs + open a PR | Update-Docs, Verify, Create-PR | — | false | ~$3¹ | ~12 min | gpt-5.1-codex² | codex | 60 | 20³ | 3¹ |
| ship | 🚀 | analyze → plan → implement → evaluate-fix → finalize | Analyze, Plan, Implement, Evaluate-Fix, Finalize | Analyze | true | ~$29.50 | ~2 hr | claude-sonnet-4-6 | claude | 200 | 120 | 30 |

¹ For **Codex** workflows (`dev`, `docs`) the `budget`/`maxBudget` columns are **not enforceable** — Codex reports `$0` cost and supports no budget/turn cap; **`timeout` is the only guardrail** (NFR-COST-1, R-10). ² Model is a prototype UI label; populate the picker from engine adapter defaults (Codex default is `gpt-5.4`, §6.1). ³ Consider tightening the default Codex `timeout` since it's the sole bound.

### 7.3 Semantic state palette (shared, from `styles.css`)

`--st-queued #94a3b8` · `--st-running #4f8cff` · `--st-paused #f5a623` · `--st-review #a78bfa` · `--st-done #34c98a` · `--st-failed #f2666b` · `--st-cancel #7c7a82`. Running/paused dots **pulse**. State must never be conveyed by color alone (pair icon + label) — accessibility (§9).

### 7.4 GitHub label colors (from `data.jsx LABELS`)

`bug #f2666b`, `backend #4f8cff`, `frontend #a78bfa`, `enhancement #34c98a`, `auth #f5a623`, `docs #7c7a82`, `infra #22b8cf`, `good first issue #34c98a`.

### 7.5 Type, radii, motion, shadows

- Type: `--font-ui "Plus Jakarta Sans"` (400–800); `--font-mono "JetBrains Mono"` for code, run ids, and numbers/meters (`font-feature-settings:"tnum"`).
- Radii: `--r-sm 8 / -md 12 / -lg 16 / -xl 22 / -pill 999`. Easing: `--ease cubic-bezier(.4,0,.2,1)`, `--ease-out cubic-bezier(.16,1,.3,1)`.
- Shadows (dark): sm `0 1px 2px rgba(0,0,0,.4)`, md `0 6px 20px -6px rgba(0,0,0,.55)`, lg `0 24px 60px -18px rgba(0,0,0,.7)`.
- Primitives: `.btn(-primary/-ghost/-soft/-danger/-lg/-sm/-icon)`, `.card`, `.badge(-soft)`, `.state(.s-queued…/.s-failed)`, `.gh-label`, `.input/.textarea/.select`, `.run-bar`, `.skel`, `.fade-in/.slide-in`, `.scrim`.

### 7.6 Frontend implementation note

The prototype is React 18 compiled in-browser via Babel standalone, hardcoded mock data, no router/bundler/icon lib (hand-rolled SVG icons; bespoke `SpendChart`). **v1 productionizes this into a real build:** React + Vite, a router, `EventSource` for live runs, real API calls replacing `data.jsx`. Port the existing JSX components/tokens; rebuild the spec-only screens (Board/Builder/Chrome) to spec.

---

## 8. Technical architecture

**Headline decision:** a single **FastAPI** process containing an **in-process asyncio orchestrator** (Symphony-style poll/dispatch/reconcile), **SQLite (WAL, event-sourced)** state, **SSE** streaming, a **fine-grained-PAT** GitHub identity with **poll-only** sync (the GitHub App + webhooks are deferred to the scaling phase — see §8.1), agent sandboxes run under a **gVisor runtime** with a **default-on egress allowlist**, and a thin **`Executor`** seam so Docker-now / cloud-later is a swap. Frontend: **React + Vite**. Deploy: `docker compose up`. (Full justification + alternatives weighed in §13.)

```
┌────────────── DKMV Platform (one process, self-hosted) ──────────────┐
│  React/Vite SPA ──HTTP──▶ FastAPI                                     │
│      ▲  └────────────────── SSE /runs/{id}/events ◀── EventBus relay  │
│      │                                                               │
│  FastAPI ── Orchestrator (asyncio loop: poll·dispatch·reconcile)     │
│      │         │  Semaphore(max_concurrent_runs) + per-state caps    │
│      │         │  retry/backoff, stall detection, boot recovery      │
│      │         ▼                                                      │
│      │     EmbeddedRuntime.start(...) ──▶ RunHandle + EventObserver   │
│      │         │                              │ on_pause callback     │
│      │         ▼                              ▼                        │
│      │     Executor (LocalDockerExecutor) ── DKMV container/run        │
│      │                                                                │
│  GitHubClient (PAT v1; App later): issues, labels, branches, PRs, poll │
│  SQLite(WAL): projects/issues/runs/stages/events/pause_decisions/...  │
│  SecretStore (encrypted): GitHub token, Anthropic/Codex keys          │
└──────────────────────────────────────────────────────────────────────┘
```

### 8.1 GitHub integration

- **Identity (v1 = fine-grained PAT; GitHub App deferred).** v1 ships a **fine-grained Personal Access Token** as the default and only required auth: a copy-paste onboarding screen lists the four permissions to grant — `issues:write`, `pull_requests:write`, `contents:write`, `metadata:read` — scoped to the single selected repo. Rationale: for the solo, single-user, single-repo, self-hosted persona (N1), GitHub's own guidance is that PATs fit "quick scripts/personal automation" while Apps are for "secure, scalable" multi-party integrations; a PAT is paste-and-go and works behind NAT with poll-only (no inbound endpoint, no private key, no installation flow). The host is already the trust boundary (it holds far-more-valuable model keys and the docker socket), so a 1-hr installation token buys little here. **The GitHub App (built-in bot identity, per-install short-lived tokens, 15k req/hr, webhook routing) is the correct *scaling/multi-tenant* identity and is deferred to the "Later" phase (§12).** Keep everything behind one `GitHubClient` interface so the App is an additive backend, not a rewrite. (Resolves OQ-1: **PAT-only for v1**.)
- **State plane: GitHub `agent:*` labels (v1 control plane).** Labels `agent:queued | agent:in-progress | agent:paused | agent:review`. **Single-occupancy invariant:** an issue has **at most one** `agent:*` label. All transitions go through a `set_agent_state(repo, num, target | none)` primitive implemented with GitHub's **`PUT /repos/{o}/{r}/issues/{num}/labels`** (replace-all semantics over the `agent:*` set, preserving non-agent labels) — *not* a non-existent `PATCH .../label` and not bare add/remove. The replace-all `PUT` makes the write idempotent and guarantees single occupancy. If multiple `agent:*` labels are ever observed, precedence for column derivation is `in-progress > paused > review > queued`. The four `agent:*` labels (with defined colors) are **created on connect** if absent, and `label.deleted/edited` webhooks (if webhooks are enabled later) recreate them. Avoid namespace collision with GitHub Copilot coding agent's `copilot/*` conventions. Projects v2 status is a later opt-in (GraphQL-only — no REST path).
- **Authority rule (resolves the "two sources of truth" tension with §6.5):** for an issue with an **active run**, the **DB `runs` row is authoritative** for the board state; labels are advisory/cosmetic while a run is live. The label→column derivation in §5.3.1 governs only issues **without** an active run. A human label edit on a running issue is handled by reconciliation (§8.2), not by blindly trusting the label.
- **Sync: poll-only (v1 default).** The orchestrator tick does a single **GraphQL** board read (issues + state + labels + linked PRs) per project, paginated (`first:100` + cursors), persisting a `since`/cursor for incremental polls and bounding the **Done** column to a window (e.g. closed in the last N days or last 50). GraphQL has **no ETag support**, so cache results yourself keyed by a query+variables hash; REST polls use ETag/conditional requests. **Webhooks are deferred** with the App; when added they MUST: dedupe deliveries on `X-GitHub-Delivery`; be HMAC-verified (NFR-SEC-3); filter self-authored events (`sender` is our bot) and recently-expected mutations (a short-TTL `expected_label_events` table recording every outbound label write) to prevent **echo/self-trigger loops**; process async and return 2xx fast. Note the **poll↔webhook asymmetry**: polls read current label state without an actor, so echo-suppression depends on the `expected_label_events` table, not on `sender`.
- **State-machine completeness (binding):**
  - **In Review → Done:** detect via the `pull_request.closed` event with `merged:true` (or, in poll mode, the GraphQL PR `merged` field) plus issue↔PR linkage (track `runs.pr_num`; parse "Closes #N"). On merge, close/strip `agent:review`.
  - **Closed/reopened:** `issues.closed` → Done (and cancel any live run on that issue); `issues.reopened` → move out of Done and restore the appropriate `agent:*` label or Backlog.
  - **Failed/cancelled runs have no column:** on a run failure, reconciliation demotes the label off `agent:in-progress` (to `agent:queued` if it will auto-retry, else strip to Backlog). The board never strands a failed issue in "In Progress."
- **Write-side rate limiting (binding).** Label/branch/PR/comment writes hit GitHub's **content-creation secondary limit (~80/min, 500/hr)**, which is *not* reflected in `X-RateLimit-Remaining` and returns 403 + `Retry-After`. Route **all mutating GitHub calls through a single serialized write-queue with token-bucket pacing**, with distinct handling for primary limits vs. 403-secondary/`Retry-After`. Reads prefer GraphQL (cheaper points); honor `Retry-After`; capped backoff; surface `X-RateLimit-*` + secondary-limit state in the UI (FR-06-2).
- **Preflight checks *effective write permission*** on the selected repo (not just token presence) so a read-only token fails fast at connect, not late at PR-creation time.
- **Endpoints (issue domain):** `POST /connect/github`, `GET /repos`, `POST /projects/{repo}/sync`, `GET /repos/{repo}/issues`, `GET /issues/{num}`, `POST /issues/{num}/agent-state` (body `{target: queued|none}` → calls `set_agent_state` for the Backlog↔Queued drag).

### 8.2 Orchestrator (in-process asyncio)

> **Why in-process (not Celery/Temporal):** the durable unit of work here is a 10–45 min Docker container, which **no** workflow engine can replay or resume — so "reconcile from external truth (Docker) + a persisted state DB" is the correct pattern at any scale, and the heavyweight engines would add infra without solving the hard part. The PRD's DB-of-record already improves on Symphony's in-memory-only recovery. The low-regret durability-escalation path (if ever needed) is **DBOS** (an embedded, in-process durable-execution library on the same SQLite/Postgres), *not* Temporal (a separate service fleet + a deterministic-workflow rewrite).

- **Tick.** A long-lived `asyncio.Task` runs a fixed-cadence tick (**default `tick_interval = 10s`**, config): reconcile running runs → validate preflight → fetch candidate issues (one GraphQL board read) → sort (priority asc, then oldest `created_at`) → **dispatch** while slots remain. Liveness comes from the **event stream** (the engine's per-run streaming), **not** a per-container busy-poll; `get_container_status` is consulted only on suspected stall.
- **Bounded concurrency + aggregate admission control.** Dispatch is gated by `asyncio.Semaphore(max_concurrent_runs)` (default 3) **and** by aggregate-resource admission, because per-run caps alone don't bound the expensive dimensions: a run is admitted only if `Σ(running container memory) + this run's memory ≤ host_memory_budget` **and** `Σ(today's spend) ≤ daily_spend_cap`. Optional per-state caps (e.g. throttle `agent:queued`).
- **Each run** = one tracked `asyncio.Task` wrapping `EmbeddedRuntime.start(...)`; its `EventObserver` pushes `RuntimeEvent`s to a per-run `asyncio.Queue` → DB append + SSE fan-out (bridge details §8.3).
- **Retries (idempotent against side effects).** Capped exponential backoff on transient failures (`delay = min(10s·2^(attempt-1), max_backoff)`, cap 5 min; max 3 attempts → retry queue, FR-06-3). **Before re-dispatching, the orchestrator MUST detect an existing branch/PR for the issue** (via `runs.pr_num` / the branch name) and **resume/skip rather than duplicate** — a blind retry would re-push commits or re-open a PR. Exactly-once is impossible; the bar is *idempotent effects*. Optionally retry with `start_task=` the last completed stage (see crash recovery).
- **Reconciliation (every tick).** (a) Stall detection: if no events for `stall_timeout` (config, default 5 min) → kill the container + schedule retry. (b) GitHub-label refresh under the **authority rule** (§8.1): if a human moved the issue to a terminal/non-active state, stop the run (terminal → also clean workspace); an active run's DB row otherwise wins over stray label edits. (c) Orphan-container sweep (containers labeled with `run_id` whose run row is terminal). All deadlines (`backoff`, `timeout_at`, stall) are **UTC timestamps persisted in the DB and re-evaluated against `now()` each tick** — never in-memory `asyncio.sleep` timers — so they survive a laptop sleep/suspend.
- **Graceful drain (SIGTERM).** A `docker compose restart` is routine; cancelling a run's `asyncio.Task` does **NOT** stop its container (the container would be orphaned and keep spending). On SIGTERM the orchestrator: (1) stops dispatching new runs; (2) for each live run, calls `RunHandle.stop(force=True)` (which cancels the task → the engine's `finally` stops the container) within a drain deadline; (3) marks any run it couldn't cleanly stop `interrupted` and records its container id for the boot sweep. Never bare-cancel a run task without stopping its container.
- **Crash recovery (boot) — the engine cannot re-attach to a live run.** Confirmed against the engine: a run is driven by the host coroutine in `ComponentRunner.run`; if the process dies, that driver is gone, the `RunHandle`/observer/event-queue are gone, and there is **no API to re-attach an observer to, or resume, a container started by a dead process** (`reconcile_stale_runs` only writes `cancelled` for *dead* containers and leaves *alive* ones untouched; `replay_events` only reads already-persisted `stream.jsonl`). Therefore boot recovery is: for each non-terminal `runs` row, **`docker kill` the orphaned container** (it is unfinishable and budget-burning), mark the run `interrupted`, and **offer retry** — optionally re-launching with `start_task=<last completed stage>` (the engine reconstructs prior stage outputs from the repo branch, so this only recovers stages whose outputs were committed/pushed). Recovery dispatch is **jittered and routed through the same semaphore** to avoid a boot thundering-herd on Docker + the GitHub API. *("Re-attach to a live run" and component-level checkpointing are tracked as engine asks, §11.)*
- **Dispatch idempotency (SQLite-correct — not SKIP LOCKED).** SQLite is **single-writer** and has no `SELECT … FOR UPDATE`/`SKIP LOCKED`; in a single-process orchestrator the only real double-dispatch race is intra-event-loop (a webhook coroutine vs. the poll tick). The mechanism is therefore a `UNIQUE(idempotency_key)` column + an atomic `INSERT … ON CONFLICT(idempotency_key) DO NOTHING` inside a `BEGIN IMMEDIATE` transaction; act only if the insert won the row. The `idempotency_key` is `issue_num + workflow_id + base_branch` (**not** a hash of mutable issue body, so an edit can't fork it); a *retry* reuses the same run row rather than colliding. (Multi-process/Postgres later genuinely needs `FOR UPDATE SKIP LOCKED` + leader election — see NFR-PORT-1.)
- **Loop self-observability.** The orchestrator emits gauges — tick duration, time-since-last-successful-tick, slots-in-use, queue depth, reconcile actions, dispatch latency — plus a loop heartbeat, so a wedged single event loop (e.g. a blocking call) is *detectable*. To keep the loop non-blocking, all SQLite writes go through an off-loop executor / `aiosqlite` and event appends are batched (§6.5).

### 8.3 Real-time streaming

- **Transport: SSE** for the live run view and meters (`GET /runs/{id}/events`, `sse-starlette` `EventSourceResponse`). Server→client only fits the data flow (the discrete client→server actions — answer/stop/retry — are plain POSTs), and SSE gives free browser reconnect; WebSocket's bidirectional/sticky-session cost isn't justified.
- **Sync→async bridge (binding — prevents a heisenbug).** The engine calls `EventObserver.on_event(event)` **synchronously, inline**, and the thread it runs on is not guaranteed to be the event-loop thread. The platform's observer MUST therefore capture the loop at startup and hand off with **`loop.call_soon_threadsafe(queue.put_nowait, event)`** (thread-agnostic). Do **not** call bare `queue.put_nowait`, `loop.create_task`, or per-event `run_coroutine_threadsafe` from the observer. Each run has a **bounded** per-subscriber queue; on overflow, **coalesce/ drop meter frames** but **never** lifecycle/decision/`task_completed` events (see meter rule below), and disconnect a persistently-slow consumer (it will reconnect and replay).
- **Resumable replay (binding contract).** On reconnect with `Last-Event-ID`, the server: (1) **subscribes to the live per-run queue first**, then (2) reads the backlog from the `events` table filtered `WHERE run_id = ? AND id > :last ORDER BY id`, flushes it, then (3) tails live — **de-duplicating by `id`** across the replay→live handoff (this subscribe-before-read ordering is what closes the gap/dup window most implementations botch). The engine's `replay_events(run_id, offset)` is a fallback source only; the platform `events` table is the primary replay log.
- **Heartbeats & proxy-safety (binding).** Emit a `:`-comment heartbeat every **~15 s** (under common 30–60 s proxy idle timeouts); set `Cache-Control: no-cache` and `X-Accel-Buffering: no` so reverse proxies don't batch or drop the stream.
- **PauseCard rehydration.** If the socket drops while a run is paused, the reconnect replay only reaches `pause_requested`; the client MUST rehydrate the decision card from the `pause_decisions` row (or a `GET /runs/{id}` field), not rely on the live push.
- **Board / chip use polling, not N SSE streams.** The board aggregate strip and the sidebar live chip (FR-NAV-1) refresh via the orchestrator's poll cadence (FR-NAV-2 "last synced"), **not** one SSE stream per running card — N per-card streams would blow the HTTP/1.1 6-connection-per-origin cap whenever HTTP/2 isn't guaranteed end-to-end. Only the **single open run view** holds an SSE stream.
- **Auth over SSE (resolves the EventSource-header gap with NFR-SEC-2).** Browser `EventSource` **cannot set an `Authorization` header**, and a token in the query string would leak into logs and the append-only `events` table (violating §8.6). v1 carries the local auth token in an **HttpOnly, `SameSite=Strict` cookie** (auto-sent by `EventSource`, unreadable by JS); the SSE handler validates the cookie + `Origin`/`Host` (NFR-SEC-2). (Alternative: a `fetch`-based SSE client that can set headers.) **The token MUST NOT appear in any URL.**
- **Fan-out & scale.** In-process per-run subscriber sets now. For multi-process later: **Redis pub/sub carries the live fan-out lane only** — it is at-most-once/fire-and-forget and **MUST NOT** be the replay source; replay stays backed by the durable `events` table (or Redis **Streams**). Cross-process also needs a single id-allocation authority (a DB sequence) for the monotonic SSE `id`.
- **Meter aggregation (binding — see §6.4 for why).** Engine `cost_usd`/`turns` are **cumulative *within a task*, and the run total is the *sum across tasks***. The meter MUST therefore compute `run_cost = Σ(final cost_usd of each completed task) + (latest cost_usd within the active task)`, de-duplicated by `(run_id, task_index)` — **never** a naive `SUM(cost_usd)` over all events (double-counts) and **never** plain "keep-latest" (would reset the meter toward $0 at every stage boundary and never reach the run total). `task_completed`/`task_failed` events are **meter-critical** (carry a completed segment's final cost) and are never coalesced/dropped. Turns aggregate identically. Codex segments contribute `$0` (FR-06-1a).

### 8.4 Run launch contract

`POST /runs` body: `{ issue_num, repo, workflow_id, agent (claude|codex|auto), branch, feature_name, model?, max_turns?, timeout_minutes?, max_budget_usd?, memory?, context[]?, keep_alive?, start_task? }`. Backend validates (§8.10), resolves agent (`auto → workflow.agent`), inserts the `runs` row (claim-lock §8.2), builds `ExecutionSource(type=remote, repo, branch)`, calls `EmbeddedRuntime.start(...)`, and returns **`{ run_id }` = the platform UUID** (the engine's `YYMMDD-HHMM-…` id is *not* available synchronously — it back-fills as `engine_run_id` via the event stream; clients address all run endpoints by the platform UUID). Other run endpoints: `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/events` (SSE), `POST /runs/{id}/answer`, `POST /runs/{id}/stop`, `POST /runs/{id}/retry`, `GET /stats`, `GET /retry-queue`. Full request/response schemas + error envelope + status codes are in **§8.9**.

### 8.5 Human-in-the-loop bridge (best-effort-durable interrupt)

The platform passes an `on_pause: Callable[[PauseRequest], Awaitable[PauseResponse]]` to `EmbeddedRuntime.start` (verified: the engine genuinely `await`s this callback at the pause point in `ComponentRunner.run`, with the container held open and the run coroutine suspended). Implementation:
1. On pause: write a `pause_decisions` row (`status=pending`, request payload, `timeout_at`), set the issue to `agent:paused`, **release the run's `max_concurrent_runs` slot** (the container is genuinely idle during the pause — no agent process is running — so it should not occupy a concurrency slot while a human is away), and emit `pause_requested` over SSE → UI renders the decision card.
2. The callback awaits an `asyncio.Event`/`Future` keyed by `decision_id`.
3. `POST /runs/{id}/answer` resolves the decision **exactly once** via a guarded transition `UPDATE pause_decisions SET status='answered', answer_json=…, resolved_by='human' WHERE id=? AND status='pending'` and fires the in-memory event **only on rowcount=1** (so a double-click / two tabs / a racing timeout can't double-resolve). The callback returns `PauseResponse(answers, skip_remaining)` → engine resumes (re-acquiring a concurrency slot).
4. **Timeout.** Each pause carries a UTC `timeout_at` re-evaluated each reconcile tick (not an in-memory timer). **Default = 60 minutes** (not 24 h — a held 8 GB container under a 3-slot cap is too costly); on expiry the tick auto-resolves per policy (`resolved_by='timeout'`; default **auto-abort**, configurable to auto-approve-recommended), using the same exactly-once guard.
5. **Durability — what actually survives a restart (corrected; do not over-claim).** Only the **decision row** is durable. The suspended run coroutine, its accumulated in-memory `task_results`, and the live container do **NOT** survive a backend restart — there is no engine API to re-enter a half-finished `ComponentRunner.run` (see §8.2 crash recovery). So on restart a paused run is **re-launchable from the last *completed* task boundary via `start_task=`, and only if that task's outputs were committed/pushed to the branch** (the engine reconstructs prior stage outputs from the repo); otherwise it is marked `interrupted` and offered for retry. **Therefore: any `pause_after` task MUST have `commit:true`/`push:true`** (or the platform must persist its outputs to the DB) so the pause boundary is recoverable — the Builder (§5.8) enforces this and the built-in `plan`/`qa`/`ship` pause tasks satisfy it. The honest claim is **"the decision is durable; the run resumes from the last pushed boundary, else interrupted,"** not "the suspended run survives." (True coroutine-level durability would require engine component-checkpointing — engine ask §11.)
6. **Stop during a pause** requires `RunHandle.stop(force=True)` — the engine checks `cancel_event` only between tasks, so a cooperative stop won't fire while parked at `await on_pause`; `force=True` cancels the task → the engine's `finally` stops the container (see §10 R-7).

### 8.6 Secrets & exfiltration containment

> **Threat framing (the defining risk of this product class):** the agent runs **attacker-influenceable input** — a GitHub **issue body *is* the prompt** and **repo content *is* the context**, both editable by anyone who can open an issue/PR — while holding a live GitHub token + model keys + network egress. A prompt-injection (OWASP **LLM01**, §10 R-14) can instruct the agent to read its own credentials and exfiltrate them. File-mounting secrets is **log-hygiene, not containment** (the agent has a shell in the same container and the token is in its git remote). The real containment controls are below.

- **Egress allowlist — DEFAULT-ON REQUIREMENT, not a recommendation.** The sandbox's network is restricted to an allowlist (GitHub API/git + the configured model API endpoints) **enforced at the network layer** (firewall/proxy with DNS pinned to a trusted resolver), **not** via the agent's own config (honor-system allowlists have shipped `endsWith`/SOCKS5/DNS bypasses). This is the primary control that blunts exfiltration of the agent's own live credentials once injected.
- **Repo-scoped, short-lived tokens.** The GitHub token injected into a run is scoped to **exactly the one target repo** with the minimum permissions, ≤1 hr TTL — so an injected agent can't push to other repos the user owns. (Fine-grained PATs are per-repo scopeable; App installation tokens, when added, mint per-run repo-scoped tokens.)
- **Injection mechanics.** Prefer **file mounts** over env vars (keeps secrets out of `docker inspect`/crash logs) and encrypt at rest on the host (OS keychain / SQLCipher / encrypted file). Note this reduces *log* exposure only; combine with egress + scoping for actual containment.
- **Redact before persist (backstop, not a boundary).** The event/log pipeline scrubs known secret patterns (`sk-ant-…`, `ghp_…`, `github_pat_…`) before writing to the append-only `events` table (a leak there is permanent + replayable). Treat redaction as defense-in-depth; pattern-matching misses transformed/split/base64 secrets, so it does not replace egress control.
- **Image supply chain.** Pin the sandbox image **by digest** (not `:latest`), generate/scan an SBOM (Trivy/Docker Scout), and treat `dkmv-sandbox` as a trusted build artifact — it runs with mounted creds and egress.
- **Audit log** (separate from the agent event stream): run launches, token mint/use, egress denials, decision resolutions. **Secret rotation** path for the long-lived model keys.

### 8.7 Executor seam (cloud-later)

Define an interface the orchestrator depends on: `Executor.start(run_spec) -> handle`, `.stream(handle)`, `.signal(handle, pause|resume|cancel)`, `.cleanup(handle)`. v1 ships `LocalDockerExecutor` (wraps `EmbeddedRuntime` + local Docker via SWE-ReX `DockerDeployment`). Later: `SSHRemoteDockerExecutor` (VM pool — SWE-ReX already ships `RemoteDeployment`/`fargate`/`modal`/`daytona`, currently unused by DKMV) and `K8sJobExecutor`. **The engine's `SandboxManager` hardcodes `DockerDeployment` and `_facade.py` shells the local `docker` CLI** — abstracting this is the single biggest engine change required for cloud (tracked as an engine ask, §11).

### 8.8 Repository, deployment & dev environment

- **New repo** at `/Users/tawab/Projects/DKMV/platform/` (sibling to `dkmv/`). The backend imports `dkmv.runtime` **in-process** (it calls the `EmbeddedRuntime` Python object directly — there is no separate engine service). Suggested layout:
  ```
  platform/
    backend/   app/ (FastAPI: api/, orchestrator/, github/, executor/, db/, sse/, secrets/, security/)
    frontend/  (React + Vite; ports docs/design_docs/platform JSX + tokens)
    docker-compose.yml   Dockerfile.backend  Dockerfile.frontend
    README.md  pyproject.toml  alembic/
  ```
- **Dev-environment setup (binding — M0 will not `docker compose up` without this):**
  1. Editable-install the engine into the backend env: `pip install -e ../dkmv` (or vendor it); pin **Python ≥ 3.12** (the engine uses 3.10+ unions / `from __future__`).
  2. **Build the sandbox image:** `docker build -t dkmv-sandbox:latest dkmv/images/` (FR-01-6 only *checks* for it; nothing auto-builds it — document the step). Pin by digest for prod (§8.6).
  3. The backend container mounts the **brokered** Docker socket (below) so it can launch sandboxes; the engine's `output_dir` points at a platform-owned volume (OQ-4).
- **Sandbox isolation (binding — see NFR-SEC-4).** The sandbox runs under **gVisor (`runsc`)** by default — plain `runc` shares the host kernel and "is not a security boundary" for autonomous untrusted-code execution. microVM (Firecracker/Kata) is the stronger tier for the cloud/multi-tenant path. This is a runtime flag, not a rewrite.
- **Broker the Docker socket (don't raw-mount).** The backend reaches Docker through a **method-allowlisted, non-root socket proxy** (only the create/start/stop/inspect calls the orchestrator needs), or **rootless Docker / Sysbox** — not a raw `-v /var/run/docker.sock` mount (a read-only mount does not help; the Docker API is root-equivalent and "a request to the API ≈ code execution on the host").
- **App network/auth (binding — NFR-SEC-2/3):** bind `127.0.0.1` + local auth token; **validate `Host`/`Origin` headers** (anti-DNS-rebinding) and apply **CSRF protection on all state-changing POSTs**; the SSE auth token rides an HttpOnly `SameSite=Strict` cookie and never appears in a URL (§8.3).
- **Config / env surface (consolidated):** `DKMV_PLATFORM_TOKEN` (local auth), `DKMV_PLATFORM_BIND` (default `127.0.0.1:8787`), `DATABASE_URL` (default `sqlite:///./data/dkmv.db`), `OUTPUT_DIR` (engine runs/artifacts volume), `GITHUB_TOKEN` (fine-grained PAT), `ANTHROPIC_API_KEY`, `CODEX_API_KEY`, `DKMV_IMAGE` (default `dkmv-sandbox:latest`, pin by digest in prod), `MAX_CONCURRENT_RUNS` (default 3), `HOST_MEMORY_BUDGET`, `DAILY_SPEND_CAP`, `TICK_INTERVAL_S` (10), `STALL_TIMEOUT_S` (300), `PAUSE_TIMEOUT_S` (3600), `SANDBOX_RUNTIME` (default `runsc`), `EGRESS_ALLOWLIST`. Secrets live in the encrypted SecretStore, not plain env, in real deployments (§8.6).
- Deploy: `docker compose up` runs backend + frontend.

### 8.9 API contracts (response shapes, errors, pagination)

All endpoints are under `/api/v1`, JSON, authed per NFR-SEC-2. **Error envelope (all non-2xx):** `{ "error": { "code": "<machine_code>", "message": "<human>", "details"?: {...} } }`. **Status codes:** `200` ok; `201` run created; `202` accepted (async action queued, e.g. stop); `400` validation (`code: validation_error` + field details); `401` missing/invalid local token; `403` Host/Origin/CSRF rejected; `404` not found (`run_not_found`, `issue_not_found`); `409` conflict (`code: duplicate_dispatch` when the idempotency key already has an active run; `pause_already_resolved`; `preflight_blocked` with the blocker list); `429` GitHub/provider rate-limited (surfaces `Retry-After`); `500` internal. **Pagination (all list endpoints):** cursor-based — request `?limit=<=100&cursor=<opaque>`; response `{ items: [...], next_cursor: string|null }`. Representative response bodies:

- `GET /runs/{id}` → `{ id (uuid), engine_run_id, repo, issue:{num,title}, workflow_id, agent, model, status (§6.3), branch, cost_usd|null, tokens_in, tokens_out, turns, duration_s|null, started_at, finished_at|null, pr:{num,title,checks}|null, error|null, stages:[RunStage], config:{...FR-04-5 keys}, sandbox:{image,mem,vcpu,health}, artifacts:[{name,size,live?}] }`. (Codex `cost_usd` = `null`/"—", FR-06-1a.)
- `GET /runs` → paginated `RunSummary` rows (FR-06-4 columns) + filters `?workflow=&agent=&status=`.
- `GET /stats` → `{ total_runs, success_rate, total_spend_usd, tokens, agent_hours, spend_series:[{date,usd}], rate_limits:{github,anthropic,openai} }` (Codex excluded from spend, FR-06-1a).
- `GET /preflight` → `{ ready: bool, checks:[{id,label,sub,ok}], blockers:[...] }` (from `get_capabilities()`, FR-01-6).
- `POST /runs/{id}/answer` → `200 {resolved:true}` or `409 pause_already_resolved`.
- `POST /runs/{id}/stop` → `202 {stopping:true}` (calls `RunHandle.stop(force=true)` for paused runs, §8.5).
- `GET /runs/{id}/events` → SSE stream (§8.3), each message `id:<events.id>` + JSON `RuntimeEvent`.

### 8.10 Input validation rules (binding)

- **branch**: matches `^[\w./-]{1,200}$`, no `..`, no leading `-`; default `dkmv/issue-{num}-{slug}`. **feature_name**: slugified (`[a-z0-9-]`, ≤30) before it flows into the run-id/git identity. **repo**: must be the connected project's repo. **workflow_id**: must resolve via `validate_component`. **agent/model**: validated via the engine's `validate_agent_model` (reject incompatible explicit pairs). **max_budget_usd/max_turns**: positive; **rejected (400 `unsupported_for_agent`) when the resolved agent's `supports_budget()`/`supports_max_turns()` is false** (Codex) rather than silently ignored. **timeout_minutes/memory**: within configured bounds. **context paths**: must exist and be inside the project. The UI hides budget/turn fields for Codex (FR-03-2/R-10); the API still enforces.

### 8.11 Happy-path sequence (the load-bearing flow)

`POST /runs` → validate (§8.10) → `INSERT runs … ON CONFLICT(idempotency_key) DO NOTHING` under `BEGIN IMMEDIATE` (win-or-409, §8.2) → admission check (slots + memory + daily-spend, §8.2) → `EmbeddedRuntime.start(..., on_pause=bridge)` returns a `RunHandle` (run_id back-fills) → register an `EventObserver` that `loop.call_soon_threadsafe`-pushes `RuntimeEvent`s to the per-run queue → a pump task batch-appends to `events`, updates `run_stages`/meters (segment-sum), and fans out to SSE subscribers → on `pause_requested`: write `pause_decisions`, set `agent:paused`, release slot, emit → `POST /runs/{id}/answer` resolves-once and wakes the awaited `on_pause` → engine resumes → on completion: write `run_totals` from the engine `result.json`, set `agent:review` + link PR (or `agent:in-progress`→demote on failure), emit `run_completed`. A sequence diagram covering this is a **M2 deliverable**.

---

## 9. Non-functional requirements

- **NFR-PERF-1.** Board/issues load < 1.5 s for ≤ 200 issues; live-run meter latency < 1 s end-to-end; SSE reconnect replays missed events with no gaps.
- **NFR-SCALE-1.** Support ≥ 5 concurrent runs on a developer machine without UI degradation; concurrency capped by config (`max_concurrent_runs`, default e.g. 3) because each container defaults to 8 GB.
- **NFR-REL-1.** Backend restart never loses run *intent* (it's in the DB) and never leaves an orphaned money-spending container: on SIGTERM the orchestrator drains (stops containers), and on boot it kills orphans + marks `interrupted` + offers retry (§8.2). **Scope honesty:** a mid-run/mid-pause run is **not** resumed in place (the engine can't re-attach, R-15) — it's re-launchable from the last pushed task boundary via `start_task`. "Recoverable" = no orphan + retryable, not "continues exactly where it left off."
- **NFR-SEC-1 (secrets & exfiltration containment).** Secrets encrypted at rest; never logged; redacted from the event log (backstop only). GitHub token **repo-scoped + ≤1 hr TTL**; least-privilege permissions. The sandbox **egress allowlist is a default-on, network-enforced requirement** (GitHub + model APIs only, pinned DNS), not a recommendation — it is the primary exfiltration control (§8.6). Sandbox image pinned by digest + scanned.
- **NFR-SEC-2 (app access control — required).** The web app is a control plane that reaches the **host Docker socket** (root-equivalent) and launches money-spending agent runs, so it MUST NOT be openly reachable. v1: backend **binds `127.0.0.1`** + requires a **local auth token** on every API/SSE request; **validate `Host`/`Origin` headers (anti-DNS-rebinding)** and apply **CSRF protection on state-changing POSTs**; the SSE token rides an HttpOnly `SameSite=Strict` cookie and never appears in a URL (§8.3). The socket is **brokered** (method-allowlisted proxy / rootless / Sysbox), not raw-mounted (§8.8). Loopback alone is **not** sufficient — it's loopback + token + Host-validation + CSRF + token-never-logged.
- **NFR-SEC-3 (webhook integrity).** If/when webhooks are enabled (deferred with the App, §8.1), verify the GitHub `X-Hub-Signature-256` HMAC on the **raw request body** with a **constant-time** comparison, **reject when the secret is unset**, and dedupe on `X-GitHub-Delivery`.
- **NFR-SEC-4 (sandbox isolation — required).** Autonomous untrusted-code execution runs under **gVisor (`runsc`)** by default in v1, microVM for cloud/multi-tenant; plain `runc` is insufficient as a security boundary (§8.8, R-13).
- **NFR-SEC-5 (prompt-injection posture — required).** Treat issue bodies + repo content as untrusted input (OWASP LLM01, R-14). Mitigations: least-privilege/repo-scoped token + egress allowlist (above) **plus a human-approval gate on the irreversible high-blast-radius action — the PR/branch push** — implemented via the existing HITL pause primitive (a platform-injected approval checkpoint independent of workflow-authored pauses). Document that this is defense-in-depth, not prevention.
- **NFR-COST-1 (capability-aware enforcement).** For agents that support it (Claude: `supports_budget`/`supports_max_turns` = true), the orchestrator enforces `max_budget_usd` + `max_turns` + `timeout_minutes` as hard caps (not suggestions), with an optional soft-threshold pause-for-approval and a daily spend alert (Settings) and the aggregate daily-spend admission cap (§8.2). **For agents where `supports_budget()` is false — Codex (verified: cost reported `$0.00`, no budget, no turn cap) — `timeout_minutes` is the *only* runtime guardrail.** Because Codex is the default agent for the `dev` and `docs` built-ins (and `dev` is the for-each `$10/phase × N` workhorse), the platform MUST: (a) surface this in the launch UI ("Codex runs are **time-bounded, not cost-bounded**"); (b) default Codex workflows to a tighter `timeout_minutes`; (c) branch enforcement on the adapter's `supports_budget()`/`supports_max_turns()` rather than assuming a budget cap exists. This reconciles the prior "hard caps in the orchestrator" promise with engine reality (R-10).
- **NFR-A11Y-1.** WCAG AA: state conveyed by icon+label (not color alone); AA contrast in dark and light; keyboard navigation for board and forms.
- **NFR-OBS-1.** v1: **structured logs** (with `run_id`/`issue`/`session` context) + the orchestrator loop gauges (§8.2) + the audit log (§8.6). **Full OpenTelemetry GenAI tracing** (`invoke_agent`→`chat`/`execute_tool` spans, `gen_ai.usage.*_tokens`, content in span events not attributes, tail-sampling) is **deferred to post-v1** as gold-plating for a single-user local tool — keep the structured-log schema OTel-compatible so it's an additive upgrade.
- **NFR-PORT-1.** SQLite→Postgres **storage** and LocalDocker→remote **execution** are additive migrations behind the repository layer + `Executor` interface + nullable `tenant_id`. **Caveat (not a free migration):** the *dispatch/concurrency model* does **not** port as-is — single-process SQLite uses a `UNIQUE`-key atomic insert for claim idempotency (§8.2); multi-process Postgres genuinely needs `SELECT … FOR UPDATE SKIP LOCKED` **plus leader election** for the singleton orchestrator loop, and SSE fan-out needs Redis (§8.3). Storage ports cleanly; orchestration is a real (but well-understood) change. The in-memory HITL `asyncio.Event` (§8.5) also becomes a DB-poll/Redis-signal at multi-process.

## 10. Risks, constraints & mitigations (engine-specific in **bold**)

| # | Risk | Mitigation |
|---|---|---|
| R-1 | Token blow-up / runaway loops (cost spiral) | Hard caps in loop; idle/no-progress kill; soft-threshold pause; live cost meter (NFR-COST-1). |
| R-2 | GitHub rate-limit storms (poll + retry) | GraphQL board read; ETag conditional polls; honor `Retry-After`; capped backoff; coalesced query. |
| R-3 | Secret exfiltration (agent reads its own mounted creds under prompt-injection) — file-mount is log-hygiene, not containment | **Default-on network-enforced egress allowlist** + repo-scoped ≤1 hr token (primary controls); redact-before-persist (backstop); see R-14, NFR-SEC-1/5, §8.6. |
| R-4 | Container OOM on large monorepos (prototype issue #256) | Per-run `--memory`/`--pids-limit`/disk quota; shallow clone; aggregate-memory admission (§8.2); OOM → mark `failed`, don't crash orchestrator. |
| R-5 | Double-dispatch (webhook + poll) / crash between commit and start | **SQLite is single-writer — no SKIP LOCKED:** `UNIQUE(idempotency_key)` + atomic `INSERT … ON CONFLICT DO NOTHING` under `BEGIN IMMEDIATE` (§8.2); boot reconciliation. (Postgres-later wants `FOR UPDATE SKIP LOCKED` + leader election — NFR-PORT-1.) |
| R-6 | **`RuntimeConfig.to_dkmv_config()` hardcodes `auth_method="api_key"`** → OAuth not wired through embedded path | v1 require API keys (Anthropic/Codex) via `RuntimeConfig`; treat OAuth as an engine ask (§11). |
| R-7 | **`RunHandle.status` never reports `"paused"`; `cancel_event` checked only between tasks** | Derive paused state from lifecycle events; for Stop-during-pause use `stop(force=True)`; engine ask to surface paused + cooperative-cancel-in-pause (§11). |
| R-8 | **Run-id is minute+4hex with 3 retries** — collision-weak under bursty concurrency | Platform owns a UUID primary key in `runs`; keep engine run-id as a human-readable secondary. |
| R-9 | **Engine `SandboxManager` hardcodes local `DockerDeployment`; `_facade.py` shells local docker** | v1 local-only via `Executor` seam; cloud requires engine abstraction (§11). |
| R-10 | **Codex adapter: no budget/max_turns support; cost reported `$0.00`** | UI must hide/disable budget+turn caps for Codex and show "cost not reported" rather than $0.00; document per-agent capability via `supports_budget/max_turns`. |
| R-11 | Paused run holds an idle container + a concurrency slot | 60-min `timeout_at` auto-resolve (UTC, tick-evaluated); **release the slot during pause** (§8.5). |
| R-12 | Spec-only screens (Board/Chrome) drift from intent; Builder is highest-drift | Build Board/Chrome strictly to `dkmv_dashboard_design_prompt.md` + PDF; **descope Builder to read-only viewer for v1** (N7, §5.8); design review before merge. |
| R-13 | Root-equivalent docker-socket exposure + plain-`runc` isolation for untrusted agent code | **gVisor runtime (NFR-SEC-4)** + **brokered socket** (proxy/rootless/Sysbox) + egress allowlist + loopback/token/Host/CSRF (NFR-SEC-2); microVM for cloud/multi-tenant. |
| R-14 | **Prompt injection (OWASP LLM01):** issue body *is* the prompt, repo content *is* the context — both attacker-influenceable | Treat as untrusted (NFR-SEC-5): repo-scoped token + egress allowlist + **human-approval gate on the PR push** (via HITL pause); defense-in-depth, not prevention. |
| R-15 | **Engine cannot re-attach to a live run after a process restart** (the host driver dies with the process) | Boot recovery = kill orphan + mark `interrupted` + retry via `start_task` (§8.2); graceful drain stops containers on SIGTERM; "re-attach"/component-checkpointing = engine asks §11. |
| R-16 | **Codex has no cost/turn cap** ($0 cost, `supports_budget/max_turns`=false) → runaway bounded only by timeout; Codex is `dev`/`docs` default | Capability-aware enforcement: timeout-only for no-budget agents, surfaced in UI, tighter default Codex timeout (NFR-COST-1, §7.2). |
| R-17 | **Cost meter mis-aggregation** (per-task-cumulative summed-across-tasks) | Segment-sum + keep-latest-within-segment, dedup by `task_index`; `task_completed` meter-critical (§6.4, §8.3). |

## 11. Engine asks (separate, optional PRs against `dkmv/`)

These are **not required for v1** (workarounds exist) but unblock later phases. They are the *only* sanctioned changes to `dkmv/`:
1. Wire OAuth through `RuntimeConfig` (add `auth_method`; stop hardcoding `api_key`). (R-6)
2. Surface `"paused"` on `RunHandle.status` and allow cooperative cancel while paused. (R-7)
3. Make `SandboxManager` deployment pluggable (Docker/Remote/Fargate/Modal) and route `_facade.py` container ops through the deployment API instead of shelling local docker. (R-9, cloud path)
4. Strengthen run-id uniqueness or accept a caller-supplied id. (R-8)
5. **Re-attach to a live run after a process restart** — an `EmbeddedRuntime` API to reconstruct a handle + observer for, and continue driving, a container started by a prior process. Unblocks true crash recovery (currently kill+interrupt only). (R-15)
6. **Component-level checkpointing** — persist mid-component state (completed `task_results`, loop position) so a paused/crashed run resumes the suspended coroutine rather than only re-launching from a pushed task boundary. Makes HITL durability real across restart. (R-15, §8.5)
7. **Capability-aware cost signal for Codex** (or a turn cap) so no-budget agents aren't timeout-only. (R-16)

## 12. Milestones / phased delivery

Each phase ends shippable and demoable.

- **M0 — Skeleton & engine bridge.** New `platform/` repo; **dev-env setup + `dkmv-sandbox` build (§8.8)**; FastAPI app behind loopback+token; SQLite schema + **Alembic** migrations + the concurrency pragmas (§6.5); `EmbeddedRuntime` wired behind a `RunService`; `LocalDockerExecutor` under **gVisor + brokered socket + egress allowlist**; secrets store; `get_capabilities` preflight; **API error envelope/§8.9 conventions**. *Exit:* launch a run via API against a local repo, see it complete, artifacts + `run_totals` indexed.
- **M1 — GitHub + Board (Screens 01, 02).** **Fine-grained-PAT auth (App deferred)**; repo picker; issue import (paginated, sync cursor); label state machine + `set_agent_state` (single-occupancy) + authority rule; serialized write-queue; board UI (rebuilt to spec) with drag Backlog↔Queued; aggregate strip (poll-driven). *Exit:* connect repo, see issues by state, move labels without echo loops.
- **M2 — Launch + Live run + HITL (Screens 03, 04, 05).** Issue detail + run panel + validation (§8.10); `POST /runs` (claim-lock + admission); SSE (bridge + replay contract + heartbeats + cookie auth, §8.3) + **segment-sum meters** + stage tracker; run-config/sandbox/artifacts rail; HITL bridge (resolve-once, slot-release, timeout) + decision card + `stop(force)`; **PR-push approval gate (NFR-SEC-5)**; **happy-path sequence diagram**. *Exit:* assign a workflow, watch it live (correct cost), approve a pause, get a PR.
- **M3 — History, analytics, retries, recovery (Screen 06).** Runs table + filters/sort; aggregate cards + spend chart (Codex-excluded); rate-limit health; retry queue + **idempotent retries** (no duplicate PRs); **graceful drain + boot recovery (kill-orphan + interrupted + `start_task` retry — no re-attach)**. *Exit:* full history + spend + a clean recovery after a mid-run and mid-pause restart.
- **M4 — Workflows viewer (Screen 07, read-only).** `list_components` viewer + pipeline summary + YAML view. *(Full authoring builder = v1.1, N7.)* *Exit:* browse built-in + registered workflows; run a registered custom one.
- **M5 — Concurrency, hardening, observability.** Bounded concurrent dispatch + per-state + aggregate-resource caps; capability-aware budget/timeout enforcement (Codex = timeout-only); loop self-observability + structured logs + audit log; a11y pass; backup; docs + `docker compose up`. *Exit:* run 3+ issues concurrently within budget + memory; NFRs met.
- **(Later, out of v1) — GitHub App + webhooks; cloud executor (SSH/Fargate/Modal via engine ask §11); full workflow authoring; OTel/Redis/Postgres; multi-tenant.**

## 13. Acceptance criteria & test matrix (v1 dev-ready bar)

**Definition of done for v1:** Screens 01–06 + Settings + a **read-only** Workflows viewer (07) implemented to the cited design specs (full Builder = v1.1, N7); the backend domains live; a solo dev can `docker compose up` (after the §8.8 setup), connect `asaficontact/DKMV` with a fine-grained PAT, and complete the happy path Connect → Board → Issue → Run → (pause→approve) → PR → History, with correct cost meters and clean restart recovery.

Representative acceptance tests (map to FRs):
- **AT-Connect:** Connect GitHub → repo picker lists repos → preflight shows GitHub/Anthropic/Docker → Open project imports issues onto the board. (FR-01)
- **AT-Board:** Issues render in correct columns per `agent:*` labels; dragging #263 Backlog→Queued adds `agent:queued` on GitHub; aggregate strip counts correct. (FR-02, §5.3.1)
- **AT-Launch:** Assign #247 `dev` + Codex, branch `dkmv/issue-247-…`, Run → a run appears, issue goes `agent:in-progress`. Budget/turn caps hidden for Codex. (FR-03, R-10)
- **AT-Live:** Live meters tick; **multi-stage `plan` run's cost climbs across stage boundaries to the run total (~$12) and never resets toward $0** (segment-sum, §8.3/§6.4); Friendly/Raw toggle; Raw shows `RuntimeEvent.data`; Stop transitions the run; SSE reconnect mid-stream replays with **no gaps and no duplicates** via `Last-Event-ID`; the SSE request carries no token in its URL. (FR-04, §8.3)
- **AT-HITL:** `plan` pauses after Analyze; decision card shows the 4-phases question + recommended option; Approve resumes; Abort sets `skip_remaining`; a double-submit/timeout race resolves the decision **exactly once**; the paused run **releases its concurrency slot**. (FR-05, §8.5)
- **AT-Recovery:** Kill the backend mid-run and (separately) mid-pause; on boot the orphan container is **killed**, the run is marked `interrupted`, and retry re-launches via `start_task` from the last pushed stage — **no orphaned money-spending container survives**; a retry of an issue that already has an open PR does **not** create a duplicate PR. (NFR-REL-1, §8.2, R-15)
- **AT-History:** Runs table sorts/filters; success rate, spend (Codex-excluded), tokens, agent-hours, and spend chart compute from seeded runs (e.g. the $13.28/153-turn completed run); retry queue shows attempt N/3 + backoff. (FR-06)
- **AT-Workflows:** The Workflows viewer lists built-in + registered components with pipeline summary (qa = 3 stages / 1 pause / $2.00) and a read-only YAML view; a component authored on disk + `register` appears and is runnable. (FR-07-1v)
- **AT-Concurrency:** Launch >3 issues; only `max_concurrent_runs` (and within `HOST_MEMORY_BUDGET`/`DAILY_SPEND_CAP`) execute at once; the rest queue; budget caps enforced for Claude and **timeout-only for Codex**. (G8, NFR-SCALE-1, NFR-COST-1)
- **AT-Isolation:** A run executes under the `runsc` runtime; the sandbox cannot reach a non-allowlisted domain (egress denied + logged); the injected GitHub token is repo-scoped (cannot push to another repo). (NFR-SEC-1/4, R-3/R-14)
- **AT-PromptInjection:** A run whose issue body contains an injected instruction still requires **human approval before the PR push** (NFR-SEC-5 gate fires). 
- **AT-Security:** No secret appears in logs or the `events` table; GitHub requests use least-privilege scopes; secrets encrypted at rest. (NFR-SEC-1, §8.6)
- **AT-AppAuth:** With default config the API/SSE bind to `127.0.0.1` and reject requests without the local auth token; a request from a non-loopback origin without the token is refused; webhook deliveries with a bad `X-Hub-Signature-256` are rejected. (NFR-SEC-2/3)
- **AT-CodexCost:** A completed Codex run shows live cost and "Total cost" as "—" (not $0.00); Total spend / SpendChart / board "spent today" exclude that run's $0 cost while counting its tokens. (FR-06-1a, R-10)

Test profiles: **unit** (state machine + single-occupancy label primitive, idempotency-key insert, **segment-sum meter math**, SSE replay dedup, validation rules), **integration** (EmbeddedRuntime against a throwaway repo + the `dkmv-sandbox` image; `on_pause` bridge resolve-once), **e2e** (the happy path above), **resilience** (kill backend mid-run and mid-pause → kill-orphan + `interrupted` + `start_task` retry; idempotent retry → no duplicate PR), **rate-limit** (simulated primary + 403-secondary `Retry-After`), **security** (egress denial, repo-scoped token, no-secret-in-events-log, Host/CSRF rejection, PR-push approval gate).

## 14. Open questions

- OQ-1. **RESOLVED** → **PAT-only for v1**; GitHub App (+ webhooks) deferred to the scaling phase (§8.1, §12).
- OQ-2. Default `max_concurrent_runs` and per-state caps for a solo machine (proposed 3, plus `HOST_MEMORY_BUDGET`/`DAILY_SPEND_CAP` aggregate caps, §8.2).
- OQ-3. **RESOLVED** → pause `timeout_at` default **60 min → auto-abort** (configurable), UTC + tick-evaluated, slot released during pause (§8.5).
- OQ-4. **RESOLVED** → platform-owned `output_dir` via `RuntimeConfig`; engine `result.json` authoritative for terminal totals (§6.5 reconciliation rule).
- OQ-5. **RESOLVED** → Codex cost shown as "—" + tokens; excluded from spend aggregates (FR-06-1a).
- OQ-6. gVisor availability on the target host (some macOS/Docker Desktop setups) — if `runsc` is unavailable, the operator must opt into a documented weaker-isolation mode with an explicit warning (NFR-SEC-4). What's the fallback policy?

## 15. References

- Engine: `/Users/tawab/Projects/DKMV/dkmv/` (esp. `runtime/`, `tasks/`, `adapters/`, `core/`), `CLAUDE.md`, ADRs `docs/adrs/`.
- Design: `docs/design_docs/platform/DKMV — Design Overview (PDF).pdf`, `connect.jsx`, `issue.jsx`, `run.jsx`, `history.jsx`, `settings.jsx`, `components.jsx`, `data.jsx`, `styles.css`, `DKMV.html`; `/Users/tawab/Projects/DKMV/dkmv_dashboard_design_prompt.md`.
- Best practices (selected): [OpenAI Symphony announcement](https://openai.com/index/open-source-codex-orchestration-symphony/) · [Symphony SPEC.md](https://github.com/openai/symphony/blob/main/SPEC.md) · [GitHub App vs OAuth (Nango)](https://nango.dev/blog/github-app-vs-github-oauth/) · [GitHub GraphQL rate limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api) · [SSE vs WebSockets for AI streaming](https://callsphere.ai/blog/server-sent-events-vs-websockets-ai-streaming-choosing-right-protocol) · [SSE + Last-Event-ID](https://mvpfactory.io/blog/server-sent-events-as-your-mobile-real-time-layer-automatic-reconnection-last/) · [Event sourcing with SQLite](https://www.sqliteforum.com/p/event-sourcing-with-sqlite) · [LangGraph interrupts (HITL)](https://docs.langchain.com/oss/python/langgraph/interrupts) · [Docker Sandboxes for agents](https://www.docker.com/blog/docker-sandboxes-run-claude-code-and-other-coding-agents-unsupervised-but-safely/) · [OTel GenAI observability](https://opentelemetry.io/blog/2026/genai-observability/) · [Docker secrets / GitGuardian](https://blog.gitguardian.com/how-to-handle-secrets-in-docker/) · [Kubernetes Jobs](https://kubernetes.io/docs/concepts/workloads/controllers/job/).

---

*End of PRD v1.1.*
