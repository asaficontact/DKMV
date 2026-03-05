# Phase 3: ComponentRunner and CLI

## Prerequisites

- Phase 1 complete (Task Model, Loader, Discovery)
- Phase 2 complete (TaskRunner executes single tasks)
- `TaskRunner.run()` works with mocked containers
- Execution parameter cascade tested and working

## Infrastructure Updates Required

Before Phase 3 tasks begin, the following changes to existing core modules are needed.

### IU-4: Relax `ComponentName` type to `str`

**File:** `dkmv/core/models.py`

Currently `ComponentName = Literal["dev", "qa", "judge", "docs"]`. This prevents custom YAML components (e.g., `dkmv run ./my-fullstack-component`) from creating runs or saving results, since `BaseResult.component`, `RunSummary.component`, and `RunManager.start_run()` all use this restricted type.

**Change:** Replace the Literal alias with `str`:
```python
# Before:
ComponentName = Literal["dev", "qa", "judge", "docs"]

# After:
ComponentName = str  # Any component name — built-in or custom YAML
```

All existing code that passes `"dev"`, `"qa"`, etc. still works since `str` is a superset. Validation (if needed) moves to the application layer.

**Impact:** `BaseResult.component`, `RunSummary.component`, `RunDetail.component` all accept any string. `RunManager.start_run()` and `list_runs(component=...)` accept any string.

**Tests:** Existing tests pass unchanged (literals are valid strings). Add 1 test to `tests/unit/test_runner.py`:
- `test_start_run_custom_component_name` — verify `start_run("my-custom", config)` works

### IU-5: Adapt `RunManager.start_run()` for task system

**File:** `dkmv/core/runner.py`

Currently `start_run(component: ComponentName, config: BaseComponentConfig)` requires a `BaseComponentConfig`. The task system's ComponentRunner doesn't naturally produce a `BaseComponentConfig`. Rather than adding a new method, the ComponentRunner will construct a `BaseComponentConfig` shim from its parameters:

```python
# In ComponentRunner.run(), before calling start_run:
base_config = BaseComponentConfig(
    repo=repo,
    branch=branch or "",
    feature_name=feature_name,
    model=cli_overrides.model or config.default_model,
    max_turns=cli_overrides.max_turns or config.default_max_turns,
    timeout_minutes=cli_overrides.timeout_minutes or config.timeout_minutes,
    max_budget_usd=cli_overrides.max_budget_usd or config.max_budget_usd,
    keep_alive=keep_alive,
    verbose=verbose,
)
run_id = self._run_manager.start_run(component_dir.name, base_config)
```

This approach reuses the existing interface without modification. The `BaseComponentConfig` captures the run's configuration snapshot for debugging.

**Tests:** No new RunManager tests needed — the shim is tested as part of ComponentRunner tests (T131).

## Phase Goal

A component (directory of task YAML files) can be orchestrated end-to-end: container started, workspace set up, tasks executed in order within a shared container, variables propagated between tasks, and results aggregated. The `dkmv run` CLI command exposes this to users.

## Phase Evaluation Criteria

- `ComponentRunner.run()` executes multi-task components in mocked containers
- Tasks execute in filename order (01-plan before 02-implement)
- All tasks share the same container
- Fail-fast: first failed task stops pipeline, remaining marked "skipped"
- Variables from previous tasks accessible in later tasks
- Cost/duration aggregated across tasks
- `dkmv run ./local-component --repo ... --var key=value` works
- `dkmv run --help` shows all options correctly
- `uv run pytest tests/unit/test_component_runner.py tests/unit/test_cli_run.py -v` all pass
- All quality gates green (ruff, mypy)

---

## Tasks

### T126: Create ComponentRunner Class Skeleton

**PRD Reference:** Section 6.4 (ComponentRunner)
**Depends on:** T117 (TaskRunner), T108 (TaskLoader)
**Blocks:** T127, T128, T129, T130, T132
**User Stories:** N/A (infrastructure)

#### Description

Create the `ComponentRunner` class with constructor and `run()` method signature. Ensure `ComponentName` type has been relaxed to `str` (IU-4) before this task.

#### Acceptance Criteria

