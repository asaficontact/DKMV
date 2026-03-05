# Phase 2: TaskRunner

## Prerequisites

- Phase 1 complete (Task Model, Loader, Discovery all working)
- `TaskDefinition` validates correctly from YAML files
- `TaskLoader.load()` resolves templates and returns validated models
- Existing `SandboxManager`, `RunManager`, `StreamParser` operational

## Infrastructure Updates Required

Before Phase 2 tasks begin, the following changes to existing core modules are needed. These are small, targeted additions — not new files.

### IU-1: Extend `SandboxManager.stream_claude()` with `env_vars` parameter

**File:** `dkmv/core/sandbox.py`

The current `stream_claude()` method has no way to pass per-invocation environment variables. Task inputs with `type: env` need env vars injected into the Claude process.

```python
async def stream_claude(
    self,
    session: SandboxSession,
    prompt: str,
    model: str,
    max_turns: int,
    timeout_minutes: int,
    max_budget_usd: float | None = None,
    working_dir: str = "/home/dkmv/workspace",
    env_vars: dict[str, str] | None = None,  # NEW
) -> AsyncIterator[dict[str, Any]]:
```

In the command construction, prepend env vars using Unix `env` syntax:
```python
env_prefix = ""
if env_vars:
    pairs = " ".join(f"{k}={shlex.quote(v)}" for k, v in env_vars.items())
    env_prefix = f"env {pairs} "
cmd = f"{env_prefix}claude -p ..."
```

**Tests:** Add 1-2 tests to `tests/unit/test_sandbox.py`:
- `test_stream_claude_with_env_vars` — verify env prefix in command
- `test_stream_claude_without_env_vars` — existing behavior unchanged

### IU-2: Add `save_artifact()` to `RunManager`

**File:** `dkmv/core/runner.py`

```python
def save_artifact(self, run_id: str, filename: str, content: str) -> None:
    """Save a named artifact file to the run directory."""
    (self._run_dir(run_id) / filename).write_text(content)
```

**Tests:** Add 1 test to `tests/unit/test_runner.py`:
- `test_save_artifact` — writes file, verify content

### IU-3: Add `save_task_prompt()` to `RunManager`

**File:** `dkmv/core/runner.py`

Multi-task components execute multiple tasks, each with its own prompt. The existing `save_prompt()` writes to `prompt.md` and would be overwritten by each subsequent task. Add a per-task variant:

```python
def save_task_prompt(self, run_id: str, task_name: str, prompt: str) -> None:
    """Save a task-specific prompt to the run directory."""
    (self._run_dir(run_id) / f"prompt_{task_name}.md").write_text(prompt)
```

**Tests:** Add 1 test to `tests/unit/test_runner.py`:
- `test_save_task_prompt` — verify filename pattern `prompt_{name}.md`

## Phase Goal

A single task can be executed inside a running container: inputs injected, instructions written, Claude Code streamed with correct parameters (respecting the execution parameter cascade), outputs collected and validated, and git operations performed. Error handling covers all failure modes.

## Phase Evaluation Criteria

- `TaskRunner.run()` executes a valid task inside a mocked container
- File inputs copied from host to container correctly
- Text inputs written to container correctly
- Env inputs passed to Claude invocation correctly
- Instructions written to `.claude/CLAUDE.md`
- Claude Code invoked with cascade-resolved model, max_turns, timeout, budget
- Required outputs validated (present → success, missing → failure)
- Git force-add of declared outputs before commit
- Error handling: missing required input → fail before Claude, missing required output → fail after Claude
- `uv run pytest tests/unit/test_task_runner.py -v` all pass
- All quality gates green (ruff, mypy)

---

## Tasks

### T117: Create TaskRunner Class Skeleton

**PRD Reference:** Section 6.3 (TaskRunner)
**Depends on:** T104 (TaskDefinition model)
**Blocks:** T118, T119, T120, T121, T122, T123, T124
**User Stories:** N/A (infrastructure)

#### Description

Create the `TaskRunner` class with constructor and `run()` method signature. Also define the `CLIOverrides` dataclass that carries CLI-level execution parameter overrides for the cascade.

#### Acceptance Criteria

