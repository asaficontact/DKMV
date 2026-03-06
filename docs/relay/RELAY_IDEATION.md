# Relay — Product Ideation Document

**The cloud UI for DKMV. Design, run, and refine AI development pipelines.**

*Author: Tawab Safi | Date: March 2026*

---

## 1. What Relay Is

Relay is the visual command center for DKMV's Component-Oriented Development paradigm. Where DKMV is the engine (Python CLI, Docker containers, YAML specs), Relay is the experience layer — a web-based dashboard where developers connect repos, design pipelines, watch agents work in real time, and manage a library of reusable workflow components.

Relay is not a chat interface. It's not another IDE. It's a **development operations dashboard** — the place where you orchestrate, observe, and refine how AI agents work on your code.

**The one-liner:** *Relay is GitHub Actions for AI agents — visual, real-time, and compounding.*

---

## 2. Core Screens & Navigation

### 2.1 Global Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│ ┌──────────┐                                                        │
│ │          │  ┌─────────────────────────────────────────────────┐   │
│ │  Sidebar │  │                                                 │   │
│ │  (240px) │  │              Main Content Area                  │   │
│ │          │  │                                                 │   │
│ │  ○ Home  │  │                                                 │   │
│ │  ○ Repos │  │                                                 │   │
│ │  ○ Runs  │  │                                                 │   │
│ │  ○ Lib   │  │                                                 │   │
│ │  ○ Cost  │  │                                                 │   │
│ │          │  │                                                 │   │
│ │  ───────  │  │                                                 │   │
│ │  ○ Gear  │  └─────────────────────────────────────────────────┘   │
│ └──────────┘                                                        │
└─────────────────────────────────────────────────────────────────────┘
```

**Navigation model:** Collapsible left sidebar (240px expanded, 64px collapsed — icon-only). Inspired by Linear's minimalism. Five primary sections:

| Section | Icon | Purpose |
|---------|------|---------|
| **Home** | ⌂ | Activity feed, active runs, quick actions |
| **Repos** | ◎ | Connected repositories, branches, project configs |
| **Runs** | ▶ | All pipeline runs across all repos, filterable |
| **Library** | ▤ | Component library (built-in + custom + community) |
| **Cost** | $ | Spend tracking, budgets, per-component analytics |
| **Settings** | ⚙ | GitHub connection, API keys, team, preferences |

**Command palette (Cmd+K / Ctrl+K):** Global search across repos, runs, components, settings. Type-ahead with categorized results. This is the power-user fast lane — inspired by Linear and VS Code.

**Keyboard shortcuts everywhere:** Every action should be keyboard-accessible. `g h` = go home, `g r` = go repos, `g l` = go library, `n p` = new pipeline, etc.

---

### 2.2 Home — The Activity Feed

The landing page after login. Shows what matters right now.

```
┌─────────────────────────────────────────────────────────────────┐
│  Good morning, Tawab.                                           │
│                                                                 │
│  ┌─── Active Runs ──────────────────────────────────────────┐  │
│  │                                                           │  │
│  │  ● feature/auth — Plan ██████████░░ 68%    $2.41         │  │
│  │    repo: tawab/my-project  ·  task 3/5  ·  12m elapsed   │  │
│  │                                                           │  │
│  │  ● feature/payments — Dev ████░░░░░░ 35%   $4.12         │  │
│  │    repo: tawab/saas-app  ·  phase 2/6  ·  24m elapsed    │  │
│  │                                                           │  │
│  │  ⏸ feature/auth — QA  [Paused: awaiting decision]         │  │
│  │    3 critical issues found. Fix / Ship / Abort?           │  │
│  │                                                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─── Recent Completed ─────────────────────────────────────┐  │
│  │  ✓ feature/search — Docs    2h ago    $6.80   14 commits │  │
│  │  ✓ feature/search — QA      4h ago    $8.20   PASS       │  │
│  │  ✗ feature/billing — Dev    6h ago    $12.40  FAIL       │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─── Quick Actions ────────────────────────────────────────┐  │
│  │  [+ New Pipeline]  [↻ Re-run Last]  [📂 Connect Repo]    │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Key interactions:**
- Click any active run → opens the Run Detail view (real-time agent output)
- The paused QA run shows inline action buttons (Fix / Ship / Abort) — this is the `pause_after` mechanism rendered visually
- Progress bars show both task progress (3/5) and cost accrual
- Completed runs show outcome (PASS/FAIL), cost, and commit count

---

### 2.3 Repos — Your Connected Projects

Shows all GitHub repos connected to Relay with their DKMV state.

