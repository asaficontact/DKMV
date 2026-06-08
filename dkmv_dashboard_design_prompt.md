# Claude Design Prompt — DKMV Dashboard ("Symphony-on-GitHub")

> Paste everything below the line into Claude Design. It is self-contained: product context, target user, visual direction, full screen-by-screen specs, and a reference appendix with REAL data shapes from the DKMV codebase so your mockups use believable values.

---

## 1. Your role and goal

You are a senior product designer. Design a high-fidelity, **clickable, interactive prototype** for a web dashboard called **DKMV**. DKMV is a control plane that turns **GitHub Issues into autonomous coding-agent work**: a user connects a GitHub repo, sees its issues on a board, assigns each issue a **workflow** (a multi-stage pipeline) and an **agent** (Claude or Codex), and presses Run. DKMV then spins up an isolated sandbox, runs the agent through the workflow, and opens a pull request — while the user watches progress live and approves decisions at checkpoints.

Think "the love-child of a GitHub Projects board and an agent-run observability console," but **friendly and approachable**, not intimidating. Inspired by OpenAI's Symphony (which uses Linear + a real-time dashboard of running sessions, retry queue, token totals, and recent events), but built on **GitHub Issues** and for a **solo developer / power user working one project at a time**.

Design for **desktop-first** (primary), with sensible tablet behavior. Show **light and dark** themes (dark is the hero).

## 2. Product context (what the user is actually doing)

The mental model, in order:

1. **Connect** a GitHub account and pick one repository ("project") to work in.
2. The repo's **issues** load onto a **Kanban board**, organized by agent state. State is tracked with GitHub **labels** (e.g. `agent:queued`, `agent:in-progress`, `agent:review`) — not Linear-style workflow states.
3. The user **opens an issue**, picks a **workflow** + **agent**, sets a couple of guardrails (branch, budget), and **launches a run**.
4. A **run** executes in an isolated sandbox container. The user can **watch it live**: streaming events, turn count, token/cost meters, per-task progress.
5. At **checkpoints**, the workflow **pauses** and asks the user a question (approve / choose an option / ship as-is / abort). The user answers and it resumes.
6. When done, the issue moves to **Review**, a **PR** is linked, and the run is archived in **history** with full cost/token/duration stats.

The product promise: **"Assign it and walk away."** The UI must make a long-running, expensive, autonomous process feel **calm, legible, and controllable**.

## 3. Target user and design principles

- **Who:** one developer running DKMV on their own GitHub repos. No teams, no roles, no multi-tenant. One active project at a time (but allow switching projects).
- **Principle 1 — Simple first, depth on demand (progressive disclosure).** The default view is uncluttered: a board, clear statuses, big obvious actions. Detail (raw logs, token breakdowns, retry internals, per-task timings) lives one click deeper. Never show everything at once.
- **Principle 2 — Always answer "what's happening and what do I do next."** Every screen has an obvious primary action and a clear status.
- **Principle 3 — Trust through visibility.** Because agents run autonomously and cost real money, surface live progress, running cost, and a always-available Stop. Watching it work builds trust.
- **Principle 4 — Friendly, not corporate.** Warm, encouraging, a little playful. Plain-language microcopy ("Pick a workflow and let's go" not "Configure execution pipeline").

## 4. Visual design direction — friendly / approachable

- **Mood:** soft, rounded, modern, calm. Approachable for a solo dev who may be new to agent orchestration. NOT a dense enterprise ops console.
- **Color:** a warm, friendly primary (consider a violet/indigo or teal). Soft surfaces, generous whitespace. Use color **semantically** for state — and keep a consistent state palette across the whole app:
  - Queued / waiting → neutral / slate
  - Running / in-progress → blue (with subtle motion: a soft pulse or animated progress)
  - Paused / needs you → amber (gently attention-grabbing, never alarming)
  - Review / done-by-agent → violet or green
  - Completed / merged → green
  - Failed / timed-out → soft red (informative, not scary)
  - Cancelled → muted gray
