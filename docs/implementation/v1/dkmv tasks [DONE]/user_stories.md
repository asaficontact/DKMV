# DKMV Tasks v1 User Stories

## Summary

24 user stories across 5 categories, derived from PRD sections 1-3 and 6-9.

## Traceability Matrix

| US ID | Title | Feature | Task(s) | Status |
|-------|-------|---------|---------|--------|
| US-01 | Create component with YAML | F1, F2 | T102-T112 | [ ] |
| US-02 | Define file inputs | F1, F4 | T102, T118 | [ ] |
| US-03 | Define text inputs | F1, F4 | T102, T118 | [ ] |
| US-04 | Use template variables | F2 | T108-T109 | [ ] |
| US-05 | Use Jinja2 conditionals | F2 | T108-T109 | [ ] |
| US-06 | Multi-task components | F1, F4, F5 | T105-T106, T128-T129 | [ ] |
| US-07 | Per-task model and budget | F1, F4 | T104, T121 | [ ] |
| US-08 | External prompt files | F2 | T110 | [ ] |
| US-09 | Run built-in component | F3, F5, F6 | T115, T127, T132 | [ ] |
| US-10 | Run local component | F3, F5, F6 | T114, T127, T132 | [ ] |
| US-11 | Pass --var flags | F6 | T133 | [ ] |
| US-12 | Override default model | F6 | T132-T133 | [ ] |
| US-13 | Backward compat wrappers | F8 | T141-T143 | [ ] |
| US-14 | Task runs in dkmv runs | F5 | T130 | [ ] |
| US-15 | Task detail in dkmv show | F5 | T130 | [ ] |
| US-16 | Fail fast: missing variables | F2 | T108 | [ ] |
| US-17 | Fail fast: missing inputs | F4 | T118 | [ ] |
| US-18 | Fail fast: missing outputs | F4 | T122 | [ ] |
| US-19 | Clear YAML error messages | F2 | T109, T112 | [ ] |
| US-20 | Execution parameter cascade | F4 | T121 | [ ] |
| US-21 | Replayability | F5 | T128 | [ ] |
| US-22 | Per-task budget caps | F1, F4 | T104, T121 | [ ] |
| US-23 | Task-level model selection | F1, F4, F7 | T104, T121, T136 | [ ] |
| US-24 | Component cost aggregation | F5 | T130 | [ ] |

---

## Stories by Category

### YAML Authoring (US-01 through US-08)

#### US-01: Create Custom Component with YAML

> As a workflow designer, I want to create a new component by writing YAML task files and markdown prompts so I don't need Python expertise

**Acceptance Criteria:**
- [ ] A directory of `.yaml` files constitutes a component
- [ ] `dkmv run ./my-component --repo ... --var key=value` executes the component
- [ ] No Python code required for new components

**Feature:** F1, F2 | **Tasks:** T102-T112 | **Priority:** Must-have

---

#### US-02: Define File Inputs

> As a task author, I want to copy files from the host into the container so Claude has the context it needs

**Acceptance Criteria:**
- [ ] `type: file` input with `src` and `dest` copies host file to container
- [ ] `src` supports template variables (`{{ prd_path }}`)
- [ ] Directory `src` copies recursively
- [ ] `optional: true` skips silently when source missing

**Feature:** F1, F4 | **Tasks:** T102, T118 | **Priority:** Must-have

---

#### US-03: Define Text Inputs

> As a task author, I want to inject inline text content into container files so I can provide dynamic guidelines

**Acceptance Criteria:**
- [ ] `type: text` input with `content` and `dest` writes text to container
- [ ] `content` supports template variables

**Feature:** F1, F4 | **Tasks:** T102, T118 | **Priority:** Must-have

---

#### US-04: Use Template Variables

> As a task author, I want to use `{{ variable }}` syntax in prompts and inputs so tasks are reusable

**Acceptance Criteria:**
- [ ] CLI `--var key=value` variables resolve in all template positions
- [ ] Built-in variables (repo, branch, feature_name, component, run_id) always available
- [ ] Previous task variables (`tasks.<name>.status`) available in later tasks

**Feature:** F2 | **Tasks:** T108-T109 | **Priority:** Must-have

---

#### US-05: Use Jinja2 Conditionals

> As a task author, I want to use `{% if %}` and `{% for %}` in prompts for conditional content

**Acceptance Criteria:**
- [ ] Jinja2 control flow works in `prompt`, `prompt_file`, `content`, `commit_message`
- [ ] `{{ var | default('') }}` works for optional variables