```
┌─────────────────────────────────────────────────────────────────┐
│  Repositories                                    [+ Connect Repo]│
│                                                                 │
│  ┌─ tawab/my-project ──────────────────────────────────────┐   │
│  │  ★ Initialized  ·  main  ·  Last run: 2h ago            │   │
│  │                                                          │   │
│  │  Active branches:                                        │   │
│  │    feature/auth     — QA paused (awaiting decision)      │   │
│  │    feature/search   — Docs completed ✓                   │   │
│  │    feature/billing  — Dev failed ✗                       │   │
│  │                                                          │   │
│  │  [View] [New Run] [Settings]                             │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─ tawab/saas-app ────────────────────────────────────────┐   │
│  │  ★ Initialized  ·  main  ·  Last run: 1d ago            │   │
│  │                                                          │   │
│  │  Active branches:                                        │   │
│  │    feature/payments — Dev in progress ●                  │   │
│  │                                                          │   │
│  │  [View] [New Run] [Settings]                             │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─ tawab/open-source-lib ─────────────────────────────────┐   │
│  │  ○ Not initialized  ·  No runs yet                       │   │
│  │  [Initialize] [Settings]                                 │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

**Clicking "View" on a repo** opens the Repo Detail page:

```
┌─────────────────────────────────────────────────────────────────┐
│  tawab/my-project                                [⚙ Settings]   │
│  ────────────────────────────────────────────────────────────── │
│                                                                 │
│  Branches                          Pipeline Runs                │
│  ─────────                         ──────────────               │
│  ● main                           (select a branch)            │
│  ● feature/auth                                                 │
│  ● feature/search                                               │
│  ● feature/billing                                              │
│                                                                 │
│  [When feature/auth is selected:]                               │
│                                                                 │
│  feature/auth                                                   │
│  ─────────────                                                  │
│  Run History:                                                   │
│  ┌─────┬──────────┬────────┬────────┬───────┬──────────────┐   │
│  │ #   │ Pipeline │ Status │ Cost   │ Time  │ When         │   │
│  ├─────┼──────────┼────────┼────────┼───────┼──────────────┤   │
│  │ 3   │ QA       │ ⏸ Pause│ $4.20  │ 18m   │ 10 min ago   │   │
│  │ 2   │ Dev      │ ✓ Pass │ $12.40 │ 45m   │ 2 hours ago  │   │
│  │ 1   │ Plan     │ ✓ Pass │ $8.80  │ 22m   │ 3 hours ago  │   │
│  └─────┴──────────┴────────┴────────┴───────┴──────────────┘   │
│                                                                 │
│  [▶ New Run on this Branch]                                     │
└─────────────────────────────────────────────────────────────────┘
```

**Key interactions:**
- Branch list pulled live from GitHub via API
- Each branch shows its latest pipeline state
- "New Run" opens the Pipeline Launcher (select component, configure, go)
- Clicking a run opens Run Detail

---

### 2.4 Pipeline Launcher — Starting a New Run

This is what you see when you click "New Run." It's the visual equivalent of typing `dkmv plan --branch feature/auth --prd requirements.md`.

```
┌─────────────────────────────────────────────────────────────────┐
│  New Pipeline Run                                               │
│  ────────────────────────────────────────────────────────────── │
│                                                                 │
│  Repository:  [tawab/my-project     ▾]                          │
│  Branch:      [feature/auth         ▾]                          │
│                                                                 │
│  ─────────────────────────────────────────────────────────────  │
│                                                                 │
│  Select Pipeline:                                               │
│                                                                 │
│  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐               │
│  │  Plan  │  │  Dev   │  │  QA    │  │  Docs  │               │
│  │  ─────  │  │  ─────  │  │  ─────  │  │  ─────  │               │
│  │ PRD →  │  │ Impl → │  │ Eval → │  │ Code → │               │
│  │ Impl   │  │ Code   │  │ Fix →  │  │ Docs → │               │
│  │ Docs   │  │ Tests  │  │ Verify │  │ PR     │               │
│  │        │  │        │  │        │  │        │               │
│  │ ~$14   │  │ ~$20   │  │ ~$12   │  │ ~$8    │               │
│  │ ~25min │  │ ~45min │  │ ~20min │  │ ~15min │               │
│  └────────┘  └────────┘  └────────┘  └────────┘               │
│                                                                 │
│  ┌──────────────┐  ┌──────────────────┐                        │
│  │ Custom       │  │ security-audit   │                        │
│  │ Component    │  │ (registered)     │                        │
│  │              │  │                  │                        │
│  │ [Browse...]  │  │ 3 tasks · ~$6    │                        │
│  └──────────────┘  └──────────────────┘                        │
│                                                                 │
│  [After selecting Plan:]                                        │
│                                                                 │
│  Configuration:                                                 │
│  ─────────────                                                  │
│  PRD File:        [requirements.md          ] [Browse repo ▾]   │
│  Design Docs:     [docs/design/             ] [Browse repo ▾]   │
│  Feature Name:    [auth-system              ]                   │
│  Context Files:   [+ Add local files]                           │
│                                                                 │
│  Advanced:  ▶ (collapsed)                                       │
│    Model:        [claude-sonnet-4-6  ▾]                         │
│    Max Budget:   [$15.00             ]                           │
│    Timeout:      [30 min             ]                           │
│    Auto mode:    [○ Off  ● On]                                  │
│                                                                 │
│                            [Cancel]  [▶ Launch Pipeline]        │
└─────────────────────────────────────────────────────────────────┘
```

**Key interactions:**
- Pipeline cards show estimated cost and time based on historical averages
- Repo file browser lets you pick PRD/impl-docs from the actual repo tree
- "Browse repo" dropdown shows the file tree of the selected branch
- Context files can be dragged from local machine
- Advanced section collapsed by default (sensible defaults from .dkmv/config.json)

---

### 2.5 Run Detail — The Control Room

This is the most important screen. It's what you watch while an agent works.

```
┌─────────────────────────────────────────────────────────────────┐
│  Run #a3f8b2c1 — Plan on feature/auth                          │
│  tawab/my-project  ·  Started 12m ago  ·  $2.41 so far         │
│  ────────────────────────────────────────────────────────────── │
│                                                                 │
│  Pipeline Progress:                                             │
│  ┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐          │
│  │Analyze │ →  │Features│ →  │ Phases │ →  │Assembly│ → ...    │
│  │  ✓     │    │  ✓     │    │  ●     │    │  ○     │          │
│  │ $0.82  │    │ $0.94  │    │ $0.65  │    │  —     │          │
│  │ 4m 12s │    │ 3m 50s │    │ 3m 02s │    │  —     │          │
│  └────────┘    └────────┘    └────────┘    └────────┘          │
│                                                                 │
│  ┌─── Agent Activity ───────────────────────────────────────┐  │
│  │                                                           │  │
│  │  ┌─ Tabs: [Stream] [Files Changed] [Outputs] [Cost] ──┐ │  │
│  │  │                                                      │ │  │
│  │  │  14:23:45  Reading docs/prds/auth.md                 │ │  │
│  │  │  14:23:48  Reading src/auth/models.py                │ │  │
│  │  │  14:23:52  Reading src/auth/middleware.py             │ │  │
│  │  │  14:24:01  ✏ Writing .agent/phase3_tasks.md          │ │  │
│  │  │            ┌──────────────────────────────────────┐  │ │  │
│  │  │            │ ## Phase 3: OAuth Integration        │  │ │  │
│  │  │            │                                      │  │ │  │
│  │  │            │ ### T301: Add OAuth provider config   │  │ │  │
│  │  │            │ - Create OAuthConfig dataclass        │  │ │  │
│  │  │            │ - Support Google, GitHub, Microsoft   │  │ │  │
│  │  │            │ ...                                   │  │ │  │
│  │  │            └──────────────────────────────────────┘  │ │  │
│  │  │  14:24:15  ✏ Writing .agent/phase3_tasks.md (cont)  │ │  │
│  │  │  14:24:22  Running: pytest tests/unit/ -v            │ │  │
│  │  │            ┌──────────────────────────────────────┐  │ │  │
│  │  │            │ tests/unit/test_auth.py::test_login  │  │ │  │
│  │  │            │   PASSED                              │  │ │  │
│  │  │            │ tests/unit/test_auth.py::test_oauth  │  │ │  │
│  │  │            │   PASSED                              │  │ │  │
│  │  │            │ 2 passed in 1.23s                     │  │ │  │
│  │  │            └──────────────────────────────────────┘  │ │  │
│  │  │                                                      │ │  │
│  │  │  ▼ Auto-scrolling                          [Pause ⏸] │ │  │
│  │  └──────────────────────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  [⏹ Stop Run]  [🔗 Share]  [📋 Copy Logs]                      │
└─────────────────────────────────────────────────────────────────┘
```

**The Stream tab** is the heart of the experience. It's NOT a raw terminal dump. It's a curated, real-time activity feed:

- **File reads** shown as one-liners (icon + filename), expandable to show content
- **File writes** shown with a preview of what was written (syntax highlighted, collapsible)
- **Shell commands** shown with command + output in a terminal-styled block
- **Agent reasoning** (thinking) shown in a muted, italic style — visible but not dominant
- **Errors** highlighted in red with full stack trace
- **Git operations** (commit, push) shown as special events with commit message

This transforms the raw `stream.jsonl` into something readable and engaging — like watching a developer work, not reading a log file.

**The Files Changed tab** shows a running diff of all files modified so far (like a live PR diff).

**The Outputs tab** shows collected artifacts (analysis.json, qa_report.json, etc.) rendered as formatted cards.

**The Cost tab** shows a live sparkline of cost accumulation per task, with budget ceiling marked.

**Pause point interaction:**
When a `pause_after` triggers, the stream pauses and a decision card appears inline:

```
┌─── Decision Required ─────────────────────────────────────┐
│                                                            │
│  QA Evaluation Complete                                    │
│                                                            │
│  Status: FAIL                                              │
│  Tests: 142 total, 138 passed, 4 failed                   │
│  Issues: 2 critical, 1 high, 3 medium                     │
│                                                            │
│  ┌─────────────────┐  ┌───────────┐  ┌─────────┐         │
│  │ Fix & Re-eval   │  │ Ship      │  │ Abort   │         │
│  │ (Recommended)   │  │ as-is     │  │         │         │
│  └─────────────────┘  └───────────┘  └─────────┘         │
│                                                            │
│  [View full evaluation report →]                           │
└────────────────────────────────────────────────────────────┘
```

---

### 2.6 Pipeline Designer — Building Custom Pipelines

This is where you compose new pipelines visually. It's the "Build Your Own" section from the README, but visual instead of YAML.

```
┌─────────────────────────────────────────────────────────────────┐
│  Pipeline Designer — security-audit                             │
│  ────────────────────────────────────────────────────────────── │
│                                                                 │
│  ┌────────────────────────────────────────────────────────┐    │
│  │                                                        │    │
│  │   ┌──────────┐     ┌──────────┐     ┌──────────┐     │    │
│  │   │ 01-Scan  │ ──→ │ 02-Fix   │ ──→ │03-Verify │     │    │
│  │   │          │     │          │     │          │     │    │
│  │   │ sonnet   │     │ sonnet   │     │ sonnet   │     │    │
│  │   │ $2 max   │     │ $5 max   │     │ $2 max   │     │    │
│  │   │ commit:✓ │     │ commit:✓ │     │ commit:✓ │     │    │
│  │   │          │     │ ⏸ pause  │     │          │     │    │
│  │   └──────────┘     └──────────┘     └──────────┘     │    │
│  │                                                        │    │
│  │                     [+ Add Task]                       │    │
│  │                                                        │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌─── Task Editor (01-Scan) ────────────────────────────────┐  │
│  │                                                           │  │
│  │  Name:         [scan                    ]                 │  │
│  │  Description:  [Scan for vulnerabilities]                 │  │
│  │                                                           │  │
│  │  Prompt:                                                  │  │
│  │  ┌────────────────────────────────────────────────────┐  │  │
│  │  │ Scan the codebase for OWASP Top 10 vulnerabilities │  │  │
│  │  │ using the checklist at `.agent/checklist.md`.      │  │  │
│  │  │ Write results to `.agent/scan_results.json`.       │  │  │
│  │  └────────────────────────────────────────────────────┘  │  │
│  │                                                           │  │
│  │  Instructions:                                            │  │
│  │  ┌────────────────────────────────────────────────────┐  │  │
│  │  │ - Focus on OWASP Top 10                            │  │  │
│  │  │ - Check dependencies for known CVEs                │  │  │
│  │  └────────────────────────────────────────────────────┘  │  │
│  │                                                           │  │
│  │  Inputs:                                                  │  │
│  │    checklist (file) ← {{ checklist_path }}                │  │
│  │    [+ Add Input]                                          │  │
│  │                                                           │  │
│  │  Outputs:                                                 │  │
│  │    scan_results.json  [required ✓] [save ✓]               │  │
│  │    [+ Add Output]                                         │  │
│  │                                                           │  │
│  │  ┌─ Advanced ────────────────────────────────────────┐   │  │
│  │  │ Model: [claude-sonnet-4-6 ▾]  Budget: [$2.00]    │   │  │
│  │  │ Turns: [80]  Timeout: [25 min]                    │   │  │
│  │  │ Commit: [✓]  Push: [○]  Pause After: [○]         │   │  │
│  │  └───────────────────────────────────────────────────┘   │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  [View YAML]  [Save]  [▶ Test Run]                              │
└─────────────────────────────────────────────────────────────────┘
```

**Key interactions:**
- Click task cards to edit them in the bottom panel
- Drag to reorder tasks
- "View YAML" shows the generated YAML (for users who want to version it in git)
- "Test Run" launches a dry run against a test branch
- Template variables ({{ checklist_path }}) are syntax-highlighted and auto-complete from previous task outputs
- Pipeline is saved to the component registry (.dkmv/components.json) and/or to the Relay cloud

**This is NOT a node-based graph builder.** It's a **linear sequence with cards** — because DKMV pipelines are sequential by design. Keeping it linear keeps it simple and true to the mental model. If we add branching/parallel execution later, the visual language can evolve.

---

### 2.7 Library — Component Marketplace

Browse, discover, and install pipeline components.

```
┌─────────────────────────────────────────────────────────────────┐
│  Component Library                        [Search components...] │
│  ────────────────────────────────────────────────────────────── │
│                                                                 │
│  ┌─ Tabs: [Built-in] [My Components] [Community] ────────────┐ │
│  │                                                             │ │
│  │  ┌─── Featured ──────────────────────────────────────────┐ │ │
│  │  │                                                        │ │ │
│  │  │  ┌────────────────┐  ┌────────────────┐               │ │ │
│  │  │  │ Rails Security │  │ React Migrator │               │ │ │
│  │  │  │ Audit          │  │ v17 → v19      │               │ │ │
│  │  │  │                │  │                │               │ │ │
│  │  │  │ 3 tasks        │  │ 4 tasks        │               │ │ │
│  │  │  │ ~$6 avg        │  │ ~$18 avg       │               │ │ │
│  │  │  │ 94% success    │  │ 87% success    │               │ │ │
│  │  │  │ 340 runs       │  │ 128 runs       │               │ │ │
│  │  │  │                │  │                │               │ │ │
│  │  │  │ by @securityco │  │ by @migrateco  │               │ │ │
│  │  │  │ ★★★★☆ (42)     │  │ ★★★★★ (18)     │               │ │ │
│  │  │  │                │  │                │               │ │ │
│  │  │  │ [Install]      │  │ [Install]      │               │ │ │
│  │  │  └────────────────┘  └────────────────┘               │ │ │
│  │  │                                                        │ │ │
│  │  └────────────────────────────────────────────────────────┘ │ │
│  │                                                             │ │
│  │  Categories:                                                │ │
│  │  [Security] [Migration] [Testing] [Documentation]           │ │
│  │  [Code Review] [DevOps] [Data] [Performance]                │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