- [ ] Infrastructure Update IU-4 applied (`ComponentName = str`)
- [ ] `ComponentRunner` class with constructor accepting: `SandboxManager`, `RunManager`, `TaskLoader`, `TaskRunner`, `StreamParser`, `Console`
- [ ] `async def run(component_dir, repo, branch, feature_name, variables, config, cli_overrides, keep_alive, verbose) -> ComponentResult` signature
- [ ] Method stubs for lifecycle steps

#### Files to Create/Modify

- `dkmv/core/models.py` — (modify) Relax `ComponentName` to `str` (IU-4)
- `dkmv/tasks/component.py` — (create) ComponentRunner class

#### Implementation Notes

From PRD Section 6.4, updated with `CLIOverrides` and `StreamParser`:
```python
class ComponentRunner:
    def __init__(
        self,
        sandbox: SandboxManager,
        run_manager: RunManager,
        task_loader: TaskLoader,
        task_runner: TaskRunner,
        stream_parser: StreamParser,
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
        cli_overrides: CLIOverrides,
        keep_alive: bool = False,
        verbose: bool = False,
    ) -> ComponentResult:
```

The `cli_overrides` parameter is passed through to `TaskRunner.run()` for each task. The `variables` dict carries Jinja2 template variables only (no execution parameter overrides mixed in).

#### Evaluation Checklist

- [ ] Class importable from `dkmv.tasks.component`
- [ ] `ComponentName` relaxed to `str`
- [ ] Type check passes

---

### T127: Implement Container Lifecycle

**PRD Reference:** Section 6.4 Steps 2-4, 6-7
**Depends on:** T126
**Blocks:** T128, T131
**User Stories:** US-09, US-10
**Estimated scope:** 2 hours

#### Description

Implement the container lifecycle in ComponentRunner: create run, start container, set up workspace (git clone, branch checkout, `.dkmv/` directory, `.gitignore`), and stop container.

#### Acceptance Criteria

- [ ] Step 1: Load and validate task files from component directory via `TaskLoader.load_component()`
- [ ] Step 2: Create run via `RunManager.start_run(component_name, base_config)` — construct a `BaseComponentConfig` shim from run parameters (see IU-5)
- [ ] Step 3: Start container via `SandboxManager.start()` with config-derived `SandboxConfig`
- [ ] Step 3.5: Persist container name via `RunManager.save_container_name()` (for attach/stop)
- [ ] Step 4: Setup workspace:
  - `git clone {repo} .` inside container
  - `git checkout {branch}` or `git checkout -b {branch}` as appropriate
  - `mkdir -p .dkmv`
  - Add `.dkmv/` to `.gitignore` if not already present
  - `gh auth login --with-token` + `gh auth setup-git`
- [ ] Step 6: Stop container (unless `keep_alive=True`)
- [ ] Step 7: Return `ComponentResult`
- [ ] Container stopped even on error (try/finally)

#### Files to Create/Modify

- `dkmv/tasks/component.py` — (modify) Implement lifecycle

#### Implementation Notes

Workspace setup mirrors existing `BaseComponent._setup_base_workspace()` from `dkmv/components/base.py`. The key addition is creating `.dkmv/` directory and adding it to `.gitignore` — this was previously a per-component concern, now it's standardized in ComponentRunner.

**Run creation (IU-5):** Construct a `BaseComponentConfig` shim for `start_run()`:
```python
base_config = BaseComponentConfig(
    repo=repo,
    branch=branch or "",
    feature_name=feature_name,
    model=cli_overrides.model or config.default_model,
    max_turns=cli_overrides.max_turns or config.default_max_turns,
    timeout_minutes=cli_overrides.timeout_minutes or config.timeout_minutes,
    max_budget_usd=cli_overrides.max_budget_usd or config.max_budget_usd,
    keep_alive=keep_alive,
    verbose=verbose,
)
run_id = self._run_manager.start_run(component_dir.name, base_config)
```

**Workspace setup:**
```python
await sandbox.execute(session, f"git clone {repo} .")
if branch:
    # Try checkout existing, fall back to create new
    result = await sandbox.execute(session, f"git checkout {branch}")
    if result.exit_code != 0:
        await sandbox.execute(session, f"git checkout -b {branch}")
await sandbox.execute(session, "mkdir -p .dkmv")
await sandbox.execute(session, 'grep -qxF ".dkmv/" .gitignore 2>/dev/null || echo ".dkmv/" >> .gitignore')
```

