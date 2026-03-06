# DKMV Tasks v1 Feature Registry

## Overview

8 features organized in 5 phases. Features must be built in dependency order — later features depend on earlier ones being complete and stable.

## Dependency Diagram

```
Phase 1: Foundation
  F1: Task Model (Pydantic)  ──┬──> F2: Task Loader
                               │         │
                               │         ▼
                               ├──> F3: Component Discovery
                               │
Phase 2: TaskRunner            │
  F4: TaskRunner  <────────────┘ (depends on F1 + existing core/)
                               │
Phase 3: ComponentRunner + CLI │
  F5: ComponentRunner  <───────┤ (depends on F2, F3, F4)
  F6: CLI `dkmv run`  <───────┘ (depends on F5)
                               │
Phase 4: Built-in Components   │
  F7: Built-in Conversion  <───┤ (depends on F2, F5)
  F8: Backward Compat Wrappers <┘ (depends on F6, F7)

Phase 5: Polish & Migration
  (depends on all above)
```

## Feature List

### F1: Task Model (Pydantic)

- **Priority:** 1 (build first)
- **Phase:** 1 — Foundation
- **Status:** [ ] Not started
- **Depends on:** None (uses existing core/models.py patterns)
- **Blocks:** F2, F3, F4
- **User Stories:** US-01, US-02, US-03, US-06, US-07
- **Tasks:** T100-T107
- **PRD Reference:** Section 6.1 (Task Model)
- **Key Deliverables:**
  - `TaskInput` with type validation (file, text, env)
  - `TaskOutput` with required/save flags
  - `TaskDefinition` with all identity, execution, data, instructions, prompt fields
  - `TaskResult` with status: completed/failed/timed_out/skipped
  - `ComponentResult` with aggregated task results
  - Model validators: instructions XOR, prompt XOR, input type fields

---

### F2: Task Loader

- **Priority:** 2 (required before runners)
- **Phase:** 1 — Foundation
- **Status:** [ ] Not started
- **Depends on:** F1
- **Blocks:** F5, F7
- **User Stories:** US-04, US-05, US-13, US-16, US-19
- **Tasks:** T108-T112
- **PRD Reference:** Section 6.2 (Task Loader)
- **Key Deliverables:**
  - Jinja2 template rendering with `StrictUndefined`
  - YAML parsing via `yaml.safe_load()`
  - Pydantic validation via `TaskDefinition.model_validate()`
  - `prompt_file` / `instructions_file` relative path resolution
  - `load_component()` for directory scanning

---

### F3: Component Discovery

- **Priority:** 2 (parallel with F2)
- **Phase:** 1 — Foundation
- **Status:** [ ] Not started
- **Depends on:** F1 (for built-in component packaging)
- **Blocks:** F5
- **User Stories:** US-09, US-10
- **Tasks:** T113-T116
- **PRD Reference:** Section 6.5 (Component Discovery)
- **Key Deliverables:**
  - `resolve_component()` — path + built-in resolution
  - Explicit path support (./path or /absolute)
  - Built-in resolution via `importlib.resources.files("dkmv.builtins")`
  - `ComponentNotFoundError` with helpful message

---

### F4: TaskRunner

- **Priority:** 3 (core execution engine)
- **Phase:** 2 — TaskRunner
- **Status:** [ ] Not started
- **Depends on:** F1, existing SandboxManager/RunManager/StreamParser
- **Blocks:** F5
- **User Stories:** US-02, US-03, US-06, US-07, US-17, US-18, US-20, US-22, US-23
- **Tasks:** T117-T125
- **PRD Reference:** Section 6.3 (TaskRunner)
- **Key Deliverables:**
  - Input injection (file, text, env) into running container
  - Instructions written to `.claude/CLAUDE.md`
  - Claude Code streaming with execution parameter cascade (task YAML > CLI > global)
  - Output collection with required/save validation
  - Git teardown: force-add declared outputs, commit, push
  - Error handling: missing inputs, missing outputs, timeouts

---

### F5: ComponentRunner

- **Priority:** 4 (orchestration layer)
- **Phase:** 3 — ComponentRunner and CLI
- **Status:** [ ] Not started
- **Depends on:** F2, F3, F4
- **Blocks:** F6, F7, F8
- **User Stories:** US-06, US-09, US-10, US-21, US-24
- **Tasks:** T126-T131
- **PRD Reference:** Section 6.4 (ComponentRunner)
- **Key Deliverables:**
  - Container lifecycle management (start once, stop once)
  - Task sequencing with fail-fast
  - Variable propagation between tasks (`tasks.<name>.status/cost/turns`)
  - Cost/duration aggregation across tasks
  - `.dkmv/` directory creation + `.gitignore` handling

---

### F6: CLI `dkmv run` Command

- **Priority:** 5 (user-facing interface)
- **Phase:** 3 — ComponentRunner and CLI
- **Status:** [ ] Not started
- **Depends on:** F5
- **Blocks:** F8
- **User Stories:** US-09, US-10, US-11, US-12, US-14, US-15
- **Tasks:** T132-T134
- **PRD Reference:** Section 6.6 (CLI: dkmv run Command)
- **Key Deliverables:**
  - `dkmv run <component> [OPTIONS]` command
  - `--var KEY=VALUE` repeatable flag for template variables
  - `--model`, `--max-turns`, `--timeout`, `--max-budget-usd` as defaults
  - `--keep-alive`, `--verbose` pass-through
  - Integration with ComponentRunner

---

### F7: Built-in Component Conversion

- **Priority:** 6 (validates entire stack)
- **Phase:** 4 — Built-in Components
- **Status:** [ ] Not started
- **Depends on:** F2, F5
- **Blocks:** F8
- **User Stories:** US-09, US-23
- **Tasks:** T135-T140
- **PRD Reference:** Section 6.7 (Built-in Component Conversion)
- **Key Deliverables:**
  - `dkmv/builtins/dev/` — 01-plan.yaml, 02-implement.yaml
  - `dkmv/builtins/qa/` — 01-evaluate.yaml
  - `dkmv/builtins/judge/` — 01-verdict.yaml
  - `dkmv/builtins/docs/` — 01-generate.yaml
  - pyproject.toml packaging for built-in YAMLs

---

### F8: Backward Compatibility Wrappers

- **Priority:** 7 (migration support)
- **Phase:** 4 — Built-in Components
- **Status:** [ ] Not started
- **Depends on:** F6, F7
- **Blocks:** None
- **User Stories:** US-13
- **Tasks:** T141-T144
- **PRD Reference:** Section 6.6 (Backward compatibility), Section 9 (Migration Plan)
- **Key Deliverables:**
  - `dkmv dev` → `ComponentRunner.run()` with option-to-variable mapping
  - `dkmv qa` → `ComponentRunner.run()` with option-to-variable mapping
  - `dkmv judge` → `ComponentRunner.run()` with option-to-variable mapping
  - `dkmv docs` → `ComponentRunner.run()` with option-to-variable mapping
  - All built-in YAMLs validate and load correctly
