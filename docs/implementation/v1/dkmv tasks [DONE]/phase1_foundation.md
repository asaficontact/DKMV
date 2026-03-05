# Phase 1: Foundation

## Prerequisites

- DKMV v1 codebase complete and tested (268+ tests, 93%+ coverage)
- Existing `dkmv/core/` infrastructure operational (SandboxManager, RunManager, StreamParser)
- `uv run dkmv --help` works, all existing commands functional
- All quality gates passing (ruff, mypy, pytest)

## Phase Goal

The task definition format is fully operational at the data layer: Pydantic models validate task YAML files, the loader parses Jinja2 templates into validated models, and component discovery finds both local directories and packaged built-ins. No execution yet — just parsing and validation.

## Phase Evaluation Criteria

- `TaskDefinition.model_validate(dict)` validates all 5 built-in task YAML examples
- `TaskLoader.load()` resolves templates and returns validated models
- `TaskLoader.load_component()` loads sorted task sequences from directories
- `resolve_component("dev")` finds the built-in dev directory
- `resolve_component("./local/path")` finds local directories
- Missing required variables produce `jinja2.UndefinedError` at load time
- Invalid YAML produces clear error messages with file paths
- `uv run pytest tests/unit/test_task_models.py tests/unit/test_task_loader.py tests/unit/test_discovery.py -v` all pass
- All new models validate correctly via Pydantic
- `uv run ruff check . && uv run mypy dkmv/` clean

---

## Tasks

### T100: Create Tasks Package

**PRD Reference:** Section 6 (all subsections use `dkmv/tasks/`)
**Depends on:** Nothing
**Blocks:** T102, T103, T105, T106, T113
**User Stories:** N/A (infrastructure)

#### Description

Create the `dkmv/tasks/` package directory with `__init__.py`. This will house the entire task engine: models, loader, runner, component runner, and discovery.

#### Acceptance Criteria

- [ ] `dkmv/tasks/__init__.py` exists with clean public API exports
- [ ] Package is importable: `from dkmv.tasks import TaskDefinition, TaskLoader`

#### Files to Create/Modify

- `dkmv/tasks/__init__.py` — (create) Package init with exports

#### Implementation Notes

Start with a minimal `__init__.py`. Add exports as modules are created. Final exports should include:
```python
from dkmv.tasks.models import TaskDefinition, TaskInput, TaskOutput, TaskResult, ComponentResult
from dkmv.tasks.loader import TaskLoader
from dkmv.tasks.discovery import resolve_component
```

#### Evaluation Checklist

- [ ] Package importable
- [ ] Type check passes

---

### T101: Add Runtime Dependencies

**PRD Reference:** Section 7 Phase 1 ("New dependencies: jinja2 and pyyaml")
**Depends on:** Nothing
**Blocks:** T108 (loader needs jinja2), T109 (loader needs pyyaml)
**User Stories:** N/A (infrastructure)

#### Description

Add `jinja2` and `pyyaml` to the runtime dependencies in `pyproject.toml`.

#### Acceptance Criteria

- [ ] `jinja2` in `[project.dependencies]`
- [ ] `pyyaml` in `[project.dependencies]`
- [ ] `uv sync` succeeds
- [ ] `python -c "import jinja2; import yaml"` works

#### Files to Create/Modify

- `pyproject.toml` — (modify) Add dependencies

#### Implementation Notes

Use reasonable version bounds: `jinja2>=3.1` and `pyyaml>=6.0`. Check that these don't conflict with existing dependencies.

#### Evaluation Checklist

- [ ] Dependencies install cleanly
- [ ] No version conflicts

---

### T102: Create TaskInput Model

**PRD Reference:** Section 6.1 (TaskInput class)
**Depends on:** T100
**Blocks:** T104, T107
**User Stories:** US-02, US-03
**Estimated scope:** 1 hour

#### Description

Create the `TaskInput` Pydantic model with type-specific field validation. The three input types (file, text, env) require different fields.

#### Acceptance Criteria

- [ ] `TaskInput` with fields: name, type, src, dest, content, key, value, optional
- [ ] `type: Literal["file", "text", "env"]`
- [ ] `@model_validator(mode="after")` validates type-specific fields:
  - `file` requires `src` and `dest`
  - `text` requires `content` and `dest`
  - `env` requires `key` and `value`
