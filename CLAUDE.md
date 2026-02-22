# DKMV — Agent Guidelines

DKMV is a Python CLI tool that orchestrates AI agents via Claude Code in Docker containers (SWE-ReX) to implement software features end-to-end.

## Quick Reference

```bash
uv sync                        # Install dependencies - Don't run this unless very much necessary!
uv run dkmv --help             # Show CLI commands
uv run pytest                  # Run unit + integration tests
uv run pytest -m "not e2e"     # Skip expensive E2E tests
uv run ruff check .            # Lint
uv run ruff format --check .   # Format check
uv run mypy dkmv/              # Type check
uv run dkmv run dev --repo <url> --var prd_path=prd.md  # Run built-in component
uv run dkmv run ./my-component --repo <url> --var k=v    # Run custom component
```

## Code Style

- Python 3.12+, modern type hints: `str | None` not `Optional[str]`, `list[str]` not `List[str]`
- Pydantic v2 models (BaseModel, BaseSettings from pydantic-settings)
- No docstrings on obvious code; add comments only where logic isn't self-evident
- `ruff` for linting/formatting (line-length=100, target py312)
- `mypy` for type checking

## Testing

- pytest with `asyncio_mode = "auto"`
- 80% coverage target (`--cov-fail-under=80`)
- `@pytest.mark.e2e` for tests requiring Docker + API key (nightly only)
- Test files mirror source: `dkmv/core/stream.py` -> `tests/unit/test_stream.py`
- Use `tmp_path` for file I/O, `monkeypatch.setenv()` for config, `AsyncMock` for sandbox
- polyfactory for Pydantic model factories in `tests/factories.py`

## Architecture

```
dkmv/
  cli.py              # Typer app, all commands (including `dkmv run`)
  config.py            # DKMVConfig (pydantic-settings, env vars + .env)
  utils/               # async_command decorator
  core/                # SandboxManager, RunManager, StreamParser, shared models
  components/          # Legacy Python component subpackages (dev/, qa/, judge/, docs/)
    base.py            # BaseComponent ABC — 12-step run() lifecycle
    {name}/            # component.py, models.py, prompt.md, __init__.py
  tasks/               # Task engine — YAML-based declarative task system
    models.py          # TaskInput, TaskOutput, TaskDefinition, TaskResult, CLIOverrides
    loader.py          # TaskLoader — Jinja2 + YAML + Pydantic pipeline
    runner.py          # TaskRunner — single task execution
    component.py       # ComponentRunner — multi-task orchestration
    discovery.py       # resolve_component() — path + built-in resolution
  builtins/            # Built-in YAML component definitions
    dev/               # 01-plan.yaml, 02-implement.yaml
    qa/                # 01-evaluate.yaml
    judge/             # 01-verdict.yaml
    docs/              # 01-generate.yaml
  images/              # Dockerfile for dkmv-sandbox
```

**Isolation rules:**
- Components import from `core/` for infrastructure, **never** from each other
- Shared types (BaseResult, BaseComponentConfig) live in `core/models.py`
- Component-specific types live in their own `models.py`
- Prompt templates are co-located as `prompt.md` inside each component subpackage
- Prompt templates (.md files) and built-in YAML files require hatchling force-include config in pyproject.toml

### Task System

The task system (`dkmv/tasks/`) provides a YAML-based declarative alternative to the Python component classes. Components are directories of YAML task files that define inputs, outputs, instructions, and prompts. The `dkmv run` command executes any component — built-in or custom.

**YAML task format** (see `docs/core/dkmv_tasks/v1/task_definition.md` for full schema):
- Identity: `name`, `description`, `commit`, `push`, `commit_message`
- Execution: `model`, `max_turns`, `timeout_minutes`, `max_budget_usd` (all cascade: task → CLI → config)
- Data: `inputs` (file/text/env types), `outputs` (path, required, save)
- Content: `instructions`/`instructions_file`, `prompt`/`prompt_file` (Jinja2 templates)

## Git Conventions

Conventional Commits: `<type>[scope]: <description>`