**Component detail page:**

```
┌─────────────────────────────────────────────────────────────────┐
│  Rails Security Audit                          [Install] [Fork] │
│  by @securityco  ·  v2.3.1  ·  Apache 2.0                      │
│  ────────────────────────────────────────────────────────────── │
│                                                                 │
│  Scans Rails applications for OWASP Top 10 vulnerabilities,     │
│  checks Gemfile for known CVEs, and generates a remediation     │
│  plan with priority rankings.                                   │
│                                                                 │
│  Pipeline:                                                      │
│  ┌──────────┐ → ┌──────────┐ → ┌──────────┐                   │
│  │ 01-Scan  │   │ 02-Fix   │   │03-Verify │                   │
│  │ $2 max   │   │ $5 max   │   │ $2 max   │                   │
│  └──────────┘   └──────────┘   └──────────┘                   │
│                                                                 │
│  Stats:                                                         │
│  ────────                                                       │
│  Total runs:     340          Avg cost:       $5.80             │
│  Success rate:   94%          Avg duration:   18 min            │
│  Refinements:    47           Last updated:   2 days ago        │
│                                                                 │
│  Required inputs:                                               │
│  - checklist_path (file) — OWASP checklist to scan against      │
│                                                                 │
│  Outputs:                                                       │
│  - scan_results.json — vulnerability findings                   │
│  - remediation_plan.md — prioritized fix plan                   │
│                                                                 │
│  ┌─ Tabs: [README] [YAML Source] [Run History] [Reviews] ────┐ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

**Key interactions:**
- "Install" adds component to your Relay account
- "Fork" creates an editable copy in your Library
- YAML Source tab shows the raw task definitions (for learning and transparency)
- Run History shows aggregate stats from community usage (anonymized)
- Reviews are short text reviews with star ratings

---

### 2.8 Cost Dashboard

```
┌─────────────────────────────────────────────────────────────────┐
│  Cost Overview                     This month: $142.60          │
│  ────────────────────────────────────────────────────────────── │
│                                                                 │
│  ┌─── Monthly Trend ────────────────────────────────────────┐  │
│  │   $                                                       │  │
│  │   150 ─                                              ╱    │  │
│  │   100 ─                               ╱─────────────╱     │  │
│  │    50 ─              ╱───────────────╱                    │  │
│  │     0 ──────────────╱                                     │  │
│  │        Jan    Feb    Mar    Apr    May    Jun              │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─── By Component ───────────┐  ┌─── By Repository ────────┐ │
│  │  Dev      ████████  $68.40 │  │  my-project  ████  $82.20│ │
│  │  Plan     █████     $38.20 │  │  saas-app    ███   $44.80│ │
│  │  QA       ████      $24.80 │  │  oss-lib     █     $15.60│ │
│  │  Docs     ██        $11.20 │  │                          │ │
│  └────────────────────────────┘  └──────────────────────────┘ │
│                                                                 │
│  Budget Alerts:                                                 │
│  Monthly limit: $200  ·  Current: $142.60  ·  Projected: $190  │
│  [Set Budget Limit]                                             │
└─────────────────────────────────────────────────────────────────┘
```

---

### 2.9 Full Pipeline Runs View

The global runs view across all repos — like a CI/CD dashboard.

```
┌─────────────────────────────────────────────────────────────────┐
│  All Runs                                                       │
│  ────────────────────────────────────────────────────────────── │
│  Filter: [All repos ▾] [All components ▾] [All statuses ▾]     │
│                                                                 │
│  ┌────┬───────────────┬──────────┬────────┬───────┬──────────┐ │
│  │ ID │ Repo/Branch   │ Pipeline │ Status │ Cost  │ Time     │ │
│  ├────┼───────────────┼──────────┼────────┼───────┼──────────┤ │
│  │ 3f │ my-proj/auth  │ QA       │ ⏸ Pause│ $4.20 │ 18m      │ │
│  │ 2a │ saas/payments │ Dev      │ ● Run  │ $4.12 │ 24m      │ │
│  │ 1c │ my-proj/auth  │ Dev      │ ✓ Pass │$12.40 │ 45m      │ │
│  │ 0f │ my-proj/auth  │ Plan     │ ✓ Pass │ $8.80 │ 22m      │ │
│  │ 9e │ saas/billing  │ Dev      │ ✗ Fail │$12.40 │ 38m      │ │
│  │ 8b │ my-proj/search│ Docs     │ ✓ Pass │ $6.80 │ 14m      │ │
│  └────┴───────────────┴──────────┴────────┴───────┴──────────┘ │
│                                                                 │
│  Showing 6 of 47 runs  ·  [Load more]                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Onboarding Flow