**Feature:** F2 | **Tasks:** T108-T109 | **Priority:** Should-have

---

#### US-06: Multi-task Components

> As a task author, I want to split a workflow into multiple tasks so each phase has its own model and budget

**Acceptance Criteria:**
- [ ] Tasks execute in filename order (01-plan.yaml, 02-implement.yaml)
- [ ] All tasks share the same container (files persist between tasks)
- [ ] Fail-fast: first failed task stops the pipeline

**Feature:** F1, F4, F5 | **Tasks:** T105-T106, T128-T129 | **Priority:** Must-have

---

#### US-07: Per-task Model and Budget

> As a task author, I want to specify model and budget per task so planning uses Opus and implementation uses Sonnet

**Acceptance Criteria:**
- [ ] `model: claude-opus-4-6` in YAML overrides CLI `--model`
- [ ] `max_budget_usd: 0.50` caps this specific task
- [ ] `max_turns: 30` limits this specific task
- [ ] Execution parameter cascade: task YAML > CLI > global config

**Feature:** F1, F4 | **Tasks:** T104, T121 | **Priority:** Must-have

---

#### US-08: External Prompt Files

> As a task author, I want to write long prompts in separate .md files so YAML stays clean

**Acceptance Criteria:**
- [ ] `prompt_file: prompts/plan.md` loads prompt from file relative to task YAML
- [ ] `instructions_file: guidelines/rules.md` loads instructions from file
- [ ] File contents support Jinja2 template syntax
- [ ] Exactly one of `prompt` / `prompt_file` required (enforced by validation)

**Feature:** F2 | **Tasks:** T110 | **Priority:** Must-have

---

### CLI Operations (US-09 through US-15)

#### US-09: Run Built-in Component

> As a developer, I want to run built-in components with `dkmv run dev` so I can use the new task system

**Acceptance Criteria:**
- [ ] `dkmv run dev --repo ... --var prd_path=...` works end-to-end
- [ ] Resolves `dev` to packaged `dkmv/builtins/dev/` directory
- [ ] Same for qa, judge, docs

**Feature:** F3, F5, F6 | **Tasks:** T115, T127, T132 | **Priority:** Must-have

---

#### US-10: Run Local Custom Component

> As a developer, I want to run a local component directory with `dkmv run ./my-component`

**Acceptance Criteria:**
- [ ] `dkmv run ./components/fullstack --repo ... --var key=value` works
- [ ] Relative and absolute paths supported
- [ ] Error if path doesn't exist or has no YAML files

**Feature:** F3, F5, F6 | **Tasks:** T114, T127, T132 | **Priority:** Must-have

---

#### US-11: Pass Variables via --var

> As a developer, I want to pass template variables on the command line

**Acceptance Criteria:**
- [ ] `--var prd_path=./prds/auth.md --var target_coverage=90` works
- [ ] Multiple --var flags supported
- [ ] Variables available in all Jinja2 template positions

**Feature:** F6 | **Tasks:** T133 | **Priority:** Must-have

---

#### US-12: Override Default Model

> As a developer, I want to set a default model via `--model` that tasks use when they don't specify their own

**Acceptance Criteria:**
- [ ] `--model claude-opus-4-6` sets default for tasks without `model:` in YAML
- [ ] Tasks with `model:` in YAML still use their own (cascade: task > CLI > global)
- [ ] Same pattern for `--max-turns`, `--timeout`, `--max-budget-usd`

**Feature:** F6 | **Tasks:** T132-T133 | **Priority:** Should-have

---

#### US-13: Backward Compatible Wrappers

> As a developer, I want existing `dkmv dev --prd ...` commands to keep working

**Acceptance Criteria:**
- [ ] `dkmv dev --prd auth.md --repo ...` internally calls ComponentRunner with `prd_path=auth.md`
- [ ] Same for `dkmv qa`, `dkmv judge`, `dkmv docs`
- [ ] All existing CLI flags continue to work

**Feature:** F8 | **Tasks:** T141-T143 | **Priority:** Must-have

---

#### US-14: Task Runs in dkmv runs

> As a developer, I want task-based runs to appear in `dkmv runs` output

**Acceptance Criteria:**
- [ ] `dkmv runs` shows runs from both old component system and new task system
- [ ] Same format, same filters

**Feature:** F5 | **Tasks:** T130 | **Priority:** Should-have

---

#### US-15: Task Detail in dkmv show

> As a developer, I want `dkmv show` to display task-level details for task-based runs

