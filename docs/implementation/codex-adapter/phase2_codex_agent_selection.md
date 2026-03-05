# Phase 2: Codex Adapter & Agent Selection

## Prerequisites

- Phase 1 complete: all tasks T010-T022 done, all quality gates green
- `dkmv/adapters/` package exists with `AgentAdapter` Protocol, `ClaudeCodeAdapter`, adapter registry
- `stream_agent()` on `SandboxManager` works with adapter parameter
- `TaskRunner.run()` accepts optional `adapter` parameter
- `StreamParser` accepts optional `adapter` parameter
- All existing tests pass without modification

## Phase Goal

Codex CLI adapter is fully implemented, agent selection works at all 7 cascade levels (task YAML → task_ref → manifest → CLI → project config → DKMVConfig → default), and model-agent validation prevents mismatches.

## Phase Evaluation Criteria

- `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short` — all tests pass, coverage >= 80%
- `uv run ruff check .` — clean
- `uv run ruff format --check .` — clean
- `uv run mypy dkmv/` — passes
- `uv run pytest tests/unit/test_adapters/test_codex.py -v` — all Codex adapter tests pass
- `python -c "from dkmv.adapters import get_adapter; a = get_adapter('codex'); print(a.name)"` prints `codex`
- `python -c "from dkmv.adapters import get_adapter; a = get_adapter('codex'); print(a.build_command('/tmp/p.md', 'gpt-5.3-codex', 100, 30))"` produces valid codex exec command
- `python -c "from dkmv.adapters import infer_agent_from_model; print(infer_agent_from_model('gpt-5.3-codex'))"` prints `codex`
- `python -c "from dkmv.tasks.models import TaskDefinition; t = TaskDefinition(name='x'); print(t.agent)"` prints `None`
- `python -c "from dkmv.tasks.models import CLIOverrides; o = CLIOverrides(); print(o.agent)"` prints `None`

---

## Tasks

### T030: Create CodexCLIAdapter — build_command()

**PRD Reference:** Section 7.1 (Command Construction), Appendix A, Appendix D
**Depends on:** T010 (Protocol), Phase 1 complete
**Blocks:** T031, T032, T033
**User Stories:** US-05
**Estimated scope:** 1.5 hours

#### Description

Create `dkmv/adapters/codex.py` with `CodexCLIAdapter` class. Implement `build_command()` that produces the `codex exec` shell command with correct flags, including resume support.

#### Acceptance Criteria