- [ ] `optional: bool = False`
- [ ] Modern type hints: `str | None = None`

#### Files to Create/Modify

- `dkmv/tasks/models.py` — (create) TaskInput model

#### Implementation Notes

From PRD Section 6.1:
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
        if self.type == "file" and (not self.src or not self.dest):
            raise ValueError("file input requires 'src' and 'dest'")
        if self.type == "text" and (not self.content or not self.dest):
            raise ValueError("text input requires 'content' and 'dest'")
        if self.type == "env" and (not self.key or not self.value):
            raise ValueError("env input requires 'key' and 'value'")
        return self
```

#### Evaluation Checklist

- [ ] Valid file/text/env inputs construct without error
- [ ] Missing required type-fields raise clear `ValidationError`
- [ ] `optional` defaults to False

---

### T103: Create TaskOutput Model

**PRD Reference:** Section 6.1 (TaskOutput class)
**Depends on:** T100
**Blocks:** T104, T107
**User Stories:** US-18

#### Description

Create the `TaskOutput` Pydantic model for declaring files to read from the container after Claude finishes.

#### Acceptance Criteria

- [ ] `TaskOutput` with fields: path, required, save
- [ ] `path: str` (required, absolute path inside container)
- [ ] `required: bool = False`
- [ ] `save: bool = True`

#### Files to Create/Modify

- `dkmv/tasks/models.py` — (modify) Add TaskOutput model

#### Implementation Notes

Simple model with defaults. From PRD Section 6.1:
```python
class TaskOutput(BaseModel):
    path: str
    required: bool = False
    save: bool = True