- **Shape & depth:** rounded cards (12–16px radius), soft shadows, gentle borders. Pill-shaped status badges and labels.
- **Typography:** friendly sans for UI (e.g. Inter/Geist). Use a **monospace** font *only* for code, logs, branch names, run IDs, and token/cost numbers — this signals "technical detail" without making the whole app feel like a terminal.
- **Motion:** subtle and purposeful. Live elements (running counters, streaming log lines, progress bars) animate smoothly. Avoid gratuitous animation.
- **Illustration/empty states:** warm, simple illustrations or large friendly icons for empty/first-run states with one-line encouragement.
- **Density:** comfortable, not cramped. It's fine to have breathing room; depth is reachable via expand/drawer.

## 5. Global layout and navigation

- **Left sidebar** (collapsible): the connected **project** (repo name + avatar) at top with a switcher; primary nav: **Board**, **Runs**, **Workflows**, **Settings**. A small global **"+ New run"** button. At the bottom: a compact **live status chip** ("2 running · $4.12 today") that links to whatever's active.
- **Top bar:** breadcrumb / page title, a **Refresh** affordance (the board/runs poll for updates; a manual refresh + "last synced 12s ago" indicator), theme toggle, and the GitHub account avatar.
- **A persistent, dismissible "active runs" presence:** if runs are in progress, keep a subtle indicator (e.g. the sidebar chip or a slim top strip) so the user can jump back to a live run from anywhere. If a run is **paused waiting for the user**, make this unmistakable (amber dot + count, e.g. "1 needs you").

## 6. Screens to design

Design these six screens. For each, show the **default state** plus the **key alternate states** noted (empty / loading / running / paused / error). Make the flow clickable: Connect → Board → Issue detail → launch → Live run (with a pause) → Runs history; plus the Workflow/Component builder reachable from nav.

### Screen A — Connect & project picker (entry flow)

- **Purpose:** first-run onboarding. Connect GitHub, choose one repo to work in.
- **Flow / states:**
  1. **Disconnected (first run):** a warm welcome, one big "Connect GitHub" button, a one-line explainer of what DKMV does, and a tiny reassurance about permissions/scope.
  2. **Connecting:** loading state.
  3. **Repo picker:** searchable list of the user's repos (org/repo, language, private/public badge, last-updated). Selecting one shows a quick "what we'll do" confirmation: "We'll read issues from `asaficontact/DKMV` and add `agent:*` labels to track work. Nothing runs until you say so." Primary action: "Open project."
  4. **First sync:** brief loading while issues import.
- **Also show:** a project **switcher** (the same picker reachable later from the sidebar), and a "preflight" hint if the sandbox image / credentials aren't ready (friendly checklist: GitHub ✓, Anthropic API key ✓, Docker sandbox ✓ — see Settings).

### Screen B — Board (HOME) — issues by agent state

- **Purpose:** the control plane. The user's home base. GitHub issues as cards in columns by agent state.
- **Columns (left→right):** **Backlog** (no agent label) · **Queued** (`agent:queued`) · **In Progress** (`agent:in-progress`, a run is live) · **Needs You** (`agent:paused` — paused for a decision) · **In Review** (`agent:review` — PR open, awaiting human) · **Done** (issue closed / merged). Keep columns scannable; allow horizontal scroll if needed.
- **Issue card contents:** issue number + title; a couple of GitHub labels (e.g. `bug`, `backend`); if a workflow is assigned, a small **workflow chip** (e.g. "dev") and **agent chip** (Claude/Codex avatar); if running, a **live mini-meter** (turn count + running cost + a thin progress bar with the blue running pulse); assignee avatar; a quick "⋯" menu (Assign workflow, Run, Open on GitHub, Stop).
- **Interactions:** cards are **draggable** between Backlog/Queued (changing the label); clicking a card opens **Issue detail** (Screen C). A column header shows a count and (for In Progress) aggregate live cost. Cards in "Needs You" get the amber treatment and a "Review decision" button.
- **Top of board:** project name, a search/filter bar (by label, workflow, agent, state), a **"+ Run an issue"** primary button, and a small **aggregate strip**: "3 in progress · 1 needs you · $12.40 spent today · 41,200 tokens." (This is the Symphony-style at-a-glance summary — keep it compact and progressive; full analytics live in Runs.)
- **States to show:** populated board (the hero); **empty** (no issues yet — friendly illustration + "Create an issue on GitHub or import"); **loading/syncing**.