- **Types:** `feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, `chore`
- **Scopes:** `cli`, `sandbox`, `runner`, `stream`, `dev`, `qa`, `judge`, `docs-component`, `docker`, `config`, `tasks`
- Agent commits use `[dkmv-<component>]` suffix

## Key Design Decisions

- **No YAML config** — env vars + `.env` file only (pydantic-settings)
- **One container per component invocation** — clean state, isolation
- **Git branches as inter-component communication** — components share zero state except the branch
- **stream-json output** — Claude Code headless mode with real-time parsing
- **File-based streaming** — SWE-ReX blocks on commands; Claude Code backgrounded with `< /dev/null` stdin redirect (required — interactive bash job control sends SIGTTIN to background processes reading from terminal), stdout redirected to file, tailed from second session
- **SWE-ReX** — container lifecycle management (DockerDeployment, RemoteRuntime)

## Configuration (env vars)

```
ANTHROPIC_API_KEY    # Required
GITHUB_TOKEN         # Required for private repos / PR creation
DKMV_MODEL           # Default: claude-sonnet-4-20250514
DKMV_MAX_TURNS       # Default: 100
DKMV_IMAGE           # Default: dkmv-sandbox:latest
DKMV_OUTPUT_DIR      # Default: ./outputs
DKMV_TIMEOUT         # Default: 30 (minutes)
DKMV_MEMORY          # Default: 8g
DKMV_MAX_BUDGET_USD  # Optional: cost cap per Claude Code invocation (dollars)
```

## Documentation

- Full PRD: `docs/core/plan_dkmv_v1.md` (read-only, source of truth)
- Task system PRD: `docs/core/dkmv_tasks/v1/prd_tasks_v1.md`
- Task YAML schema: `docs/core/dkmv_tasks/v1/task_definition.md`
- ADRs: `docs/decisions/NNNN-short-title.md` (MADR 4.0 template)

## Dependencies

Runtime: `typer`, `pydantic`, `pydantic-settings`, `swe-rex>=1.4`, `rich`, `jinja2`, `pyyaml`
Dev: `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-timeout`, `syrupy`, `polyfactory`, `ruff`, `mypy`, `commitizen`, `pre-commit`

---

# DKMV Tasks v1 — Implementation Guide

## Current State (Pre-Implementation Baseline)

**Existing codebase is stable and production-ready:**
- 268 tests passing, 93.89% coverage
- All quality gates green (ruff, mypy, pytest)
- 4 Python components fully operational: dev, qa, judge, docs
- Core infrastructure: SandboxManager, RunManager, StreamParser, DKMVConfig
- CLI commands: `dkmv build`, `dkmv dev`, `dkmv qa`, `dkmv judge`, `dkmv docs`, `dkmv runs`, `dkmv show`, `dkmv attach`, `dkmv stop`, `dkmv clean`

**What we are building:** A YAML-based declarative task system that replaces the hardcoded Python components with configurable YAML task files. The existing Python component system will coexist during migration — old commands still work, new `dkmv run` command added.

## Implementation Documentation

All specs live in `docs/implementation/v1 - dkmv + tasks/`. **Read the phase doc before starting each phase.**

| Document | Purpose | When to read |
|----------|---------|-------------|
| `features.md` | Feature registry with dependency diagram (F1-F8) | Before starting any phase — understand the big picture |
| `tasks.md` | Master checklist (T100-T149) — check off tasks as you complete them | Every task — update checkboxes as you work |
| `progress.md` | Session-by-session implementation log | End of every session — add session entry |
| `user_stories.md` | 24 user stories with acceptance criteria | When implementing features — verify against user expectations |
| `phase1_foundation.md` | Phase 1: Task Model, Loader, Discovery (T100-T116) | Before starting Phase 1 |
| `phase2_taskrunner.md` | Phase 2: TaskRunner execution engine (T117-T125) | Before starting Phase 2 |
| `phase3_component_and_cli.md` | Phase 3: ComponentRunner + CLI (T126-T134) | Before starting Phase 3 |
| `phase4_builtins.md` | Phase 4: Built-in conversion + backward compat (T135-T144) | Before starting Phase 4 |
| `phase5_polish.md` | Phase 5: Documentation + final verification (T145-T149) | Before starting Phase 5 |

**PRD and schema reference (read-only, source of truth):**
- `docs/core/dkmv_tasks/v1/prd_tasks_v1.md` — Full PRD for the task system
- `docs/core/dkmv_tasks/v1/task_definition.md` — YAML task schema reference

## Existing Core Infrastructure (Key Interfaces)

You MUST understand these existing interfaces before implementing. The task system builds ON TOP of them — it does NOT replace them.

### DKMVConfig (`dkmv/config.py`)

```python
class DKMVConfig(BaseSettings):
    anthropic_api_key: str
    github_token: str
    default_model: str = "claude-sonnet-4-6"
    default_max_turns: int = 100
    image_name: str = "dkmv-sandbox:latest"
    output_dir: Path = Path("./outputs")
    timeout_minutes: int = 30
    memory_limit: str = "8g"
    max_budget_usd: float | None = None