First-time user experience. Needs to feel effortless — like Vercel's "deploy in 60 seconds" but for agent pipelines.

### Step 1: Sign Up & Connect GitHub

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│                         Welcome to Relay                        │
│                                                                 │
│            Design, run, and refine AI dev pipelines.            │
│                                                                 │
│              ┌───────────────────────────────┐                  │
│              │  ◉ Sign in with GitHub        │                  │
│              └───────────────────────────────┘                  │
│                                                                 │
│       We'll ask for repo access. Nothing is modified            │
│       until you launch a pipeline.                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Step 2: Select a Repo

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  Pick a repository to start with                                │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  🔍 Search repositories...                               │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │  ○ tawab/my-project         ★ 12   Updated 2h ago       │  │
│  │  ○ tawab/saas-app           ★ 3    Updated 1d ago       │  │
│  │  ○ tawab/open-source-lib    ★ 45   Updated 3d ago       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  You can add more repos later.                                  │
│                                                                 │
│                                          [Continue →]           │
└─────────────────────────────────────────────────────────────────┘
```

### Step 3: Add API Key

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  Connect your Anthropic account                                 │
│                                                                 │
│  Relay uses Claude Code agents inside containers.               │
│  Choose your auth method:                                       │
│                                                                 │
│  ● API Key                                                      │
│    ┌────────────────────────────────────────────────┐           │
│    │  sk-ant-...                                    │           │
│    └────────────────────────────────────────────────┘           │
│                                                                 │
│  ○ Claude Code Subscription (OAuth)                             │
│    Connect your existing Claude subscription.                   │
│                                                                 │
│                                          [Continue →]           │
└─────────────────────────────────────────────────────────────────┘
```

