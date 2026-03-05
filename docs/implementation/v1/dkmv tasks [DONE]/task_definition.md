# DKMV Task Definition Format

This document is the complete reference for defining DKMV tasks. A task is a single Claude Code invocation inside a Docker container — the atomic unit of work in DKMV.

## Table of Contents

- [Overview](#overview)
- [How Tasks Fit Into Components](#how-tasks-fit-into-components)
- [File Structure](#file-structure)
- [Schema Reference](#schema-reference)
  - [Identity Fields](#identity-fields)
  - [Execution Fields](#execution-fields)
  - [Inputs](#inputs)
  - [Outputs](#outputs)
  - [Instructions](#instructions)
  - [Prompt](#prompt)
- [Template Variables](#template-variables)
- [Task Chaining](#task-chaining)
- [Examples](#examples)
  - [Minimal Task](#minimal-task)
  - [Planning Task](#planning-task)
  - [Implementation Task](#implementation-task)
  - [Review Task](#review-task)
- [Best Practices](#best-practices)

---

## Overview

DKMV v1 ships with four hardcoded components (dev, qa, judge, docs). Each is a Python class with a single prompt template. This works but limits extensibility — adding a new workflow means writing Python code.

The task definition format solves this by letting users define components as **ordered sequences of YAML task files**. Each task file declares:

- **What context** to inject (files, inline text, environment variables)
- **What prompt** to send to Claude Code
- **What outputs** to capture from the container
- **What constraints** to apply (turns, budget, timeout, model)

The DKMV runtime reads these files in order and executes them inside a single Docker container. All tasks share the same container, so files written by one task are automatically visible to the next.

### Key Design Principles

1. **YAML frontmatter + prompt body** — Structured config where it matters, freeform markdown for prompts. Inspired by Hugo/Astro frontmatter, Microsoft Prompty, and Claude Code SKILL.md.
2. **Explicit data flow** — Inputs and outputs are declared, not implicit. You can see exactly what each task reads and writes.
3. **Single container** — All tasks in a component share one container. The workspace persists between tasks. Git state accumulates.
4. **Fail-fast by default** — A failed task stops the pipeline. If a required input is missing, the task errors out without running.

---

## How Tasks Fit Into Components

```
component/                          # A component = directory of task files
├── tasks/
│   ├── 01-plan.yaml               # Task 1: Analyze & plan
│   ├── 02-implement.yaml          # Task 2: Write code
│   ├── 03-test.yaml               # Task 3: Run tests & fix
│   └── 04-cleanup.yaml            # Task 4: Final commit & push
└── prompts/                        # Optional: separate prompt files
    ├── plan.md
    └── implement.md
```

Tasks execute in filename order (lexicographic sort). The `01-`, `02-` prefix convention ensures correct ordering.

A **component** is registered with DKMV by pointing to its directory:

```bash
# Run a custom component
dkmv run ./components/fullstack-feature \
  --repo https://github.com/org/repo \
  --feature-name auth \
  --prd-path ./prds/auth.md
```

---

## File Structure

Each task is a single `.yaml` file. The file contains structured configuration — the prompt can be inline (`prompt` field) or in a separate file (`prompt_file` field).

```yaml
# Structured config
name: implement
description: Write code based on the plan
commit: true
push: true
commit_message: "feat({{ component }}): {{ feature_name }} [dkmv]"
model: claude-sonnet-4-6
max_turns: 100

inputs:
  - name: prd
    type: file
    src: "{{ prd_path }}"
    dest: /home/dkmv/workspace/.agent/prd.md

outputs:
  - path: /home/dkmv/workspace/CHANGELOG.md
    required: false
    save: true

# Agent instructions (persistent behavioral context)
instructions: |
  - Follow the plan at `.agent/plan.md` precisely
  - Run tests before finishing

# Task prompt (what to do)
prompt: |
  You are a senior engineer. Implement the plan at `.agent/plan.md`.
  ...
```

---

## Schema Reference

### Identity Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | **yes** | — | Unique identifier within the component. Used in logs and output references. Lowercase, hyphens allowed. |
| `description` | string | no | `""` | Human-readable description of what this task does. Shown in `dkmv runs` output. |
| `commit` | boolean | no | `true` | Whether to stage and commit changes after the task. |
| `push` | boolean | no | `true` | Whether to push after committing. Ignored if `commit` is `false`. |
| `commit_message` | string | no | auto-generated | Custom commit message. Supports template variables. |

```yaml
name: plan-architecture
description: Analyze the PRD and produce an implementation plan
commit: false
push: false
```

**Naming conventions:**
- Use lowercase with hyphens: `plan-architecture`, `write-tests`, `fix-feedback`
- Be specific: `implement-auth` is better than `implement`
- Keep it short: used in logs and error messages

**Git behavior:**

When `commit` is `true`, the runtime runs after the task completes:
1. `git add -A` (stage all changes)
2. `git status --porcelain` (skip if nothing to commit)
3. `git commit -m "<message>"`

When `push` is additionally `true`:
4. `git push origin <branch>`

Common patterns:
- Planning task: `commit: false, push: false` — no code changes to commit
- Implementation task: `commit: true, push: false` — commit locally, push at end
- Final task: `commit: true, push: true` — commit and push everything

### Execution Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `model` | string | no | `DKMV_MODEL` env var | Claude model to use. Overrides the global default for this task only. |
| `max_turns` | integer | no | `100` | Maximum conversation turns for Claude Code. |
| `timeout_minutes` | integer | no | global `DKMV_TIMEOUT` | Task-level timeout. The task is killed if it exceeds this. |
| `max_budget_usd` | float | no | global `DKMV_MAX_BUDGET_USD` | Cost cap for this single Claude Code invocation. |

```yaml
model: claude-sonnet-4-6
max_turns: 50
timeout_minutes: 15
max_budget_usd: 0.50
```

**When to override the model:**
- Planning tasks can use a more capable model (`claude-opus-4-6`) with lower `max_turns`
- Test-fixing tasks can use a faster model (`claude-sonnet-4-6`) with higher `max_turns`
- Review/judge tasks benefit from a different model than the one that wrote the code

**Budget guidance:**
- Planning tasks: $0.25–$0.75 (mostly reading, short output)
- Implementation tasks: $1.00–$5.00 (heavy code generation)
- Test/fix tasks: $0.50–$2.00 (iterative, but bounded)
- Review tasks: $0.25–$0.50 (read-only, structured output)

### Inputs

Inputs inject context into the container before Claude Code runs. Each input is an object in the `inputs` list.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | **yes** | Identifier for this input. Used in logs. |
| `type` | string | **yes** | One of: `file`, `text`, `env` |
| `optional` | boolean | no | If `true`, skip silently when the source is missing. Default: `false`. |

#### Type: `file`

Copy a file or directory from the source machine into the container.

DKMV runs Claude Code inside a Docker container. The container has its own filesystem, separate from the machine where you run `dkmv`. The `src` path is a file on **your machine** (where you invoke the `dkmv` CLI). The `dest` path is where that file ends up **inside the Docker container** where Claude Code runs. At runtime, DKMV reads the file from `src`, transfers it into the container, and writes it to `dest`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `src` | string | **yes** | Source path on the machine running `dkmv`. Supports template variables (see below). |
| `dest` | string | **yes** | Absolute path inside the container where the file is written. |

The `src` path supports **template variables** using `{{ }}` syntax. Template variables are resolved from CLI arguments passed when invoking the component. For example, if you run:

```bash
dkmv run ./components/dev \
  --repo https://github.com/org/repo \
  --var prd_path=./prds/auth.md
```

Then `{{ prd_path }}` in the task YAML resolves to `./prds/auth.md` — a path on your machine. DKMV reads that file and copies it into the container at `dest`.

```yaml
- name: prd
  type: file
  src: "{{ prd_path }}"
  dest: /home/dkmv/workspace/.agent/prd.md
```

If `src` points to a directory, its contents are copied recursively into `dest`.

#### Type: `text`

Write literal text content to a file in the container.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | string | **yes** | The text to write. Supports template variables. |
| `dest` | string | **yes** | Absolute path inside the container. |

```yaml
- name: guidelines
  type: text
  content: |
    - Target coverage: {{ target_coverage }}%
    - No breaking changes
  dest: /home/dkmv/workspace/.agent/guidelines.md
```

#### Type: `env`

Set an environment variable inside the container for this task.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key` | string | **yes** | Environment variable name. |
| `value` | string | **yes** | Value. Supports template variables. |

```yaml
- name: coverage_target
  type: env
  key: TARGET_COVERAGE
  value: "80"
```

### Outputs

Outputs declare files to read from the container after Claude Code finishes. They can be saved to the run output directory on your machine for inspection, and validated to ensure the task produced the expected results.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `path` | string | **yes** | — | Absolute path inside the container to read. |
| `required` | boolean | no | `false` | If `true`, the task fails when this file is missing. |
| `save` | boolean | no | `true` | If `true`, copy the file to the run output directory on your machine. |

```yaml
outputs:
  - path: /home/dkmv/workspace/.agent/plan.md
    required: true
    save: true

  - path: /home/dkmv/workspace/.agent/test_report.json
    required: false
    save: true
```

### Instructions

Persistent behavioral instructions for the agent. These are appended to the auto-generated agent instructions file in the container (e.g., `.claude/CLAUDE.md` for Claude Code, `AGENTS.md` for other agents). The agent loads these into context automatically and references them throughout the session.

You must provide exactly one of `instructions` or `instructions_file`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `instructions` | string | conditional | Inline markdown instructions for the agent. |
| `instructions_file` | string | conditional | Path to a markdown file containing the instructions. Relative to the task file. |

```yaml
# Inline instructions (short rules)
instructions: |
  ## Task-Specific Rules
  - Always run `npm test` before committing
  - Output structured data as JSON, not markdown
  - Do not modify files outside the `src/` directory
```

```yaml
# External instructions file (longer guidelines)
instructions_file: guidelines/coding-standards.md
```

**When to use `instructions` vs the prompt:**
- **Prompt**: The task objective. What you want the agent to do right now.
- **Instructions**: Persistent rules and constraints. What the agent should always keep in mind. These shape behavior throughout the entire session.

### Prompt

The instruction sent to Claude Code. This is the core of what the task does.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `prompt` | string | conditional | Inline prompt text. Supports Jinja2 template syntax. |
| `prompt_file` | string | conditional | Path to a file containing the prompt. Relative to the task file. Supports Jinja2 template syntax inside the file, same as inline `prompt`. |

You must provide exactly one of `prompt` or `prompt_file`.

```yaml
# Inline prompt
prompt: |
  You are a senior engineer. Read the PRD at `.agent/prd.md` and implement
  all requirements.

  ## Constraints
  - Follow existing code patterns
  - Write tests for all new public interfaces
```

```yaml
# External prompt file
prompt_file: prompts/implement.md
```

**Template syntax** uses Jinja2:

```yaml
prompt: |
  ## Context
  - Repository: {{ repo }}
  - Branch: {{ branch }}
  - Feature: {{ feature_name }}

  {% if design_docs_path %}
  Review the design documents in `.agent/design_docs/`.
  {% endif %}

  {% for requirement in requirements %}
  - {{ requirement }}
  {% endfor %}
```

---

## Template Variables

Template variables use Jinja2 syntax (`{{ variable }}`) and are available in: `prompt`, `prompt_file` contents, input `src`/`content`/`value`, and `commit_message`.

### Built-in Variables

These are always available:

| Variable | Source | Description |
|----------|--------|-------------|
| `repo` | CLI `--repo` | Repository URL |
| `branch` | CLI `--branch` or derived | Git branch name |
| `feature_name` | CLI `--feature-name` | Feature identifier |
| `component` | Directory name | Component name |
| `model` | Task config or global | Model being used |
| `run_id` | Runtime | Unique run identifier |

### CLI Variables

Additional variables can be passed via `--var` flags:

```bash
dkmv run ./components/my-component \
  --repo https://github.com/org/repo \
  --var prd_path=./prds/auth.md \
  --var design_docs_path=./docs/design \
  --var target_coverage=90
```

These become available as `{{ prd_path }}`, `{{ design_docs_path }}`, `{{ target_coverage }}`.

### Previous Task Variables

Access results from earlier tasks in the pipeline:

| Variable | Description |
|----------|-------------|
| `{{ tasks.<name>.status }}` | Status of a previous task: `completed`, `failed`, `skipped` |
| `{{ tasks.<name>.cost }}` | Cost in USD of that task's Claude Code invocation |
| `{{ tasks.<name>.turns }}` | Number of turns used |

---

## Task Chaining

Tasks in a component form a pipeline. All tasks run in the **same Docker container**, so files written by one task are automatically available to the next.

```
01-plan.yaml                    02-implement.yaml
┌──────────────────┐           ┌──────────────────────────────┐
│ prompt:          │           │ prompt:                      │
│   "Produce a     │           │   "Read the plan at          │
│    plan at       │ ────────▶ │    .agent/plan.md and         │
│    .agent/plan.md"│  (file    │    implement all features."  │
│                  │  persists │                              │
│ outputs:         │  on disk) │                              │
│   - path: ...    │           │                              │
│     save: true   │           │                              │
└──────────────────┘           └──────────────────────────────┘
```

### How It Works

1. Task 01's prompt tells Claude to write `.agent/plan.md` inside the container
2. DKMV validates the output exists (if `required: true`) and saves a copy to your machine (if `save: true`)
3. Task 02 starts in the same container — the plan file is already on disk
4. Task 02's prompt tells Claude to read `.agent/plan.md` and implement it

No explicit artifact-passing mechanism is needed. The shared container filesystem is the data channel between tasks, and the prompt is where you tell Claude which files to read.

Use **outputs** on the producing task to validate and save important files. Use the **prompt** on the consuming task to reference them by path.

### Container Persistence

All tasks in a component run in the **same Docker container**. This means:

- Files written by task 01 are visible to task 02 automatically
- Git state (staged changes, commits) accumulates across tasks
- Installed packages persist (npm install in task 01 is available in task 02)
- Environment modifications persist (cd, export, etc.)

---

## Examples

### Minimal Task

The simplest possible task — just a name, instructions, and a prompt:

```yaml
name: explore
description: Explore the codebase and understand the architecture

instructions: |
  - Do not modify any existing files
  - Output findings to `.agent/summary.md`

prompt: |
  Explore this codebase. Read the README, look at the project structure,
  and produce a summary at `.agent/summary.md` covering:
  - Tech stack and dependencies
  - Project structure
  - Key abstractions and patterns
```

Everything else uses defaults: global model, 100 turns, no budget cap, no special inputs/outputs, auto git commit and push.

### Planning Task

A task that reads a PRD and produces a plan without modifying code:

```yaml
name: plan
description: Produce an implementation plan from the PRD
commit: false
push: false
model: claude-opus-4-6
max_turns: 30
max_budget_usd: 0.75

inputs:
  - name: prd
    type: file
    src: "{{ prd_path }}"
    dest: /home/dkmv/workspace/.agent/prd.md

outputs:
  - path: /home/dkmv/workspace/.agent/plan.md
    required: true
    save: true

instructions: |
  ## Planning Rules
  - Output the plan to `.agent/plan.md`
  - Do NOT write any implementation code in this phase
  - Include sections for: architecture, file changes, test strategy

prompt: |
  Read the PRD at `.agent/prd.md` and produce an implementation plan
  at `.agent/plan.md`.

  The plan must include:
  1. Files to create or modify
  2. Implementation approach
  3. Test strategy
  4. Risk assessment

  Do NOT write any implementation code.
```

### Implementation Task

A task that implements code based on a plan from the previous task:

```yaml
name: implement
description: Implement the feature based on the plan
commit: true
push: true
commit_message: "feat({{ component }}): {{ feature_name }} [dkmv]"
max_turns: 100
max_budget_usd: 3.00

inputs:
  - name: prd
    type: file
    src: "{{ prd_path }}"
    dest: /home/dkmv/workspace/.agent/prd.md

  # No need to re-inject the plan — it's already on disk from task 01
  # (all tasks share the same container)

outputs:
  - path: /home/dkmv/workspace/.agent/changes.md
    required: false
    save: true

instructions: |
  ## Implementation Rules
  - Follow the plan at `.agent/plan.md` precisely
  - Write tests for all new public interfaces
  - Run the test suite before finishing
  - All tests must pass

prompt: |
  You are a senior software engineer. Implement the feature described
  in the PRD at `.agent/prd.md` following the plan at `.agent/plan.md`.

  After implementation:
  1. Write comprehensive tests
  2. Run the full test suite
  3. Fix any failures
  4. Write a brief changelog at `.agent/changes.md`
```

### Review Task

A read-only task that evaluates code without modifying it:

```yaml
name: review
description: Code review against the PRD
commit: false
push: false
model: claude-opus-4-6
max_turns: 40
max_budget_usd: 0.50

inputs:
  - name: prd
    type: file
    src: "{{ prd_path }}"
    dest: /home/dkmv/workspace/.agent/prd.md

outputs:
  - path: /home/dkmv/workspace/.agent/review.json
    required: true
    save: true

instructions: |
  - Do NOT modify any source code — this is a read-only review
  - Be thorough but fair in your evaluation
  - Output structured JSON, not prose

prompt: |
  You are an independent code reviewer. Evaluate the implementation on
  this branch against the PRD at `.agent/prd.md`.

  Produce a structured review at `.agent/review.json`:
  ```json
  {
    "verdict": "pass|fail",
    "confidence": 0.85,
    "issues": [
      {"severity": "high", "description": "...", "file": "...", "line": 42}
    ],
    "suggestions": ["..."]
  }
  ```

  Do NOT modify any code.
```

---

## Best Practices

### Task Granularity

**Split tasks when they have different goals.** A planning task and an implementation task have different models, budgets, and constraints. Splitting them gives you:

- Better cost control (planning is cheap, implementation is expensive)
- Model flexibility (use Opus for planning, Sonnet for implementation)
- Debuggability (if implementation fails, the plan is already saved)
- Replayability (re-run just the implementation with a different model)

**Don't over-split.** If two steps are tightly coupled and always run together, keep them in one task. Three tasks is a good default for most components:

1. Plan
2. Implement
3. Verify

### Prompt Writing

- **Be specific about outputs.** Tell Claude exactly what file to write and what format to use.
- **Use file paths, not descriptions.** "Write the plan to `.agent/plan.md`" is better than "produce a plan."
- **Set boundaries.** "Do NOT write implementation code" prevents planning tasks from doing too much.
- **Reference inputs by path.** "Read the PRD at `.agent/prd.md`" — Claude needs to know where to find things.

### Budget and Turn Management

- Set `max_budget_usd` on every task. It prevents runaway costs from infinite loops.
- Planning tasks rarely need more than 30–50 turns.
- Implementation tasks may need 80–150 turns for complex features.
- Review tasks should use 20–40 turns (they're read-only).
- When in doubt, start with lower limits and increase after observing actual usage.

### Git Strategy

- **First N-1 tasks:** `commit: false, push: false` or `commit: true, push: false`
- **Last task:** `commit: true, push: true`
- This avoids noisy intermediate commits and pushes a single coherent changeset.
- Use descriptive commit messages with template variables.

### Debugging

- Use `save: true` on outputs to inspect intermediate artifacts.
- Check the run output directory for saved artifacts, prompts, and stream logs.
- Lower `max_turns` to quickly test task definitions without burning budget.
- Use `dkmv show <run-id>` to inspect results and errors.

### Security

- Never put secrets in task YAML files. Use `type: env` inputs referencing environment variables.
- Sensitive values should come from CLI `--var` flags or environment variables, never hardcoded.
- The container inherits `ANTHROPIC_API_KEY` and `GITHUB_TOKEN` from the global DKMV config automatically — you don't need to declare them as inputs.