```

#### Evaluation Checklist

- [ ] Constructs with just `path`
- [ ] Defaults applied correctly

---

### T104: Create TaskDefinition Model

**PRD Reference:** Section 6.1 (TaskDefinition class)
**Depends on:** T102, T103
**Blocks:** T107, T108, T117
**User Stories:** US-01, US-07, US-22
**Estimated scope:** 2 hours

#### Description

Create the main `TaskDefinition` Pydantic model with all fields from the task YAML schema, plus mutual exclusivity validators for instructions and prompt.

#### Acceptance Criteria

- [ ] Identity fields: `name`, `description`, `commit`, `push`, `commit_message`
- [ ] Execution fields: `model`, `max_turns`, `timeout_minutes`, `max_budget_usd` — all `| None = None` for cascade
- [ ] Data fields: `inputs: list[TaskInput] = []`, `outputs: list[TaskOutput] = []`
- [ ] Instructions: `instructions: str | None = None`, `instructions_file: str | None = None`
- [ ] Prompt: `prompt: str | None = None`, `prompt_file: str | None = None`
- [ ] `@model_validator` enforces exactly one of instructions/instructions_file
- [ ] `@model_validator` enforces exactly one of prompt/prompt_file
- [ ] `commit: bool = True`, `push: bool = True` defaults

#### Files to Create/Modify

- `dkmv/tasks/models.py` — (modify) Add TaskDefinition model

#### Implementation Notes

From PRD Section 6.1. Key: execution fields use `None` defaults to enable the cascade (task YAML > CLI > global config). If a field is `None`, the runner checks CLI, then global.

```python
class TaskDefinition(BaseModel):
    # Identity
    name: str
    description: str = ""
    commit: bool = True
    push: bool = True
    commit_message: str | None = None

    # Execution — None enables cascade
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
```

XOR validators should produce clear error messages:
- "Exactly one of 'instructions' or 'instructions_file' must be set, got both"
- "Exactly one of 'instructions' or 'instructions_file' must be set, got neither"

#### Evaluation Checklist

- [ ] Valid minimal task (name + instructions + prompt) validates
- [ ] Valid full task (all fields) validates
- [ ] Both `prompt` and `prompt_file` → ValidationError
- [ ] Neither instructions nor instructions_file → ValidationError
- [ ] Execution fields default to None
- [ ] `commit` defaults to True

---

### T105: Create TaskResult Model

**PRD Reference:** Section 6.1 (TaskResult class)
**Depends on:** T100
**Blocks:** T106, T107, T117
**User Stories:** US-06

#### Description

Create the `TaskResult` model representing the outcome of a single task execution.

#### Acceptance Criteria

- [ ] `task_name: str`
- [ ] `status: Literal["completed", "failed", "timed_out", "skipped"]`
- [ ] `total_cost_usd: float = 0.0`
- [ ] `duration_seconds: float = 0.0`
- [ ] `num_turns: int = 0`
- [ ] `session_id: str = ""`
- [ ] `error_message: str = ""`
- [ ] `outputs: dict[str, str] = {}` (path → content for saved outputs)

#### Files to Create/Modify

- `dkmv/tasks/models.py` — (modify) Add TaskResult model

#### Implementation Notes

Note the four status values from PRD Section 6.1:
- `completed` — task finished successfully
- `failed` — task encountered an error or missing required output
- `timed_out` — task exceeded timeout
- `skipped` — task was not executed because a prior task failed (fail-fast)

#### Evaluation Checklist

- [ ] All status values accepted
- [ ] Defaults applied correctly
- [ ] JSON serialization works

---

### T106: Create ComponentResult Model

**PRD Reference:** Section 6.4 (ComponentResult class)
**Depends on:** T105
**Blocks:** T107, T126
**User Stories:** US-24

#### Description

Create the `ComponentResult` model representing the outcome of a full component run (all tasks).

#### Acceptance Criteria

- [ ] `run_id: str`
- [ ] `component: str`
- [ ] `status: Literal["completed", "failed", "timed_out"]`
- [ ] `repo: str`, `branch: str`, `feature_name: str`
- [ ] `total_cost_usd: float`, `duration_seconds: float`
- [ ] `task_results: list[TaskResult]`
- [ ] `error_message: str = ""`

#### Files to Create/Modify

- `dkmv/tasks/models.py` — (modify) Add ComponentResult model

#### Implementation Notes

`total_cost_usd` is aggregated from `task_results`. Consider a `@computed_field` or compute it in the runner. ComponentResult status does NOT include "skipped" (a component itself can't be skipped).

#### Evaluation Checklist

- [ ] Constructs with valid data
- [ ] JSON serialization works
- [ ] Status excludes "skipped"

---

### T107: Write Task Model Tests

**PRD Reference:** Section 8 Level 1 (~30 tests)
**Depends on:** T102-T106
**Blocks:** Nothing
**User Stories:** N/A

#### Description

Write comprehensive unit tests for all task models: valid cases, invalid cases, edge cases, and round-trip serialization.

#### Acceptance Criteria

- [ ] Valid complete TaskDefinition with all fields
- [ ] Valid minimal TaskDefinition (name + instructions + prompt only)
- [ ] Missing `name` → ValidationError
- [ ] Both `prompt` and `prompt_file` set → ValidationError
- [ ] Neither `prompt` nor `prompt_file` → ValidationError
- [ ] Same XOR tests for instructions/instructions_file
- [ ] TaskInput type validation:
  - file without src → error
  - text without content → error
  - env without key → error
- [ ] TaskInput valid for each type (file, text, env)
- [ ] TaskOutput defaults: required=False, save=True
- [ ] TaskResult with each status value
- [ ] ComponentResult JSON round-trip
- [ ] Empty inputs/outputs lists accepted
- [ ] Execution fields default to None

#### Files to Create/Modify

- `tests/unit/test_task_models.py` — (create)

#### Implementation Notes

Follow existing test patterns from `tests/unit/test_config.py`. Use parametrize for input type validation. Aim for ~30 tests.

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_task_models.py -v` passes
- [ ] Coverage of models.py > 90%

---

### T108: Create TaskLoader with Jinja2 Rendering

**PRD Reference:** Section 6.2 (TaskLoader class)
**Depends on:** T104, T101
**Blocks:** T109, T112
**User Stories:** US-04, US-05, US-16
**Estimated scope:** 2 hours

#### Description

Create the `TaskLoader` class with Jinja2 template rendering. The loader reads raw YAML text, renders Jinja2 templates with provided variables, then passes the result to YAML parsing.

#### Acceptance Criteria

- [ ] `TaskLoader` class with configurable Jinja2 environment
- [ ] Uses `jinja2.StrictUndefined` to catch missing required variables
- [ ] `load(task_path, variables)` renders templates before YAML parsing
- [ ] `{{ var | default('') }}` works for optional variables
- [ ] `{% if %}` and `{% for %}` control flow works
- [ ] Missing required variable → `jinja2.UndefinedError` with variable name

#### Files to Create/Modify

- `dkmv/tasks/loader.py` — (create) TaskLoader class

#### Implementation Notes