#### Evaluation Checklist

- [ ] Container starts and stops correctly
- [ ] Workspace cloned and branch set up
- [ ] `.dkmv/` directory created
- [ ] `.gitignore` updated
- [ ] Container cleaned up on error
- [ ] Container kept alive when requested

---

### T128: Implement Task Sequencing with Fail-Fast

**PRD Reference:** Section 6.4 Step 5 ("For each task: execute via TaskRunner")
**Depends on:** T127
**Blocks:** T129, T131
**User Stories:** US-06, US-21
**Estimated scope:** 1 hour

#### Description

Implement the task execution loop: iterate over loaded tasks, execute each via TaskRunner, and implement fail-fast behavior.

#### Acceptance Criteria

- [ ] Tasks execute in the order returned by `TaskLoader.load_component()` (sorted by filename)
- [ ] Before each task, append a `task_start` separator event to `stream.jsonl` for debugging
- [ ] Each task executed via `TaskRunner.run(task, session, run_id, config, cli_overrides)`
- [ ] On task failure (status `failed` or `timed_out`):
  - Stop the pipeline immediately
  - Mark all remaining tasks as `skipped` in results
  - Set overall component status to `failed`
- [ ] On success of all tasks: set overall component status to `completed`
- [ ] All `TaskResult` objects collected in `ComponentResult.task_results`

#### Files to Create/Modify

- `dkmv/tasks/component.py` — (modify) Implement task loop

#### Implementation Notes

Before each task execution, write a separator event to `stream.jsonl` so multi-task component logs have clear task boundaries:

```python
task_results: list[TaskResult] = []
component_status = "completed"

for i, task in enumerate(tasks):
    # Mark task boundary in stream log
    self._run_manager.append_stream(run_id, {
        "type": "task_start",
        "task_name": task.name,
        "task_index": i,
        "total_tasks": len(tasks),
    })

    result = await self._task_runner.run(task, session, run_id, config, cli_overrides)
    task_results.append(result)

    if result.status in ("failed", "timed_out"):
        component_status = result.status
        # Mark remaining tasks as skipped
        for remaining_task in tasks[i + 1:]:
            task_results.append(TaskResult(
                task_name=remaining_task.name,
                status="skipped",
            ))
        break
```

#### Evaluation Checklist

- [ ] Tasks run in order
- [ ] Failure stops pipeline
- [ ] Remaining tasks marked as skipped
- [ ] All results collected

---

### T129: Implement Variable Propagation

**PRD Reference:** Section 6.4 ("Template variables available to tasks")
**Depends on:** T128
**Blocks:** T130, T131
**User Stories:** US-04
**Estimated scope:** 1 hour

#### Description

Implement the template variable propagation system: built-in variables, CLI variables, and previous task result variables.

#### Acceptance Criteria

