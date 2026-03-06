# PRD: DKMV Tasks v1

**Author:** DKMV Team
**Status:** Draft
**Last Updated:** 2026-02-21

---

## Table of Contents

- [1. Executive Summary](#1-executive-summary)
- [2. Problem Statement](#2-problem-statement)
- [3. Goals and Non-Goals](#3-goals-and-non-goals)
- [4. Background: Current Architecture](#4-background-current-architecture)
- [5. Proposed Architecture](#5-proposed-architecture)
  - [5.1 Core Concepts](#51-core-concepts)
  - [5.2 System Diagram](#52-system-diagram)
  - [5.3 Processing Pipeline](#53-processing-pipeline)
- [6. What to Build](#6-what-to-build)
  - [6.1 Task Model (Pydantic)](#61-task-model-pydantic)
  - [6.2 Task Loader](#62-task-loader)
  - [6.3 TaskRunner](#63-taskrunner)
  - [6.4 ComponentRunner](#64-componentrunner)
  - [6.5 Component Discovery](#65-component-discovery)
  - [6.6 CLI: `dkmv run` Command](#66-cli-dkmv-run-command)
  - [6.7 Built-in Component Conversion](#67-built-in-component-conversion)
- [7. Implementation Phases](#7-implementation-phases)
  - [Phase 1: Foundation](#phase-1-foundation)
  - [Phase 2: TaskRunner](#phase-2-taskrunner)
  - [Phase 3: ComponentRunner and CLI](#phase-3-componentrunner-and-cli)
  - [Phase 4: Built-in Components](#phase-4-built-in-components)
  - [Phase 5: Polish and Migration](#phase-5-polish-and-migration)
- [8. Testing Strategy](#8-testing-strategy)
- [9. Migration Plan](#9-migration-plan)
- [10. Open Questions](#10-open-questions)
- [11. Evaluation Criteria](#11-evaluation-criteria)

---

## 1. Executive Summary

DKMV v1 ships with four hardcoded Python components (dev, qa, judge, docs). Each component is a Python class that inherits from `BaseComponent`, overrides specific hooks, and bundles a `prompt.md` template. Adding a new workflow requires writing Python code, understanding the 12-step lifecycle, creating Pydantic models, and registering the component in the CLI.

**DKMV Tasks v1** replaces this with a declarative YAML-based system. Components become directories of task YAML files instead of Python classes. A single generic runtime reads, validates, and executes any task file — no Python required. The four built-in components are converted from Python classes to YAML task files packaged with the `dkmv` distribution.

This enables:

- **Non-developers** to create new workflows by writing YAML + markdown
- **Community contributions** as shareable component directories
- **Better cost control** by splitting monolithic components into discrete tasks with individual budgets
- **Easier debugging** with inspectable, declarative task definitions

---

## 2. Problem Statement

### Current Pain Points

**1. Adding a workflow requires Python expertise.**
To create a new component today, you must: write a Python class inheriting `BaseComponent`, override 4-6 hook methods, create a Pydantic config model, create a Pydantic result model, write a prompt template, register the component in `cli.py` with option definitions, and add hatchling force-include config for the prompt file. This is ~200-300 lines of Python spread across 4-5 files per component.

**2. The 12-step lifecycle is unnecessarily coupled.**
`BaseComponent.run()` is 109 lines orchestrating 12 steps. Steps 1-4 (validation, run creation, sandbox start, workspace setup) and steps 9-12 (git teardown, post-teardown, mark completed, return) are identical for every component. Only steps 5-8 (write CLAUDE.md, build prompt, stream Claude, collect results) vary — and those variations are exactly what the task YAML captures declaratively.

**3. Component-specific logic is scattered.**
Each component's behavior is spread across: `component.py` (hooks), `models.py` (config + result types), `prompt.md` (prompt template), `cli.py` (option definitions + config building), and `pyproject.toml` (force-include). Understanding what a component does requires reading all five.

**4. No cost isolation between phases.**
The dev component does planning AND implementation in a single Claude Code session. If planning uses $2 of a $5 budget, implementation gets only $3. Splitting into separate tasks gives each phase its own budget.

**5. No replayability.**
If implementation fails but planning succeeded, you must re-run the entire component. With separate tasks, you can re-run just the implementation task — the plan is already on disk.

---

## 3. Goals and Non-Goals

### Goals

1. **A generic task runner** that can execute any valid task YAML file without task-specific Python code
2. **A component runner** that orchestrates sequences of tasks within a shared container
3. **Component discovery** that finds components from: packaged built-ins, local directories, and (future) pip-installed packages
4. **A `dkmv run` CLI command** that accepts a component directory + variables and runs all tasks
5. **Conversion of all four built-in components** from Python classes to YAML task files
6. **Backward compatibility** for the existing `dkmv dev`, `dkmv qa`, `dkmv judge`, `dkmv docs` commands (they become thin wrappers around `dkmv run`)

### Non-Goals

- **Conditional execution / DAG scheduling** — Tasks run sequentially. No `condition.when`, no parallel tasks, no skip logic. Fail-fast.
- **Remote task registries** — No `dkmv install <component>` from a registry. Components are local directories or pip packages.
- **Custom Python hooks** — No `pre_run.py` or `post_run.py` scripts. The task YAML is the complete definition. If custom logic is needed, it goes in the prompt (Claude runs it in the container).
- **Multi-container tasks** — All tasks in a component share one container. No task-level container isolation.
- **Web UI / API** — CLI only.
- **Dynamic task generation** — The task list is static (files in a directory). No programmatic task creation at runtime.

---

## 4. Background: Current Architecture

### The 12-Step Lifecycle

`BaseComponent.run()` in `dkmv/components/base.py` orchestrates these steps:

| Step | What | Generic? | Maps to Task YAML |
|------|------|----------|-------------------|
| 1 | Validate config | Yes | Runtime validation |
| 2 | Create run (RunManager) | Yes | Runtime |
| 3 | Start sandbox (SandboxManager) | Yes | Runtime |
| 4 | Setup workspace (git clone, branch) | Yes | Runtime + `commit`/`push` fields |
| 5 | Write CLAUDE.md | **Varies** | `instructions` / `instructions_file` |
| 6 | Build prompt | **Varies** | `prompt` / `prompt_file` |
| 7 | Stream Claude Code | Yes | `model`, `max_turns`, `timeout_minutes`, `max_budget_usd` |
| 8 | Collect results | **Varies** | `outputs` |
| 9 | Git teardown (commit, push) | Yes | `commit`, `push`, `commit_message` |
| 10 | Post-teardown hook | **Varies** | Out of scope (see Open Questions) |
| 11 | Mark completed | Yes | Runtime |
| 12 | Return result | Yes | Runtime |

Steps marked "Varies" are what make each component unique. These are exactly the fields captured in a task YAML file. Steps marked "Yes" are identical across components and belong in the generic runtime.

### Component Hooks Used Today

| Component | `pre_workspace_setup` | `setup_workspace` | `collect_artifacts` | `post_teardown` | `_teardown_git` override |
|-----------|---|---|---|---|---|
| Dev | Branch derivation | Copy PRD, feedback, design docs | — | Save plan.md | — |
| QA | — | Copy PRD | Read qa_report.json | — | Force-add report |
| Judge | — | Copy PRD | Read verdict.json | — | Force-add verdict |
| Docs | — | — | — | Create PR | — |

### What Each Hook Becomes in Task YAML

| Hook | Task YAML Equivalent |
|------|---------------------|
| `pre_workspace_setup` (branch derivation) | CLI `--branch` or template: `feature/{{ feature_name }}-dev` |
| `setup_workspace` (copy files into container) | `inputs` with `type: file` |
| `collect_artifacts` (read files from container) | `outputs` with `required` and `save` |
| `_teardown_git` override (force-add) | Runtime auto-force-adds declared outputs before commit |
| `post_teardown` (save plan, create PR) | `outputs` with `save: true` (plan), prompt-driven (PR creation) |
| `build_prompt` (format template) | `prompt` / `prompt_file` with Jinja2 |

### What Resists Declarative YAML

Two behaviors in the current codebase don't have clean YAML equivalents:

1. **PRD stripping** (`DevComponent._strip_eval_criteria()`): Removes `## Evaluation Criteria` from the PRD before giving it to the dev agent. This is a content transformation, not a copy. **Resolution:** The prompt tells Claude to ignore that section. Alternatively, a future `transform` field could support built-in transforms like `strip-section("## Evaluation Criteria")`.

2. **PR creation** (`DocsComponent.post_teardown()`): Runs `gh pr create` as a post-run shell command. **Resolution:** The prompt instructs Claude to run the command if an env var is set. The env var is injected via `inputs` with `type: env`. This is a reasonable pattern — Claude has shell access inside the container.

---

## 5. Proposed Architecture

### 5.1 Core Concepts

| Concept | Definition |
|---------|-----------|
| **Task** | A single Claude Code invocation. Defined by a `.yaml` file. The atomic unit. |
| **Component** | An ordered directory of task YAML files executed in a shared container. |
| **Task Model** | Pydantic model validating the YAML schema. |
| **Task Loader** | Reads YAML, resolves Jinja2 templates, returns validated Task Model. |
| **TaskRunner** | Executes a single task: injects inputs, writes instructions, streams Claude, collects outputs. |
| **ComponentRunner** | Orchestrates a sequence of tasks: starts container, runs tasks in order, handles teardown. |

### 5.2 System Diagram

```
CLI (dkmv run ./components/dev --repo ... --var prd_path=...)
  │
  ▼
ComponentRunner
  │
  ├── Discover component directory
  ├── List + sort task YAML files
  ├── Start container (SandboxManager)
  ├── Setup workspace (git clone, branch checkout)
  │
  ├── For each task file:
  │   │
  │   ├── TaskLoader
  │   │   ├── Read YAML
  │   │   ├── Resolve Jinja2 templates (CLI vars + built-in vars + previous task vars)
  │   │   ├── Parse with yaml.safe_load()
  │   │   └── Validate with TaskModel.model_validate()
  │   │
  │   └── TaskRunner
  │       ├── Inject inputs (file copy, text write, env set)
  │       ├── Write instructions (.claude/CLAUDE.md)
  │       ├── Stream Claude Code (SandboxManager.stream_claude)
  │       ├── Collect outputs (validate, save)
  │       ├── Git teardown (force-add outputs, commit, push)
  │       └── Return TaskResult
  │
  ├── Stop container
  └── Return ComponentResult (list of TaskResults)
```

### 5.3 Processing Pipeline

For each task YAML file, the processing pipeline is:

```
task.yaml (raw text)
    │
    ▼
Jinja2 render(template_vars)      ← CLI vars, built-in vars, previous task vars
    │                                  StrictUndefined for required vars
    ▼                                  Graceful handling for optional vars
YAML string (templates resolved)
    │
    ▼
yaml.safe_load()
    │
    ▼
dict
    │
    ▼
TaskModel.model_validate(dict)    ← Pydantic v2 strict validation
    │                                Mutual exclusivity checks
    ▼                                Type coercion, defaults
TaskModel instance (ready to execute)
```

**Why Jinja2 before YAML?** Templates like `{{ prd_path }}` appear in YAML string values. Resolving them before YAML parsing means the YAML parser always sees valid values. This is the pattern used by Ansible, dbt, and Helm.

**Why `StrictUndefined`?** Using Jinja2's `StrictUndefined` catches typos in variable names at load time, before the task runs. Optional inputs use `{{ var | default('') }}` to provide fallbacks.

---

## 6. What to Build

### 6.1 Task Model (Pydantic)

A Pydantic v2 model that validates the task YAML schema defined in `task_definition.md`.

**Location:** `dkmv/tasks/models.py`

```python
class TaskInput(BaseModel):
    name: str
    type: Literal["file", "text", "env"]
    src: str | None = None
    dest: str | None = None
    content: str | None = None
    key: str | None = None
    value: str | None = None
    optional: bool = False

    @model_validator(mode="after")
    def validate_type_fields(self) -> Self:
        """Ensure correct fields are present for each input type."""
        ...

class TaskOutput(BaseModel):
    path: str
    required: bool = False
    save: bool = True

class TaskDefinition(BaseModel):
    # Identity
    name: str
    description: str = ""
    commit: bool = True
    push: bool = True
    commit_message: str | None = None

    # Execution
    model: str | None = None
    max_turns: int | None = None
    timeout_minutes: int | None = None
    max_budget_usd: float | None = None

    # Data
    inputs: list[TaskInput] = []
    outputs: list[TaskOutput] = []

    # Instructions (exactly one required)
    instructions: str | None = None
    instructions_file: str | None = None

    # Prompt (exactly one required)
    prompt: str | None = None
    prompt_file: str | None = None

    @model_validator(mode="after")
    def validate_instructions_xor(self) -> Self:
        """Exactly one of instructions / instructions_file must be set."""
        ...

    @model_validator(mode="after")
    def validate_prompt_xor(self) -> Self:
        """Exactly one of prompt / prompt_file must be set."""
        ...

class TaskResult(BaseModel):
    task_name: str
    status: Literal["completed", "failed", "timed_out", "skipped"]
    total_cost_usd: float = 0.0
    duration_seconds: float = 0.0
    num_turns: int = 0
    session_id: str = ""
    error_message: str = ""
    outputs: dict[str, str] = {}   # path -> content (for saved outputs)
```

**Complexity:** Low. Standard Pydantic models with validators.

### 6.2 Task Loader

Reads a task YAML file, resolves Jinja2 templates, validates the result, and resolves `prompt_file` / `instructions_file` references.

**Location:** `dkmv/tasks/loader.py`

```python
class TaskLoader:
    def __init__(self, jinja_env: jinja2.Environment | None = None):
        self._jinja_env = jinja_env or jinja2.Environment(
            undefined=jinja2.StrictUndefined,
            keep_trailing_newline=True,
        )

    def load(
        self,
        task_path: Path,
        variables: dict[str, str],
    ) -> TaskDefinition:
        """Load a task YAML file with template resolution.

        Pipeline:
        1. Read raw YAML text
        2. Render Jinja2 templates with provided variables
        3. Parse YAML
        4. Validate with Pydantic
        5. Resolve prompt_file / instructions_file paths
        """
        ...

    def load_component(
        self,
        component_dir: Path,
        variables: dict[str, str],
    ) -> list[TaskDefinition]:
        """Load all task files from a component directory, sorted by filename."""
        ...
```

**Key decisions:**

- Template variables that are missing and not `optional` raise `jinja2.UndefinedError` at load time, not at runtime. Fail fast.
- `prompt_file` and `instructions_file` paths are resolved relative to the task YAML file's directory.
- Prompt/instructions file contents are read and inlined into the `TaskDefinition` (the `prompt` / `instructions` field is populated). The `_file` variant is a convenience for authoring — by load time, the model always has the resolved content.
- The raw YAML text is rendered as a single Jinja2 template. This means Jinja2 syntax is available everywhere in the file — not just in designated fields.

**Complexity:** Medium. Jinja2 + YAML parsing with error handling for template errors, YAML syntax errors, and file resolution.

### 6.3 TaskRunner

Executes a single `TaskDefinition` inside an already-running container. This class replaces the "varying" steps (5-8) from `BaseComponent.run()`.

**Location:** `dkmv/tasks/runner.py`

```python
class TaskRunner:
    def __init__(
        self,
        sandbox: SandboxManager,
        run_manager: RunManager,
        console: Console,
    ):
        self._sandbox = sandbox
        self._run_manager = run_manager
        self._console = console

    async def run(
        self,
        task: TaskDefinition,
        session: SandboxSession,
        run_id: str,
        config: DKMVConfig,
        variables: dict[str, str],
    ) -> TaskResult:
        """Execute a single task in the container.

        Steps:
        1. Inject inputs (file, text, env)
        2. Write instructions to .claude/CLAUDE.md
        3. Save prompt to run directory
        4. Stream Claude Code
        5. Collect and validate outputs
        6. Git teardown (force-add outputs, commit, push)
        7. Return TaskResult
        """
        ...
```

**Step-by-step:**

**Step 1: Inject inputs.** For each input in `task.inputs`:
- `type: file` → Read `src` from host, call `sandbox.write_file(session, dest, content)`. If `src` is a directory, iterate and copy each file.
- `type: text` → Call `sandbox.write_file(session, dest, content)`.
- `type: env` → Add to environment for Claude invocation. (Environment variables are passed through the `stream_claude` call.)
- If `optional: true` and source is missing, skip silently.
- If `optional: false` (default) and source is missing, raise `FileNotFoundError` with a clear message.

**Step 2: Write instructions.** Create `.claude/CLAUDE.md` in the container with the resolved `instructions` content. The file includes a standard header (agent role, feature name, branch) followed by the task-specific instructions.

**Step 3: Save prompt.** Call `run_manager.save_prompt(run_id, prompt)` to persist the resolved prompt for debugging.

**Step 4: Stream Claude Code.** Resolve execution parameters using the priority cascade (see below), then call `sandbox.stream_claude()`. Process stream events, render output, append to `stream.jsonl`.

**Execution parameter cascade:** For `model`, `max_turns`, `timeout_minutes`, and `max_budget_usd`, the resolution priority is:

1. **Task YAML value** (highest) — If the task definition sets the field, use it. The task author deliberately chose this value for this specific task (e.g., Opus for planning, Sonnet for implementation).
2. **CLI flag** — If the task definition doesn't set the field, use the CLI override (`--model`, `--timeout`, `--max-budget-usd`). This lets operators adjust defaults without editing YAML files.
3. **Global config** (lowest) — If neither task YAML nor CLI provides a value, use `DKMVConfig` defaults (`DKMV_MODEL`, `DKMV_TIMEOUT`, `DKMV_MAX_BUDGET_USD`).

This means `dkmv run dev --model claude-opus-4-6` sets Opus as the default for tasks that don't specify their own model, but a task with `model: claude-sonnet-4-6` still uses Sonnet. Task definitions are authoritative for their own execution parameters.

**Step 5: Collect outputs.** For each output in `task.outputs`:
- Call `sandbox.read_file(session, output.path)`.
- If `required: true` and file is missing, set status to `failed` with error message.
- If `save: true`, save to `{run_dir}/{filename}` via `run_manager`.

**Step 6: Git teardown.** If `task.commit` is true:
- Force-add all declared output paths that exist in the container (replaces the per-component `_teardown_git` override pattern).
- Stage all changes: `git add -A`.
- Check for changes: `git status --porcelain`.
- Commit with `task.commit_message` or auto-generated message.
- If `task.push` is true, push to the current branch.

**Complexity:** High. This is the core execution engine — needs careful error handling, timeout management, and integration with SandboxManager, RunManager, and StreamParser.

### 6.4 ComponentRunner

Orchestrates a sequence of tasks in a shared container. Replaces `BaseComponent.run()` entirely.

**Location:** `dkmv/tasks/component.py`

```python
class ComponentRunner:
    def __init__(
        self,
        sandbox: SandboxManager,
        run_manager: RunManager,
        task_loader: TaskLoader,
        task_runner: TaskRunner,
        console: Console,
    ):
        ...

    async def run(
        self,
        component_dir: Path,
        repo: str,
        branch: str | None,
        feature_name: str,
        variables: dict[str, str],
        config: DKMVConfig,
        keep_alive: bool = False,
        verbose: bool = False,
    ) -> ComponentResult:
        """Run all tasks in a component directory.

        Steps:
        1. Discover and load task files
        2. Create run (RunManager.start_run)
        3. Start container (SandboxManager.start)
        4. Setup workspace (git clone, branch checkout, create `.dkmv/`
           directory and add it to `.gitignore`)
        5. For each task: execute via TaskRunner
           - On failure: stop pipeline, mark remaining tasks as skipped
           - Track costs, durations, results per task
        6. Stop container
        7. Return ComponentResult
        """
        ...
```

**Template variables available to tasks:**

| Variable | Source |
|----------|--------|
| `repo` | CLI argument |
| `branch` | CLI argument or derived |
| `feature_name` | CLI argument |
| `component` | Component directory name |
| `model` | Task-level or global default |
| `run_id` | Generated at runtime |
| `tasks.<name>.status` | Previous task result |
| `tasks.<name>.cost` | Previous task cost |
| `tasks.<name>.turns` | Previous task turns |
| All `--var` flags | CLI arguments |

**ComponentResult model:**

```python
class ComponentResult(BaseModel):
    run_id: str
    component: str
    status: Literal["completed", "failed", "timed_out"]
    repo: str
    branch: str
    feature_name: str
    total_cost_usd: float
    duration_seconds: float
    task_results: list[TaskResult]
    error_message: str = ""
```

**Complexity:** High. Lifecycle management, variable propagation between tasks, error handling across task boundaries.

### 6.5 Component Discovery

Finds component directories from three sources, evaluated in order:

1. **Explicit path** — `dkmv run ./my-component` or `dkmv run /absolute/path`
2. **Built-in** — `dkmv run dev` resolves to `dkmv/builtins/dev/`
3. **Future: pip entry points** — `dkmv run community-component` resolves via `importlib.metadata.entry_points(group="dkmv.components")`

**Location:** `dkmv/tasks/discovery.py`

```python
def resolve_component(name_or_path: str) -> Path:
    """Resolve a component name or path to a directory containing task YAML files.

    Resolution order:
    1. If it's a path (contains / or .), resolve and validate
    2. If it matches a built-in name, use packaged files
    3. Raise ComponentNotFoundError
    """
    ...
```

**Built-in component packaging:**

Built-in task YAMLs live in `dkmv/builtins/{dev,qa,judge,docs}/` and are accessed via `importlib.resources.files("dkmv.builtins")`. They must be included in the wheel via `pyproject.toml` configuration. The `builtins/` package lives at the same level as `tasks/` (engine code) and `components/` (legacy Python components) — this reflects that built-ins are component definitions, not part of the task engine itself.

```
dkmv/
  builtins/
    dev/
      01-plan.yaml
      02-implement.yaml
    qa/
      01-evaluate.yaml
    judge/
      01-verdict.yaml
    docs/
      01-generate.yaml
```

**Complexity:** Low-Medium. Path resolution + `importlib.resources` for built-in components.

### 6.6 CLI: `dkmv run` Command

New top-level command that accepts a component reference and variables.

**Location:** Added to `dkmv/cli.py`

```
dkmv run <component> [OPTIONS]

Arguments:
  component    Component name or path to a component directory

Options:
  --repo TEXT              Repository URL (required)
  --branch TEXT            Git branch (optional, derived if not set)
  --feature-name TEXT      Feature identifier
  --var KEY=VALUE          Template variable (repeatable)
  --model TEXT             Default model for tasks that don't specify their own
  --max-turns INT          Default max turns for tasks that don't specify their own
  --timeout INT            Default timeout for tasks that don't specify their own
  --max-budget-usd FLOAT   Default budget for tasks that don't specify their own
  --keep-alive             Keep container running after completion
  --verbose                Enable verbose output
```

**Examples:**

```bash
# Run built-in dev component
dkmv run dev --repo https://github.com/org/repo \
  --feature-name auth --var prd_path=./prds/auth.md

# Run local custom component
dkmv run ./components/fullstack-feature --repo https://github.com/org/repo \
  --feature-name auth --var prd_path=./prds/auth.md --var target_coverage=90

# Run with defaults (used by tasks that don't specify their own model/budget)
dkmv run dev --repo https://github.com/org/repo \
  --var prd_path=./prds/auth.md --model claude-opus-4-6 --max-budget-usd 10.0
```

**Backward compatibility:** The existing `dkmv dev`, `dkmv qa`, `dkmv judge`, `dkmv docs` commands become thin wrappers that call `ComponentRunner.run()` directly (not as a subprocess). Each wrapper translates its typed CLI options into a `dict[str, str]` of template variables:

| Wrapper Option | Variable |
|----------------|----------|
| `dkmv dev --prd PATH` | `prd_path=PATH` |
| `dkmv dev --feedback PATH` | `feedback_path=PATH` |
| `dkmv dev --design-docs PATH` | `design_docs_path=PATH` |
| `dkmv docs --create-pr` | `create_pr=true` |
| `dkmv docs --pr-base BRANCH` | `pr_base=BRANCH` |

Common options (`--repo`, `--branch`, `--feature-name`, `--model`, `--max-turns`, `--max-budget-usd`, `--timeout`, `--keep-alive`, `--verbose`) pass through directly as `ComponentRunner.run()` arguments. This preserves the familiar interface while adding the generic `dkmv run` path.

**Complexity:** Medium. Typer command definition, var parsing, integration with ComponentRunner.

### 6.7 Built-in Component Conversion

Convert the four existing Python components into YAML task files. The task YAML files already exist in `docs/core/dkmv_tasks/v1/components/` — they need to be:

1. Moved into `dkmv/builtins/`
2. Refined for production use (remove documentation comments)
3. Tested to produce equivalent results to the Python implementations

**Conversion mapping per component:**

#### Dev Component (2 tasks)

| Python Code | YAML Equivalent |
|-------------|----------------|
| `DevComponent.pre_workspace_setup()` — branch derivation | CLI `--branch` or default `feature/{feature_name}-dev` |
| `DevComponent.setup_workspace()` — copy PRD, strip eval criteria | `inputs` with `type: file` + prompt instruction to ignore eval criteria |
| `DevComponent.setup_workspace()` — copy feedback, design docs | `inputs` with `type: file` + `optional: true` |
| `DevComponent.post_teardown()` — save plan.md | `outputs` with `save: true` on plan.md |
| `DevComponent.build_prompt()` — format template | `prompt` field with Jinja2 |
| `DevConfig` model | CLI `--var` flags (`prd_path`, `feedback_path`, `design_docs_path`) |
| `DevResult` model | `ComponentResult` + `TaskResult` (fields like `files_changed` come from Claude stream) |

#### QA Component (1 task)

| Python Code | YAML Equivalent |
|-------------|----------------|
| `QAComponent.setup_workspace()` — copy full PRD | `inputs` with `type: file` |
| `QAComponent.collect_artifacts()` — read qa_report.json | `outputs` with `required: true`, `save: true` |
| `QAComponent._teardown_git()` — force-add report | Runtime auto-force-adds declared outputs |
| `QAConfig` model | CLI `--var prd_path=...` |
| `QAResult` model | `TaskResult.outputs["qa_report.json"]` → parsed JSON |

#### Judge Component (1 task)

| Python Code | YAML Equivalent |
|-------------|----------------|
| `JudgeComponent.setup_workspace()` — copy full PRD | `inputs` with `type: file` |
| `JudgeComponent.collect_artifacts()` — read verdict.json | `outputs` with `required: true`, `save: true` |
| `JudgeComponent._teardown_git()` — force-add verdict | Runtime auto-force-adds declared outputs |
| `JudgeConfig` model | CLI `--var prd_path=...` |
| `JudgeResult` model | `TaskResult.outputs["verdict.json"]` → parsed JSON |

#### Docs Component (1 task)

| Python Code | YAML Equivalent |
|-------------|----------------|
| `DocsComponent.post_teardown()` — create PR | Prompt instructs Claude to run `gh pr create` if env var set |
| `DocsConfig.create_pr`, `DocsConfig.pr_base` | `inputs` with `type: env` (`DKMV_CREATE_PR`, `DKMV_PR_BASE`) |
| `DocsResult` model | `TaskResult.outputs["docs_manifest.json"]` → parsed JSON |

**Complexity:** Medium. The YAML files exist as drafts. Refinement, testing, and packaging are the main work.

---

## 7. Implementation Phases

### Phase 1: Foundation

**Goal:** Task model, loader, and discovery. No execution yet — just parsing and validation.

| Item | Description | Complexity |
|------|-------------|-----------|
| `dkmv/tasks/__init__.py` | Package init | Trivial |
| `dkmv/tasks/models.py` | `TaskInput`, `TaskOutput`, `TaskDefinition`, `TaskResult`, `ComponentResult` | Low |
| `dkmv/tasks/loader.py` | `TaskLoader` — Jinja2 + YAML + Pydantic pipeline | Medium |
| `dkmv/tasks/discovery.py` | `resolve_component()` — path + built-in resolution | Low |
| `tests/unit/test_task_models.py` | Model validation tests (valid, invalid, edge cases) | Low |
| `tests/unit/test_task_loader.py` | Loader tests (template resolution, file references, error cases) | Medium |
| `tests/unit/test_discovery.py` | Discovery tests (explicit path, built-in, not found) | Low |

**Deliverables:**
- Can load any task YAML file into a validated `TaskDefinition`
- Can discover component directories
- Template variables resolve correctly
- `prompt_file` / `instructions_file` resolve relative to task file
- Mutual exclusivity validated (instructions vs instructions_file, prompt vs prompt_file)
- Missing required variables produce clear error messages

**New dependencies:** `jinja2` and `pyyaml` must be added to `pyproject.toml` runtime dependencies.

**Estimated test count:** ~30 tests

### Phase 2: TaskRunner

**Goal:** Execute a single task inside a running container.

| Item | Description | Complexity |
|------|-------------|-----------|
| `dkmv/tasks/runner.py` | `TaskRunner.run()` — inject inputs, write instructions, stream Claude, collect outputs, git teardown | High |
| `tests/unit/test_task_runner.py` | Unit tests with mocked SandboxManager | High |

**Deliverables:**
- File inputs copied from host to container
- Text inputs written to container
- Env inputs passed to Claude invocation
- Instructions written to `.claude/CLAUDE.md`
- Claude Code streamed with correct parameters
- Outputs validated and saved
- Git commit and push with correct message
- Declared outputs auto-force-added before commit
- Error handling: missing required inputs, missing required outputs, Claude errors, timeouts

**Dependencies:** Phase 1 (TaskDefinition model), existing SandboxManager, RunManager, StreamParser.

**Estimated test count:** ~20 tests

### Phase 3: ComponentRunner and CLI

**Goal:** Orchestrate task sequences and expose via CLI.

| Item | Description | Complexity |
|------|-------------|-----------|
| `dkmv/tasks/component.py` | `ComponentRunner.run()` — container lifecycle, task sequencing, variable propagation | High |
| CLI addition in `dkmv/cli.py` | `dkmv run` command with options | Medium |
| `tests/unit/test_component_runner.py` | Unit tests with mocked TaskRunner | Medium |
| `tests/unit/test_cli_run.py` | CLI integration tests | Medium |

**Deliverables:**
- `dkmv run` command works with local directories
- Tasks execute in filename order
- Container shared across all tasks
- Previous task variables (`tasks.<name>.status`, etc.) propagated
- Fail-fast: first failed task stops the pipeline
- Run results saved to RunManager
- `dkmv runs` and `dkmv show` work with task-based runs

**Dependencies:** Phase 1 + Phase 2.

**Estimated test count:** ~20 tests

### Phase 4: Built-in Components

**Goal:** Package built-in components and create backward-compatible wrappers.

| Item | Description | Complexity |
|------|-------------|-----------|
| `dkmv/builtins/{dev,qa,judge,docs}/` | Production-ready task YAML files | Medium |
| `pyproject.toml` | Package data includes for built-in YAMLs | Low |
| CLI wrappers in `dkmv/cli.py` | `dkmv dev` → `dkmv run dev` translation | Medium |
| `tests/unit/test_builtins.py` | Validate all built-in YAMLs load correctly | Low |
| `tests/integration/test_run_e2e.py` | E2E test with Docker container | High |

**Deliverables:**
- `dkmv run dev --repo ... --var prd_path=...` works end-to-end
- `dkmv dev --repo ... --prd ...` still works (backward compat wrapper)
- Same for qa, judge, docs
- Built-in YAMLs packaged in wheel
- E2E test verifies actual container execution

**Dependencies:** Phase 1 + Phase 2 + Phase 3.

**Estimated test count:** ~15 tests

### Phase 5: Polish and Migration

**Goal:** Documentation, cleanup, and migration of existing Python component code.

| Item | Description | Complexity |
|------|-------------|-----------|
| Documentation | Update CLAUDE.md, README, CLI help text | Low |
| Deprecation notices | Mark `dkmv dev/qa/judge/docs` as wrappers in help text | Low |
| Old component code | Keep but mark as deprecated (remove in v2) | Low |
| Full test suite verification | All existing tests still pass + new tests | Low |

**Deliverables:**
- Complete documentation of the task system
- All quality gates pass (ruff, mypy, pytest, coverage)
- Clear migration path from Python components to YAML tasks

**Dependencies:** All previous phases.

---

## 8. Testing Strategy

### Level 1: Model Tests (~30 tests)

Test `TaskDefinition` validation with:
- Valid complete task, valid minimal task
- Missing required fields (name, instructions/prompt)
- Mutual exclusivity violations (both prompt and prompt_file)
- Invalid input types, missing type-specific fields
- Default values applied correctly
- Edge cases: empty inputs/outputs lists, very long strings

### Level 2: Loader Tests (~20 tests)

Test `TaskLoader` with:
- Template variable resolution (simple, nested, missing)
- `StrictUndefined` errors for missing required variables
- `{{ var | default('') }}` for optional variables
- `prompt_file` / `instructions_file` resolution (relative paths)
- Invalid YAML syntax after template resolution
- Component directory loading (sorted by filename)
- Jinja2 control flow in prompts (`{% if %}`, `{% for %}`)

### Level 3: Runner Tests (~20 tests)

Test `TaskRunner` with mocked `SandboxManager`:
- File input injection (single file, directory)
- Text input injection
- Env input injection
- Optional input skipping
- Required input missing → error
- Instructions written to correct path
- Claude invocation with correct parameters (cascade: task YAML > CLI > global)
- Output collection (required present, required missing, save flag)
- Git teardown (commit, push, skip scenarios)
- Force-add of declared outputs
- Error handling (Claude error, timeout, container error)

### Level 4: ComponentRunner Tests (~15 tests)

Test `ComponentRunner` with mocked `TaskRunner`:
- Multi-task execution in order
- Variable propagation between tasks
- Fail-fast on first failure
- Cost/duration aggregation
- Container lifecycle (start once, stop once)
- Run results saved correctly

### Level 5: Integration Tests (~5 tests)

Test full pipeline with real YAML files (no Docker):
- Load built-in dev component → validate all tasks
- Load built-in qa component → validate task
- CLI `dkmv run` with mocked execution

### Level 6: E2E Tests (~2 tests)

Test with Docker (marked `@pytest.mark.e2e`):
- `dkmv run dev` with real container + mock Claude
- Verify inputs copied, outputs collected, git operations work

**Test file structure:**
```
tests/
  unit/
    test_task_models.py
    test_task_loader.py
    test_task_runner.py
    test_component_runner.py
    test_discovery.py
    test_builtins.py
  integration/
    test_run_e2e.py
```

**Estimated total: ~90 new tests.** Combined with existing 268 tests = ~358 tests.

---

## 9. Migration Plan

### Phase A: Coexistence (This PRD)

Both systems exist:
- Old: `dkmv dev`, `dkmv qa`, `dkmv judge`, `dkmv docs` → Python `BaseComponent` subclasses
- New: `dkmv run dev`, `dkmv run qa`, etc. → YAML task files via `ComponentRunner`
- CLI wrappers make old commands use the new system internally
- All existing tests continue to pass
- The existing component registry (`dkmv/components/__init__.py` — `register_component()`, `get_component()`) is retained for the Python-based component system. The new `resolve_component()` in `dkmv/tasks/discovery.py` handles task-based component discovery. Both coexist independently.

### Phase B: Deprecation (Future, post-v1)

- Mark `dkmv dev/qa/judge/docs` CLI commands as deprecated (show notice)
- Direct users to `dkmv run dev/qa/judge/docs`
- Keep Python component code but stop maintaining it

### Phase C: Removal (v2)

- Remove `dkmv/components/` directory entirely
- Remove `dkmv dev/qa/judge/docs` commands
- Only `dkmv run` exists
- Task YAML files are the sole way to define components

**For this PRD (v1), we implement Phase A only.** The old system continues to work. The new system is additive.

---

## 10. Open Questions

### Q1: Branch Derivation

The dev component derives the branch name (`feature/{feature_name}-dev`) in `pre_workspace_setup()`. Should the task system support a `branch_template` field?

**Recommendation:** No. Keep it simple. The `--branch` CLI flag is explicit. If not provided, use the branch from the repo or create one with a standard convention (`feature/{feature_name}`) at the ComponentRunner level. Component-specific branch naming belongs in documentation, not schema.

### Q2: PR Creation

The docs component creates a PR in `post_teardown()`. In the task system, this is handled by the prompt instructing Claude to run `gh pr create`. Is this reliable enough?

**Recommendation:** Yes, for v1. Claude has shell access and `gh` is installed in the container. The prompt can include the exact command. If this proves unreliable, a future `post_run` section could support declarative post-run actions.

### Q3: Result Parsing

Current components parse structured results from container files (qa_report.json → QAResult, verdict.json → JudgeResult). Should the task system support typed result parsing?

**Recommendation:** For v1, results are generic (`TaskResult` with `outputs` dict). The CLI wrapper commands (`dkmv qa`, `dkmv judge`) can parse the saved output files into typed results for display. The generic `dkmv run` command shows raw results.

### Q4: PRD Stripping

The dev component strips `## Evaluation Criteria` from the PRD. The task system uses prompt instructions to tell Claude to ignore that section. Is this sufficient?

**Recommendation:** Yes, for v1. Prompt-based instruction is simpler and more transparent. If Claude consistently fails to ignore the section, a future `transform` field on file inputs could support built-in transforms.

### Q5: Prompt Template Loading

Current components load prompt templates via `importlib.resources.files()`. Should task YAML files support the same mechanism for prompt files referenced via `prompt_file`?

**Recommendation:** `prompt_file` is resolved relative to the task YAML file. For built-in components, the task YAML and prompt files are co-located in the same package directory, so `importlib.resources` handles both transparently.

---

## 11. Evaluation Criteria

### Functional

- [ ] `TaskLoader` correctly loads and validates all 5 built-in task YAML files
- [ ] `TaskRunner` injects file, text, and env inputs into a container
- [ ] `TaskRunner` writes instructions to `.claude/CLAUDE.md`
- [ ] `TaskRunner` streams Claude Code with correct parameters (respects execution parameter cascade: task YAML > CLI > global)
- [ ] `TaskRunner` collects outputs, validates required, saves to host
- [ ] `TaskRunner` performs git commit and push with correct behavior
- [ ] `ComponentRunner` runs tasks in order within a shared container
- [ ] `ComponentRunner` propagates variables between tasks
- [ ] `ComponentRunner` fails fast on task failure
- [ ] `dkmv run dev --repo ... --var prd_path=...` works end-to-end
- [ ] `dkmv dev --repo ... --prd ...` continues to work (backward compat)
- [ ] Missing required variables produce clear, actionable error messages
- [ ] Missing required outputs produce clear, actionable error messages

### Quality

- [ ] All tests pass: `uv run pytest tests/ -v --cov --cov-fail-under=80`
- [ ] Linting clean: `uv run ruff check .`
- [ ] Formatting clean: `uv run ruff format --check .`
- [ ] Type checking clean: `uv run mypy dkmv/`
- [ ] No regressions in existing tests
- [ ] Coverage >= 80%

### Usability

- [ ] A non-developer can create a new component by writing YAML + markdown only
- [ ] `dkmv run --help` provides clear documentation of all options
- [ ] Error messages for invalid YAML include the file path and line number
- [ ] Error messages for missing variables include the variable name and which task references it
- [ ] The built-in task YAML files serve as clear examples for custom components

---

## Appendix: File Structure

```
dkmv/
  tasks/
    __init__.py
    models.py          # TaskInput, TaskOutput, TaskDefinition, TaskResult, ComponentResult
    loader.py          # TaskLoader — Jinja2 + YAML + Pydantic pipeline
    runner.py          # TaskRunner — single task execution
    component.py       # ComponentRunner — task sequence orchestration
    discovery.py       # resolve_component() — find component directories
  builtins/            # Built-in YAML component definitions (separate from task engine)
    dev/
      01-plan.yaml
      02-implement.yaml
    qa/
      01-evaluate.yaml
    judge/
      01-verdict.yaml
    docs/
      01-generate.yaml
  components/          # (existing Python components, kept for backward compat in v1)
    ...
  cli.py               # Add `dkmv run` command + update wrappers
  ...

tests/
  unit/
    test_task_models.py
    test_task_loader.py
    test_task_runner.py
    test_component_runner.py
    test_discovery.py
    test_builtins.py
  integration/
    test_run_e2e.py
```