From PRD Section 6.2:
```python
class TaskLoader:
    def __init__(self, jinja_env: jinja2.Environment | None = None):
        self._jinja_env = jinja_env or jinja2.Environment(
            undefined=jinja2.StrictUndefined,
            keep_trailing_newline=True,
        )

    def load(self, task_path: Path, variables: dict[str, str]) -> TaskDefinition:
        raw = task_path.read_text()
        rendered = self._jinja_env.from_string(raw).render(variables)
        # Next step: YAML parse + validate (T109)
```

**Why Jinja2 before YAML?** Templates like `{{ prd_path }}` appear in YAML string values. Resolving them before YAML parsing means the YAML parser always sees valid values. This is the pattern used by Ansible, dbt, and Helm.

#### Evaluation Checklist

- [ ] Template variables resolve in all positions
- [ ] `StrictUndefined` catches typos
- [ ] Optional variables work with `| default()`

---

### T109: Implement YAML Parsing + Pydantic Validation

**PRD Reference:** Section 6.2 (Processing pipeline), Section 5.3
**Depends on:** T108
**Blocks:** T110, T112
**User Stories:** US-19
**Estimated scope:** 1 hour

#### Description

Complete the `TaskLoader.load()` pipeline: after Jinja2 rendering, parse the YAML string with `yaml.safe_load()`, then validate with `TaskDefinition.model_validate()`.

#### Acceptance Criteria

- [ ] `yaml.safe_load()` parses the rendered string
- [ ] `TaskDefinition.model_validate(dict)` validates the parsed dict
- [ ] Invalid YAML syntax → clear error with file path
- [ ] Pydantic validation errors → clear error with field name and file path
- [ ] Wraps errors in a `TaskLoadError` with context (file path, variable name, etc.)

#### Files to Create/Modify

- `dkmv/tasks/loader.py` — (modify) Complete load() pipeline

#### Implementation Notes

Pipeline from PRD Section 5.3:
```
raw YAML text → Jinja2 render → yaml.safe_load() → TaskDefinition.model_validate()
```

Define custom exceptions for clear error reporting:
```python
class TaskLoadError(Exception):
    def __init__(self, message: str, task_path: Path | None = None):
        self.task_path = task_path
        super().__init__(f"{task_path}: {message}" if task_path else message)
```

#### Evaluation Checklist

- [ ] Full pipeline works end-to-end
- [ ] Error messages include file path
- [ ] Invalid YAML handled gracefully

---

### T110: Implement prompt_file / instructions_file Resolution

**PRD Reference:** Section 6.2 ("prompt_file and instructions_file paths are resolved relative to the task YAML file's directory")
**Depends on:** T109
**Blocks:** T111, T112
**User Stories:** US-08

#### Description

After Pydantic validation, resolve `prompt_file` and `instructions_file` references: read the file content and populate the corresponding `prompt` / `instructions` field.

#### Acceptance Criteria

- [ ] `prompt_file` path resolved relative to task YAML file's directory
- [ ] File content read and stored in `prompt` field (replacing `prompt_file`)
- [ ] Same for `instructions_file` → `instructions`
- [ ] File content also supports Jinja2 templates (rendered with same variables)
- [ ] Missing file → `TaskLoadError` with path info

#### Files to Create/Modify

- `dkmv/tasks/loader.py` — (modify) Add file resolution after validation

#### Implementation Notes

From PRD Section 6.2: "Prompt/instructions file contents are read and inlined into the TaskDefinition (the prompt/instructions field is populated). The _file variant is a convenience for authoring — by load time, the model always has the resolved content."

Resolution order:
1. Validate model (XOR check passes — either inline or file)
2. If `prompt_file` is set, resolve path relative to task file, read content, render Jinja2, set `prompt`, clear `prompt_file`
3. Same for `instructions_file`

#### Evaluation Checklist

- [ ] Relative path resolution works
- [ ] File content inlined into model
- [ ] Jinja2 in file content resolved
- [ ] Missing file produces clear error

---

### T111: Implement load_component()

**PRD Reference:** Section 6.2 (load_component method)
**Depends on:** T110
**Blocks:** T112
**User Stories:** US-06

#### Description

Implement `TaskLoader.load_component()` that loads all task YAML files from a component directory, sorted by filename.

#### Acceptance Criteria