```

### RunManager (`dkmv/core/runner.py`)

```python
class RunManager:
    def __init__(self, output_dir: Path) -> None: ...
    def start_run(self, component: ComponentName, config: BaseComponentConfig) -> str: ...
    def save_result(self, run_id: str, result: BaseResult) -> None: ...
    def save_prompt(self, run_id: str, prompt: str) -> None: ...
    def save_container_name(self, run_id: str, container_name: str) -> None: ...
    def get_container_name(self, run_id: str) -> str | None: ...
    def append_stream(self, run_id: str, event: dict[str, Any]) -> None: ...
    def list_runs(self, component=None, feature=None, status=None, limit=20) -> list[RunSummary]: ...
    def get_run(self, run_id: str) -> RunDetail: ...
```

### SandboxManager (`dkmv/core/sandbox.py`)

```python
class SandboxManager:
    async def start(self, sandbox_config: SandboxConfig, component_name: str) -> SandboxSession: ...
    async def execute(self, session: SandboxSession, command: str, timeout=None) -> CommandResult: ...
    async def write_file(self, session: SandboxSession, path: str, content: str) -> None: ...
    async def read_file(self, session: SandboxSession, path: str) -> str: ...
    async def stop(self, session: SandboxSession, keep_alive: bool = False) -> None: ...
    def get_container_name(self, session: SandboxSession) -> str: ...
    async def setup_git_auth(self, session: SandboxSession) -> CommandResult: ...
    async def stream_claude(self, session, prompt, model, max_turns, timeout_minutes,
                            max_budget_usd=None, working_dir="/home/dkmv/workspace") -> AsyncIterator[dict]: ...
```

### StreamParser (`dkmv/core/stream.py`)

```python
class StreamParser:
    def __init__(self, console: Console | None = None, verbose: bool = False): ...
    def parse_line(self, line: str) -> StreamEvent | None: ...
    def render_event(self, event: StreamEvent) -> None: ...
```

### Core Models (`dkmv/core/models.py`)

```python
RunStatus = Literal["pending", "running", "completed", "failed", "timed_out"]
ComponentName = Literal["dev", "qa", "judge", "docs"]  # ← Will be relaxed to str in Phase 3 (IU-4)

