# YAML Manifest Component System

## Status

Accepted — replaces the previous Python ABC-based `BaseComponent` approach

## Context and Problem Statement

DKMV needs a way to define components — collections of tasks that an AI agent executes sequentially inside a Docker sandbox. The original design used Python abstract base classes (`BaseComponent`) with subclasses for each component (DevComponent, QAComponent, etc.). This required writing Python code for every new component, coupling component logic to the framework.

How should components be defined so that users can create custom components without writing Python?

## Decision Drivers

- Users must be able to create components without writing Python code
- Component definitions must be portable (shareable, version-controllable)
- Must support variable interpolation for repo URLs, branch names, model selection
- Must support sequential task execution with shared context
- Must support per-task and per-component configuration defaults
- Must integrate with the existing `SandboxManager` and `TaskRunner` infrastructure

## Considered Options

- Python ABC subclasses (`BaseComponent`) — each component is a Python class
- YAML manifests with Jinja2 templating — declarative component definitions
- JSON Schema-based configuration — components defined in JSON

## Decision Outcome

Chosen option: "YAML manifests with Jinja2 templating", because declarative YAML definitions are more accessible to users, portable across projects, and naturally suit the sequential-task-with-variables pattern that DKMV components follow.

### Architecture

```
Component Directory Layout
├── component.yaml          # Manifest: inputs, defaults, task refs
├── 01-first-task.yaml      # Task definition (prompt, outputs, flags)
├── 02-second-task.yaml     # Task definition
└── prompt.md               # Optional external prompt file
```

```
┌─────────────────────────────────────────────────────────┐
│  CLI Command (dkmv dev / dkmv qa / dkmv run)            │
│  Builds variables dict from CLI flags                    │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  ComponentRunner.run()                                   │
│                                                          │
│  1. Load component.yaml → ComponentManifest              │
│  2. Inject shared inputs (files, text, env vars)         │
│  3. Create workspace dirs, write state files             │
│  4. Expand for_each task refs into instances              │
│  5. For each task:                                        │
│     a. Build cumulative variables (includes prior         │
│        task outputs for inter-task data flow)             │
│     b. TaskLoader.load(task.yaml, variables) → Jinja2    │
│     c. Apply manifest defaults (model, max_turns, etc.)  │
│     d. TaskRunner.run(task, session)                      │
│     e. Handle pause_after if configured                   │
└─────────────────────────────────────────────────────────┘
```

### Component Manifest Schema (`component.yaml`)

```yaml
name: qa                              # Component name
description: "QA evaluation..."       # Human-readable description

# Defaults applied to all tasks (task-level overrides take precedence)
model: claude-sonnet-4-6
max_turns: 80
timeout_minutes: 25
max_budget_usd: 2.00

# Agent CLAUDE.md — injected into every task's CLAUDE.md
agent_md: |                           # Inline markdown
  ## Rules
  - ...
agent_md_file: "{{ impl_docs_path }}/CLAUDE.md"  # Or file path (Jinja2)

# Shared inputs — injected into container before any task runs
inputs:
  - name: impl_docs
    type: file                        # file | text | env
    src: "{{ impl_docs_path }}"       # Host path (Jinja2-templated)
    dest: impl_docs                   # Container dest (auto-prefixed with .agent/)
    optional: false                   # Skip if source doesn't exist

# Task sequence
tasks:
  - file: 01-evaluate.yaml
    pause_after: true                 # Trigger interactive pause (see ADR-0013)
  - file: 02-fix.yaml
  - file: implement-phase.yaml
    for_each: "phases"                # Repeat for each item in variable
    max_turns: 100                    # Per-task-ref override
```

### Task Definition Schema (individual YAML files)

```yaml
name: evaluate
description: "Evaluate the implementation..."

commit: false                         # Git commit after task completes
push: false                           # Git push after task completes

model: claude-sonnet-4-6              # Override manifest default
max_turns: 80
timeout_minutes: 25
max_budget_usd: 2.00

inputs:                               # Per-task inputs (in addition to shared)
  - name: data
    type: text
    content: "{{ some_variable }}"
    dest: data.json

outputs:                              # Declared outputs — force-added to git
  - path: qa_evaluation.json          # Auto-prefixed with .agent/
    required: true
    save: true                        # Save to host run artifacts

instructions: |                       # CLAUDE.md content for this task
  ## Rules
  - ...
instructions_file: instructions.md   # Or load from file (mutually exclusive)

prompt: |                             # The prompt sent to Claude Code
  You are a senior QA engineer...
prompt_file: prompt.md                # Or load from file (mutually exclusive)
```

### Variable System

Variables are available in all Jinja2 contexts (manifest, task YAML, prompt files):

| Variable | Source | Example |
|----------|--------|---------|
| `repo` | CLI `--repo` or project config | `https://github.com/org/repo` |
| `branch` | CLI `--branch` or auto-derived | `feature/auth-dev` |
| `feature_name` | CLI `--feature-name` | `user-auth` |
| `component` | Component directory name | `qa` |
| `model` | CLI `--model` or config default | `claude-sonnet-4-6` |
| `run_id` | Auto-generated | `qa_20240115_143052` |
| `tasks` | Cumulative task results | `tasks.evaluate.outputs.qa_evaluation` |
| CLI-specific | Wrapper command flags | `prd_path`, `impl_docs_path`, `phases` |

The `tasks` variable enables inter-task data flow: task 2 can reference task 1's outputs via `{{ tasks.evaluate.outputs.qa_evaluation }}`.

### Configuration Cascade

Settings resolve in this priority order (highest wins):

1. CLI flags (`--model`, `--max-turns`, etc.)
2. Task YAML fields (`model: ...`)
3. Task ref overrides in manifest (`tasks: [{ file: ..., max_turns: 100 }]`)
4. Manifest defaults (`model: ...` at top level)
5. `DKMVConfig` defaults (from env vars / `.env` / `.dkmv/config.json`)

### Input Types

| Type | Required Fields | Behavior |
|------|----------------|----------|
| `file` | `src`, `dest` | Copy file/directory from host to container |
| `text` | `content`, `dest` | Write inline content to container path |
| `env` | `key`, `value` | Set environment variable in container |

The `dest` field on `file` and `text` inputs is auto-prefixed with `/home/dkmv/workspace/.agent/` unless it starts with `/`.

### Resolution Order

Components are resolved by `resolve_component()` in this order:

1. **Path** — if `name_or_path` contains `/` or starts with `.`, treat as filesystem path
2. **Built-in** — match against `BUILTIN_COMPONENTS` set (`dev`, `qa`, `docs`, `plan`)
3. **Registry** — look up in `.dkmv/components.json` (project-scoped)
4. **Error** — list available components

### Consequences

- Good: Components are declarative YAML — no Python required for custom components
- Good: Jinja2 templating enables dynamic configuration with variable interpolation
- Good: `for_each` enables repeating tasks over lists (e.g., implement each phase)
- Good: Configuration cascade provides sensible defaults with fine-grained overrides
- Good: Inter-task data flow via cumulative `tasks` variable and `.agent/` outputs
- Good: Component registry (`.dkmv/components.json`) enables project-scoped custom components
- Bad: Jinja2 `StrictUndefined` means undefined variables cause immediate errors (fails fast, but can be confusing)
- Bad: YAML syntax errors can be harder to debug than Python errors
- Neutral: Both `prompt`/`prompt_file` and `instructions`/`instructions_file` are mutually exclusive (validated at load time)