- [ ] Scans directory for `*.yaml` and `*.yml` files
- [ ] Sorts by filename (lexicographic — `01-plan.yaml` before `02-implement.yaml`)
- [ ] Calls `load()` for each file with the same variables
- [ ] Returns `list[TaskDefinition]`
- [ ] Empty directory → empty list (or error — decide based on usage)

#### Files to Create/Modify

- `dkmv/tasks/loader.py` — (modify) Add load_component()

#### Implementation Notes

```python
def load_component(self, component_dir: Path, variables: dict[str, str]) -> list[TaskDefinition]:
    yaml_files = sorted(
        p for p in component_dir.iterdir()
        if p.suffix in (".yaml", ".yml") and p.is_file()
    )
    return [self.load(f, variables) for f in yaml_files]
```

Consider whether to look for a `tasks/` subdirectory or scan the component directory directly. The PRD examples show both patterns — task_definition.md shows `component/tasks/01-plan.yaml` while the built-in examples show `dkmv/builtins/dev/01-plan.yaml` (no `tasks/` subdirectory). For built-ins, scan the directory directly. For local components, support both patterns: check for `tasks/` subdirectory first, fall back to root.

#### Evaluation Checklist

- [ ] Files sorted correctly
- [ ] All tasks loaded with same variables
- [ ] Empty directory handled

---

### T112: Write TaskLoader Tests

**PRD Reference:** Section 8 Level 2 (~20 tests)
**Depends on:** T108-T111
**Blocks:** Nothing
**User Stories:** N/A

#### Description

Write comprehensive tests for the TaskLoader: template resolution, file references, error cases, component loading.

#### Acceptance Criteria

- [ ] Template variable resolution (simple `{{ var }}`, nested)
- [ ] Missing required variable → `UndefinedError`
- [ ] `{{ var | default('') }}` for optional variables
- [ ] `{% if %}` / `{% for %}` control flow in prompts
- [ ] `prompt_file` resolution (relative path, content inlined)
- [ ] `instructions_file` resolution
- [ ] Invalid YAML after template resolution → error with file path
- [ ] Invalid Pydantic after YAML parse → error with field info
- [ ] `load_component()` returns sorted list
- [ ] `load_component()` with empty directory
- [ ] All tests use `tmp_path` for file I/O

#### Files to Create/Modify

- `tests/unit/test_task_loader.py` — (create)

#### Implementation Notes

Create fixture YAML files in `tmp_path` for each test. Use the example task YAML from `docs/core/dkmv_tasks/v1/example_task.yaml` as a reference for valid complete task.

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_task_loader.py -v` passes
- [ ] Good coverage of error paths

---

### T113: Create Discovery Module

**PRD Reference:** Section 6.5 (Component Discovery)
**Depends on:** T100
**Blocks:** T114, T115, T116
**User Stories:** US-09, US-10

#### Description

Create the `dkmv/tasks/discovery.py` module with the `resolve_component()` function skeleton.

#### Acceptance Criteria

- [ ] `resolve_component(name_or_path: str) -> Path` function
- [ ] `ComponentNotFoundError` exception class
- [ ] Clear resolution order documented in code

#### Files to Create/Modify

- `dkmv/tasks/discovery.py` — (create)

#### Implementation Notes

From PRD Section 6.5:
```python
def resolve_component(name_or_path: str) -> Path:
    """Resolve a component name or path to a directory containing task YAML files.

    Resolution order:
    1. If it's a path (contains / or .), resolve and validate
    2. If it matches a built-in name, use packaged files
    3. Raise ComponentNotFoundError
    """
```

#### Evaluation Checklist

- [ ] Function importable
- [ ] Type check passes

---

### T114: Implement Explicit Path Resolution

**PRD Reference:** Section 6.5 ("Explicit path — dkmv run ./my-component or dkmv run /absolute/path")
**Depends on:** T113
**Blocks:** T116
**User Stories:** US-10

#### Description

Implement resolution for explicit paths (relative or absolute) in `resolve_component()`.

#### Acceptance Criteria

- [ ] `./my-component` resolves to absolute path
- [ ] `/absolute/path` used directly
- [ ] Validates directory exists
- [ ] Validates directory contains at least one `.yaml` or `.yml` file
- [ ] Clear error if directory doesn't exist or has no YAML files

#### Files to Create/Modify

- `dkmv/tasks/discovery.py` — (modify) Implement path resolution

#### Implementation Notes

Detection heuristic: if `name_or_path` contains `/` or `.`, treat as a path. Otherwise, try built-in lookup.

```python
if "/" in name_or_path or name_or_path.startswith("."):
    path = Path(name_or_path).resolve()
    if not path.is_dir():
        raise ComponentNotFoundError(f"Directory not found: {path}")
    yaml_files = list(path.glob("*.yaml")) + list(path.glob("*.yml"))
    if not yaml_files:
        raise ComponentNotFoundError(f"No task YAML files in: {path}")
    return path
