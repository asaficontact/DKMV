# DKMV v1 Feature Registry

## Overview

11 features organized in 4 phases. Features must be built in dependency order — later features depend on earlier ones being complete and stable.

## Dependency Diagram

```
Phase 1: Foundation
  F1: CLI Framework & Config  ──┬──> F2: Docker Image & Build
                                │
Phase 2: Core Framework         │
  F3: SandboxManager  <─────────┤
  F4: RunManager       <────────┤  (F3, F4, F5 parallelizable)
  F5: StreamParser     <────────┘
  F6: BaseComponent  <── F3, F4, F5
                                │
Phase 3: Components             │
  F7: Dev Component  <──────────┤
  F8: QA Component   <──────────┤  (F8-F10 depend on F6, sequential build)
  F9: Judge Component <──────────┤
  F10: Docs Component <──────────┘

Phase 4: Utilities
  F11: Run Management Commands  <── F4
```

## Feature List

### F1: CLI Framework & Global Configuration

- **Priority:** 1 (build first)
- **Phase:** 1 — Foundation
- **Status:** [ ] Not started
- **Depends on:** None
- **Blocks:** F2, F3, F4, F5, F6
- **User Stories:** US-01, US-03, US-04
- **Tasks:** T010-T022, T027-T029
- **PRD Reference:** Section 6/F1 (lines ~392-445)
- **Key Deliverables:**
  - Typer app with subcommands
  - DKMVConfig (pydantic-settings, env vars + .env)
  - Global options (--verbose, --dry-run)
  - async_command decorator
  - Entry point: `dkmv = "dkmv.cli:app"`

---

### F2: Docker Image & Build Command

- **Priority:** 2 (required before components)
- **Phase:** 1 — Foundation
- **Status:** [ ] Not started
- **Depends on:** F1
- **Blocks:** F3 (SandboxManager needs an image)
- **User Stories:** US-02, US-04
- **Tasks:** T023-T026
- **PRD Reference:** Section 6/F2 (lines ~448-520)
- **Key Deliverables:**
  - dkmv-sandbox Docker image (node:20-bookworm base)
  - `dkmv build` command with --no-cache, --claude-version flags
  - Image includes: git, gh, node, python3, Claude Code, SWE-ReX

---

### F3: SandboxManager (Core Framework)

- **Priority:** 3 (required before components)
- **Phase:** 2 — Core Framework
- **Status:** [ ] Not started
- **Depends on:** F1, F2
- **Blocks:** F6
- **User Stories:** US-22, US-23, US-24
- **Tasks:** T030-T039
- **PRD Reference:** Section 6/F3 (lines ~525-591)
- **Key Deliverables:**
  - SWE-ReX DockerDeployment wrapper
  - start(), execute(), stream_claude(), stop()
  - write_file(), read_file() via SWE-ReX
  - Env var forwarding, gh auth, asyncio timeout

---

### F4: RunManager & Results (Core Framework)

- **Priority:** 3 (parallel with F3)
- **Phase:** 2 — Core Framework
- **Status:** [ ] Not started
- **Depends on:** F1
- **Blocks:** F6, F11
- **User Stories:** US-25
- **Tasks:** T040-T045
- **PRD Reference:** Section 6/F4 (lines ~594-715)
- **Key Deliverables:**
  - Run ID generation and directory structure
  - save_result(), append_stream(), list_runs(), get_run()
  - Shared Pydantic models (BaseResult, BaseComponentConfig, SandboxConfig)
  - session_id tracking from stream-json

---

### F5: StreamParser (Core Framework)

- **Priority:** 3 (parallel with F3, F4)
- **Phase:** 2 — Core Framework
- **Status:** [ ] Not started
- **Depends on:** F1
- **Blocks:** F6
- **User Stories:** US-06
- **Tasks:** T046-T049
- **PRD Reference:** Section 6/F5 (lines ~719-744)
- **Key Deliverables:**
  - Line-by-line JSON parsing of stream-json
  - Terminal rendering with rich (colors, formatting)
  - Event type handling (system, assistant, user, result)
  - Final result extraction (cost, duration, turns, session_id)