class SandboxConfig(BaseModel): ...     # image, env_vars, docker_args, keep_alive, memory_limit, timeout_minutes
class BaseComponentConfig(BaseModel): ... # repo, branch, feature_name, model, max_turns, keep_alive, verbose, timeout_minutes, max_budget_usd
class BaseResult(BaseModel): ...         # run_id, component, status, repo, branch, total_cost_usd, duration_seconds, etc.
class RunSummary(BaseModel): ...         # run_id, component, status, feature_name, timestamp, cost, duration
class RunDetail(BaseResult): ...         # + config, stream_events_count, prompt, log_path
```

### BaseComponent (`dkmv/components/base.py`)

The existing 12-step run lifecycle that the new task system replaces for declarative workflows. Reference it for patterns — the task system uses the same SandboxManager, RunManager, and StreamParser, but with a different orchestration approach.

## Infrastructure Updates (Must Apply Before Their Phase)

These are small changes to existing core modules required by the task system. Each is documented in the relevant phase doc.

| ID | Phase | File | Change | Why |
|----|-------|------|--------|-----|
| IU-1 | 2 | `dkmv/core/sandbox.py` | Add `env_vars: dict[str, str] \| None = None` parameter to `stream_claude()`, use Unix `env` prefix | Task `type: env` inputs need env vars passed to Claude process |
| IU-2 | 2 | `dkmv/core/runner.py` | Add `save_artifact(run_id, filename, content)` method | Save per-task outputs and task_result.json |
| IU-3 | 2 | `dkmv/core/runner.py` | Add `save_task_prompt(run_id, task_name, prompt)` method | Per-task prompt files (multi-task components) |
| IU-4 | 3 | `dkmv/core/models.py` | Change `ComponentName = Literal[...]` to `ComponentName = str` | Custom YAML components need arbitrary names |
| IU-5 | 3 | N/A (code pattern) | ComponentRunner constructs `BaseComponentConfig` shim for `start_run()` | Compatibility with existing RunManager interface |

**CRITICAL:** Apply IU-1/2/3 at the START of Phase 2 (before T117). Apply IU-4/5 at the START of Phase 3 (before T126). Add tests for each IU alongside their implementation.

## Phase Implementation Procedure

**Follow this exact procedure for each phase. Do NOT skip steps.**

### Before Starting a Phase

1. **Read the phase doc** thoroughly: `docs/implementation/v1 - dkmv + tasks/phaseN_*.md`
2. **Check prerequisites** in the phase doc — ensure all prerequisite phases are complete
3. **Apply infrastructure updates** if any are listed for this phase (IU-1 through IU-5)
4. **Run the full test suite** to confirm green baseline: `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short`
5. **Run quality gates:** `uv run ruff check . && uv run ruff format --check . && uv run mypy dkmv/`

### Verify-First Implementation (CRITICAL)

**Approach every task with skepticism toward the documentation.** The implementation docs are a guide, not gospel. Before writing any code for a task:

1. **Verify the claims.** Read the referenced existing code (method signatures, class constructors, model fields). Confirm that what the doc says about existing interfaces is actually true. If the doc references `sandbox.write_file(session, dest, content)`, open `dkmv/core/sandbox.py` and confirm that signature exists.

2. **Verify the approach.** Think about whether the documented approach is actually the best way. Check if there's a simpler pattern already established in the codebase that achieves the same result. If the doc suggests a 20-line solution but you see a 5-line approach using an existing utility — prefer the simpler one.

3. **Fix the doc if it's wrong.** If you discover that an implementation note is incorrect (wrong method name, wrong parameter, outdated assumption about existing code), **fix the phase doc first**, then implement the corrected version. Do not implement known-incorrect guidance. Log what you changed and why in the session's "Findings" section.

4. **Do not introduce regressions.** If a "better" approach would require changing existing interfaces or break existing callers, it is not better. Evaluate improvements strictly within the constraint of backward compatibility.

5. **Implement everything specified.** After verification, implement ALL acceptance criteria for the task. Do not skip criteria because they seem minor. Every checkbox in the acceptance criteria must be satisfiable by the code you write.

The goal is: verify → think → fix docs if needed → implement correctly → test thoroughly.

### Implementing Tasks Within a Phase

For each task (in dependency order as listed in the phase doc):

1. **Read the task section** in the phase doc — understand acceptance criteria, files to modify, implementation notes
2. **Verify against actual code** — confirm method signatures, model fields, and interfaces referenced in the doc match reality (see "Verify-First" above)
3. **If the doc is wrong or suboptimal** — fix the doc, then implement the corrected version
4. **Implement the code** following the (verified) implementation notes and code examples
5. **Write tests** if the task includes a test file (or add to existing test files as specified)
6. **Run the relevant tests:** `uv run pytest tests/unit/test_<relevant>.py -v`
7. **Run quality gates:** `uv run ruff check . && uv run ruff format --check . && uv run mypy dkmv/`
8. **Fix any failures** before moving to the next task
9. **Check off the task** in `docs/implementation/v1 - dkmv + tasks/tasks.md`

### After Completing a Phase

1. **Run the FULL test suite:** `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short`
2. **Run ALL quality gates:** `uv run ruff check . && uv run ruff format --check . && uv run mypy dkmv/`
3. **Verify phase evaluation criteria** from the phase doc's "Phase Evaluation Criteria" section
4. **Check the phase completion checklist** at the bottom of the phase doc
5. **Update progress.md** — add a session entry with tasks completed, tests added, coverage, notes
6. **Update tasks.md** — verify all phase tasks are checked off

### End-of-Turn Logging

At the end of every implementation turn (conversation session), update `docs/implementation/v1 - dkmv + tasks/progress.md` with:

```markdown
### Session N — YYYY-MM-DD