### Step 4: First Run

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  Run your first pipeline                                        │
│                                                                 │
│  Try the Plan component on a branch with a PRD:                 │
│                                                                 │
│  Branch:    [feature/auth         ▾]                            │
│  PRD File:  [docs/auth-prd.md     ▾]                            │
│                                                                 │
│           ┌──────────────────────────────┐                      │
│           │   ▶ Launch your first run    │                      │
│           └──────────────────────────────┘                      │
│                                                                 │
│  Or explore the component library first →                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Target: first meaningful run within 3 minutes of signup.**

---

## 4. Visual Design Direction

### 4.1 Design Principles

1. **Dark by default.** Developer tool. Optimized for long sessions. Light mode available but dark is primary.
2. **Calm, not flashy.** Muted backgrounds, sharp accent colors only for status and actions. Inspired by Linear and Vercel — not Figma's candy palette.
3. **Information density over whitespace.** Developers want to see data. Don't hide it behind clicks. But use hierarchy (size, weight, opacity) to prevent overwhelm.
4. **Terminal aesthetics where appropriate.** Agent output uses monospace. But the chrome (nav, cards, controls) is modern sans-serif.
5. **Motion with purpose.** Subtle transitions for state changes (run starting, task completing). No gratuitous animation.

### 4.2 Color Palette