- [ ] `CLIOverrides` dataclass in `dkmv/tasks/models.py` with: `model`, `max_turns`, `timeout_minutes`, `max_budget_usd` — all `| None = None`
- [ ] `TaskRunner` class with constructor accepting `SandboxManager`, `RunManager`, `StreamParser`, `Console`
- [ ] `async def run(task, session, run_id, config, cli_overrides, task_name_for_prompt) -> TaskResult` signature
- [ ] Method stubs for each step (to be implemented in T118-T123)

#### Files to Create/Modify

- `dkmv/tasks/models.py` — (modify) Add `CLIOverrides` dataclass
- `dkmv/tasks/runner.py` — (create) TaskRunner class

#### Implementation Notes

The `CLIOverrides` dataclass carries values from CLI flags (`--model`, `--max-turns`, etc.) that serve as the middle tier of the execution parameter cascade (task YAML > CLI > global config). A `None` value means "not set by user, fall through to global config."

```python
from dataclasses import dataclass

@dataclass
class CLIOverrides:
    """CLI-level execution parameter overrides for the cascade.

    These are the middle tier: task YAML > CLI > global config.
    None means 'not set by user' — fall through to DKMVConfig defaults.
    """
    model: str | None = None
    max_turns: int | None = None
    timeout_minutes: int | None = None
    max_budget_usd: float | None = None
```

The TaskRunner receives `CLIOverrides` as a dedicated parameter, keeping it separate from template `variables` and `DKMVConfig`:

```python
class TaskRunner:
    def __init__(
        self,
        sandbox: SandboxManager,
        run_manager: RunManager,
        stream_parser: StreamParser,
        console: Console,
    ):
        self._sandbox = sandbox
        self._run_manager = run_manager
        self._stream_parser = stream_parser
        self._console = console

    async def run(
        self,
        task: TaskDefinition,
        session: SandboxSession,
        run_id: str,
        config: DKMVConfig,
        cli_overrides: CLIOverrides,
    ) -> TaskResult:
        """Execute a single task in the container.
        Steps: inject inputs, write instructions, stream Claude, collect outputs, git teardown.
        """
```