---

### F6: BaseComponent Abstract Class

- **Priority:** 4 (required before individual components)
- **Phase:** 2 — Core Framework
- **Status:** [ ] Not started
- **Depends on:** F3, F4, F5
- **Blocks:** F7, F8, F9, F10
- **User Stories:** All component stories
- **Tasks:** T050-T057
- **PRD Reference:** Section 6/F6 (lines ~748-879)
- **Key Deliverables:**
  - BaseComponent ABC (Generic[C, R])
  - 12-step run() method
  - Component registry (register_component, get_component)
  - Prompt template loading via importlib.resources
  - Workspace setup (clone, branch, CLAUDE.md, .gitignore)
  - Feedback synthesis transformation
  - Shared teardown (git add, commit, push)

---

### F7: Dev Component

- **Priority:** 5 (first component — validates entire stack)
- **Phase:** 3 — Components
- **Status:** [ ] Not started
- **Depends on:** F6
- **Blocks:** None (F8-F10 can start once F6 is done)
- **User Stories:** US-05, US-06, US-07, US-08, US-09, US-10, US-11, US-26
- **Tasks:** T060-T072
- **PRD Reference:** Section 6/F7 (lines ~884-968)
- **Key Deliverables:**
  - DevConfig, DevResult models
  - DevComponent with prompt building (strips eval criteria)
  - `dkmv dev` CLI command with all flags
  - Design docs handling, feedback injection
  - Plan-first prompt approach (.dkmv/plan.md)
  - Fresh branch creation vs existing branch checkout

---

### F8: QA Component

- **Priority:** 6 (after Dev validates the stack)
- **Phase:** 3 — Components
- **Status:** [ ] Not started
- **Depends on:** F6
- **Blocks:** None
- **User Stories:** US-12, US-13, US-14
- **Tasks:** T073-T077
- **PRD Reference:** Section 6/F8 (lines ~972-1010)
- **Key Deliverables:**
  - QAConfig, QAResult models
  - QAComponent with full PRD (including eval criteria)
  - `dkmv qa` CLI command
  - QA report committed to branch (.dkmv/qa_report.json)

---

### F9: Judge Component

- **Priority:** 7 (after QA)
- **Phase:** 3 — Components
- **Status:** [ ] Not started
- **Depends on:** F6
- **Blocks:** None
- **User Stories:** US-15, US-16, US-17
- **Tasks:** T078-T082
- **PRD Reference:** Section 6/F9 (lines ~1014-1064)
- **Key Deliverables:**
  - JudgeConfig, JudgeResult models
  - JudgeComponent with full PRD (including eval criteria)
  - `dkmv judge` CLI command
  - Verdict committed to branch (.dkmv/verdict.json)
  - Colored PASS/FAIL display

---

### F10: Docs Component

- **Priority:** 8 (last component)
- **Phase:** 3 — Components
- **Status:** [ ] Not started
- **Depends on:** F6
- **Blocks:** None
- **User Stories:** US-18, US-19
- **Tasks:** T083-T086
- **PRD Reference:** Section 6/F10 (lines ~1068-1098)
- **Key Deliverables:**
  - DocsConfig, DocsResult models
  - DocsComponent with doc generation prompt
  - `dkmv docs` CLI command
  - PR creation via gh pr create (--create-pr flag)

---

### F11: Run Management Commands

- **Priority:** 9 (utility, not on critical path)
- **Phase:** 4 — Utilities
- **Status:** [ ] Not started
- **Depends on:** F4
- **Blocks:** None
- **User Stories:** US-20, US-21, US-22, US-23, US-24
- **Tasks:** T090-T095
- **PRD Reference:** Section 6/F11 (lines ~1102-1147)
- **Key Deliverables:**
  - `dkmv runs` — rich table listing
  - `dkmv show <run-id>` — detailed view
  - `dkmv attach <run-id>` — docker exec passthrough
  - `dkmv stop <run-id>` — container cleanup