- [ ] Built-in variables always available: `repo`, `branch`, `feature_name`, `component`, `model`, `run_id`
- [ ] `model` is the CLI-level default or global default (the default model for tasks that don't specify their own)
- [ ] CLI `--var` variables available: all key=value pairs from user
- [ ] Previous task variables: `tasks.<name>.status`, `tasks.<name>.cost`, `tasks.<name>.turns`
- [ ] Variables merged in correct precedence: CLI vars override built-ins, task vars additive
- [ ] Each task gets the cumulative variable set (including results from all preceding tasks)

#### Files to Create/Modify

- `dkmv/tasks/component.py` — (modify) Implement variable propagation

#### Implementation Notes

From PRD Section 6.4 template variables table. Note: `model` is included per the PRD as a built-in variable — it represents the CLI-level or global default model, not the task-specific model (which is resolved via the cascade at execution time):

```python
def _build_variables(
    self,
    cli_vars: dict[str, str],
    repo: str,
    branch: str,
    feature_name: str,
    component: str,
    run_id: str,
    cli_overrides: CLIOverrides,
    config: DKMVConfig,
    task_results: list[TaskResult],
) -> dict[str, str]:
    variables = {
        "repo": repo,
        "branch": branch,
        "feature_name": feature_name,
        "component": component,
        "model": cli_overrides.model or config.default_model,
        "run_id": run_id,
    }
    # CLI vars override built-ins
    variables.update(cli_vars)

    # Add previous task results as nested dict
    # Access via tasks.<name>.status, tasks.<name>.cost, tasks.<name>.turns
    tasks_dict: dict[str, dict[str, str]] = {}
    for result in task_results:
        tasks_dict[result.task_name] = {
            "status": result.status,
            "cost": str(result.total_cost_usd),
            "turns": str(result.num_turns),
        }
    variables["tasks"] = tasks_dict  # type: ignore[assignment]

    return variables
```

NOTE: The `tasks` variable is a nested dict, not a flat string. Jinja2 supports dot access on dicts: `{{ tasks.plan.status }}`.

#### Evaluation Checklist

- [ ] Built-in variables available in first task
- [ ] CLI variables available in all tasks
- [ ] Task results available in subsequent tasks
- [ ] `{{ tasks.plan.status }}` resolves to "completed"

---

### T130: Implement Cost/Duration Aggregation and Run Saving

**PRD Reference:** Section 6.4 (ComponentResult model)
**Depends on:** T129
**Blocks:** T131
**User Stories:** US-14, US-15, US-24

#### Description

Implement cost and duration aggregation across all tasks, and save the component run result via RunManager.

#### Acceptance Criteria

- [ ] `ComponentResult.total_cost_usd` = sum of all `TaskResult.total_cost_usd`
- [ ] `ComponentResult.duration_seconds` = total wall-clock time for the component
- [ ] Run result saved via `RunManager.save_result()` (compatible with existing `dkmv runs`/`dkmv show`)
- [ ] Task-level details available via run directory artifacts

#### Files to Create/Modify

- `dkmv/tasks/component.py` — (modify) Implement aggregation + saving

#### Implementation Notes

The ComponentResult must be compatible with the existing `dkmv runs` and `dkmv show` commands. These read `result.json` from run directories. The existing `BaseResult` model is what's saved.

**Approach:** Save a `BaseResult`-compatible `result.json` for `dkmv runs`/`dkmv show` compatibility. Additionally save `tasks_result.json` with the full `ComponentResult` including per-task details via `save_artifact()` (IU-2). Since `ComponentName` is now `str` (IU-4), `component_dir.name` works for any component — custom or built-in.

```python
# After all tasks complete
import time
total_cost = sum(r.total_cost_usd for r in task_results)
duration = time.monotonic() - start_time

component_result = ComponentResult(
    run_id=run_id,
    component=component_dir.name,
    status=component_status,
    repo=repo,
    branch=branch or "",
    feature_name=feature_name,
    total_cost_usd=total_cost,
    duration_seconds=duration,
    task_results=task_results,
)

# Save BaseResult-compatible result for dkmv runs/show
base_result = BaseResult(
    run_id=run_id,
    component=component_dir.name,  # str — works for any component (IU-4)
    status=component_status,
    repo=repo,
    branch=branch or "",
    feature_name=feature_name,
    total_cost_usd=total_cost,
    duration_seconds=duration,
    num_turns=sum(r.num_turns for r in task_results),
)
run_manager.save_result(run_id, base_result)

# Save full task-level details as separate artifact
run_manager.save_artifact(
    run_id, "tasks_result.json", component_result.model_dump_json(indent=2)
)
```

#### Evaluation Checklist

- [ ] Cost aggregated correctly
- [ ] Duration measured correctly
- [ ] Compatible with `dkmv runs` and `dkmv show`
- [ ] Task-level details preserved

---

### T131: Write ComponentRunner Tests

**PRD Reference:** Section 8 Level 4 (~15 tests)
**Depends on:** T126-T130
**Blocks:** Nothing
**User Stories:** N/A

#### Description

Write comprehensive tests for ComponentRunner with mocked TaskRunner.

#### Acceptance Criteria

- [ ] Test: multi-task execution in correct order (01 before 02)
- [ ] Test: single-task component works
- [ ] Test: fail-fast — task 1 fails, task 2 is skipped
- [ ] Test: fail-fast — timed_out task stops pipeline
- [ ] Test: all tasks succeed → component status "completed"
- [ ] Test: variable propagation — built-in vars available
- [ ] Test: variable propagation — CLI vars available
- [ ] Test: variable propagation — previous task results available
- [ ] Test: cost aggregation across tasks
- [ ] Test: duration measured correctly
- [ ] Test: container lifecycle — started once, stopped once
- [ ] Test: container kept alive when keep_alive=True
- [ ] Test: workspace setup (git clone, branch, .dkmv/, .gitignore)
- [ ] Test: run result saved via RunManager
- [ ] Test: empty component directory → error or empty result

#### Files to Create/Modify

- `tests/unit/test_component_runner.py` — (create)

#### Implementation Notes

Mock `TaskRunner.run()` to return configurable `TaskResult` objects. Mock `TaskLoader.load_component()` to return predefined `TaskDefinition` lists. Mock `SandboxManager` for container lifecycle. Use `tmp_path` for RunManager output directory.

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_component_runner.py -v` passes
- [ ] Lifecycle, sequencing, and error paths covered

---

### T132: Add `dkmv run` CLI Command

**PRD Reference:** Section 6.6 (CLI: dkmv run Command)
**Depends on:** T126
**Blocks:** T133, T134, T141
**User Stories:** US-09, US-10, US-12, US-14, US-15
**Estimated scope:** 2 hours

#### Description

Add the `dkmv run <component> [OPTIONS]` command to `dkmv/cli.py`.

#### Acceptance Criteria

- [ ] `dkmv run <component>` as positional argument
- [ ] `--repo TEXT` (required)
- [ ] `--branch TEXT` (optional)
- [ ] `--feature-name TEXT` (optional, defaults to component name if not provided)
- [ ] `--var KEY=VALUE` (repeatable)
- [ ] `--model TEXT` — "Default model for tasks that don't specify their own"
- [ ] `--max-turns INT` — "Default max turns for tasks that don't specify their own"
- [ ] `--timeout INT` — "Default timeout for tasks that don't specify their own"
- [ ] `--max-budget-usd FLOAT` — "Default budget for tasks that don't specify their own"
- [ ] `--keep-alive` flag
- [ ] `--verbose` flag
- [ ] Constructs `CLIOverrides(model=model, max_turns=max_turns, timeout_minutes=timeout, max_budget_usd=max_budget_usd)` — preserving `None` for unset flags (do NOT resolve to config defaults here)
- [ ] Calls `resolve_component()` then `ComponentRunner.run()` with `cli_overrides`
- [ ] `dkmv run --help` shows clear documentation

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) Add `run` command

#### Implementation Notes

Follow the existing CLI patterns from `dkmv/cli.py`. Use `Annotated[str, typer.Argument(...)]` for the component argument. Use `Annotated[list[str] | None, typer.Option(...)]` for `--var`.

**Critical:** Unlike existing commands that resolve `model or config.default_model` at the CLI layer, the `run` command must preserve `None` for unset flags. The cascade (task YAML > CLI > global) requires distinguishing "user set a value" from "no value set." The `CLIOverrides` dataclass carries these nullable values to the TaskRunner.

**Default for `--feature-name`:** When not provided, defaults to the component name (resolved from the component argument). This ensures `ComponentResult.feature_name` and `BaseResult.feature_name` always have a meaningful value.

```python
@app.command(name="run")
@async_command
async def run_component(  # avoid shadowing builtin 'run'
    component: Annotated[str, typer.Argument(help="Component name or path")],
    repo: Annotated[str, typer.Option("--repo", help="Repository URL")],
    branch: Annotated[str | None, typer.Option("--branch")] = None,
    feature_name: Annotated[str | None, typer.Option("--feature-name")] = None,
    var: Annotated[list[str] | None, typer.Option("--var", help="KEY=VALUE")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Default model for tasks that don't specify their own")] = None,
    max_turns: Annotated[int | None, typer.Option("--max-turns")] = None,
    timeout: Annotated[int | None, typer.Option("--timeout")] = None,
    max_budget_usd: Annotated[float | None, typer.Option("--max-budget-usd")] = None,
    keep_alive: Annotated[bool, typer.Option("--keep-alive")] = False,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
) -> None:
    from dkmv.tasks.component import ComponentRunner
    from dkmv.tasks.discovery import resolve_component
    from dkmv.tasks.models import CLIOverrides

    config = load_config()
    component_dir = resolve_component(component)
    variables = _parse_vars(var)

    cli_overrides = CLIOverrides(
        model=model,               # None if not set — cascade will use config default
        max_turns=max_turns,       # None if not set
        timeout_minutes=timeout,   # None if not set
        max_budget_usd=max_budget_usd,  # None if not set
    )

    # ... instantiate ComponentRunner and call .run(
    #     component_dir, repo, branch,
    #     feature_name=feature_name or component_dir.name,
    #     variables, config, cli_overrides, keep_alive, verbose
    # )
```

NOTE: The function is named `run_component` to avoid shadowing Python's `run` builtin, but registered as `name="run"` in Typer so the CLI command is `dkmv run`.

#### Evaluation Checklist

- [ ] `dkmv run --help` shows all options
- [ ] Positional component argument works
- [ ] `--var` accepts multiple values
- [ ] `CLIOverrides` preserves `None` for unset flags
- [ ] `feature_name` defaults to component name
- [ ] Help text clear for each option

---

### T133: Implement --var Parsing and Variable Mapping

**PRD Reference:** Section 6.6 (--var KEY=VALUE)
**Depends on:** T132
**Blocks:** T134
**User Stories:** US-11

#### Description

Implement the `--var KEY=VALUE` parsing logic that converts CLI arguments into the `variables` dict passed to ComponentRunner.

#### Acceptance Criteria

- [ ] `--var prd_path=./auth.md --var coverage=90` → `{"prd_path": "./auth.md", "coverage": "90"}`
- [ ] Invalid format (no `=`) → clear error message
- [ ] Empty value allowed: `--var flag=` → `{"flag": ""}`
- [ ] Duplicate keys: last wins

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) Implement var parsing in run command

#### Implementation Notes

```python
def _parse_vars(var_list: list[str] | None) -> dict[str, str]:
    if not var_list:
        return {}
    variables: dict[str, str] = {}
    for item in var_list:
        if "=" not in item:
            raise typer.BadParameter(f"Invalid --var format: '{item}'. Expected KEY=VALUE")
        key, _, value = item.partition("=")
        variables[key.strip()] = value.strip()
    return variables
```

#### Evaluation Checklist

- [ ] Multiple vars parsed correctly
- [ ] Invalid format produces clear error
- [ ] Empty values handled

---

### T134: Write CLI Run Command Tests

**PRD Reference:** Section 8 ("CLI integration tests")
**Depends on:** T132-T133
**Blocks:** Nothing
**User Stories:** N/A

#### Description

Write tests for the `dkmv run` CLI command using Typer's `CliRunner`.

#### Acceptance Criteria

- [ ] Test: `dkmv run --help` shows all options
- [ ] Test: `dkmv run ./path --repo https://...` invokes ComponentRunner
- [ ] Test: `--var key=value` parsed correctly
- [ ] Test: `--var` with invalid format → error
- [ ] Test: `--model`, `--max-turns`, `--timeout`, `--max-budget-usd` passed through
- [ ] Test: missing `--repo` → error
- [ ] Test: invalid component path → ComponentNotFoundError displayed
- [ ] Test: `--keep-alive` and `--verbose` flags pass through

#### Files to Create/Modify

- `tests/unit/test_cli_run.py` — (create)

#### Implementation Notes

Mock `ComponentRunner` and `resolve_component` at the import location in `dkmv.cli`. Use `CliRunner(app).invoke()` pattern from existing `tests/unit/test_cli.py`.

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_cli_run.py -v` passes
- [ ] Happy path and error paths covered

---

## Phase Completion Checklist

- [ ] All tasks T126-T134 completed
- [ ] Multi-task components execute in correct order
- [ ] Fail-fast stops pipeline on failure
- [ ] Variables propagate between tasks
- [ ] `dkmv run` CLI command works with local paths
- [ ] All tests passing
- [ ] Lint clean: `uv run ruff check .`
- [ ] Format clean: `uv run ruff format --check .`
- [ ] Type check clean: `uv run mypy dkmv/`
- [ ] No regressions: existing tests still pass
- [ ] Progress updated in tasks.md and progress.md