```

#### Evaluation Checklist

- [ ] Relative paths resolve correctly
- [ ] Absolute paths work
- [ ] Missing directory → clear error
- [ ] Empty directory → clear error

---

### T115: Implement Built-in Name Resolution

**PRD Reference:** Section 6.5 ("Built-in — dkmv run dev resolves to dkmv/builtins/dev/")
**Depends on:** T113
**Blocks:** T116
**User Stories:** US-09

#### Description

Implement resolution for built-in component names using `importlib.resources`.

#### Acceptance Criteria

- [ ] `resolve_component("dev")` → path to `dkmv/builtins/dev/`
- [ ] Same for "qa", "judge", "docs"
- [ ] Unknown name → `ComponentNotFoundError` with helpful message listing available built-ins
- [ ] Uses `importlib.resources.files("dkmv.builtins")` for package access

#### Files to Create/Modify

- `dkmv/tasks/discovery.py` — (modify) Implement built-in resolution

#### Implementation Notes

```python
from importlib.resources import files

BUILTIN_COMPONENTS = {"dev", "qa", "judge", "docs"}

def _resolve_builtin(name: str) -> Path:
    if name not in BUILTIN_COMPONENTS:
        available = ", ".join(sorted(BUILTIN_COMPONENTS))
        raise ComponentNotFoundError(
            f"Unknown component '{name}'. Available built-ins: {available}"
        )
    resource = files("dkmv.builtins").joinpath(name)
    # importlib.resources may return a Traversable — need actual path
    with as_file(resource) as path:
        return path
```

NOTE: `importlib.resources.as_file()` is needed for proper extraction from wheel/zip archives. For development installs, `files()` returns a direct `Path`. Test both modes.

This depends on `dkmv/builtins/` existing with task YAML files — for Phase 1 testing, the built-in resolution should work with test fixtures. The actual built-in YAMLs are created in Phase 4 (T135-T139).

#### Evaluation Checklist

- [ ] Known names resolve correctly
- [ ] Unknown names produce helpful error with available list
- [ ] Works in both development and installed modes

---

### T116: Write Discovery Tests

**PRD Reference:** Section 8 ("discovery tests")
**Depends on:** T113-T115
**Blocks:** Nothing
**User Stories:** N/A

#### Description

Write unit tests for component discovery: explicit paths, built-in names, error cases.

#### Acceptance Criteria

- [ ] Test: explicit relative path resolves
- [ ] Test: explicit absolute path resolves
- [ ] Test: path with no YAML files → error
- [ ] Test: non-existent path → error
- [ ] Test: built-in "dev" resolves (mock or fixture)
- [ ] Test: unknown name → ComponentNotFoundError with available list
- [ ] Test: path detection heuristic (contains "/" or ".")
- [ ] All tests use `tmp_path`

#### Files to Create/Modify

- `tests/unit/test_discovery.py` — (create)

#### Implementation Notes

For built-in tests in Phase 1, create temporary fixtures that mimic the built-in structure. Phase 4 will add real built-in YAMLs. Alternatively, mock `importlib.resources.files()`.

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_discovery.py -v` passes
- [ ] Both success and error paths covered

---

## Phase Completion Checklist

- [ ] All tasks T100-T116 completed
- [ ] `TaskDefinition` validates all example YAML structures
- [ ] `TaskLoader` resolves templates and returns validated models
- [ ] `resolve_component()` finds local and built-in components
- [ ] All tests passing: `uv run pytest tests/unit/test_task_models.py tests/unit/test_task_loader.py tests/unit/test_discovery.py -v`
- [ ] Lint clean: `uv run ruff check .`
- [ ] Format clean: `uv run ruff format --check .`
- [ ] Type check clean: `uv run mypy dkmv/`
- [ ] No regressions: existing tests still pass
- [ ] Progress updated in tasks.md and progress.md