### Screen C — Issue detail + assign workflow (the launch screen)

- **Purpose:** read the issue, choose how to work it, launch a run. This is the most important conversion moment — make it feel easy and confident.
- **Layout:** two-pane. **Left:** the GitHub issue rendered cleanly — title, number, author, full markdown body, labels, linked issues/sub-issues, and a short comment thread. **Right:** the **"Run this issue" panel.**
- **Run panel fields (with smart defaults, progressive):**
  - **Workflow** — a friendly picker of the available workflows/components, each shown as a card with its name, one-line purpose, the **ordered stages** it runs, est. cost range, and whether it pauses for you. (See reference appendix for the real built-ins: **plan, dev, qa, docs, ship** + any custom ones.)
  - **Agent** — Claude or Codex, with the model it'll use (e.g. Claude → `claude-sonnet-4-6`, Codex → `gpt-5.x`). Show the agent's avatar/brand. Let "Auto" pick based on the workflow default.
  - **Branch** — defaults to a generated branch name like `dkmv/issue-247-fix-auth`; editable. Show base branch (e.g. `main`).
  - **Guardrails (collapsed "Advanced" by default):** max budget ($), max turns, timeout (min), container memory, extra context files. Keep these tucked away — most users just hit Run.
  - A clear **cost/▶ estimate**: "Est. $2–5 · ~15–40 min · pauses once for your review."
  - **Primary action:** big "Run with [Agent]" button. Secondary: "Queue for later" (adds `agent:queued`).
- **Also show:** the state where the issue **already has a run** (show its status inline with a link to the live run / history), and a **"reassign workflow"** affordance.

### Screen D — Live run / session view (watch the agent work)

- **Purpose:** real-time observability + control for a single run. This is where trust is won. Calm, legible, with depth on demand.
- **Header:** issue title + number, workflow name, agent + model, branch, run ID (mono), and a prominent **status** (Running / Paused / Completed / Failed). A persistent **Stop** button (and "Attach"/"Keep alive" for power users, tucked away).
- **Live meters (top strip, glanceable):** elapsed time, **running cost $** (live), **tokens** (in/out/total), **turn count**, and an overall **progress** indicator. Numbers in mono, animating smoothly. Keep this calm — no flashing.
- **Stage / task tracker:** a horizontal or vertical **stepper** showing the workflow's tasks in order with per-task status (done ✓ / running ● / pending ○ / paused ⏸). Each task shows its own cost + turns + duration when complete. (E.g. for **plan**: Analyze → Features & Stories → Phases → Assembly → Evaluate-Fix. For **dev**: one step per phase via "for-each".) Clicking a task expands its detail.
- **Event stream (the centerpiece, progressive):** a live, auto-scrolling feed of agent activity rendered **human-friendly by default** — e.g. "🔧 Ran `pytest` (passed 41/41)", "✏️ Edited `dkmv/adapters/codex.py`", "💬 'I'll start by reading the implementation docs…'". A toggle switches to **raw stream** (the underlying JSON lines) for power users. Tool calls, file edits, reasoning snippets, and errors are visually distinct. Include a search/filter.
- **Pause / decision card (the HITL moment — design this carefully):** when the run pauses, surface a prominent **amber decision card** inline (and as the reason the issue sits in "Needs You"). It shows the **question**, a short **context** blurb, and the **options** as selectable choices (each option = label + description). Buttons map to real outcomes: choose an option, or **"Ship as-is"** / **"Abort"** (which set `skip_remaining`). After answering, the run resumes and the card collapses into the event log as a recorded decision. (See the real `PauseRequest` shape + a real example in the appendix.)
- **Right rail (collapsible, depth-on-demand):** run config snapshot (all guardrails), the live container/workspace info, output artifacts as they're produced (e.g. `qa_evaluation.json`, `analysis.json`, `GUIDE.md`), and — when present — the **linked PR** with its checks.
- **States to show:** **Running** (hero), **Paused / needs you** (with the decision card), **Completed** (success summary: total cost/tokens/turns/duration, links to PR + artifacts, "Run next stage?" suggestion), **Failed/Timed-out** (clear error, the retry/backoff state if applicable, and a friendly "Retry" / "Open logs" path).