**Phase:** N
**Tasks completed:** T100-T107
**Tests added:** 30
**Coverage:** XX%

#### What was done
- Bullet list of what was implemented

#### Takeaways
- Key implementation decisions made during this session
- Patterns that worked well
- Approaches that needed adjustment

#### Findings
- Unexpected behaviors or edge cases discovered
- Bugs found and fixed in existing code (if any)
- Deviations from the implementation spec (with reasons)

#### Notes for Next Session
- What to implement next (specific task IDs)
- Any blockers or open questions
- Things to watch out for in the next phase
- Existing code patterns to reuse or avoid

#### Quality Gates
- ruff: clean / X issues
- mypy: clean / X issues
- pytest: X tests, Y% coverage
- regressions: none / description
```

## Phase-by-Phase Summary

### Phase 1 — Foundation (T100-T116)

**Goal:** Data layer — Pydantic models validate YAML, loader parses Jinja2 templates, discovery finds components.

**New files:**
- `dkmv/tasks/__init__.py` — package with public API exports
- `dkmv/tasks/models.py` — TaskInput, TaskOutput, TaskDefinition, TaskResult, ComponentResult
- `dkmv/tasks/loader.py` — TaskLoader (Jinja2 + YAML + Pydantic pipeline)
- `dkmv/tasks/discovery.py` — resolve_component() for paths and built-ins
- `tests/unit/test_task_models.py` — ~30 tests
- `tests/unit/test_task_loader.py` — ~20 tests
- `tests/unit/test_discovery.py` — ~10 tests

**Modified files:**
- `pyproject.toml` — add jinja2, pyyaml dependencies

**Key implementation details:**
- TaskDefinition execution fields (model, max_turns, etc.) default to `None` to enable the cascade
- TaskDefinition has XOR validators: exactly one of instructions/instructions_file, exactly one of prompt/prompt_file
- TaskLoader processing pipeline: raw YAML → Jinja2 render (StrictUndefined) → yaml.safe_load() → model_validate()
- prompt_file/instructions_file resolved relative to the task YAML file's directory
- load_component() scans directory for *.yaml/*.yml, sorted by filename
- resolve_component() checks for path first (contains / or .), then tries built-in

### Phase 2 — TaskRunner (T117-T125)

**Goal:** Single task execution — inputs injected, instructions written, Claude streamed with cascade, outputs collected, git operations performed.

**Infrastructure updates first:** IU-1 (stream_claude env_vars), IU-2 (save_artifact), IU-3 (save_task_prompt)

**New files:**
- `dkmv/tasks/runner.py` — TaskRunner class + StreamResult dataclass
- `tests/unit/test_task_runner.py` — ~20 tests

**Modified files:**
- `dkmv/tasks/models.py` — add CLIOverrides dataclass
- `dkmv/core/sandbox.py` — add env_vars parameter to stream_claude() (IU-1)
- `dkmv/core/runner.py` — add save_artifact(), save_task_prompt() (IU-2, IU-3)
- `tests/unit/test_sandbox.py` — add env_vars tests
- `tests/unit/test_runner.py` — add save_artifact/save_task_prompt tests

**Key implementation details:**
- CLIOverrides dataclass: `model`, `max_turns`, `timeout_minutes`, `max_budget_usd` — all `| None = None`
- Execution parameter cascade: `task.field or cli_overrides.field or config.field` (use `_resolve_param` helper)
- TaskRunner.run() steps: inject inputs → write instructions → save prompt → stream Claude → collect outputs → git teardown
- Input types: file (copy host→container), text (write content→container), env (collect for stream_claude)
- Env vars injected via `env KEY=VALUE ... claude -p ...` prefix (IU-1)
- Output validation: required=True + missing → status="failed"
- Git teardown: force-add declared outputs → git add -A → check porcelain → commit → push
- Error handling: TimeoutError→timed_out, FileNotFoundError→failed, Exception→failed
- TaskRunner does NOT manage container lifecycle (that's ComponentRunner's job)

### Phase 3 — ComponentRunner + CLI (T126-T134)

**Goal:** Multi-task orchestration and `dkmv run` CLI command.

**Infrastructure updates first:** IU-4 (ComponentName=str), IU-5 (BaseComponentConfig shim pattern)

**New files:**
- `dkmv/tasks/component.py` — ComponentRunner class
- `tests/unit/test_component_runner.py` — ~15 tests
- `tests/unit/test_cli_run.py` — ~10 tests

**Modified files:**
- `dkmv/core/models.py` — relax ComponentName to str (IU-4)
- `dkmv/cli.py` — add `dkmv run` command + _parse_vars() helper

**Key implementation details:**
- ComponentRunner.run() lifecycle: load tasks → create run (BaseComponentConfig shim) → start container → setup workspace → execute tasks sequentially → aggregate results → stop container
- Fail-fast: first failed/timed_out task stops pipeline, remaining marked "skipped"
- Variable propagation: built-in vars (repo, branch, feature_name, component, model, run_id) + CLI --var vars + previous task vars (tasks.<name>.status/cost/turns)
- `model` built-in var = `cli_overrides.model or config.default_model` (NOT the task-level model)
- task_start separator events in stream.jsonl for multi-task debugging
- Container stopped in finally block (even on error), unless keep_alive=True
- CLI run command: function named `run_component` with `name="run"` (avoids shadowing builtin)
- CLIOverrides preserves None for unset flags — do NOT resolve to config defaults in CLI layer
- feature_name defaults to component_dir.name when not provided

### Phase 4 — Built-in Components (T135-T144)

**Goal:** Convert 4 Python components to YAML, add backward compat wrappers.

**New files:**
- `dkmv/builtins/__init__.py` + subdirectories with `__init__.py`
- `dkmv/builtins/dev/01-plan.yaml`, `02-implement.yaml`
- `dkmv/builtins/qa/01-evaluate.yaml`
- `dkmv/builtins/judge/01-verdict.yaml`
- `dkmv/builtins/docs/01-generate.yaml`
- `tests/unit/test_builtins.py` — ~15 tests
- `tests/integration/test_run_e2e.py` — ~2 E2E tests

**Modified files:**
- `pyproject.toml` — force-include for built-in YAML files
- `dkmv/cli.py` — refactor dev/qa/judge/docs commands to call ComponentRunner internally

**Key implementation details:**
- Dev: 2 tasks (plan + implement). Plan: commit=false, low budget. Implement: commit=true, push=true, high budget
- QA, Judge, Docs: 1 task each
- Wrappers translate typed CLI flags to --var variables: `--prd path` → `variables={"prd_path": "path"}`
- All wrappers construct CLIOverrides from execution-parameter flags
- Dev wrapper: feature_name defaults to Path(prd).stem
- Built-in YAMLs must use Jinja2 conditionals for optional inputs (e.g., `{% if feedback_path %}`)

### Phase 5 — Polish & Migration (T145-T149)

**Goal:** Documentation, deprecation notices, final verification.

**Modified files:**
- `CLAUDE.md` — add task system to architecture, dkmv run to quick reference
- `README.md` — add dkmv run documentation
- `dkmv/cli.py` — deprecation notices on old commands

## Critical Rules — DO NOT BREAK EXISTING CODE

1. **Run the full test suite before AND after every phase.** All 268 existing tests must continue to pass.
2. **Do NOT modify BaseComponent or existing component subpackages** (dkmv/components/) unless explicitly required by infrastructure updates.
3. **Do NOT modify existing CLI command signatures** — only change internal implementations (Phase 4 wrappers).
4. **Infrastructure updates (IU-1 through IU-5) must be backward-compatible.** New parameters have default values. Existing callers are unaffected.
5. **ComponentName relaxation (IU-4)** from Literal to str is backward-compatible — literal strings are valid strings.
6. **New code goes in `dkmv/tasks/`** — the task system is a new package alongside the existing code.
7. **New tests go in new test files** (test_task_models.py, test_task_runner.py, etc.) — do not modify existing test files except to add IU tests.
8. **If a quality gate fails, fix it immediately** — do not move to the next task with failures.

## Testing Patterns for Task System

```python
# Task model tests — construct models programmatically
task = TaskDefinition(name="test", instructions="do stuff", prompt="go")