Note: `StreamParser` is added as a constructor dependency (matching `BaseComponent`'s pattern) since the TaskRunner needs to parse and render stream events.

#### Evaluation Checklist

- [ ] `CLIOverrides` importable from `dkmv.tasks.models`
- [ ] Class importable from `dkmv.tasks.runner`
- [ ] Type check passes
- [ ] Method signature includes `cli_overrides: CLIOverrides`

---

### T118: Implement Input Injection

**PRD Reference:** Section 6.3 Step 1 ("Inject inputs")
**Depends on:** T117
**Blocks:** T124, T125
**User Stories:** US-02, US-03, US-17
**Estimated scope:** 2 hours

#### Description

Implement Step 1 of TaskRunner: inject all inputs into the running container based on their type.

#### Acceptance Criteria

- [ ] `type: file` → Read `src` from host, call `sandbox.write_file(session, dest, content)`. If `src` is a directory, iterate and copy each file recursively.
- [ ] `type: text` → Call `sandbox.write_file(session, dest, content)`.
- [ ] `type: env` → Collect env vars into a dict for passing to `stream_claude(env_vars=...)` (see Infrastructure Update IU-1).
- [ ] `optional: true` + missing source → skip silently, log at debug level.
- [ ] `optional: false` + missing source → raise `FileNotFoundError` with clear message including the input name and expected path.
- [ ] Inputs processed before Claude invocation (fail-fast).

#### Files to Create/Modify

- `dkmv/tasks/runner.py` — (modify) Implement input injection

#### Implementation Notes

For file inputs, `src` is a path on the host machine. Read the file locally, then write it into the container via `sandbox.write_file()`. For directory `src`, recursively enumerate files and write each one.

```python
async def _inject_inputs(self, task: TaskDefinition, session: SandboxSession) -> dict[str, str]:
    env_vars: dict[str, str] = {}
    for inp in task.inputs:
        if inp.type == "file":
            src_path = Path(inp.src)
            if not src_path.exists():
                if inp.optional:
                    continue
                raise FileNotFoundError(f"Input '{inp.name}': source not found: {inp.src}")
            if src_path.is_dir():
                for file in src_path.rglob("*"):
                    if file.is_file():
                        rel = file.relative_to(src_path)
                        dest = f"{inp.dest}/{rel}"
                        await self._sandbox.write_file(session, dest, file.read_text())
            else:
                await self._sandbox.write_file(session, inp.dest, src_path.read_text())
        elif inp.type == "text":
            await self._sandbox.write_file(session, inp.dest, inp.content)
        elif inp.type == "env":
            env_vars[inp.key] = inp.value
    return env_vars
```

NOTE: Binary files (images, compiled assets) need special handling — `read_text()` will fail. For v1, document that file inputs must be text-based. Consider `read_bytes()` + base64 for v2.

#### Evaluation Checklist

- [ ] File input: host file → container file
- [ ] File input: host directory → container directory (recursive)
- [ ] Text input: content → container file
- [ ] Env input: collected for Claude invocation
- [ ] Optional missing → skip silently
- [ ] Required missing → FileNotFoundError before Claude runs

---

### T119: Implement Instructions Writing

**PRD Reference:** Section 6.3 Step 2 ("Write instructions to .claude/CLAUDE.md")
**Depends on:** T117
**Blocks:** T121, T125
**User Stories:** N/A (infrastructure)

#### Description

Implement Step 2 of TaskRunner: create `.claude/CLAUDE.md` in the container with a standard header plus the task-specific instructions.

#### Acceptance Criteria

- [ ] Creates `.claude/` directory in container if not exists
- [ ] Writes `.claude/CLAUDE.md` with standard header + task instructions
- [ ] Header includes: agent role, feature name, component name, branch
- [ ] Task-specific instructions appended after header

#### Files to Create/Modify

- `dkmv/tasks/runner.py` — (modify) Implement instructions writing

#### Implementation Notes

The instructions file format:
```markdown
# DKMV Agent Context

You are running as part of the DKMV pipeline.

## Task-Specific Instructions

{task.instructions}
```

Use `sandbox.execute()` to create the `.claude/` directory and `sandbox.write_file()` to write CLAUDE.md. This replaces the per-component `_build_claude_md()` pattern.

#### Evaluation Checklist

- [ ] CLAUDE.md created in container
- [ ] Task instructions included
- [ ] Standard header present

---

### T120: Implement Prompt Saving

**PRD Reference:** Section 6.3 Step 3 ("Save prompt to run directory")
**Depends on:** T117
**Blocks:** T121, T125
**User Stories:** N/A (infrastructure)

#### Description

Implement Step 3 of TaskRunner: save the resolved prompt to the run output directory for debugging and inspection.

#### Acceptance Criteria

- [ ] Calls `run_manager.save_task_prompt(run_id, task.name, prompt)` with the resolved prompt (see Infrastructure Update IU-3)
- [ ] Prompt is the final text sent to Claude (after all template resolution)
- [ ] Each task's prompt saved as `prompt_{task_name}.md` (not overwriting previous tasks' prompts)

#### Files to Create/Modify

- `dkmv/tasks/runner.py` — (modify) Implement prompt saving

#### Implementation Notes

Uses the new `save_task_prompt()` method (IU-3) instead of `save_prompt()`. This is critical for multi-task components — the existing `save_prompt()` writes to a single `prompt.md` and would be overwritten by each subsequent task. The per-task variant saves as `prompt_{task_name}.md`:

```python
self._run_manager.save_task_prompt(run_id, task.name, task.prompt)
```

#### Evaluation Checklist

- [ ] Prompt saved as `prompt_{task_name}.md`
- [ ] Saved content matches what's sent to Claude
- [ ] Multi-task components preserve all prompts

---

### T121: Implement Claude Code Streaming with Parameter Cascade

**PRD Reference:** Section 6.3 Step 4 ("Stream Claude Code"), Section 6.3 ("Execution parameter cascade")
**Depends on:** T119, T120
**Blocks:** T122, T125
**User Stories:** US-07, US-20, US-22, US-23
**Estimated scope:** 3 hours

#### Description

Implement Step 4 of TaskRunner: resolve execution parameters using the cascade (task YAML > CLI > global config), then invoke `sandbox.stream_claude()` with the resolved parameters. Process stream events and render output.

#### Acceptance Criteria

