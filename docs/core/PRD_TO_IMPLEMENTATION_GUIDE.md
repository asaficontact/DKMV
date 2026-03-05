# PRD to Implementation Documents — Policy & Guideline

A complete process for decomposing a Product Requirements Document (PRD) into developer-ready implementation documents optimized for AI agent execution.

---

## Table of Contents

1. [Purpose & Audience](#1-purpose--audience)
2. [Overview: The Decomposition Pipeline](#2-overview-the-decomposition-pipeline)
3. [Document Inventory](#3-document-inventory)
4. [Step 1: Analyze the PRD](#step-1-analyze-the-prd)
5. [Step 2: Review & Update ADRs](#step-2-review--update-architecture-decision-records-adrs)
6. [Step 3: Extract Features](#step-3-extract-features)
7. [Step 4: Derive User Stories](#step-4-derive-user-stories)
8. [Step 5: Define Phases](#step-5-define-phases)
9. [Step 6: Decompose Tasks](#step-6-decompose-tasks)
10. [Step 7: Write Phase Documents](#step-7-write-phase-documents)
11. [Step 8: Create the Master Task List](#step-8-create-the-master-task-list)
12. [Step 9: Initialize Progress Tracking](#step-9-initialize-progress-tracking)
13. [Step 10: Write the README](#step-10-write-the-readme)
14. [Step 11: Include Supporting Documents](#step-11-include-supporting-documents)
15. [Step 12: Create the Implementation CLAUDE.md](#step-12-create-the-implementation-claudemd)
16. [Step 13: Verification & Validation](#step-13-verification--validation)
17. [Heuristics & Best Practices](#heuristics--best-practices)
18. [Templates](#templates)
19. [Multi-Cycle Planning](#multi-cycle-planning)
20. [Anti-Patterns](#anti-patterns)

---

## 1. Purpose & Audience

This document defines the **exact process** for taking a PRD and producing a complete set of implementation documents that an AI coding agent (or human developer) can execute phase-by-phase to deliver the specified system.

**Use when:**
- You have a finalized PRD and need to begin implementation
- You are planning work for AI agents (Claude Code, Cursor, etc.)
- You need traceability from requirements through to code

**Audience:** Anyone creating implementation documents — whether a human planner, a product manager, or an AI agent acting in a planning capacity.

---

## 2. Overview: The Decomposition Pipeline

```
PRD (What/Why)
    │
    ▼
┌────────────────────────────────────────────────────────────────────┐
│  Step 1: Analyze the PRD                                           │
│    Read the full PRD. Identify features, constraints, non-goals.   │
│    Note architecture decisions, external dependencies, risks.      │
└────────────────────┬───────────────────────────────────────────────┘
                     │
    ┌────────────────┼────────────────┐
    ▼                ▼                ▼
┌──────────┐  ┌──────────────┐  ┌──────────────┐
│ features │  │ user_stories │  │  Identify     │
│   .md    │  │     .md      │  │  phases &     │
│          │  │              │  │  dependencies │
└────┬─────┘  └──────┬───────┘  └──────┬───────┘
     │               │                 │
     └───────────────┼─────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────────────────┐
│  Step 6-7: Decompose into tasks per phase                          │
│    Each phase gets its own phaseN_*.md with task specifications.    │
│    Tasks link back to features, user stories, and PRD sections.    │
└────────────────────┬───────────────────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
  ┌──────────┐ ┌──────────┐ ┌──────────┐
  │ tasks.md │ │progress  │ │ README   │
  │ (master  │ │   .md    │ │   .md    │
  │  list)   │ │(tracking)│ │ (index)  │
  └──────────┘ └──────────┘ └──────────┘
```

**The full set of output documents:**

```
docs/implementation/{version-label}/
├── README.md                  # Navigation index, source-of-truth pointer
├── {prd_name}.md              # Original PRD (read-only copy or link)
├── features.md                # Feature registry with dependencies
├── user_stories.md            # User stories with traceability matrix
├── tasks.md                   # Master task list with checkboxes
├── phase1_{name}.md           # Phase 1 detailed task specs
├── phase2_{name}.md           # Phase 2 detailed task specs
├── ...                        # One file per phase
├── progress.md                # Session log (starts empty)
└── {supporting_docs}.md       # Any reference docs (schemas, specs, etc.)
```

---

## 3. Document Inventory

Every implementation directory MUST contain these documents:

| Document | Purpose | Created By | Updated By |
|----------|---------|------------|------------|
| **README.md** | Entry point. Lists all docs and their purpose. Points to source of truth. | Planner | Planner (if docs added) |
| **PRD** (copy or link) | The source of truth. Read-only during implementation. | Product/planner | Never (locked) |
| **features.md** | Feature registry: IDs, dependencies, status, linked stories/tasks | Planner | Agent (status only) |
| **user_stories.md** | User stories with acceptance criteria and traceability matrix | Planner | Agent (status only) |
| **tasks.md** | Master checklist of all tasks across all phases | Planner | Agent (checkbox updates) |
| **phaseN_{name}.md** | Detailed task specifications for one phase | Planner | Agent (checkbox updates) |
| **progress.md** | Session-by-session implementation log | Planner (template) | Agent (after each session) |

**Optional supporting documents:**

| Document | When Needed |
|----------|-------------|
| Schema reference (e.g., `task_definition.md`) | When the PRD defines a new data format or API schema |
| Architecture diagrams | When the system has complex internal structure |
| Migration plan | When refactoring existing code |

---

## Step 1: Analyze the PRD

**Input:** The complete PRD.
**Output:** Mental model of scope, architecture, features, dependencies, and risks.

### What to Extract

Read the PRD end-to-end and identify:

1. **Features** — Distinct capabilities the system must have. Each feature is a coherent, deliverable unit.
2. **Architecture decisions** — Technology choices, patterns, constraints that are locked.
3. **External dependencies** — APIs, services, libraries, infrastructure.
4. **Non-goals** — What is explicitly out of scope. Critical for preventing scope creep.
5. **User personas** — Who uses the system and how.
6. **Success criteria** — How we know the implementation is complete.
7. **Risks** — Technical uncertainties, integration challenges.
8. **Testing strategy** — Coverage targets, test levels, mocking approach.

### Heuristics

- **Every section heading in the PRD maps to something.** Features, constraints, or context — nothing should be orphaned.
- **If the PRD has a "Feature Specifications" section,** those become your feature registry entries directly.
- **If the PRD has a "User Stories" section,** those become your user stories directly (don't reinvent them).
- **If the PRD is missing non-goals,** ask the PRD author. Non-goals prevent the most common implementation drift, especially with AI agents.
- **Count the features.** If there are more than 15, the PRD may need splitting into multiple implementation cycles.

---

## Step 2: Review & Update Architecture Decision Records (ADRs)

**Input:** PRD analysis, existing ADRs (if any).
**Output:** Updated or new ADR documents aligned with the PRD.

### Why This Step Comes Before Feature Extraction

ADRs capture the architectural decisions that *constrain the solution space*. If you extract features and plan tasks before resolving architectural questions, you risk:
- Planning 50 tasks only to discover at task 23 that your approach contradicts an architectural constraint
- Writing ambiguous implementation notes because the "how" hasn't been decided yet
- Agents making ad-hoc architectural decisions that conflict with each other

By formalizing ADRs first, every subsequent step (features, stories, tasks, phase docs) can reference specific ADR IDs. The agent has guardrails established before it writes a single line of code.

### Process

1. **Locate existing ADRs.** Check `docs/decisions/`, `docs/adr/`, or wherever the project stores ADRs. If none exist, create the directory.

2. **Review each existing ADR against the PRD.** For each ADR, ask:
   - Does this ADR still hold, or does the PRD introduce requirements that conflict with it?
   - Does the PRD depend on this decision? If so, the ADR is a prerequisite — note it.
   - Does the PRD make this ADR obsolete? If so, mark it superseded.

3. **Identify decision prerequisites.** These are architectural questions that, if left unresolved, would make task decomposition ambiguous. Common examples:
   - Which database/storage pattern? (affects every data-related task)
   - Monorepo vs separate repo? (affects project structure tasks)
   - Sync vs async? (affects every service implementation task)
   - Which auth pattern? (affects every endpoint task)
   - Which deployment target? (affects Docker, CI, config tasks)

4. **Draft ADRs for decision prerequisites only.** Write ADRs for decisions that block planning. Defer implementation-detail ADRs (e.g., "which ORM query pattern," "how to structure test fixtures") — these emerge during implementation and the agent captures them in `progress.md`.

5. **Use the MADR template** (Markdown Any Decision Record):

```markdown
# ADR-{NNN}: {Title}

## Status

{Proposed | Accepted | Superseded by ADR-NNN}

## Context

{What is the issue? What forces are at play?}

## Decision

{What was decided and why.}

## Consequences

- {Positive consequence}
- {Negative consequence / trade-off}
- {Implication for implementation}

## PRD Reference

{Which PRD section(s) drove this decision.}
```

6. **Update existing ADRs** if the PRD changes their context. Add a "PRD Reference" footer linking the decision to the new requirements.

### What to Decide Now vs Defer

| Decide Now (Blocks Planning) | Defer (Emerges During Implementation) |
|------------------------------|---------------------------------------|
| Database/storage technology | Specific query patterns |
| API framework & patterns | Endpoint naming conventions |
| Deployment target & infra | Container tuning, scaling params |
| Auth mechanism | Token refresh strategy |
| Project structure (mono/multi-repo) | File naming within packages |
| Testing framework & strategy | Specific fixture patterns |
| External service choices | Client library wrapper details |

### Heuristics

- **If an architectural question affects 3+ tasks, decide it now.** Fewer than 3 = can be decided inline.
- **An ADR should be 1-2 pages max.** If it's longer, you're combining multiple decisions. Split into separate ADRs.
- **Every ADR needs consequences.** An ADR without consequences is just a statement. The consequences inform task implementation notes.
- **ADRs are living documents.** If implementation reveals a decision was wrong, supersede the ADR rather than silently diverging.
- **Reference ADRs in phase docs.** Implementation notes should say "Per ADR-003, use PostgreSQL" not "Use PostgreSQL." This gives the agent a trail to follow when it needs context.

---

## Step 3: Extract Features

**Input:** PRD analysis, established ADRs.
**Output:** `features.md`

### Process

1. **Enumerate features.** Assign each a unique ID: `F1`, `F2`, ... `FN`.
2. **Determine dependencies.** Which features require other features to be complete first?
3. **Draw the dependency graph.** Use ASCII art — it must be scannable in a terminal.
4. **Assign priorities.** Priority = build order, not business importance. Foundation features are priority 1.
5. **Link to PRD sections.** Each feature traces to a specific PRD section.
6. **Link to user stories.** Each feature serves one or more user stories.

### features.md Structure

```markdown
# {Project} Feature Registry

## Overview

{N} features organized in {M} phases. Features must be built in dependency order.

## Dependency Diagram

{ASCII diagram showing feature dependencies across phases}

## Feature List

### F1: {Feature Name}

- **Priority:** {build order number}
- **Phase:** {phase number} — {phase name}
- **Status:** [ ] Not started
- **Depends on:** {F-IDs or "None"}
- **Blocks:** {F-IDs that depend on this}
- **User Stories:** {US-IDs}
- **Tasks:** {T-ID range}
- **PRD Reference:** Section {N} ({description})
- **Key Deliverables:**
  - {Concrete output 1}
  - {Concrete output 2}
  - ...
```

### Heuristics

- **A feature is too big if** it would take more than one phase to implement. Split it.
- **A feature is too small if** it doesn't have at least 2-3 tasks. Merge with a related feature.
- **Foundation features come first.** Config, project structure, testing infrastructure, build system — these always form Phase 1.
- **Every feature must produce something testable.** If you can't write a test for it, it's not a feature — it's a sub-task of a feature.
- **Dependency arrows only point forward.** If F5 depends on F3, F3 must be in an earlier or same phase. Circular dependencies indicate a design problem in the PRD.

---

## Step 4: Derive User Stories

**Input:** PRD features, user personas.
**Output:** `user_stories.md`

### Process

1. **Identify personas** from the PRD. Common: end user, developer, admin, operator.
2. **For each feature,** write 1-3 user stories using the format:
   > As a {role}, I want to {action} so I can {benefit}
3. **Write acceptance criteria** for each story (3-7 per story).
4. **Build the traceability matrix** linking stories to features and tasks.
5. **Group stories by category** (setup, core workflow, management, etc.).

### user_stories.md Structure

```markdown
# {Project} User Stories

## Summary

{N} user stories across {M} categories.

## Traceability Matrix

| US ID | Title | Feature | Task(s) | Status |
|-------|-------|---------|---------|--------|
| US-01 | {title} | F1 | T010-T015 | [ ] |
| US-02 | {title} | F2 | T023-T026 | [ ] |
...

---

## Stories by Category

### {Category Name} (US-01 through US-04)

#### US-01: {Title}

> As a {role}, I want to {action} so I can {benefit}

**Acceptance Criteria:**
- [ ] {Criterion 1 — testable, specific}
- [ ] {Criterion 2}
- [ ] {Criterion 3}

**Feature:** F1 | **Tasks:** T010-T015 | **Priority:** Must-have
```

### Heuristics

- **Atomic stories.** One behavior per story. If it contains "and," split it.
- **3-7 acceptance criteria per story.** Fewer than 3 = underspecified. More than 7 = story needs splitting.
- **Acceptance criteria are testable.** Each criterion maps to something an agent can verify: a command that succeeds, an output that matches, a test that passes.
- **Use plain language.** Avoid implementation details in acceptance criteria. Say "form validates email format" not "regex `^[a-zA-Z0-9_.+-]+@...` is applied."
- **For AI agents: mandate, don't suggest.** Write "MUST verify ownership before writes" not "Consider checking ownership."
- **INVEST criteria.** Stories should be Independent, Negotiable, Valuable, Estimable, Small, Testable.
- **Every feature should have at least one story.** Infrastructure features (F1: project scaffolding) map to stories like "As a developer, I want to install the CLI with a single command."

---

## Step 5: Define Phases

**Input:** Feature dependency graph, task estimates.
**Output:** Phase boundaries and sequencing.

### Process

1. **Topological sort the feature dependency graph.** Features with no dependencies come first.
2. **Group features into phases.** Each phase is a set of features that can be built together once all their dependencies are satisfied.
3. **Name each phase** descriptively: "Foundation," "Core Framework," "Components," "Utilities," "Polish."
4. **Verify phase boundaries** — each phase should end with something verifiable.

### Phase Design Rules

```
Phase 0 (optional): Testing Infrastructure
  - Test directory structure, pytest config, shared fixtures, factory functions
  - Only needed if the project has zero test setup

Phase 1: Foundation
  - Project scaffolding, configuration, build system, CI/CD
  - Always the first "real" phase

Phase 2-N: Feature Phases
  - Group by dependency layer
  - Each phase builds on the previous
  - Sequential within a phase is fine; parallel tasks marked [P]

Final Phase: Polish / Verification
  - Documentation, deprecation notices, final integration verification
  - Covers cross-cutting concerns
```

### Heuristics

- **Each phase should represent 5-15 minutes of AI agent work** per task, with the total phase being verifiable after completion.
- **A phase should end with manually verifiable functionality.** "Health endpoint returns 200" is verifiable. "Refactored internal module" is not (by itself).
- **Phase count: 3-7 phases is typical.** Fewer than 3 = phases are too large (agent context drift risk). More than 7 = phases are too granular (overhead risk).
- **Phase boundaries are quality gates.** At the end of each phase, all tests pass, linting is clean, and the evaluation criteria are met before moving on.

---

## Step 6: Decompose Tasks

**Input:** Phase definitions, features, PRD sections.
**Output:** Task list per phase.

### Process

1. **For each feature in a phase,** identify the concrete implementation steps.
2. **Assign task IDs.** Use a sequential scheme: `T001`, `T002`, ... with ranges per phase (e.g., Phase 1 = T010-T029). Leave gaps between phases for future insertions. If this is a multi-cycle project, start at the next round hundred (see [Multi-Cycle Planning](#multi-cycle-planning)).
3. **Define dependencies.** Which tasks must complete before this one can start?
4. **Mark parallelizable tasks** with `[P]`.
5. **Estimate scope.** (15 min, 30 min, 1 hour, 2 hours, 3 hours). If a task exceeds 3 hours, split it.
6. **Link to user stories.** Every task should trace to at least one user story (infrastructure tasks may be "N/A").

### Task Numbering Convention

```
Phase 0 (if needed):  T001-T009
Phase 1:              T010-T029
Phase 2:              T030-T059
Phase 3:              T060-T089
Phase 4:              T090-T099

Next cycle:           T100-T149, T150-T199, etc.
```

- Leave gaps between phases (e.g., T010-T029 with room up to T029) so you can insert tasks without renumbering
- Start each phase at a round number for easy identification
- For multi-cycle projects, continue the sequence across cycles (see [Multi-Cycle Planning](#multi-cycle-planning))

### Task Decomposition Categories

From research on AI agent workflows, tasks fall into three reliability tiers:

| Type | Context Required | AI Reliability | Example |
|------|-----------------|----------------|---------|
| **Type 1: Narrow** | Minimal, one correct answer | High | Create `__init__.py`, write test for specific function, add dependency to config |
| **Type 2: Context-Dependent** | Specific codebase knowledge | Medium | Implement endpoint matching existing pattern, refactor module |
| **Type 3: Large/Open-Ended** | Broad, creative | Low | "Build authentication system," "Design the API" |

**Rule: Always decompose Type 3 tasks into multiple Type 1 and Type 2 tasks.** Never assign a Type 3 task directly.

### Heuristics

- **One task = one focused change.** A task should modify 1-3 files. If it touches more, it likely needs splitting.
- **Each task is independently testable.** You should be able to verify a task's completion without looking at future tasks.
- **Foundation before features.** Models before services, services before endpoints, endpoints before CLI.
- **The "could I explain this in one sentence?" test.** If a task description needs two sentences, it might be two tasks.
- **Git commit per task.** Each task should produce a meaningful, atomic commit.

---

## Step 7: Write Phase Documents

**Input:** Task list, PRD sections, feature specs.
**Output:** One `phaseN_{name}.md` file per phase.

### Phase Document Structure

```markdown
# Phase {N}: {Name}

## Prerequisites

- {What must be complete before this phase begins}
- {Specific tests that must pass, tools that must work}

## Infrastructure Updates Required

<!-- Include this section when the phase's new work requires small, targeted
     changes to existing modules BEFORE the phase's tasks can begin.
     These are NOT new features — they are additions to existing code
     (new parameters, new methods, new fields) that the phase's tasks depend on.
     Number them IU-1, IU-2, etc. across the entire implementation cycle. -->

### IU-{N}: {Description}

**File:** `{path/to/file}`

{Why this change is needed. What phase task depends on it.}

```{language}
{Code snippet showing the exact change — signature, parameters, logic}
```

**Tests:** {What tests to add/modify for this infrastructure change}

<!-- Repeat for each infrastructure update needed -->

## Phase Goal

{One sentence: what is true at the end of this phase that wasn't true before?}

## Phase Evaluation Criteria

- {Verifiable command or check 1}
- {Verifiable command or check 2}
- {Verifiable command or check 3}
- ...
- All quality gates green (ruff, mypy, pytest)

---

## Tasks

### T{NNN}: {Task Title}

**PRD Reference:** Section {N}
**Depends on:** {T-IDs or "Nothing"}
**Blocks:** {T-IDs}
**User Stories:** {US-IDs or "N/A (infrastructure)"}
**Estimated scope:** {time}

#### Description

{What to build. Be specific about the deliverable.}

#### Acceptance Criteria

- [ ] {Criterion 1}
- [ ] {Criterion 2}
- [ ] {Criterion 3}
...

#### Files to Create/Modify

- `{path}` — ({create|modify}) {what changes}
...

#### Implementation Notes

{Technical guidance: patterns to follow, gotchas, code snippets, pseudocode.
Reference specific PRD sections. Include enough detail that the agent doesn't
need to guess.}

#### Evaluation Checklist

- [ ] {How to verify this task is complete}
- [ ] {Test command that must pass}
...
```

### Infrastructure Updates — When Existing Code Needs Small Changes

When building on top of an existing codebase (which is most of the time), new phases often need small additions to modules built in earlier phases. These are NOT tasks — they are pre-requisites for the phase's tasks.

**Examples from real projects:**
- Adding an `env_vars` parameter to an existing `stream_claude()` method (Phase 2 built the method; Phase 3 needs the parameter)
- Adding a `save_artifact()` method to an existing `RunManager` class
- Widening a type annotation from `Literal[...]` to `str`

**When to use Infrastructure Updates:**
- The change is to a module built in a *prior* phase
- The change is small (1-10 lines) and targeted
- The change is a prerequisite for multiple tasks in the current phase
- The change should NOT be a standalone task because it's too small and has no independent value

**Structure:**
- Number them `IU-1`, `IU-2`, etc. across the entire implementation (not per-phase)
- Include the exact file path, code snippet, and required tests
- The agent implements all IU items at the start of the phase, before any T-tasks
- IU items are tracked in `progress.md` under the session's "Infrastructure Updates Applied" section

**If the change is large enough to be its own deliverable** (new class, new module, new endpoint), it's not an IU — it's a task. Put it in tasks.md.

### Evaluation Criteria — The Critical Section

The **Phase Evaluation Criteria** and per-task **Evaluation Checklist** are the most important parts of the phase document. They tell the agent exactly when a phase/task is done.

**Rules for writing evaluation criteria:**

1. **Every criterion must be a command or observable check.** "Passes lint" → `uv run ruff check .` is clean. "Works correctly" → not a valid criterion.
2. **Include the exact commands.** `uv run pytest tests/unit/test_config.py -v` not "tests pass."
3. **Cover functional + quality.**
   - Functional: "endpoint returns 200 with expected body"
   - Quality: "ruff clean, mypy passes, no regressions in existing tests"
4. **Be exhaustive for the phase; concise per task.** Phase criteria cover the full phase outcome (5-10 items). Task criteria cover just that task (2-5 items).
5. **Criteria must be achievable with the current phase's work.** Don't reference things built in future phases.

### Heuristics

- **Implementation Notes are your leverage.** The more specific and actionable they are, the higher the success rate of AI agent execution. Include: exact function signatures, import paths, patterns to follow from existing code, known gotchas.
- **"Files to Create/Modify" prevents drift.** An agent that knows exactly which files to touch is far less likely to create unnecessary files or modify the wrong ones.
- **Reference the PRD section directly.** "PRD Reference: Section 6/F3 (lines ~525-591)" lets the agent find the authoritative spec instantly.
- **Acceptance criteria use checkboxes.** `- [ ]` format. The agent checks them off as it completes work.

---

## Step 8: Create the Master Task List

**Input:** All phase documents.
**Output:** `tasks.md`

### tasks.md Structure

```markdown
# {Project} — Master Task List

## How to Use This Document

- Tasks are numbered T{NNN}-T{NNN} sequentially
- [P] = parallelizable with other [P] tasks in same phase
- Check off tasks as completed: `- [x] T001 ...`
- Dependencies noted as "depends: T001, T003"
- Each phase has a detailed doc in `phaseN_*.md`

## Progress Summary

- **Total tasks:** {N}
- **Completed:** 0
- **In progress:** 0
- **Blocked:** 0
- **Remaining:** {N}

---

## Phase {N} — {Name} (depends: {prerequisite})

> Detailed specs: [phaseN_{name}.md](phaseN_{name}.md)

### Task {N}.1: {Group Name} ({Feature ID})

- [ ] T{NNN} {Description} (depends: {T-IDs or "nothing"})
- [ ] T{NNN} [P] {Description} (depends: T{NNN})
- [ ] T{NNN} [P] {Description} (depends: T{NNN})
- [ ] T{NNN} {Description} (depends: T{NNN}, T{NNN})

### Task {N}.2: {Group Name} ({Feature ID})

- [ ] T{NNN} {Description} (depends: T{NNN})
...
```

### Heuristics

- **tasks.md is the "start here" document.** It provides the bird's-eye view. Phase documents provide the detail.
- **Group tasks within phases.** Use sub-headers like "Task 1.1: Project Scaffolding" to make scanning easier.
- **Progress Summary is updated by the agent** after each session. The planner initializes it at zero.
- **Link to phase docs.** Each phase section includes a `> Detailed specs: [link]` reference.

---

## Step 9: Initialize Progress Tracking

**Input:** Phase count, task count.
**Output:** `progress.md`

### progress.md Structure

```markdown
# {Project} Implementation Progress

## Current Status

- **Phase:** 0 (not started)
- **Tasks completed:** 0 / {N}
<!-- Task count from tasks.md. Update when tasks are added/removed. -->
- **Test coverage:** N/A
- **Last session:** N/A

## Session Log

<!-- Agents: Add a new session entry after each implementation session.
     Follow this template exactly. Use the appropriate template below
     depending on whether this is an implementation or review session. -->

### Session {N} — {YYYY-MM-DD}

**Goal:** Implement Phase {N} — {Phase Name}
**Completed:** {T-IDs completed}
**Infrastructure Updates Applied:** {IU-IDs, or "None"}
**Blockers:** {Any blockers encountered, or "None"}
**Discoveries:**
- {Non-obvious finding 1}
- {Non-obvious finding 2}
**Changes:**
- {File-level summary of what changed}
**Coverage:** {test coverage % and count}
**Quality:** {ruff, mypy, pytest status}
**Next:** Phase {N} review pass

### Session {N+1} — {YYYY-MM-DD}

**Goal:** Review Phase {N} implementation
**Issues Found:** {count} issues across {severity levels}
**Fixes Applied:**
- {Fix 1: what was wrong and how it was fixed}
- {Fix 2}
**Tests Added:** {count of new tests from the review}
**Regressions:** {count, or "None"}
**Coverage:** {updated coverage % and count}
**Quality:** {ruff, mypy, pytest status}
**Next:** {Phase N+1 implementation, or "Another review pass" if issues remain}
```

### The Phase Completion Loop

Each phase follows an implement → review → fix cycle. In practice, the DKMV project showed that phases typically require 1-3 review sessions after the initial implementation session:

```
┌─────────────────────┐
│ Implement Phase N    │  Session K: build all tasks
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Review Phase N       │  Session K+1: read phase doc, run all checks,
│                      │  compare output against evaluation criteria
└──────────┬──────────┘
           │
     ┌─────┴─────┐
     │ Issues?    │
     └─────┬─────┘
       Yes │         No
           ▼          ▼
┌──────────────┐  ┌──────────────────┐
│ Fix issues   │  │ Proceed to       │
│ + re-review  │  │ Phase N+1        │
└──────┬───────┘  └──────────────────┘
       │
       └──► (back to Review)
```

**What happens in a review session:**
1. Re-read the phase document's evaluation criteria
2. Run every evaluation command — record which pass and which fail
3. Run the *full* test suite (not just the phase's tests) — catch regressions
4. Check linting and type checking
5. Read through the code changes for logic errors the tests don't catch
6. Log all issues found, fix them, and log the fixes in progress.md
7. If any issues were structural (not just typos), do another review pass

**Typical pattern from real projects:**
- Session 1: Implement phase (e.g., 28 tasks)
- Session 2: Review — find 19 issues, fix all, add 8 new tests
- Session 3: Second review — find 5 more issues, add 11 tests
- Session 4: Final review — 0 issues found, proceed

### Heuristics

- **The agent writes session entries.** The planner only creates the template.
- **Session entries capture institutional knowledge.** Discoveries like "library X uses method Y, not Z" prevent future agents from hitting the same issue.
- **Metrics matter.** Track: tasks completed, tests added, coverage %, quality gate status. These are the heartbeat of implementation health.
- **Review sessions are normal, not failures.** Expect 1-3 review passes per phase. Budget for them.
- **Use a fresh agent session for reviews** when possible. A different context catches what the builder missed (heuristic H24).

---

## Step 10: Write the README

**Input:** Complete document list.
**Output:** `README.md`

### README.md Structure

```markdown
# Implementation Documents — {Project/Version}

- `tasks.md` — Start here. Master task list with checkboxes.
- `features.md` — Feature registry ({F-range}) with dependency diagram.
- `user_stories.md` — All {N} user stories with traceability.
- `phase1_{name}.md` — Phase 1: {description}.
- `phase2_{name}.md` — Phase 2: {description}.
- ...
- `progress.md` — Session log and metrics.

Source of truth: `{path/to/prd.md}` (read-only)

{Optional: Supporting reference: `{path/to/schema.md}` (spec)}
```

### Heuristics

- **README is the agent's entry point.** When an agent starts a new session, it reads README first to orient itself.
- **"Source of truth" declaration is mandatory.** The PRD is read-only during implementation. If requirements change, the PRD is updated first, then implementation docs are reconciled.
- **Keep it short.** One line per document. No prose.

---

## Step 11: Include Supporting Documents

**Input:** PRD, any referenced schemas or specs.
**Output:** Copies or links in the implementation directory.

### What to Include

1. **The PRD itself** — either copy it into the directory or reference its canonical path. Mark it `(read-only)`.
2. **Schema references** — if the PRD defines data formats (YAML schemas, API contracts, database schemas), extract them into dedicated reference docs.
3. **Architecture diagrams** — if they exist, include them. System-level ASCII diagrams are ideal for agent consumption.

### Heuristics

- **Don't duplicate what's in the PRD.** Phase documents reference PRD sections — they don't copy them.
- **Supporting docs are reference material,** not instructions. They're consulted, not executed.

---

## Step 12: Create the Implementation CLAUDE.md

**Input:** All implementation documents, ADRs, project conventions.
**Output:** A `CLAUDE.md` file that briefs the AI agent on how to execute the implementation.

### Why This Step Exists

The CLAUDE.md is the **agent's operating manual**. Without it, the agent has to read multiple documents and infer the workflow. With it, the agent knows on first read: what we're building, where everything is, and the exact process to follow phase by phase.

This step is last (before verification) because the CLAUDE.md references the final document structure, phase count, ADR locations, and evaluation process — all of which are only settled after all other docs are complete.

### CLAUDE.md Structure

```markdown
# {Project} — Implementation Guide

## What We're Implementing

{1-3 sentence summary of what the PRD delivers. Link to the PRD.}

- **PRD:** `{path/to/prd.md}` (read-only — do not modify)
- **Implementation docs:** `{path/to/implementation/directory/}`
- **ADRs:** `{path/to/decisions/}`

## Document Map

- `tasks.md` — Master task list. Start here for the current phase.
- `features.md` — Feature registry with dependencies.
- `user_stories.md` — User stories with acceptance criteria.
- `phase1_{name}.md` through `phaseN_{name}.md` — Detailed task specs per phase.
- `progress.md` — Session log. Update after every session.

## Relevant ADRs

- ADR-{NNN}: {Title} — {One-line summary of the decision}
- ADR-{NNN}: {Title} — {One-line summary}
- ...

## Implementation Process

Work through phases sequentially. For each phase:

### 1. Read the Phase Document

Open `phaseN_{name}.md`. Read the Prerequisites, Phase Goal, and Phase Evaluation Criteria
before touching any code. If there are Infrastructure Updates Required, implement those first.

### 2. Implement Tasks in Order

Work through each task (T-IDs) in the phase document sequentially.
For each task:
- Read the Description, Acceptance Criteria, Files to Create/Modify, and Implementation Notes
- Implement the task
- Check off the Acceptance Criteria in the phase doc
- Check off the task in `tasks.md`
- Commit the work

### 3. Verify the Phase

After all tasks in the phase are complete:
- Run every command in the Phase Evaluation Criteria
- All must pass. If any fail, fix the issue before proceeding.

### 4. Review Pass

Do a second pass of the phase implementation:
- Re-read the phase doc and verify nothing was missed
- Run the full test suite (not just the phase's tests) to catch regressions
- Check linting and type checking
- If there are gaps, issues, or regressions — fix them now

### 5. Update Progress

Add a session entry to `progress.md` with:
- Tasks completed
- Blockers encountered
- Discoveries (non-obvious findings for future sessions)
- Test coverage and quality gate status

### 6. Proceed to Next Phase

Only move to the next phase when:
- All tasks in the current phase are checked off
- All Phase Evaluation Criteria pass
- All quality gates are green (lint, types, tests)
- The review pass found no remaining issues

## Quality Gates

Every phase must pass these before proceeding:

- `{lint command}` — clean (zero warnings)
- `{type check command}` — passes
- `{test command}` — all tests pass, no regressions
- Coverage: {target}%+

## Conventions

- {Commit message convention, e.g., conventional commits}
- {Branch naming convention}
- {Test file naming convention}
- {Import ordering convention}

## DO NOT CHANGE

The following are stable and must not be modified during implementation:

- {List of files/modules/APIs that are locked}
- {Any external contracts that must be preserved}
```

### Heuristics

- **The CLAUDE.md goes in the implementation directory** (alongside tasks.md, features.md, etc.), not in the project root. The project root may already have its own CLAUDE.md with different conventions.
- **Keep it under 200 lines.** The CLAUDE.md should be a concise briefing, not a third copy of the PRD. Link to details, don't embed them.
- **The "DO NOT CHANGE" section is critical.** AI agents cannot infer boundaries from omission. Explicitly list what is off-limits.
- **The 6-step phase process is the core.** Read → Implement → Verify → Review → Update Progress → Proceed. This loop prevents the most common failure mode: an agent racing through tasks without verifying its work.
- **List ADRs with one-line summaries.** The agent reads these first to understand architectural constraints before diving into tasks.

---

## Step 13: Verification & Validation

After creating all implementation documents (including CLAUDE.md), run these verification checks before any implementation begins.

### Verification Checklist

```
COMPLETENESS
[ ] Every PRD feature maps to at least one feature in features.md
[ ] Every feature in features.md has at least one user story
[ ] Every user story has 3-7 acceptance criteria
[ ] Every feature maps to specific tasks in tasks.md
[ ] Every task in tasks.md has a corresponding entry in a phaseN_*.md
[ ] Every phaseN_*.md has Phase Evaluation Criteria
[ ] Every task has an Evaluation Checklist
[ ] PRD non-goals are not accidentally covered by any task

CONSISTENCY
[ ] Feature dependency graph has no cycles
[ ] Task dependency graph has no cycles
[ ] Task numbering is sequential with no gaps within phases
[ ] Feature IDs in features.md match references in user_stories.md and tasks.md
[ ] User story IDs in user_stories.md match references in features.md and phase docs
[ ] Task IDs in tasks.md match IDs in phase docs
[ ] Phase count in README matches actual phase documents
[ ] Total task count in tasks.md progress summary matches actual task count

TRACEABILITY
[ ] Forward: every PRD requirement → feature → user story → task → phase doc
[ ] Backward: every task → user story → feature → PRD section
[ ] No orphan tasks (tasks not linked to any feature or user story)
[ ] No orphan stories (stories not linked to any feature)
[ ] No unimplemented features (features with no tasks)

QUALITY
[ ] Phase evaluation criteria are executable commands, not vague descriptions
[ ] Task acceptance criteria are specific and testable
[ ] Implementation notes provide enough detail for autonomous execution
[ ] "Files to Create/Modify" is specified for every task
[ ] Dependencies are realistic (no forward references)
[ ] Estimated scope is provided for every task
[ ] No task exceeds 3 hours estimated scope
```

### Cross-Validation Process

Run this 3-pass validation:

**Pass 1 — PRD → Implementation (Forward Traceability):**
Read the PRD section by section. For each requirement, find the corresponding feature, story, and tasks. Flag any PRD requirement that doesn't map to implementation work.

**Pass 2 — Implementation → PRD (Backward Traceability):**
Read tasks.md task by task. For each task, trace back to the user story, feature, and PRD section. Flag any task that doesn't trace back to the PRD (potential scope creep).

**Pass 3 — Internal Consistency:**
Verify all cross-references are correct: feature IDs, user story IDs, task IDs, phase document links, dependency chains.

---

## Heuristics & Best Practices

### For PRD Analysis

| # | Heuristic | Rationale |
|---|-----------|-----------|
| H1 | **Separate "what" from "how."** The PRD says what; phase docs say how. Don't repeat the PRD in phase docs — reference it. | Prevents divergence between spec and implementation plan. |
| H2 | **If the PRD lacks non-goals, add them.** AI agents cannot infer boundaries from omission. | Prevents the most common implementation drift. |
| H3 | **Count features before planning.** 5-12 features per implementation cycle is ideal. >15 means split the PRD. | Keeps implementation manageable. |

### For Feature Extraction

| # | Heuristic | Rationale |
|---|-----------|-----------|
| H4 | **A feature = one coherent, deliverable unit.** It should be describable in one sentence. | Keeps features testable and atomic. |
| H5 | **Foundation features are always Phase 1.** Config, project structure, build system, testing infrastructure. | Everything else depends on them. |
| H6 | **Dependency arrows only point forward.** No feature should depend on something in a later phase. | Ensures buildable ordering. |

### For User Stories

| # | Heuristic | Rationale |
|---|-----------|-----------|
| H7 | **One behavior per story.** If it says "and," split it. | Atomic stories are testable stories. |
| H8 | **3-7 acceptance criteria per story.** <3 = underspecified. >7 = too big, split the story. | Balanced coverage without bloat. |
| H9 | **Acceptance criteria are commands or observable checks.** "Returns 200" not "works correctly." | Agents need binary pass/fail signals. |

### For Phase Design

| # | Heuristic | Rationale |
|---|-----------|-----------|
| H10 | **Each phase ends with verifiable functionality.** The agent must be able to prove the phase is complete. | Phase boundaries are quality gates. |
| H11 | **3-7 phases per implementation cycle.** <3 = too coarse (context drift). >7 = too granular (overhead). | Sweet spot for AI agent sessions. |
| H12 | **Each phase = one agent session.** Fresh context per phase prevents accumulated confusion. | Reduces context window pollution. |

### For Task Decomposition

| # | Heuristic | Rationale |
|---|-----------|-----------|
| H13 | **One task = 1-3 files.** If a task touches more, split it. | Narrow scope = higher AI reliability. |
| H14 | **No task exceeds 3 hours.** Split any task estimated beyond this. | Long tasks compound errors. |
| H15 | **Models before services, services before endpoints, endpoints before CLI.** | Natural dependency order. |
| H16 | **Each task = one git commit.** Atomic commits enable rollback. | Commits become save points. |

### For Evaluation Criteria

| # | Heuristic | Rationale |
|---|-----------|-----------|
| H17 | **Phase criteria: 5-10 verifiable commands.** Include the exact commands to run. | Agent knows exactly when the phase is done. |
| H18 | **Task criteria: 2-5 checklist items.** Concise but sufficient. | Quick verification without overhead. |
| H19 | **Always include quality gates.** Ruff/lint clean, type checker passes, all tests green. | Quality is a phase exit requirement, not optional. |
| H20 | **Criteria reference only current and prior work.** Never reference future phases. | Prevents premature coupling. |

### For AI Agent Optimization

| # | Heuristic | Rationale |
|---|-----------|-----------|
| H21 | **~150-200 instructions per document is the practical limit.** Beyond this, AI compliance degrades. | Research from HumanLayer (2025). |
| H22 | **Include protection sections.** Explicit "DO NOT CHANGE" lists for stable code. | AI cannot infer boundaries from omission. |
| H23 | **Implementation notes are your highest-leverage writing.** Specific function signatures, import paths, patterns to follow, known gotchas. | The more specific, the higher the success rate. |
| H24 | **Use a different agent/session for review.** Code quality review after each phase, separate from the implementation agent. | Fresh eyes catch what the builder misses. |

---

## Templates

### Minimal Implementation Directory (Small PRD, 3 phases, ~20 tasks)

```
docs/implementation/v1/
├── README.md
├── prd.md
├── features.md          (3-5 features)
├── user_stories.md       (8-12 stories)
├── tasks.md              (~20 tasks)
├── phase1_foundation.md
├── phase2_core.md
├── phase3_polish.md
└── progress.md
```

### Standard Implementation Directory (Medium PRD, 4-5 phases, ~50 tasks)

```
docs/implementation/v1/
├── README.md
├── prd.md
├── features.md          (6-10 features)
├── user_stories.md       (15-25 stories)
├── tasks.md              (~50 tasks)
├── phase1_foundation.md
├── phase2_core.md
├── phase3_features.md
├── phase4_integration.md
├── phase5_polish.md
└── progress.md
```

### Large Implementation Directory (Complex PRD, 5-7 phases, ~90+ tasks)

```
docs/implementation/v1/
├── README.md
├── prd.md
├── supporting_schema.md  (reference doc)
├── features.md          (10-15 features)
├── user_stories.md       (25+ stories)
├── tasks.md              (90+ tasks)
├── phase0_testing.md
├── phase1_foundation.md
├── phase2_core.md
├── phase3_components.md
├── phase4_integration.md
├── phase5_utilities.md
├── phase6_polish.md
└── progress.md
```

---

## Multi-Cycle Planning

Not every project fits in a single implementation cycle. When a PRD is too large, or when a project evolves through multiple PRDs, you need to plan across cycles.

### When to Split Into Multiple Cycles

| Signal | Threshold | Action |
|--------|-----------|--------|
| Feature count | >15 features | Split into 2+ cycles by subsystem or value delivery |
| Task count | >90 tasks | Split into 2+ cycles by dependency layer |
| Independent subsystems | System has 2+ major subsystems with minimal coupling | Each subsystem gets its own cycle |
| Phased value delivery | MVP → Enhancement → Polish | Each value tier gets its own cycle |

### How to Split

1. **By dependency layer:** Core infrastructure first (cycle 1), then features that build on it (cycle 2), then extensions (cycle 3).
2. **By subsystem:** If the PRD describes two largely independent systems (e.g., "build a CLI tool" + "add a declarative task engine"), each gets its own cycle.
3. **By value delivery:** MVP with core functionality (cycle 1), enhanced features (cycle 2), polish and edge cases (cycle 3).

### Task Numbering Across Cycles

Continue task numbering across cycles to prevent ID collisions. Leave gaps at round numbers:

| Cycle | Task Range | Example |
|-------|-----------|---------|
| Cycle 1 | T001-T095 | Core DKMV system |
| Cycle 2 | T100-T149 | DKMV Tasks feature |
| Cycle 3 | T200-T249 | DKMV Multi-Agent |

**Feature IDs can restart per cycle** (each cycle has its own F1-FN) since features are scoped to a single implementation directory. Or they can continue (F1-F11 in cycle 1, F12-F19 in cycle 2) — choose one convention and stick with it.

### Directory Structure

Each cycle gets its own implementation directory:

```
docs/implementation/
├── v1 - core/                    # Cycle 1: Core system
│   ├── README.md
│   ├── prd_core_v1.md
│   ├── features.md
│   ├── tasks.md                  # T001-T095
│   ├── phase1_foundation.md
│   └── ...
│
├── v1 - tasks/                   # Cycle 2: Tasks feature
│   ├── README.md
│   ├── prd_tasks_v1.md
│   ├── features.md
│   ├── tasks.md                  # T100-T149
│   ├── phase1_foundation.md
│   └── ...
│
└── v2 - multi-agent/             # Cycle 3: Next version
    └── ...
```

### Cross-Cycle Dependencies

Later cycles often depend on infrastructure built in earlier cycles. Document these in the later cycle's Phase 1 Prerequisites:

```markdown
## Prerequisites

- Cycle 1 fully complete (T001-T095 all passing)
- `SandboxManager` class operational (from cycle 1, Phase 2)
- `RunManager` class operational (from cycle 1, Phase 2)
```

---

## Anti-Patterns

Avoid these common mistakes when creating implementation documents:

| Anti-Pattern | Why It Fails | Fix |
|--------------|-------------|-----|
| **Copying PRD text into phase docs** | Creates divergence. Two sources of truth means neither is authoritative. | Reference PRD sections: "PRD Reference: Section 6/F3" |
| **Vague evaluation criteria** | "Works correctly" is not verifiable. Agent doesn't know when it's done. | Use exact commands: `pytest tests/unit/test_config.py -v passes` |
| **Tasks without acceptance criteria** | Agent guesses what "done" means. Inconsistent quality. | Every task gets 2-5 checkbox items. |
| **Monolithic phases** | Agent context drift over long sessions degrades quality. | Split into 10-20 tasks per phase max. |
| **Missing dependencies** | Agent attempts tasks before prerequisites are complete. | Explicit `depends: T001, T003` on every task. |
| **No "Files to Create/Modify"** | Agent creates unexpected files or modifies wrong ones. | List every file affected per task. |
| **Testing as afterthought** | Tests written after all code = lower coverage, missed edge cases. | Include test tasks alongside implementation tasks, or require tests in acceptance criteria. |
| **No progress tracking** | No institutional memory. Same bugs rediscovered. | `progress.md` with session-level discovery logging. |
| **Orphan tasks** | Tasks not linked to features/stories indicate scope creep. | Every task traces to a user story and feature. |
| **Phase docs without evaluation criteria** | No quality gate = no clear boundary between phases. | Phase Evaluation Criteria section is mandatory. |

---

## Quick Reference: The 13-Step Process

```
 1. ANALYZE      Read the full PRD. Extract features, personas, constraints, risks.
 2. ADRs         Review/create Architecture Decision Records for decisions that block planning.
 3. FEATURES     Create features.md — IDs, dependencies, diagram, deliverables.
 4. STORIES      Create user_stories.md — personas, acceptance criteria, traceability.
 5. PHASES       Group features into 3-7 phases by dependency order.
 6. TASKS        Decompose features into tasks (T-IDs, deps, scope estimates).
 7. PHASE DOCS   Write phaseN_*.md — prerequisites, goal, evaluation criteria, task specs.
 8. TASK LIST    Create tasks.md — master checklist with progress summary.
 9. PROGRESS     Create progress.md — empty session log template.
10. README       Create README.md — document index, source-of-truth pointer.
11. SUPPORTING   Include PRD copy, schemas, architecture diagrams.
12. CLAUDE.md    Create the agent operating manual — document map, ADRs, 6-step phase process.
13. VERIFY       Run the 3-pass verification (forward, backward, internal consistency).
```

---

*This guide is a living document. Update it as new patterns emerge from implementation experience.*