# Loader tests — create YAML files in tmp_path
(tmp_path / "task.yaml").write_text("name: test\n...")
loader = TaskLoader()
result = loader.load(tmp_path / "task.yaml", {"var": "value"})

# TaskRunner tests — mock SandboxManager + RunManager
sandbox = AsyncMock(spec=SandboxManager)
run_manager = MagicMock(spec=RunManager)
runner = TaskRunner(sandbox, run_manager, stream_parser, console)

# ComponentRunner tests — mock TaskRunner + TaskLoader
task_runner = AsyncMock(spec=TaskRunner)
loader = MagicMock(spec=TaskLoader)
component_runner = ComponentRunner(sandbox, run_manager, loader, task_runner, stream_parser, console)

# CLI tests — Typer CliRunner with mocked dependencies
from typer.testing import CliRunner
result = CliRunner().invoke(app, ["run", "./path", "--repo", "https://..."])

# CLIOverrides for cascade testing
cli_overrides = CLIOverrides()  # all None — fall through to config
cli_overrides = CLIOverrides(model="claude-opus-4-6")  # model set, rest None
```

## File Layout Reference

After all phases are complete:

```
dkmv/
  tasks/                    # NEW — Task engine
    __init__.py             # Public exports
    models.py               # TaskInput, TaskOutput, TaskDefinition, TaskResult, ComponentResult, CLIOverrides
    loader.py               # TaskLoader — Jinja2 + YAML + Pydantic
    runner.py               # TaskRunner + StreamResult — single task execution
    component.py            # ComponentRunner — multi-task orchestration
    discovery.py            # resolve_component() — path + built-in resolution
  builtins/                 # NEW — Built-in YAML components
    __init__.py
    dev/
      __init__.py
      01-plan.yaml
      02-implement.yaml
    qa/
      __init__.py
      01-evaluate.yaml
    judge/
      __init__.py
      01-verdict.yaml
    docs/
      __init__.py
      01-generate.yaml
  core/                     # EXISTING — modified with IU-1/2/3/4
  components/               # EXISTING — unchanged (Phase 4 wrappers only change cli.py)
  cli.py                    # EXISTING — add `dkmv run`, refactor wrapper commands
  config.py                 # EXISTING — unchanged
tests/
  unit/
    test_task_models.py     # NEW — ~30 tests
    test_task_loader.py     # NEW — ~20 tests
    test_discovery.py       # NEW — ~10 tests
    test_task_runner.py     # NEW — ~20 tests
    test_component_runner.py # NEW — ~15 tests
    test_cli_run.py         # NEW — ~10 tests
    test_builtins.py        # NEW — ~15 tests
    test_runner.py          # EXISTING — add IU-2/3 tests
    test_sandbox.py         # EXISTING — add IU-1 tests
  integration/
    test_run_e2e.py         # NEW — ~2 E2E tests
```