- [ ] **Cascade resolution for each parameter using `CLIOverrides` (T117):**
  - `model`: `task.model or cli_overrides.model or config.default_model`
  - `max_turns`: `task.max_turns or cli_overrides.max_turns or config.default_max_turns`
  - `timeout_minutes`: `task.timeout_minutes or cli_overrides.timeout_minutes or config.timeout_minutes`
  - `max_budget_usd`: `task.max_budget_usd or cli_overrides.max_budget_usd or config.max_budget_usd`
- [ ] Task YAML value wins when set (not None)
- [ ] CLI value used when task value is None
- [ ] Global config used when both task and CLI are None
- [ ] Calls `sandbox.stream_claude(session, prompt, model, max_turns, ..., env_vars=env_vars)` with resolved params
- [ ] Env vars from inputs (type: env) passed via `stream_claude(env_vars=...)` (see IU-1)
- [ ] Stream events rendered via StreamParser
- [ ] Stream events appended to `stream.jsonl` via RunManager

#### Files to Create/Modify

- `dkmv/tasks/runner.py` — (modify) Implement streaming with cascade

#### Implementation Notes

The cascade uses the `CLIOverrides` dataclass (defined in T117) as the middle tier:

```python
def _resolve_param(self, task_value: T | None, cli_value: T | None, config_value: T) -> T:
    """Resolve execution parameter: task YAML > CLI > global config."""
    if task_value is not None:
        return task_value
    if cli_value is not None:
        return cli_value
    return config_value
```

Define a simple dataclass to hold stream output (can live in `dkmv/tasks/runner.py` alongside TaskRunner):
```python
@dataclass
class StreamResult:
    cost: float = 0.0
    turns: int = 0
    session_id: str = ""
```

Usage in `_stream_claude()`:
```python
async def _stream_claude(
    self,
    task: TaskDefinition,
    session: SandboxSession,
    run_id: str,
    config: DKMVConfig,
    cli_overrides: CLIOverrides,
    env_vars: dict[str, str],
) -> StreamResult:
    model = self._resolve_param(task.model, cli_overrides.model, config.default_model)
    max_turns = self._resolve_param(task.max_turns, cli_overrides.max_turns, config.default_max_turns)
    timeout = self._resolve_param(task.timeout_minutes, cli_overrides.timeout_minutes, config.timeout_minutes)
    budget = self._resolve_param(task.max_budget_usd, cli_overrides.max_budget_usd, config.max_budget_usd)

    async for event in self._sandbox.stream_claude(
        session=session,
        prompt=task.prompt,
        model=model,
        max_turns=max_turns,
        timeout_minutes=timeout,
        max_budget_usd=budget,
        env_vars=env_vars,  # from type: env inputs (IU-1)
    ):
        self._run_manager.append_stream(run_id, event)
        parsed = self._stream_parser.parse_line(json.dumps(event))
        if parsed:
            self._stream_parser.render_event(parsed)
        if event.get("type") == "result":
            result_event = event
```

**Key design decision (resolved):** CLI overrides are carried by the dedicated `CLIOverrides` dataclass, NOT embedded in the `variables` dict or `DKMVConfig`. This cleanly separates:
- `variables: dict[str, str]` — Jinja2 template variables for YAML rendering
- `cli_overrides: CLIOverrides` — execution parameter overrides for the cascade
- `config: DKMVConfig` — global defaults from env vars / .env file

The `dkmv run` CLI command preserves `None` for unset flags (does NOT resolve to config defaults), so the cascade works correctly.

#### Evaluation Checklist

- [ ] Task YAML model overrides CLI model
- [ ] CLI model overrides global config
- [ ] Global config used as fallback
- [ ] Same cascade for all 4 parameters
- [ ] Stream events processed correctly
- [ ] Env vars passed to Claude via `stream_claude(env_vars=...)`

---

### T122: Implement Output Collection

**PRD Reference:** Section 6.3 Step 5 ("Collect and validate outputs")
**Depends on:** T121
**Blocks:** T123, T125
**User Stories:** US-18
**Estimated scope:** 1 hour

#### Description

Implement Step 5 of TaskRunner: read declared outputs from the container, validate required outputs exist, and save outputs to the run directory.

#### Acceptance Criteria

- [ ] For each output in `task.outputs`:
  - Call `sandbox.read_file(session, output.path)`
  - If `required: true` and file missing → set status to `failed`, record error
  - If `required: false` and file missing → skip silently
  - If `save: true` → save to `{run_dir}/{filename}` via `RunManager.save_artifact()` (see IU-2)