```
Background:
  --bg-primary:     #0a0a0b      (near-black, main background)
  --bg-secondary:   #141416      (cards, panels)
  --bg-tertiary:    #1c1c1f      (hover states, elevated surfaces)

Text:
  --text-primary:   #e8e8ed      (high emphasis)
  --text-secondary: #8e8e93      (low emphasis, labels)
  --text-muted:     #48484a      (disabled, hints)

Accent (the "Relay blue"):
  --accent:         #3b82f6      (primary actions, links)
  --accent-hover:   #60a5fa      (hover state)

Status:
  --status-success: #22c55e      (green — completed, pass)
  --status-warning: #eab308      (yellow — paused, attention)
  --status-error:   #ef4444      (red — failed, error)
  --status-running: #3b82f6      (blue — in progress)
  --status-pending: #6b7280      (gray — queued)

Borders:
  --border:         #27272a      (subtle card borders)
  --border-focus:   #3b82f6      (focus rings)
```

### 4.3 Typography

```
UI Text:     Inter (or system font stack)
Code/Logs:   JetBrains Mono (or Fira Code)

Scale:
  --text-xs:   12px   (metadata, timestamps)
  --text-sm:   13px   (secondary text, table cells)
  --text-base: 14px   (body text, inputs)
  --text-lg:   16px   (section headers)
  --text-xl:   20px   (page titles)
  --text-2xl:  24px   (hero text)
```