- [ ] `build_command()` produces: `cd <working_dir> && env CODEX_API_KEY=<key> codex exec --json --full-auto --sandbox danger-full-access --skip-git-repo-check -m <model> "$(cat <prompt_file>)" < /dev/null > /tmp/dkmv_stream.jsonl 2>/tmp/dkmv_stream.err & echo $!`
- [ ] Resume mode produces: `codex exec resume <session_id> --json --full-auto --sandbox danger-full-access "$(cat <prompt_file>)" ...`
- [ ] `--yolo` is NOT used
- [ ] `--ephemeral` is NOT used
- [ ] `max_turns` and `max_budget_usd` are accepted but not included in command (Codex doesn't support them)
- [ ] Env vars are formatted as `env KEY=VALUE` prefix using `shlex.quote()`
- [ ] `name` property returns `"codex"`

#### Files to Create/Modify

- `dkmv/adapters/codex.py` — (create) CodexCLIAdapter with build_command()

#### Implementation Notes

```python
import shlex
from dkmv.adapters.base import StreamResult
from dkmv.core.stream import StreamEvent

class CodexCLIAdapter:
    @property
    def name(self) -> str:
        return "codex"

    def build_command(
        self,
        prompt_file: str,
        model: str,
        max_turns: int,
        timeout_minutes: int,
        max_budget_usd: float | None = None,
        env_vars: dict[str, str] | None = None,
        resume_session_id: str | None = None,
        working_dir: str = "/home/dkmv/workspace",
    ) -> str:
        env_prefix = ""
        if env_vars:
            pairs = " ".join(f"{k}={shlex.quote(v)}" for k, v in env_vars.items())
            env_prefix = f"env {pairs} "

        if resume_session_id:
            exec_part = f"codex exec resume {resume_session_id}"
        else:
            exec_part = "codex exec"

        cmd = (
            f"cd {working_dir} && "
            f"{env_prefix}{exec_part} "
            "--json "
            "--full-auto "
            "--sandbox danger-full-access "
            "--skip-git-repo-check "
            f"-m {model} "
            f'"$(cat {prompt_file})"'
            " < /dev/null > /tmp/dkmv_stream.jsonl 2>/tmp/dkmv_stream.err & echo $!"
        )
        return cmd
```

Note: `--max-turns` and `--max-budget-usd` are intentionally omitted — Codex doesn't support them. The `max_turns` and `max_budget_usd` parameters are accepted but ignored.

For resume: `codex exec resume <SESSION_ID> --json --full-auto --sandbox danger-full-access "$(cat ...)"` — the resume subcommand takes session_id, then flags, then prompt.

#### Evaluation Checklist

- [ ] `uv run mypy dkmv/adapters/codex.py` passes
- [ ] `uv run ruff check dkmv/adapters/codex.py` clean

---

### T031: Add parse_event() to CodexCLIAdapter

**PRD Reference:** Section 7.4 (Stream Event Mapping), Appendix B (JSONL Format)
**Depends on:** T030
**Blocks:** T032, T045
**User Stories:** US-06
**Estimated scope:** 2 hours

#### Description

Add `parse_event()` to `CodexCLIAdapter` that maps Codex JSONL events (dot-separated types, snake_case items) to `StreamEvent` objects. Handle all documented event types.

#### Acceptance Criteria

- [ ] `thread.started` → `StreamEvent(type="system", session_id=thread_id)`
- [ ] `item.completed` with `type="agent_message"` → `StreamEvent(type="assistant", subtype="text", content=item.text)`
- [ ] `item.started` with `type="command_execution"` → `StreamEvent(type="assistant", subtype="tool_use", tool_name="shell", tool_input=item.command)`
- [ ] `item.completed` with `type="command_execution"` → `StreamEvent(type="user", subtype="tool_result", content=item.aggregated_output)`
- [ ] `item.completed` with `type="file_change"` → `StreamEvent(type="assistant", subtype="tool_use", tool_name="edit_file")`
- [ ] `turn.started` → `None` (logged but not emitted as event)
- [ ] `turn.completed` → `None` (accumulates usage internally, not emitted)
- [ ] `error` → `StreamEvent(type="result", is_error=True, content=message)`
- [ ] Unknown event types → `StreamEvent(type=<event_type>, raw=data)` (graceful handling)
- [ ] `StreamEvent.raw` always contains the original event dict

#### Files to Create/Modify

- `dkmv/adapters/codex.py` — (modify) add parse_event()

#### Implementation Notes

Codex events use **dot separators** (`thread.started`) and **snake_case** item types (`agent_message`, `command_execution`). The `thread_id` is a flat field on `thread.started`.

The adapter needs internal state for turn accumulation. Add instance vars:

```python
class CodexCLIAdapter:
    def __init__(self) -> None:
        self._turn_count: int = 0
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._session_id: str = ""

    def parse_event(self, raw: dict[str, Any]) -> StreamEvent | None:
        event_type = raw.get("type", "")

        if event_type == "thread.started":
            self._session_id = raw.get("thread_id", "")
            return StreamEvent(type="system", session_id=self._session_id, raw=raw)

        if event_type == "turn.started":
            return None  # Silently track turn boundary

        if event_type == "turn.completed":
            self._turn_count += 1
            usage = raw.get("usage", {})
            self._total_input_tokens += usage.get("input_tokens", 0)
            self._total_output_tokens += usage.get("output_tokens", 0)
            return None  # Accumulated, not emitted until session end

        if event_type in ("item.started", "item.completed"):
            return self._parse_item_event(raw)

        if event_type == "turn.failed":
            error_msg = raw.get("error", "Turn failed")
            return StreamEvent(type="result", is_error=True, content=str(error_msg), raw=raw)

        if event_type == "thread.closed":
            # Emit accumulated result
            return StreamEvent(
                type="result",
                total_cost_usd=0.0,
                num_turns=self._turn_count,
                session_id=self._session_id,
                raw=raw,
            )

        if event_type == "error":
            return StreamEvent(
                type="result", is_error=True,
                content=raw.get("message", "Unknown error"),
                raw=raw,
            )

        # Unknown event type — return with raw data
        return StreamEvent(type=event_type, raw=raw)
```

For `_parse_item_event()`, switch on `item.type`:
- `agent_message`: content from `item["text"]`
- `command_execution`: started → tool_use with command; completed → tool_result with output
- `file_change`: tool_use with file path info
- `reasoning`, `plan`: assistant text with content
- Other: generic assistant event

#### Evaluation Checklist

- [ ] `uv run mypy dkmv/adapters/codex.py` passes
- [ ] `uv run ruff check dkmv/adapters/codex.py` clean

---

### T032: Add is_result_event() and extract_result() with State Tracking

**PRD Reference:** Section 7.4 (Completion Detection), Appendix B (Result Extraction)
**Depends on:** T031
**Blocks:** T033
**User Stories:** US-06, US-07
**Estimated scope:** 45 min

#### Description

Add `is_result_event()` and `extract_result()` to `CodexCLIAdapter`. Codex completion is detected by `thread.closed`, `error`, or `turn.failed` events. Result extraction returns accumulated turn count and `cost=0.0`.

#### Acceptance Criteria

- [ ] `is_result_event({"type": "thread.closed"})` returns `True`
- [ ] `is_result_event({"type": "error"})` returns `True`
- [ ] `is_result_event({"type": "turn.failed"})` returns `True`
- [ ] `is_result_event({"type": "item.completed"})` returns `False`
- [ ] `extract_result()` returns `StreamResult(cost=0.0, turns=<accumulated>, session_id=<from thread.started>)`
- [ ] Session ID captured from `thread.started` event's `thread_id` field

#### Files to Create/Modify

- `dkmv/adapters/codex.py` — (modify) add is_result_event() and extract_result()

#### Implementation Notes

```python
_CODEX_RESULT_EVENTS = {"thread.closed", "error", "turn.failed"}

def is_result_event(self, raw: dict[str, Any]) -> bool:
    return raw.get("type", "") in self._CODEX_RESULT_EVENTS

def extract_result(self, raw: dict[str, Any]) -> StreamResult:
    return StreamResult(
        cost=0.0,  # Codex is subscription-based
        turns=self._turn_count,
        session_id=self._session_id,
    )
```

#### Evaluation Checklist

- [ ] `uv run mypy dkmv/adapters/codex.py` passes
- [ ] `uv run ruff check dkmv/adapters/codex.py` clean

---

### T033: Complete CodexCLIAdapter and Register in Registry

**PRD Reference:** Section 6, Section 7.2 (Instructions), Section 7.3 (Auth)
**Depends on:** T032
**Blocks:** T044, T045
**User Stories:** US-05, US-07
**Estimated scope:** 1 hour

#### Description

Add remaining methods to `CodexCLIAdapter` and register it as `"codex"` in the adapter registry.

#### Acceptance Criteria

- [ ] `instructions_path` returns `"AGENTS.md"`
- [ ] `prepend_instructions` returns `True`
- [ ] `gitignore_entries` returns `[".codex/"]`
- [ ] `get_auth_env_vars(config)` returns `{"CODEX_API_KEY": key}` when available
- [ ] `get_docker_args(config)` returns `([], None)` (no special mounts for Codex)
- [ ] `get_env_overrides()` returns `{}`
- [ ] `supports_resume()` returns `True`
- [ ] `supports_budget()` returns `False`
- [ ] `supports_max_turns()` returns `False`
- [ ] `default_model` returns `"gpt-5.3-codex"`
- [ ] `validate_model("gpt-5.3-codex")` returns `True`
- [ ] `validate_model("o3")` returns `True`
- [ ] `validate_model("claude-sonnet-4-6")` returns `False`
- [ ] `get_adapter("codex")` returns `CodexCLIAdapter` instance

#### Files to Create/Modify

- `dkmv/adapters/codex.py` — (modify) add remaining methods
- `dkmv/adapters/__init__.py` — (modify) register "codex" adapter

#### Implementation Notes

```python
import re

@property
def instructions_path(self) -> str:
    return "AGENTS.md"

@property
def prepend_instructions(self) -> bool:
    return True

@property
def gitignore_entries(self) -> list[str]:
    return [".codex/"]

def get_auth_env_vars(self, config: DKMVConfig) -> dict[str, str]:
    key = config.codex_api_key
    if key:
        return {"CODEX_API_KEY": key}
    return {}

def get_docker_args(self, config: DKMVConfig) -> tuple[list[str], Path | None]:
    return ([], None)

def validate_model(self, model: str) -> bool:
    if model.startswith("gpt-"):
        return True
    if re.match(r"^o\d", model):
        return True
    return False

@property
def default_model(self) -> str:
    return "gpt-5.3-codex"
```

Update `dkmv/adapters/__init__.py`:
```python
from dkmv.adapters.codex import CodexCLIAdapter

_ADAPTERS: dict[str, type] = {
    "claude": ClaudeCodeAdapter,
    "codex": CodexCLIAdapter,
}
```

#### Evaluation Checklist

- [ ] `python -c "from dkmv.adapters import get_adapter; print(get_adapter('codex').name)"` prints `codex`
- [ ] `uv run mypy dkmv/adapters/` passes

---

### T034: Add `agent` Field to TaskDefinition

**PRD Reference:** Section 10.1 (Task YAML), Section 10.3 (Agent Resolution)
**Depends on:** Phase 1 complete
**Blocks:** T039, T040
**User Stories:** US-08
**Estimated scope:** 15 min

#### Description

Add optional `agent: str | None = None` field to `TaskDefinition` in `dkmv/tasks/models.py`.

#### Acceptance Criteria

- [ ] `TaskDefinition` has `agent: str | None = None` field
- [ ] Existing YAML files without `agent` field load without errors (defaults to `None`)
- [ ] `TaskDefinition(name="test", agent="codex").agent == "codex"`
- [ ] All existing tests pass

#### Files to Create/Modify

- `dkmv/tasks/models.py` — (modify) add agent field to TaskDefinition

#### Implementation Notes

Add after the existing optional fields (model, max_turns, etc.):
```python
class TaskDefinition(BaseModel):
    name: str
    description: str = ""
    commit: bool = True
    push: bool = True
    agent: str | None = None      # NEW — agent override for this task
    model: str | None = None
    # ... rest unchanged
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all pass
- [ ] `uv run mypy dkmv/tasks/models.py` passes

---

### T035: Add `agent` Field to ManifestTaskRef and ComponentManifest

**PRD Reference:** Section 10.2 (Component Manifest), Section 10.3
**Depends on:** Phase 1 complete
**Blocks:** T039
**User Stories:** US-08
**Estimated scope:** 15 min

#### Description

Add optional `agent: str | None = None` field to both `ManifestTaskRef` and `ComponentManifest` in `dkmv/tasks/manifest.py`.

#### Acceptance Criteria

- [ ] `ManifestTaskRef` has `agent: str | None = None` field
- [ ] `ComponentManifest` has `agent: str | None = None` field
- [ ] Existing manifests without `agent` load without errors
- [ ] All existing tests pass

#### Files to Create/Modify

- `dkmv/tasks/manifest.py` — (modify) add agent field to both models

#### Implementation Notes

```python
class ManifestTaskRef(BaseModel):
    file: str
    agent: str | None = None       # NEW
    model: str | None = None
    # ... rest unchanged

class ComponentManifest(BaseModel):
    name: str
    agent: str | None = None       # NEW — default agent for all tasks
    # ... rest unchanged
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all pass
- [ ] `uv run mypy dkmv/tasks/manifest.py` passes

---

### T036: Add `agent` to CLIOverrides

**PRD Reference:** Section 8 (Changes by File — Phase 2, tasks/models.py)
**Depends on:** Phase 1 complete
**Blocks:** T039, T040, T043
**User Stories:** US-20
**Estimated scope:** 15 min

#### Description

Add `agent: str | None = None` field to `CLIOverrides` dataclass.

#### Acceptance Criteria

- [ ] `CLIOverrides` has `agent: str | None = None` field
- [ ] `CLIOverrides()` defaults to `agent=None`
- [ ] All existing tests pass (they create CLIOverrides without agent)

#### Files to Create/Modify

- `dkmv/tasks/models.py` — (modify) add agent to CLIOverrides

#### Implementation Notes

```python
@dataclass
class CLIOverrides:
    model: str | None = None
    max_turns: int | None = None
    timeout_minutes: int | None = None
    max_budget_usd: float | None = None
    agent: str | None = None       # NEW
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all pass

---

### T037: Add `default_agent` and `codex_api_key` to DKMVConfig

**PRD Reference:** Section 9.1 (DKMVConfig Additions)
**Depends on:** Phase 1 complete
**Blocks:** T038, T040
**User Stories:** US-09
**Estimated scope:** 30 min

#### Description

Add `default_agent` and `codex_api_key` fields to `DKMVConfig`. These are read from `DKMV_AGENT` and `CODEX_API_KEY` env vars respectively, with defaults of `"claude"` and `""`.

#### Acceptance Criteria

- [ ] `DKMVConfig.default_agent` defaults to `"claude"`
- [ ] `DKMVConfig.default_agent` reads from `DKMV_AGENT` env var
- [ ] `DKMVConfig.codex_api_key` defaults to `""`
- [ ] `DKMVConfig.codex_api_key` reads from `CODEX_API_KEY` env var
- [ ] All existing tests pass (new fields have defaults)

#### Files to Create/Modify

- `dkmv/config.py` — (modify) add new fields to DKMVConfig

#### Implementation Notes

```python
class DKMVConfig(BaseSettings):
    # ... existing fields ...

    # NEW — Codex auth
    codex_api_key: str = Field(default="", validation_alias="CODEX_API_KEY")

    # NEW — agent selection
    default_agent: str = Field(default="claude", validation_alias="DKMV_AGENT")
```

**Important:** The `codex_api_key` field is initially only populated from `CODEX_API_KEY` env var via pydantic-settings. The `OPENAI_API_KEY` fallback is added in Phase 3 (T066) in `load_config()`.

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all pass
- [ ] `uv run mypy dkmv/config.py` passes

---

### T038: Add `agent` to ProjectDefaults and `codex_api_key_source` to CredentialSources

**PRD Reference:** Section 9.2 (ProjectConfig Additions)
**Depends on:** Phase 1 complete
**Blocks:** T040
**User Stories:** US-09
**Estimated scope:** 15 min

#### Description

Add `agent: str | None = None` to `ProjectDefaults` and `codex_api_key_source: str = "none"` to `CredentialSources`.

#### Acceptance Criteria

- [ ] `ProjectDefaults.agent` defaults to `None`
- [ ] `CredentialSources.codex_api_key_source` defaults to `"none"`
- [ ] Existing `.dkmv/config.json` files without these fields load without errors
- [ ] All existing tests pass

#### Files to Create/Modify

- `dkmv/project.py` — (modify) add fields to ProjectDefaults and CredentialSources

#### Implementation Notes

```python
class CredentialSources(BaseModel):
    auth_method: AuthMethod = "api_key"
    anthropic_api_key_source: str = "env"
    oauth_token_source: str = "none"
    github_token_source: str = "env"
    codex_api_key_source: str = "none"     # NEW

class ProjectDefaults(BaseModel):
    model: str | None = None
    max_turns: int | None = None
    timeout_minutes: int | None = None
    max_budget_usd: float | None = None
    memory: str | None = None
    agent: str | None = None               # NEW
```

Also update `load_config()` in `config.py` to apply `project_config.defaults.agent` to `config.default_agent` (same pattern as existing defaults):

```python
if project_config.defaults.agent is not None:
    if config.default_agent == "claude":  # only override if still at default
        config.default_agent = project_config.defaults.agent
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all pass
- [ ] `uv run mypy dkmv/project.py` passes

---

### T039: Implement Manifest-Level Agent Resolution in ComponentRunner

**PRD Reference:** Section 5 (Agent Resolution Cascade — levels 1-3), Section 10.3
**Depends on:** T034, T035, T036
**Blocks:** T040, T044, T047
**User Stories:** US-08, US-09
**Estimated scope:** 1.5 hours

#### Description

Implement agent resolution cascade levels 1-3 in `ComponentRunner`: task YAML `agent` → manifest task_ref `agent` → component manifest `agent`. This is analogous to how `model` defaults are currently applied from manifest to tasks.

#### Acceptance Criteria

- [ ] Task-level `agent` (from YAML) overrides all other sources (level 1)
- [ ] Task-ref `agent` (from manifest) overrides manifest-level (level 2)
- [ ] Manifest-level `agent` applies as component default (level 3)
- [ ] When all are `None`, agent resolution falls through to TaskRunner (levels 4-7)
- [ ] Resolution applied in `_apply_manifest_defaults()` or equivalent location
- [ ] All existing tests pass

#### Files to Create/Modify

- `dkmv/tasks/component.py` — (modify) add agent resolution in manifest defaults

#### Implementation Notes

Study how `model`, `max_turns`, etc. are currently applied from manifest defaults in `ComponentRunner.run()`. The agent field follows the same pattern.

Look for the section where manifest defaults are applied to tasks:
```python
# Existing pattern for model:
if task.model is None:
    if task_ref and task_ref.model is not None:
        task.model = task_ref.model
    elif manifest.model is not None:
        task.model = manifest.model

# Add same pattern for agent:
if task.agent is None:
    if task_ref and task_ref.agent is not None:
        task.agent = task_ref.agent
    elif manifest and manifest.agent is not None:
        task.agent = manifest.agent
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all pass
- [ ] `uv run mypy dkmv/tasks/component.py` passes

---

### T040: Implement Runtime Agent Resolution and Adapter Creation in TaskRunner

**PRD Reference:** Section 5 (Agent Resolution Cascade — levels 4-7), Section 10.3
**Depends on:** T036, T037, T038, T039
**Blocks:** T044, T045, T047
**User Stories:** US-09, US-17
**Estimated scope:** 1.5 hours

#### Description

Implement agent resolution cascade levels 4-7 in `TaskRunner`: CLI `--agent` → project config `defaults.agent` → DKMVConfig `default_agent` → built-in default `"claude"`. Create the adapter instance per-task.

#### Acceptance Criteria

- [ ] TaskRunner resolves agent from: `task.agent` → `cli_overrides.agent` → `config.default_agent` → `"claude"`
- [ ] Adapter is created via `get_adapter(resolved_agent_name)` per-task
- [ ] Adapter is passed to `_write_instructions()` and stream methods
- [ ] When `adapter` is explicitly passed to `run()`, it is used directly (skip resolution)
- [ ] Default resolution produces `"claude"` when no agent is specified at any level

#### Files to Create/Modify

- `dkmv/tasks/runner.py` — (modify) add agent resolution logic

#### Implementation Notes

Update `TaskRunner.run()` to resolve agent and create adapter:

```python
async def run(
    self,
    task: TaskDefinition,
    session: SandboxSession,
    run_id: str,
    config: DKMVConfig,
    cli_overrides: CLIOverrides,
    component_agent_md: str | None = None,
    shared_env_vars: dict[str, str] | None = None,
    adapter: AgentAdapter | None = None,
) -> TaskResult:
    if adapter is None:
        # Resolve agent through cascade levels 4-7
        # (levels 1-3 already resolved by ComponentRunner)
        agent_name = task.agent or cli_overrides.agent or config.default_agent
        from dkmv.adapters import get_adapter
        adapter = get_adapter(agent_name)
    # ... use adapter throughout
```

The resolution helper can use a simple `or` chain since `None` and empty string are both falsy. The `config.default_agent` always has a value (`"claude"` by default from env or DKMVConfig).

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all pass
- [ ] `uv run mypy dkmv/tasks/runner.py` passes

---

### T041: Add infer_agent_from_model() to Adapter Registry

**PRD Reference:** Section 10.4 (Agent Inference from Model)
**Depends on:** T033
**Blocks:** T042
**User Stories:** US-10
**Estimated scope:** 30 min

#### Description

Add `infer_agent_from_model()` function to `dkmv/adapters/__init__.py`. Given a model string, infer the appropriate agent.

#### Acceptance Criteria

- [ ] `infer_agent_from_model("claude-sonnet-4-6")` returns `"claude"`
- [ ] `infer_agent_from_model("claude-opus-4-6")` returns `"claude"`
- [ ] `infer_agent_from_model("gpt-5.3-codex")` returns `"codex"`
- [ ] `infer_agent_from_model("gpt-5.3-codex-spark")` returns `"codex"`
- [ ] `infer_agent_from_model("o3")` returns `"codex"`
- [ ] `infer_agent_from_model("o4-mini")` returns `"codex"`
- [ ] `infer_agent_from_model("unknown-model")` returns `None`

#### Files to Create/Modify

- `dkmv/adapters/__init__.py` — (modify) add infer_agent_from_model()

#### Implementation Notes

```python
import re

def infer_agent_from_model(model: str) -> str | None:
    if model.startswith("claude-"):
        return "claude"
    if model.startswith("gpt-"):
        return "codex"
    if re.match(r"^o\d", model):
        return "codex"
    return None
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_adapters/test_base.py -v` — inference tests pass
- [ ] `uv run mypy dkmv/adapters/__init__.py` passes

---

### T042: Add Model-Agent Validation and Auto-Substitution Logic

**PRD Reference:** Section 5 (Agent-Model Validation), US-11
**Depends on:** T041
**Blocks:** T048
**User Stories:** US-10, US-11
**Estimated scope:** 1.5 hours

#### Description

Add validation logic that checks model-agent compatibility and auto-substitutes models when needed. This runs after agent and model are both resolved.

#### Acceptance Criteria

- [ ] Explicit `--agent codex --model claude-opus-4-6` → error before container startup
- [ ] Error message names the agent, the incompatible model, and compatible patterns
- [ ] When model is from wrong family but agent was auto-resolved (not explicit), auto-substitute agent's default model with info log
- [ ] `validate_agent_model()` function is testable independently
- [ ] No error when model and agent are compatible

#### Files to Create/Modify

- `dkmv/adapters/__init__.py` — (modify) add validate_agent_model() function

#### Implementation Notes

```python
import logging

logger = logging.getLogger(__name__)

def validate_agent_model(
    agent_name: str,
    model: str,
    agent_explicit: bool = False,
    model_explicit: bool = False,
) -> str:
    """Validate model-agent compatibility. Returns resolved model.

    Raises ValueError if explicit agent+model are incompatible.
    Auto-substitutes default model if conflict is from defaults.
    """
    adapter = get_adapter(agent_name)

    if adapter.validate_model(model):
        return model  # Compatible

    if agent_explicit and model_explicit:
        raise ValueError(
            f"Model '{model}' is not compatible with agent '{agent_name}'. "
            f"Compatible models: {_model_patterns(agent_name)}"
        )

    # Auto-substitute: use agent's default model
    default = adapter.default_model
    logger.info(
        "Model '%s' not compatible with agent '%s'; using default '%s'",
        model, agent_name, default,
    )
    return default

def _model_patterns(agent_name: str) -> str:
    patterns = {"claude": "claude-*", "codex": "gpt-*, o<digit>*"}
    return patterns.get(agent_name, "unknown")
```

This function is called in TaskRunner after resolving both agent and model, before building the command.

#### Evaluation Checklist

- [ ] `uv run mypy dkmv/adapters/__init__.py` passes
- [ ] `uv run ruff check dkmv/adapters/__init__.py` clean

---

### T043: Add --agent Flag to CLI Run Commands

**PRD Reference:** Section 8 (CLI Changes), F10
**Depends on:** T036
**Blocks:** T049
**User Stories:** US-20, US-21
**Estimated scope:** 1 hour

#### Description

Add `--agent` option to all 5 run commands (`dev`, `qa`, `docs`, `plan`, `run_component`) in `cli.py`. Pass the value through to `CLIOverrides.agent`.

#### Acceptance Criteria

- [ ] `--agent` option available on `dev`, `qa`, `docs`, `plan`, `run_component` (the `run` alias)
- [ ] `--agent` accepts string values (e.g., `"claude"`, `"codex"`)
- [ ] Default is `None` (no agent override)
- [ ] Value stored in `CLIOverrides(agent=...)` passed to `ComponentRunner.run()`
- [ ] `dkmv dev --help` shows `--agent` option
- [ ] Existing commands without `--agent` work unchanged

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) add --agent option to 5 run commands

#### Implementation Notes

Add `agent` parameter to each wrapper command function, same pattern as `model`:

```python
@async_command(app)
async def dev(
    impl_docs: ...,
    repo: str | None = None,
    # ... existing params ...
    agent: Annotated[str | None, typer.Option("--agent", help="Agent to use (claude, codex).")] = None,
    model: str | None = None,
    # ... rest ...
) -> None:
    cli_overrides = CLIOverrides(
        model=model,
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        timeout_minutes=timeout,
        agent=agent,
    )
```

Apply the same pattern to `qa`, `docs`, `plan`, and `run_component`. The `agent` parameter should appear near `model` for consistency.

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all pass
- [ ] `dkmv dev --help 2>&1 | grep -q agent` shows --agent option

---

### T044: Implement AGENTS.md Prepend Behavior for Codex

**PRD Reference:** Section 7.2 (Instructions File), Appendix C (AGENTS.md Discovery)
**Depends on:** T033, T039, T040
**Blocks:** T046
**User Stories:** US-05
**Estimated scope:** 1 hour

#### Description

Update `TaskRunner._write_instructions()` to handle the Codex adapter's prepend behavior. When `adapter.prepend_instructions` is `True`, read the existing file content and prepend DKMV's instructions before it.

#### Acceptance Criteria

- [ ] When `adapter.prepend_instructions` is `False` (Claude), behavior is unchanged — overwrite
- [ ] When `adapter.prepend_instructions` is `True` (Codex), DKMV content is prepended before existing file content
- [ ] Existing file content is preserved after the `---` separator
- [ ] If no existing file, just write DKMV content
- [ ] Parent directory is created (`mkdir -p`) regardless of prepend mode

#### Files to Create/Modify

- `dkmv/tasks/runner.py` — (modify) update _write_instructions() for prepend support

#### Implementation Notes

```python
async def _write_instructions(
    self,
    task: TaskDefinition,
    session: SandboxSession,
    adapter: AgentAdapter,
    component_agent_md: str | None = None,
) -> str:
    content = self._build_instructions_content(task, component_agent_md)

    instructions_rel_path = adapter.instructions_path
    instructions_full_path = f"{WORKSPACE_DIR}/{instructions_rel_path}"
    parent_dir = str(Path(instructions_full_path).parent)

    if parent_dir != WORKSPACE_DIR:
        await self._sandbox.execute(session, f"mkdir -p {parent_dir}")

    if adapter.prepend_instructions:
        # Read existing content if file exists
        existing = ""
        if await self._sandbox.file_exists(session, instructions_full_path):
            existing = await self._sandbox.read_file(session, instructions_full_path)
        if existing.strip():
            content = content + "\n\n---\n\n" + existing

    await self._sandbox.write_file(session, instructions_full_path, content)
    return content
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all pass
- [ ] `uv run mypy dkmv/tasks/runner.py` passes

---

### T045: Wire Adapter Through StreamParser in Task Execution

**PRD Reference:** Section 12.2 (Adapter-Based Parsing Flow)
**Depends on:** T033, T040
**Blocks:** T046
**User Stories:** US-18, US-19
**Estimated scope:** 45 min

#### Description

Ensure the adapter is passed to `StreamParser` during task execution so Codex events are parsed by the Codex adapter. Update `TaskRunner._stream_agent()` to create `StreamParser(adapter=adapter)`.

#### Acceptance Criteria

- [ ] `StreamParser` receives adapter when streaming agent output
- [ ] Claude adapter parsing is used for Claude tasks
- [ ] Codex adapter parsing would be used for Codex tasks
- [ ] `render_event()` works identically regardless of adapter (agent-agnostic)
- [ ] All existing tests pass

#### Files to Create/Modify

- `dkmv/tasks/runner.py` — (modify) pass adapter to StreamParser

#### Implementation Notes

In `TaskRunner._stream_agent()` (or the streaming section of `run()`), when creating or using `StreamParser`:

```python
# If StreamParser is created per-task:
parser = StreamParser(console=self._console, verbose=verbose, adapter=adapter)

# If StreamParser is a class attribute, update it for the task:
self._stream_parser = StreamParser(
    console=self._console, verbose=verbose, adapter=adapter
)
```

Check how `StreamParser` is currently instantiated — it may be created in `__init__` or per-task. If it's created in `__init__`, create a task-local parser with the adapter.

The key insight: `render_event()` on `StreamParser` operates on `StreamEvent` fields only, which are agent-agnostic. So rendering works without changes. The adapter is only needed for `parse_line()` delegation.

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all pass
- [ ] `uv run mypy dkmv/tasks/runner.py` passes

---

### T046: Write Codex Adapter Unit Tests

**PRD Reference:** Section 16.2 (Phase 2 Tests)
**Depends on:** T033
**Blocks:** T050
**User Stories:** US-05, US-06, US-07
**Estimated scope:** 2.5 hours

#### Description

Create comprehensive tests for `CodexCLIAdapter` covering command construction, event parsing, result extraction, and all adapter methods.

#### Acceptance Criteria

- [ ] `test_build_command_basic` — correct codex exec command
- [ ] `test_build_command_resume` — resume session command
- [ ] `test_build_command_env_vars` — env prefix format
- [ ] `test_parse_event_thread_started` — system event with session_id
- [ ] `test_parse_event_item_completed_agent_message` — assistant text
- [ ] `test_parse_event_item_started_command_execution` — tool use
- [ ] `test_parse_event_item_completed_command_execution` — tool result
- [ ] `test_parse_event_item_completed_file_change` — file edit
- [ ] `test_parse_event_turn_completed` — accumulates usage, returns None
- [ ] `test_parse_event_thread_closed` — result event with accumulated turns
- [ ] `test_parse_event_error` — error result
- [ ] `test_parse_event_unknown` — graceful handling
- [ ] `test_is_result_event` — correct detection
- [ ] `test_extract_result` — correct fields
- [ ] `test_turn_accumulation` — multiple turns counted correctly
- [ ] `test_instructions_path` — returns `AGENTS.md`
- [ ] `test_validate_model_gpt` — True
- [ ] `test_validate_model_o_series` — True for o3, o4-mini
- [ ] `test_validate_model_claude_rejected` — False
- [ ] `test_supports_max_turns_false`
- [ ] `test_supports_budget_false`
- [ ] `test_default_model` — `gpt-5.3-codex`
- [ ] `test_prepend_instructions_true`

#### Files to Create/Modify

- `tests/unit/test_adapters/test_codex.py` — (create) Codex adapter tests

#### Implementation Notes

Use sample Codex JSONL events from PRD Appendix B:

```python
def test_parse_event_thread_started():
    adapter = CodexCLIAdapter()
    event = adapter.parse_event({
        "type": "thread.started",
        "thread_id": "0199a213-81c0-7800-8aa1-bbab2a035a53"
    })
    assert event.type == "system"
    assert event.session_id == "0199a213-81c0-7800-8aa1-bbab2a035a53"

def test_turn_accumulation():
    adapter = CodexCLIAdapter()
    # First turn
    adapter.parse_event({"type": "turn.started"})
    result = adapter.parse_event({
        "type": "turn.completed",
        "usage": {"input_tokens": 100, "cached_input_tokens": 50, "output_tokens": 20}
    })
    assert result is None  # Not emitted as event

    # Second turn
    adapter.parse_event({"type": "turn.started"})
    adapter.parse_event({
        "type": "turn.completed",
        "usage": {"input_tokens": 200, "cached_input_tokens": 100, "output_tokens": 40}
    })

    # Thread closed — emit accumulated result
    event = adapter.parse_event({"type": "thread.closed"})
    assert event.type == "result"
    assert event.num_turns == 2
    assert event.total_cost_usd == 0.0
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_adapters/test_codex.py -v` — all pass
- [ ] Coverage of `dkmv/adapters/codex.py` >= 90%

---

### T047: Write Agent Resolution Cascade Tests

**PRD Reference:** Section 5 (Resolution Cascade), US-08, US-09
**Depends on:** T039, T040
**Blocks:** T050
**User Stories:** US-08, US-09
**Estimated scope:** 1.5 hours

#### Description

Write tests verifying the 7-level agent resolution cascade works correctly.

#### Acceptance Criteria

- [ ] Test: task YAML `agent: codex` overrides all other levels
- [ ] Test: task_ref `agent: codex` overrides manifest + lower levels
- [ ] Test: manifest `agent: codex` overrides CLI + lower levels
- [ ] Test: CLI `--agent codex` overrides config + lower levels
- [ ] Test: project config `defaults.agent: codex` overrides DKMVConfig + lower
- [ ] Test: DKMVConfig `default_agent: codex` (from DKMV_AGENT env) overrides built-in
- [ ] Test: no agent at any level → resolves to `"claude"` (built-in default)
- [ ] Test: all levels set → task YAML wins

#### Files to Create/Modify

- `tests/unit/test_adapters/test_resolution.py` — (create) resolution cascade tests

#### Implementation Notes

These tests should unit-test the resolution logic directly. If resolution is inline in ComponentRunner/TaskRunner, test it by constructing the right inputs:

```python
from dkmv.tasks.models import TaskDefinition, CLIOverrides

def test_resolution_task_yaml_wins():
    task = TaskDefinition(name="test", agent="codex")
    cli_overrides = CLIOverrides(agent="claude")
    # Resolution: task.agent or cli_overrides.agent or config.default_agent
    resolved = task.agent or cli_overrides.agent or "claude"
    assert resolved == "codex"

def test_resolution_no_agent_defaults_claude():
    task = TaskDefinition(name="test")
    cli_overrides = CLIOverrides()
    resolved = task.agent or cli_overrides.agent or "claude"
    assert resolved == "claude"
```

For manifest-level resolution (levels 1-3), test that `ComponentRunner` correctly applies manifest defaults to the task's agent field.

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_adapters/test_resolution.py -v` — all pass

---

### T048: Write Model Validation and Inference Tests

**PRD Reference:** Section 5 (Agent-Model Validation), Section 10.4
**Depends on:** T041, T042
**Blocks:** T049
**User Stories:** US-10, US-11
**Estimated scope:** 1 hour

#### Description

Write tests for `infer_agent_from_model()` and `validate_agent_model()`.

#### Acceptance Criteria

- [ ] Test all inference cases from US-10 acceptance criteria
- [ ] Test explicit mismatch raises ValueError
- [ ] Test auto-substitution returns default model with info log
- [ ] Test compatible pairs pass through unchanged

#### Files to Create/Modify

- `tests/unit/test_adapters/test_base.py` — (modify) add inference and validation tests

#### Implementation Notes

```python
import pytest
from dkmv.adapters import infer_agent_from_model, validate_agent_model

@pytest.mark.parametrize("model,expected", [
    ("claude-sonnet-4-6", "claude"),
    ("claude-opus-4-6", "claude"),
    ("gpt-5.3-codex", "codex"),
    ("gpt-5.3-codex-spark", "codex"),
    ("o3", "codex"),
    ("o4-mini", "codex"),
    ("unknown-model", None),
])
def test_infer_agent_from_model(model, expected):
    assert infer_agent_from_model(model) == expected

def test_validate_agent_model_explicit_mismatch():
    with pytest.raises(ValueError, match="not compatible"):
        validate_agent_model("codex", "claude-opus-4-6",
                           agent_explicit=True, model_explicit=True)

def test_validate_agent_model_auto_substitute(caplog):
    result = validate_agent_model("codex", "claude-sonnet-4-6",
                                  agent_explicit=True, model_explicit=False)
    assert result == "gpt-5.3-codex"
    assert "not compatible" in caplog.text or "using default" in caplog.text
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_adapters/test_base.py -v` — all pass

---

### T049: Write CLI --agent Flag Tests and Full Test Suite Verification

**PRD Reference:** Section 16.2, Section 18 (Evaluation Criteria), F10
**Depends on:** T043, T046, T047, T048
**Blocks:** Nothing
**User Stories:** US-04, US-20, US-21
**Estimated scope:** 1 hour

#### Description

Write tests verifying the `--agent` CLI flag is available and correctly passed to `CLIOverrides`. Then run the complete test suite and all quality gates to verify Phase 2 is complete with no regressions.

#### Acceptance Criteria

- [ ] Test `--agent codex` is accepted by dev command
- [ ] Test `--agent` appears in help text
- [ ] Test commands without `--agent` default to agent=None in CLIOverrides
- [ ] Test existing commands work unchanged without --agent
- [ ] `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short` — all pass, coverage >= 80%
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy dkmv/` — all clean
- [ ] Both adapters registered and functional: `get_adapter("claude")`, `get_adapter("codex")`

#### Files to Create/Modify

- `tests/unit/test_cli_agent.py` — (create) CLI agent flag tests

#### Implementation Notes

Use `typer.testing.CliRunner` to test CLI commands:

```python
from typer.testing import CliRunner
from dkmv.cli import app

runner = CliRunner()

def test_dev_accepts_agent_flag():
    result = runner.invoke(app, ["dev", "--help"])
    assert "--agent" in result.output

def test_dev_without_agent_flag():
    result = runner.invoke(app, ["dev", "--help"])
    assert result.exit_code == 0
```

After tests pass, run full quality gate suite:
```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy dkmv/
uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short
python -c "from dkmv.adapters import get_adapter; print(get_adapter('claude').name, get_adapter('codex').name)"
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_cli_agent.py -v` — all pass
- [ ] All quality gates pass
- [ ] Both adapters registered and functional