### Screen E — Runs history + analytics

- **Purpose:** look back, learn, and monitor spend. Combines a runs list (drill-down) with an aggregate dashboard (Symphony-style at-a-glance), respecting progressive disclosure (summary up top, table below).
- **Top — aggregate cards:** total runs, success rate, total spend (with a small spend-over-time chart), total tokens, total agent-hours, and a current **rate-limit / health** indicator. Keep to ~5–6 friendly stat cards + one chart.
- **Filters:** by workflow, agent, status, date, and issue/label.
- **Runs table:** each row = run ID (mono), issue (number + title), workflow, agent+model, status badge, cost, tokens, turns, duration, started-at, and a link to the run view / the PR. Sortable. Clicking a row → the run view (read-only for finished runs, same layout as Screen D).
- **Also show:** an **empty** state (no runs yet), and a subtle **retry-queue** section if any runs are waiting to retry (attempt #, backoff "due in 2m", last error) — this mirrors Symphony's retry visibility but keep it secondary/collapsed.

### Screen F — Workflow / component builder (create a new workflow or task)

- **Purpose:** let the user create or edit a **workflow** (DKMV calls these "components") and its **tasks** — without hand-writing YAML. A workflow = an ordered list of tasks; each task = a prompt + instructions + declared inputs/outputs + guardrails, optionally with a **pause-after** checkpoint and a **for-each** iteration.
- **Two levels:**
  1. **Workflow (component) editor:** name, description, defaults (agent, model, max turns, timeout, **max budget**), component-level inputs (e.g. an `impl_docs` folder), an **agent instructions** field, and the **ordered list of tasks** (drag to reorder). Each task row shows: name, whether it pauses after, whether it iterates (for-each), and its budget. A live **summary** of the pipeline (stages, total est. budget, pause points). A "Test run on an issue" button.
  2. **Task editor (drawer or sub-page):** name + description; **Prompt** (the main instruction to the agent, big code/markdown editor with a friendly preview); **Instructions/rules** (secondary guidance); **Inputs** (add file/text/env inputs — type, source, destination); **Outputs** (declared output files, each: path, required?, save?, required JSON fields); toggles for **commit / push**; per-task overrides (agent, model, max turns, timeout, **max budget**); and **pause-after** with its question(s) + options builder (so the user can author the HITL decision card — question text, options as label+description, default).
- **Make it approachable:** offer **templates** ("Start from: plan / dev / qa / docs / blank") and inline help. Show a **read-only "this compiles to YAML" peek** for power users (progressive disclosure), but the primary editing experience is form-based, not raw YAML.
- **States to show:** the workflow editor with the **qa** workflow loaded (3 tasks, evaluate pauses), the task editor open on the "evaluate" task (showing its real outputs + prompt), and a **blank/new** state.

## 7. Cross-cutting things to get right

- **Status is sacred:** the same state palette and badge style everywhere (board card, run header, history row, sidebar chip).
- **Cost is always visible during runs** and summarized after. Treat money with respect — it's a key anxiety for autonomous agents.
- **Stop is always reachable** for anything running.
- **"Needs you" is unmissable** but never stressful (amber, gentle, with a clear CTA).
- **Empty, loading, running, paused, and error states** for every screen — don't only design the happy path.
- **Microcopy is warm and plain.** Buttons say what happens ("Run with Claude", "Approve & continue", "Ship as-is").
- **Accessibility:** state never conveyed by color alone (pair with icon/label); good contrast in both themes.

---

## 8. Reference appendix — REAL data shapes & examples (use these so mockups feel authentic)

> These are pulled from the actual DKMV codebase. Use these names, values, and shapes in your mockups instead of inventing placeholders.

### Run states (`RunStatus`)
`pending` · `running` · `paused` · `stopping` · `cancelled` · `completed` · `failed` · `timed_out`

### Run ID format
`YYMMDD-HHMM-<component>-<feature>-<suffix>` — e.g. `260305-1355-plan-prd-multi-agent-adapter-7389`

### A REAL completed run (use these exact-ish numbers)
```json
{
  "run_id": "260305-1355-plan-prd-multi-agent-adapter-7389",
  "component": "plan",
  "status": "completed",
  "repo": "https://github.com/asaficontact/DKMV.git",
  "branch": "feat/codex",
  "feature_name": "prd_multi_agent_adapter",
  "model": "claude-sonnet-4-6",
  "total_cost_usd": 13.28,
  "duration_seconds": 2611.8,        // ≈ 43.5 min
  "num_turns": 153,
  "timestamp": "2026-03-05T19:38:41Z"
}
```
Other real runs on disk (for the history table): `260305-1455-dev-codex-adapter-4a6c` (dev, Codex), `260305-1946-qa-codex-adapter-30b8` (qa, Codex), `260306-1458-docs-codex-adapter-35a2` (docs, Codex). So history can show a mix of plan/dev/qa/docs runs across Claude and Codex on branch `feat/codex`.

### Run config snapshot (what the run-config rail shows)
```json
{
  "repo": "https://github.com/asaficontact/DKMV.git",
  "branch": "feat/codex",
  "feature_name": "prd_multi_agent_adapter",
  "model": "claude-sonnet-4-6",
  "max_turns": 100,
  "timeout_minutes": 30,
  "max_budget_usd": null,
  "memory_limit": "8g"
}
```

### The built-in workflows (components) — use these in the workflow picker & builder
| Workflow | Purpose | Ordered tasks (stages) | Pause? | Budget signal |
|---|---|---|---|---|
| **plan** | PRD → full implementation docs | Analyze → Features & Stories → Phases → Assembly → Evaluate-Fix | Pauses after **Analyze** | ~$12 total (per-task $2–$5) |
| **dev** | Implement each phase from the plan docs | Implement-Phase (repeats once **per phase** via for-each) | No | $10 per phase |
| **qa** | Evaluate → fix → re-evaluate | Evaluate → Fix → Re-evaluate | Pauses after **Evaluate** | ~$2 |
| **docs** | Update docs + open a PR | Update-Docs → Verify → Create-PR | No | ~$3 |
| **ship** | End-to-end: analyze → plan → implement → evaluate-fix → finalize | 5 tasks | Pauses after **Analyze** | ~$29.50 |

### Agents & models
- **Claude** (default model `claude-sonnet-4-6`) — model names start with `claude-`.
- **Codex** (default model in the `gpt-5.x` family) — model names like `gpt-*` or `o3`/`o4` map to Codex.
- "Auto" can infer the agent from the chosen model.

### Real QA workflow manifest (for the builder's "qa loaded" state)
```yaml
name: qa
description: >
  QA evaluation component: reviews an implementation against implementation docs,
  runs tests, evaluates quality, and optionally fixes issues with an
  interactive evaluate-fix loop.
model: claude-sonnet-4-6
max_turns: 80
timeout_minutes: 25
max_budget_usd: 2.00
inputs:
  - name: impl_docs
    type: file
    src: "{{ impl_docs_path }}"
    dest: impl_docs/
tasks:
  - file: 01-evaluate.yaml
    pause_after: true        # ← this is the HITL checkpoint
  - file: 02-fix.yaml
  - file: 03-re-evaluate.yaml
```

### Real task (the "evaluate" task — for the task editor & its declared outputs)
- **commit:** false, **push:** false (read-only evaluation)
- **Outputs:**
  - `qa_evaluation.json` — required, saved
  - `qa_evaluation.md` — optional, saved
- **Output JSON schema the agent must produce** (use this to render an artifact preview / required-fields UI):
```json
{
  "status": "pass|fail",
  "issues": [
    { "severity": "critical|high|medium|low",
      "description": "…", "file": "path/to/file.py", "suggestion": "…" }
  ],
  "tests_total": 0, "tests_passed": 0, "tests_failed": 0,
  "summary": "overall assessment"
}
```

### Stream event shape (for the live event feed; raw-mode toggle)
Each event has: `type` (system | assistant | user | result), `subtype` (text | tool_use | tool_result), `content`, `tool_name`, `tool_input`, `total_cost_usd`, `duration_ms`, `num_turns`, `session_id`, `is_error`. Friendly renderings:
- system → "Session started · model claude-sonnet-4-6"
- assistant/tool_use → "🔧 `pytest -q` …" or "✏️ Edited `dkmv/adapters/codex.py`"
- user/tool_result (is_error=true) → red "✗ command failed: …"
- result → "✓ Done · 153 turns · $13.28 · 43m 32s"

### Pause / decision card shape (the HITL card) — REAL structure
A pause request has a `task_name`, a `context` map, and a list of **questions**. Each question:
```
PauseQuestion {
  id: string,
  question: string,
  options: [ { label: "...", description: "..." }, ... ],   // selectable choices
  default: string | null
}
```
The user's answer is `{ answers: { questionId: chosenLabel }, skip_remaining: boolean }`.
Example decision card (after the **plan → Analyze** stage):
- **Question:** "I found 4 candidate phases for this implementation. How would you like to proceed?"
- **Options:**
  - **"Proceed with all 4 phases"** — "Implement the full plan as analyzed (recommended)."
  - **"Merge phases 3 & 4"** — "Combine the last two phases to ship a smaller first cut."
  - **"Let me edit the plan first"** — "Pause here so I can adjust scope before continuing."
- Plus the global actions on QA-style pauses: **Ship as-is** and **Abort** (these set `skip_remaining = true`).

### GitHub label → board state mapping (the control plane)
- no `agent:*` label → **Backlog**
- `agent:queued` → **Queued**
- `agent:in-progress` → **In Progress** (a run is live)
- `agent:paused` → **Needs You**
- `agent:review` → **In Review** (PR open)
- issue closed / PR merged → **Done**

### Launch options the run panel maps to (real CLI flags — for the Advanced section)
`--branch`, `--feature-name`, `--model`, `--agent` (claude|codex), `--max-turns`, `--timeout` (min), `--max-budget-usd`, `--memory` (e.g. `8g`), `--context` (extra files), `--keep-alive`, `--start-task`.

---

## 9. Deliverables

Produce a clickable, multi-screen prototype covering Screens A–F above, with:
- The full happy-path flow linked: Connect → Board → Issue detail → launch → Live run (including a pause/decision card) → Completed → Runs history. Plus the Workflow/Task builder reachable from nav.
- **Dark theme as the hero**, light theme shown.
- For each screen, the **default state and the noted alternates** (empty / loading / running / paused / error).
- A small **style tile**: color tokens (incl. the state palette), type scale, button/badge/card styles, and the status-badge set.
- Realistic content using the reference appendix values (real repo `asaficontact/DKMV`, branch `feat/codex`, the plan/dev/qa/docs workflows, the $13.28 / 153-turn run, etc.).

Keep it **friendly, calm, and progressive**: simple on the surface, with real depth one click away.