**Acceptance Criteria:**
- [ ] `dkmv show <run-id>` shows per-task status, cost, duration for multi-task components
- [ ] Shows which tasks completed, failed, or were skipped

**Feature:** F5 | **Tasks:** T130 | **Priority:** Should-have

---

### Safety & Quality (US-16 through US-20)

#### US-16: Fail Fast on Missing Variables

> As a developer, I want clear errors when a required template variable is missing so I know what to pass

**Acceptance Criteria:**
- [ ] Missing required variable → `jinja2.UndefinedError` at load time (before execution)
- [ ] Error message includes variable name and task file path
- [ ] Optional variables use `{{ var | default('') }}` pattern

**Feature:** F2 | **Tasks:** T108 | **Priority:** Must-have

---

#### US-17: Fail Fast on Missing Required Inputs

> As a developer, I want the task to fail before running Claude if a required input file is missing

**Acceptance Criteria:**
- [ ] `optional: false` (default) + missing `src` → `FileNotFoundError` with clear message
- [ ] `optional: true` + missing `src` → skip silently
- [ ] Error before Claude Code invocation (no wasted budget)

**Feature:** F4 | **Tasks:** T118 | **Priority:** Must-have

---

#### US-18: Fail Fast on Missing Required Outputs

> As a developer, I want the task to fail if Claude didn't produce a required output file

**Acceptance Criteria:**
- [ ] `required: true` output + missing file → task status `failed` with error message
- [ ] `required: false` output + missing file → skip silently
- [ ] Output validation happens after Claude Code finishes

**Feature:** F4 | **Tasks:** T122 | **Priority:** Must-have

---

#### US-19: Clear YAML Error Messages

> As a developer, I want clear error messages when my task YAML is invalid

**Acceptance Criteria:**
- [ ] Invalid YAML syntax → error with file path and line number
- [ ] Missing required fields → Pydantic validation error with field name
- [ ] Both `prompt` and `prompt_file` set → clear mutual exclusivity error
- [ ] Invalid input type → error listing valid types (file, text, env)

**Feature:** F2 | **Tasks:** T109, T112 | **Priority:** Must-have

---

#### US-20: Execution Parameter Cascade

> As a developer, I want the cascade to work correctly: task YAML > CLI > global config

**Acceptance Criteria:**
- [ ] Task with `model: claude-sonnet-4-6` uses Sonnet even when CLI has `--model claude-opus-4-6`
- [ ] Task without `model:` field uses CLI `--model` value
- [ ] Task without `model:` and no CLI flag uses `DKMVConfig.default_model`
- [ ] Same cascade for `max_turns`, `timeout_minutes`, `max_budget_usd`

**Feature:** F4 | **Tasks:** T121 | **Priority:** Must-have

---

### Cost & Efficiency (US-21 through US-24)

#### US-21: Replayability

> As a developer, I want to re-run just the implementation task when planning succeeded but implementation failed

**Acceptance Criteria:**
- [ ] Planning artifacts persist on disk between tasks (shared container)
- [ ] Future: ability to re-run from task N (tracked as open question, not v1 scope)

**Feature:** F5 | **Tasks:** T128 | **Priority:** Should-have

---

#### US-22: Per-task Budget Caps

> As a developer, I want individual budget caps per task so planning doesn't consume the implementation budget

**Acceptance Criteria:**
- [ ] `max_budget_usd: 0.50` in task YAML caps that specific Claude invocation
- [ ] Passed to Claude Code as `--max-budget-usd` flag
- [ ] Independent per task (not shared across component)

**Feature:** F1, F4 | **Tasks:** T104, T121 | **Priority:** Must-have

---

#### US-23: Task-level Model Selection

> As a developer, I want to use Opus for planning and Sonnet for implementation within the same component

**Acceptance Criteria:**
- [ ] 01-plan.yaml with `model: claude-opus-4-6` and 02-implement.yaml with `model: claude-sonnet-4-6`
- [ ] Both respected in the same component run
- [ ] Built-in dev component uses this pattern

**Feature:** F1, F4, F7 | **Tasks:** T104, T121, T136 | **Priority:** Must-have

---

#### US-24: Component Cost Aggregation

> As a developer, I want to see total cost across all tasks in a component run

**Acceptance Criteria:**
- [ ] `ComponentResult.total_cost_usd` is the sum of all `TaskResult.total_cost_usd`
- [ ] Visible in `dkmv show` output
- [ ] Per-task costs also visible

**Feature:** F5 | **Tasks:** T130 | **Priority:** Should-have