- [ ] Collected outputs stored in `TaskResult.outputs` dict (path → content)
- [ ] All outputs processed (don't stop on first missing optional)

#### Files to Create/Modify

- `dkmv/tasks/runner.py` — (modify) Implement output collection

#### Implementation Notes

Uses `RunManager.save_artifact()` (Infrastructure Update IU-2) for output persistence:

```python
async def _collect_outputs(self, task, session, run_id) -> tuple[dict[str, str], str | None]:
    outputs: dict[str, str] = {}
    for output in task.outputs:
        try:
            content = await self._sandbox.read_file(session, output.path)
            outputs[output.path] = content
            if output.save:
                filename = Path(output.path).name
                self._run_manager.save_artifact(run_id, filename, content)
        except FileNotFoundError:
            if output.required:
                return outputs, f"Required output missing: {output.path}"
    return outputs, None
```

#### Evaluation Checklist

- [ ] Required present → success
- [ ] Required missing → failed with error message
- [ ] Optional missing → skip silently
- [ ] Save flag respected
- [ ] Outputs in TaskResult dict

---

### T123: Implement Git Teardown

**PRD Reference:** Section 6.3 Step 6 ("Git teardown")
**Depends on:** T122
**Blocks:** T124, T125
**User Stories:** N/A (infrastructure)
**Estimated scope:** 1 hour

#### Description

Implement Step 6 of TaskRunner: force-add declared output paths, stage all changes, commit, and push.

#### Acceptance Criteria

- [ ] If `task.commit` is true:
  - Force-add all declared output paths that exist: `git add -f {path}` for each
  - Stage all other changes: `git add -A`
  - Check for changes: `git status --porcelain`
  - If changes exist, commit with `task.commit_message` or auto-generated message
- [ ] If `task.push` is true (and commit was made), push to current branch
- [ ] If `task.commit` is false, skip entire git section
- [ ] No error when nothing to commit (empty `git status --porcelain`)

#### Files to Create/Modify

- `dkmv/tasks/runner.py` — (modify) Implement git teardown

#### Implementation Notes

From PRD Section 6.3 Step 6: "Force-add all declared output paths that exist in the container (replaces the per-component `_teardown_git` override pattern)."

```python
async def _git_teardown(self, task, session):
    if not task.commit:
        return

    # Force-add declared outputs (bypasses .gitignore for .dkmv/ files)
    for output in task.outputs:
        await self._sandbox.execute(session, f"git add -f {output.path} 2>/dev/null || true")

    # Stage all other changes
    await self._sandbox.execute(session, "git add -A")

    # Check if there's anything to commit
    result = await self._sandbox.execute(session, "git status --porcelain")
    if not result.output.strip():
        return  # Nothing to commit

    # Commit
    msg = task.commit_message or f"feat: {task.name} [dkmv]"
    await self._sandbox.execute(session, f'git commit -m "{msg}"')

    # Push
    if task.push:
        await self._sandbox.execute(session, "git push origin HEAD")
```

The force-add pattern is key — it replaces QA's and Judge's `_teardown_git()` overrides. Since `.dkmv/` is in `.gitignore`, but QA and Judge need their reports committed, the force-add bypasses the gitignore for declared outputs.

#### Evaluation Checklist

- [ ] Declared outputs force-added before commit
- [ ] `git add -A` stages other changes
- [ ] Nothing to commit → no error
- [ ] Push only when `task.push` is true
- [ ] Commit skipped when `task.commit` is false

---

### T124: Implement Error Handling

**PRD Reference:** Section 6.3 (error handling throughout)
**Depends on:** T118-T123
**Blocks:** T125
**User Stories:** US-17, US-18
**Estimated scope:** 1 hour

#### Description

Wire up the `run()` method with comprehensive error handling: try/except around the full lifecycle, status tracking, and cleanup.

#### Acceptance Criteria

- [ ] Missing required input → `TaskResult(status="failed", error_message="...")`
- [ ] Missing required output → `TaskResult(status="failed", error_message="...")`
- [ ] Claude error → `TaskResult(status="failed", error_message="...")`
- [ ] Timeout → `TaskResult(status="timed_out", error_message="...")`
- [ ] Unexpected exception → `TaskResult(status="failed", error_message=str(e))`
- [ ] Partial results preserved (cost, turns from stream before failure)
- [ ] Error does NOT stop the container (that's ComponentRunner's job)

#### Files to Create/Modify

- `dkmv/tasks/runner.py` — (modify) Wire up run() with error handling

#### Implementation Notes

```python
async def run(self, task, session, run_id, config, cli_overrides) -> TaskResult:
    result = TaskResult(task_name=task.name, status="failed")
    try:
        env_vars = await self._inject_inputs(task, session)
        await self._write_instructions(task, session)
        self._run_manager.save_task_prompt(run_id, task.name, task.prompt)
        stream_result = await self._stream_claude(task, session, run_id, config, cli_overrides, env_vars)
        result.total_cost_usd = stream_result.cost
        result.num_turns = stream_result.turns
        result.session_id = stream_result.session_id
        outputs, error = await self._collect_outputs(task, session, run_id)
        if error:
            result.error_message = error
            return result
        result.outputs = outputs
        await self._git_teardown(task, session)
        result.status = "completed"
    except asyncio.TimeoutError:
        result.status = "timed_out"
        result.error_message = f"Task '{task.name}' timed out"
    except FileNotFoundError as e:
        result.error_message = str(e)
    except Exception as e:
        result.error_message = f"Unexpected error: {e}"
    return result
```

#### Evaluation Checklist

- [ ] Each failure mode produces correct status
- [ ] Error messages are specific and actionable
- [ ] Partial results (cost, turns) preserved
- [ ] No container cleanup in TaskRunner (that's ComponentRunner's responsibility)

---

### T125: Write TaskRunner Tests

**PRD Reference:** Section 8 Level 3 (~20 tests)
**Depends on:** T117-T124
**Blocks:** Nothing
**User Stories:** N/A

#### Description

Write comprehensive tests for the TaskRunner with mocked SandboxManager.

#### Acceptance Criteria

- [ ] Test: file input injection — host file copied to container
- [ ] Test: file input with directory — recursive copy
- [ ] Test: text input injection — content written to container
- [ ] Test: env input — collected for Claude invocation
- [ ] Test: optional input missing → skip silently
- [ ] Test: required input missing → FileNotFoundError before Claude
- [ ] Test: instructions written to `.claude/CLAUDE.md`
- [ ] Test: execution parameter cascade — task > CLI > global
- [ ] Test: cascade with task model set → uses task model
- [ ] Test: cascade without task model → uses CLI model
- [ ] Test: cascade without task or CLI model → uses global
- [ ] Test: output collection — required present → success
- [ ] Test: output collection — required missing → failed
- [ ] Test: output save flag respected
- [ ] Test: git force-add of declared outputs
- [ ] Test: git commit with custom message
- [ ] Test: git commit skipped when commit=false
- [ ] Test: nothing to commit → no error
- [ ] Test: timeout → timed_out status
- [ ] Test: Claude error → failed status

#### Files to Create/Modify

- `tests/unit/test_task_runner.py` — (create)

#### Implementation Notes

Mock SandboxManager with AsyncMock. Mock RunManager for `save_task_prompt` and `save_artifact`. Mock StreamParser for `parse_line` and `render_event`. Create TaskDefinition instances programmatically (not from YAML files — that's the loader's job). Use `CLIOverrides()` with various combinations (all None, some set, all set) for cascade testing. Test each step independently where possible, then test the full `run()` flow.

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_task_runner.py -v` passes
- [ ] All 7 steps tested
- [ ] Cascade tested thoroughly (3 levels for each parameter)
- [ ] Error paths covered

---

## Phase Completion Checklist

- [ ] All tasks T117-T125 completed
- [ ] TaskRunner executes a task in a mocked container
- [ ] Input injection works for all three types
- [ ] Execution parameter cascade works correctly
- [ ] Output collection validates required outputs
- [ ] Git teardown force-adds declared outputs
- [ ] All tests passing: `uv run pytest tests/unit/test_task_runner.py -v`
- [ ] Lint clean: `uv run ruff check .`
- [ ] Format clean: `uv run ruff format --check .`
- [ ] Type check clean: `uv run mypy dkmv/`
- [ ] No regressions: existing tests still pass
- [ ] Progress updated in tasks.md and progress.md