### 4.4 Spacing System

8px base unit. All spacing is multiples: 4, 8, 12, 16, 24, 32, 48, 64.

---

## 5. Architecture & Tech Stack

### 5.1 Frontend

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | **Next.js 15 (App Router)** | Server components for initial load, client components for interactivity. Vercel deployment. |
| Styling | **Tailwind CSS** | Utility-first, matches dark-mode-first design system. |
| State | **Zustand** | Lightweight, no boilerplate. Good for real-time state (run progress, agent stream). |
| Real-time | **WebSocket (Socket.io)** | For agent stream, run status updates, cost ticks. |
| Terminal | **xterm.js** | For raw log view (optional "raw mode" toggle). |
| Components | **shadcn/ui** | Accessible, unstyled primitives. Customizable to match Relay's design system. |
| Charts | **Recharts** | For cost dashboard, trend lines, pipeline analytics. |
| Code highlighting | **Shiki** | For syntax-highlighted file diffs and code output. |

### 5.2 Backend

| Layer | Choice | Rationale |
|-------|--------|-----------|
| API | **Next.js API routes + tRPC** | Type-safe API layer. Co-located with frontend. |
| Auth | **NextAuth.js + GitHub OAuth** | GitHub-first auth. Session management. |
| Database | **PostgreSQL (via Supabase or Neon)** | Runs, components, user data, analytics. |
| Queue | **BullMQ (Redis)** | Job queue for pipeline execution. |
| Execution | **DKMV Python engine** | The existing CLI, invoked as a subprocess or service. |
| Storage | **S3 / R2** | Run artifacts, stream logs, component packages. |
| Real-time | **Socket.io server** | Bridges DKMV's stream.jsonl to WebSocket clients. |

### 5.3 Execution Model

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐
│   Browser    │     │   Relay API  │     │   Execution Worker   │
│   (Next.js)  │◄───►│   (tRPC)     │◄───►│   (Python/DKMV)      │
│              │ WS  │              │ BullMQ│                      │
│  - Dashboard │     │  - Auth      │     │  - Docker containers  │
│  - Stream    │     │  - Jobs      │     │  - Claude Code agents │
│  - Controls  │     │  - GitHub    │     │  - stream.jsonl → WS  │
└──────────────┘     └──────────────┘     └──────────────────────┘
```

**Phase 1 (Local):** Execution worker runs on user's machine. Relay web UI talks to local daemon over localhost WebSocket. Docker containers run locally. This is the fastest path to a working product.

**Phase 2 (Cloud):** Execution worker runs on cloud infrastructure. Docker containers run on managed compute (ECS, Fly.io, or similar). Users don't need Docker locally. This enables teams and the marketplace.

---

## 6. Key Differentiators vs. Competition

| Feature | Relay | Codex | Devin | Copilot WS | Factory |
|---------|-------|-------|-------|------------|---------|
| **Reusable pipeline definitions** | ✓ YAML components, versionable | ✗ Sessions | ✗ Sessions | ✗ Workspaces | Partial (Droids) |
| **Pipeline compounding** | ✓ Refinement tracked, success rates improve | ✗ | ✗ | ✗ | ✗ |
| **Visual pipeline designer** | ✓ Card-based, generates YAML | ✗ | ✗ | ✗ | ✗ |
| **Component marketplace** | ✓ Share, fork, install | ✗ | ✗ | ✗ | ✗ |
| **Multi-repo dashboard** | ✓ All repos, all branches | ✗ | ✗ | Single repo | Enterprise |
| **Cost per component** | ✓ Per-task budgets, tracking | ✗ | Per-ACU | ✗ | Enterprise |
| **Human-in-the-loop gates** | ✓ Visual pause points | ✗ | Interactive | Editable specs | ✗ |
| **Open source engine** | ✓ DKMV (Apache 2.0) | ✗ | ✗ | ✗ | ✗ |

**The moat in one sentence:** Relay is the only platform where the development workflow itself is a first-class, versionable, refinable, shareable artifact — not a conversation that disappears.

---

## 7. User Flows

### 7.1 "I have a PRD and want to ship a feature"

1. Open Relay → Home
2. Click "New Pipeline" → select repo → select branch (or create new)
3. Select "Plan" component → point to PRD file in repo
4. Watch Plan run in real-time → pause point at analysis → approve
5. Plan completes → implementation docs created on branch
6. Click "Continue with Dev" (suggested next step)
7. Dev runs → watch phase-by-phase implementation
8. Click "Continue with QA"
9. QA evaluates → pause → choose "Fix & Re-eval"
10. QA passes → click "Continue with Docs"
11. Docs generates → PR created on GitHub
12. Done. Total time: ~2 hours. Total cost: ~$45.

### 7.2 "I want to create a custom security audit component"

1. Open Relay → Library → My Components → "+ New Component"
2. Pipeline Designer opens
3. Click "+ Add Task" three times (scan, fix, verify)
4. Configure each task: prompt, inputs, outputs, budget
5. "Save" → component saved to Library
6. "Test Run" → pick a test repo and branch → watch it run
7. Refine based on results → re-test
8. "Publish to Community" (optional)

### 7.3 "I want to see what all my agents are doing right now"

1. Open Relay → Home
2. Active Runs section shows all in-progress pipelines
3. Click any run → full streaming view
4. Or: Runs tab → filter by "Running" status → see all active runs across repos

### 7.4 "I want to run the same pipeline on multiple repos"

1. Open Relay → Library → select component
2. Click "Run" → select multiple repos from dropdown
3. Each repo gets its own run, visible on Home
4. (Future: batch run UI with aggregate progress)

---

## 8. Feature Prioritization

### Phase 1: Core (MVP — 6-8 weeks)
- GitHub OAuth + repo connection
- Pipeline launcher (select component, configure, launch)
- Run Detail with real-time agent stream
- Home dashboard with active/recent runs
- Runs list with filtering
- Built-in components (plan, dev, qa, docs)
- Cost tracking per run

### Phase 2: Design (4-6 weeks)
- Pipeline Designer (visual task editor)
- Component save/load to Library
- Repo detail with branch-level run history
- Pause point interaction UI

### Phase 3: Ecosystem (4-6 weeks)
- Community component marketplace
- Component publishing and forking
- Star ratings and usage stats
- Component search and discovery

### Phase 4: Teams (4-6 weeks)
- Team workspaces
- Shared component libraries
- Role-based access
- Budget limits per team member

### Phase 5: Cloud Execution (6-8 weeks)
- Cloud-hosted Docker containers
- No local Docker requirement
- Persistent execution with recovery
- Parallel runs across cloud workers

---

## 9. Open Questions

1. **Local-first or cloud-first?** Phase 1 could be a local Electron/Tauri app that wraps the existing CLI with a UI. Or it could be web-first with a local daemon. Web-first is better for sharing and marketplace but requires more infra. Recommendation: web-first with local execution daemon.

2. **Pricing model?** Options: (a) Free tier + paid per-run compute, (b) Monthly subscription for cloud execution, (c) Free for local execution, paid for cloud. The DKMV engine stays open source regardless.

3. **How to handle secrets?** API keys and GitHub tokens need secure storage. For local execution, use the existing .env/keychain approach. For cloud, need a secrets manager (Vault, AWS Secrets Manager, or encrypted at rest in DB).

4. **Mobile?** Not for MVP. But the Home dashboard and Run Detail should be responsive enough to check on a phone (read-only monitoring).

5. **Notifications?** When a run completes or pauses, notify via: browser notification, email, Slack webhook, or mobile push. Start with browser + email.

6. **Component versioning?** When community components are updated, how do users handle breaking changes? Semantic versioning + lockfile approach (like package.json)?

---

## 10. The Name & Brand

**Relay** works because:
- It captures the pipeline metaphor (passing the baton between agent stages)
- It implies speed and coordination
- It's one word, memorable, easy to type
- relay.dev / relay.sh / getrelay.dev are viable domain options
- "Set up a Relay" / "My auth Relay ran clean" / "Check the Relay dashboard"
- It doesn't conflict with Facebook's Relay (GraphQL library) in meaningful ways — different market, different audience

**Tagline options:**
- "Relay — Ship with agents that compound."
- "Relay — The command center for AI development."
- "Relay — Design pipelines. Watch agents work. Ship code."
- "Relay — Where development workflows compound."

---

*This is a living document. Update as the vision evolves.*
