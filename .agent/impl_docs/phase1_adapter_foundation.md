# Phase 1: Adapter Foundation (Pure Refactor)

## Prerequisites

- All existing tests pass: `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short`
- Quality gates green: `uv run ruff check . && uv run ruff format --check . && uv run mypy dkmv/`
- PRD read: Sections 4 (Coupling Points), 5 (Target Architecture), 6 (Agent Adapter Interface), 8 (Changes by File — Phase 1)

## Phase Goal

Extract all Claude Code-specific logic (command construction, stream parsing, auth, instructions) into an `AgentAdapter` Protocol and `ClaudeCodeAdapter` implementation with **zero behavioral changes**. All existing tests pass without modification.

## Phase Evaluation Criteria

- `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short` — all tests pass, zero failures, coverage >= 80%
- `uv run ruff check .` — clean
- `uv run ruff format --check .` — clean
- `uv run mypy dkmv/` — passes
- `uv run pytest tests/unit/test_adapters/ -v` — all new adapter tests pass
- `python -c "from dkmv.adapters import get_adapter; a = get_adapter('claude'); print(a.name)"` prints `claude`
- `python -c "from dkmv.adapters import get_adapter; get_adapter('unknown')"` raises `ValueError`
- No existing test files modified (verify with `git diff --name-only tests/`)
- `stream_claude()` method still exists on `SandboxManager` with identical signature

---

## Tasks

### T010: Create AgentAdapter Protocol and StreamResult Dataclass

**PRD Reference:** Section 6 (Agent Adapter Interface)
**Depends on:** Nothing
**Blocks:** T011, T012, T013, T014, T015
**User Stories:** US-01
**Estimated scope:** 1 hour

#### Description

Create `dkmv/adapters/base.py` with the `AgentAdapter` Protocol class and `StreamResult` dataclass. The Protocol defines the contract all agent adapters must satisfy.

#### Acceptance Criteria

- [ ] `AgentAdapter` is defined as `typing.Protocol` with `@runtime_checkable`
- [ ] All Protocol methods match PRD Section 6 signatures exactly
- [ ] `StreamResult` dataclass has `cost: float`, `turns: int`, `session_id: str` fields
- [ ] `mypy dkmv/adapters/base.py` passes clean

#### Files to Create/Modify

- `dkmv/adapters/base.py` — (create) AgentAdapter Protocol + StreamResult dataclass

#### Implementation Notes

Use `from __future__ import annotations` for forward references. The Protocol must include these methods/properties:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from dkmv.core.stream import StreamEvent


@dataclass
class StreamResult:
    cost: float = 0.0
    turns: int = 0
    session_id: str = ""


@runtime_checkable
class AgentAdapter(Protocol):
    @property
    def name(self) -> str: ...

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
    ) -> str: ...

    def parse_event(self, raw: dict[str, Any]) -> StreamEvent | None: ...
    def is_result_event(self, raw: dict[str, Any]) -> bool: ...
    def extract_result(self, raw: dict[str, Any]) -> StreamResult: ...

    @property
    def instructions_path(self) -> str: ...

    @property
    def prepend_instructions(self) -> bool: ...

    @property
    def gitignore_entries(self) -> list[str]: ...

    def get_auth_env_vars(self, config: Any) -> dict[str, str]: ...
    def get_docker_args(self, config: Any) -> tuple[list[str], Path | None]: ...
    def get_env_overrides(self) -> dict[str, str]: ...

    def supports_resume(self) -> bool: ...
    def supports_budget(self) -> bool: ...
    def supports_max_turns(self) -> bool: ...

    @property
    def default_model(self) -> str: ...

    def validate_model(self, model: str) -> bool: ...
```

Note: Use `config: Any` for the type hint in Protocol methods to avoid circular imports. Concrete implementations will use `DKMVConfig`.

The `prepend_instructions` property is not in the PRD Protocol but is needed for Codex's AGENTS.md handling (Phase 2). Adding it now keeps the Protocol stable.

#### Evaluation Checklist

- [ ] `uv run mypy dkmv/adapters/base.py` passes
- [ ] `uv run ruff check dkmv/adapters/base.py` clean

---

### T011: Create Adapter Registry with get_adapter()

**PRD Reference:** Section 8 (New Files — `dkmv/adapters/__init__.py`)
**Depends on:** T010
**Blocks:** T016, T017, T018, T019, T020
**User Stories:** US-02
**Estimated scope:** 30 min

#### Description

Create `dkmv/adapters/__init__.py` with the adapter registry and `get_adapter(name)` factory function. Initially registers only `"claude"`.

#### Acceptance Criteria

- [ ] `get_adapter("claude")` returns a `ClaudeCodeAdapter` instance
- [ ] `get_adapter("unknown")` raises `ValueError` listing registered adapters
- [ ] Registry is a module-level dict `_ADAPTERS: dict[str, type]`
- [ ] Exports: `AgentAdapter`, `StreamResult`, `get_adapter`

#### Files to Create/Modify

- `dkmv/adapters/__init__.py` — (create) registry + factory

#### Implementation Notes

```python
from dkmv.adapters.base import AgentAdapter, StreamResult
from dkmv.adapters.claude import ClaudeCodeAdapter

_ADAPTERS: dict[str, type] = {
    "claude": ClaudeCodeAdapter,
}

def get_adapter(name: str) -> AgentAdapter:
    cls = _ADAPTERS.get(name)
    if cls is None:
        available = ", ".join(sorted(_ADAPTERS.keys()))
        raise ValueError(f"Unknown agent '{name}'. Available: {available}")
    return cls()
```

The `"codex"` entry will be added in Phase 2 (T033).

#### Evaluation Checklist

- [ ] `python -c "from dkmv.adapters import get_adapter; print(get_adapter('claude').name)"` prints `claude`
- [ ] `python -c "from dkmv.adapters import get_adapter; get_adapter('x')"` raises `ValueError`

---

### T012: Create ClaudeCodeAdapter — build_command()

**PRD Reference:** Section 4 (CP-1: Command Construction, `sandbox.py:177-219`), Section 6
**Depends on:** T010
**Blocks:** T013, T014, T015, T016
**User Stories:** US-03
**Estimated scope:** 1.5 hours

#### Description

Create `dkmv/adapters/claude.py` with the `ClaudeCodeAdapter` class. Implement `build_command()` by extracting the command construction logic from `SandboxManager.stream_claude()` in `sandbox.py`. The generated command must be **byte-identical** to the current hardcoded implementation.

#### Acceptance Criteria

- [ ] `ClaudeCodeAdapter` class exists in `dkmv/adapters/claude.py`
- [ ] `build_command()` produces the exact same shell command as current `sandbox.py` lines ~207-219
- [ ] Command includes: `cd <working_dir> && <env_prefix>claude [-p | --resume] "$(cat <prompt_file>)" --dangerously-skip-permissions --verbose --output-format stream-json --model <model> --max-turns <max_turns> [--max-budget-usd <budget>] < /dev/null > /tmp/dkmv_stream.jsonl 2>/tmp/dkmv_stream.err & echo $!`
- [ ] Resume mode uses `--resume <session_id>` flag instead of `-p`
- [ ] Env vars are formatted as `env KEY=VALUE` prefix using `shlex.quote()`
- [ ] `name` property returns `"claude"`

#### Files to Create/Modify

- `dkmv/adapters/claude.py` — (create) ClaudeCodeAdapter class with build_command()

#### Implementation Notes

Study `SandboxManager.stream_claude()` in `dkmv/core/sandbox.py`. The command construction is around lines 207-219. Extract the logic into `build_command()`. Key details:

```python
import shlex

class ClaudeCodeAdapter:
    @property
    def name(self) -> str:
        return "claude"

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
        # Build env prefix from env_vars dict
        env_prefix = ""
        if env_vars:
            pairs = " ".join(f"{k}={shlex.quote(v)}" for k, v in env_vars.items())
            env_prefix = f"env {pairs} "

        # Build budget flag
        budget_flag = ""
        if max_budget_usd is not None:
            budget_flag = f" --max-budget-usd {max_budget_usd}"

        # Build command with resume or prompt
        if resume_session_id:
            prompt_part = f"--resume {resume_session_id}"
        else:
            prompt_part = f'-p "$(cat {prompt_file})"'

        cmd = (
            f"cd {working_dir} && "
            f"{env_prefix}claude {prompt_part} "
            "--dangerously-skip-permissions "
            "--verbose "
            "--output-format stream-json "
            f"--model {model} "
            f"--max-turns {max_turns}"
            f"{budget_flag}"
            " < /dev/null > /tmp/dkmv_stream.jsonl 2>/tmp/dkmv_stream.err & echo $!"
        )
        return cmd
```

**Critical:** Compare the output of this method against the current `sandbox.py` command construction character-by-character. The regression test in T021 will enforce this.

#### Evaluation Checklist

- [ ] `uv run mypy dkmv/adapters/claude.py` passes
- [ ] `uv run ruff check dkmv/adapters/claude.py` clean

---

### T013: Add parse_event() to ClaudeCodeAdapter

**PRD Reference:** Section 4 (CP-2: Stream Parsing), Section 12 (Stream Parsing & Normalization)
**Depends on:** T012
**Blocks:** T016, T017
**User Stories:** US-03
**Estimated scope:** 1.5 hours

#### Description

Add `parse_event()` to `ClaudeCodeAdapter` that converts raw Claude JSONL event dicts into `StreamEvent` objects. Extract the parsing logic from `StreamParser.parse_line()` in `dkmv/core/stream.py`.

#### Acceptance Criteria

- [ ] `parse_event()` handles `type="system"` → `StreamEvent(type="system", session_id=...)`
- [ ] `parse_event()` handles `type="assistant"` with text content → `StreamEvent(type="assistant", subtype="text", content=...)`
- [ ] `parse_event()` handles `type="assistant"` with tool_use → `StreamEvent(type="assistant", subtype="tool_use", tool_name=..., tool_input=...)`
- [ ] `parse_event()` handles `type="user"` with tool_result → `StreamEvent(type="user", subtype="tool_result", content=...)`
- [ ] `parse_event()` handles `type="result"` → `StreamEvent(type="result", total_cost_usd=..., num_turns=..., session_id=..., is_error=...)`
- [ ] `StreamEvent.raw` always contains the original event dict
- [ ] Unknown event types return `StreamEvent(type=<event_type>, raw=<data>)`

#### Files to Create/Modify

- `dkmv/adapters/claude.py` — (modify) add parse_event()

#### Implementation Notes

Read `StreamParser.parse_line()` in `dkmv/core/stream.py` carefully. It currently does `json.loads(line)` then branches on `data.get("type")`. Extract the dict-based logic (post-json.loads) into `parse_event()`.

For `assistant` events, content is in `data["message"]["content"]` which is a list of content blocks. Each block has a `type` field: `"text"` or `"tool_use"`.

For `result` events, fields are: `total_cost_usd`, `duration_ms`, `num_turns`, `session_id`, `is_error`.

Ensure the raw dict is always stored: `raw=raw`.

#### Evaluation Checklist

- [ ] `uv run mypy dkmv/adapters/claude.py` passes
- [ ] `uv run ruff check dkmv/adapters/claude.py` clean

---

### T014: Add is_result_event() and extract_result() to ClaudeCodeAdapter

**PRD Reference:** Section 6 (Agent Adapter Interface)
**Depends on:** T013
**Blocks:** T016
**User Stories:** US-03
**Estimated scope:** 30 min

#### Description

Add `is_result_event()` and `extract_result()` to `ClaudeCodeAdapter`. These are used by `SandboxManager.stream_agent()` to detect when the agent has finished and extract the final result.

#### Acceptance Criteria

- [ ] `is_result_event({"type": "result", ...})` returns `True`
- [ ] `is_result_event({"type": "assistant", ...})` returns `False`
- [ ] `extract_result()` returns `StreamResult(cost=total_cost_usd, turns=num_turns, session_id=session_id)`
- [ ] `extract_result()` handles missing fields gracefully (defaults to 0.0, 0, "")

#### Files to Create/Modify

- `dkmv/adapters/claude.py` — (modify) add is_result_event() and extract_result()

#### Implementation Notes

```python
def is_result_event(self, raw: dict[str, Any]) -> bool:
    return raw.get("type") == "result"

def extract_result(self, raw: dict[str, Any]) -> StreamResult:
    return StreamResult(
        cost=raw.get("total_cost_usd", 0.0),
        turns=raw.get("num_turns", 0),
        session_id=raw.get("session_id", ""),
    )
```

Study `SandboxManager.stream_claude()` to see how it currently detects completion (`if event.get("type") == "result"`) and how it uses `session_id` for retry.

#### Evaluation Checklist

- [ ] `uv run mypy dkmv/adapters/claude.py` passes
- [ ] `uv run ruff check dkmv/adapters/claude.py` clean

---

### T015: Complete ClaudeCodeAdapter — Properties, Auth, and Capabilities

**PRD Reference:** Section 4 (CP-3, CP-4, CP-8), Section 6
**Depends on:** T014
**Blocks:** T018, T019
**User Stories:** US-03
**Estimated scope:** 2 hours

#### Description

Add all remaining methods and properties to `ClaudeCodeAdapter`: `instructions_path`, `prepend_instructions`, `gitignore_entries`, `get_auth_env_vars()`, `get_docker_args()`, `get_env_overrides()`, `supports_resume()`, `supports_budget()`, `supports_max_turns()`, `default_model`, and `validate_model()`.

The auth methods (`get_auth_env_vars`, `get_docker_args`) must extract the Claude-specific credential handling from `component.py`'s `_build_sandbox_config()`.

#### Acceptance Criteria

- [ ] `instructions_path` returns `".claude/CLAUDE.md"`
- [ ] `prepend_instructions` returns `False`
- [ ] `gitignore_entries` returns `[".claude/"]`
- [ ] `get_auth_env_vars(config)` returns `{"ANTHROPIC_API_KEY": key}` for api_key auth, `{}` for oauth
- [ ] `get_docker_args(config)` returns bind-mount args + temp_creds_file for OAuth, empty for api_key
- [ ] `get_env_overrides()` returns `{}`
- [ ] `supports_resume()` returns `True`
- [ ] `supports_budget()` returns `True`
- [ ] `supports_max_turns()` returns `True`
- [ ] `default_model` returns `"claude-sonnet-4-6"`
- [ ] `validate_model("claude-sonnet-4-6")` returns `True`
- [ ] `validate_model("gpt-5.3-codex")` returns `False`
- [ ] `mypy` validates `ClaudeCodeAdapter` satisfies `AgentAdapter` Protocol

#### Files to Create/Modify

- `dkmv/adapters/claude.py` — (modify) add all remaining methods

#### Implementation Notes

**Auth handling:** Study `ComponentRunner._build_sandbox_config()` in `dkmv/tasks/component.py` (around lines 60-113). Extract the Claude-specific credential logic:

```python
from dkmv.config import DKMVConfig, _fetch_oauth_credentials

def get_auth_env_vars(self, config: DKMVConfig) -> dict[str, str]:
    if config.auth_method == "api_key":
        return {"ANTHROPIC_API_KEY": config.anthropic_api_key}
    # OAuth: token passed via bind-mount or env var
    if config.claude_oauth_token:
        return {"CLAUDE_CODE_OAUTH_TOKEN": config.claude_oauth_token}
    return {}

def get_docker_args(self, config: DKMVConfig) -> tuple[list[str], Path | None]:
    if config.auth_method != "oauth":
        return ([], None)
    # OAuth credential bind-mount logic (from component.py)
    # ... extract the macOS Keychain / Linux file / env fallback chain
```

The OAuth credential handling in `component.py` has a three-tier fallback:
1. macOS Keychain → write to temp file → bind-mount
2. Linux: bind-mount `~/.claude/.credentials.json` directly
3. Fallback: `CLAUDE_CODE_OAUTH_TOKEN` env var

Extract this exactly. Use `_fetch_oauth_credentials()` from `config.py`.

**Model validation:**
```python
def validate_model(self, model: str) -> bool:
    return model.startswith("claude-")
```

#### Evaluation Checklist

- [ ] `uv run mypy dkmv/adapters/claude.py` passes
- [ ] `python -c "from dkmv.adapters.base import AgentAdapter; from dkmv.adapters.claude import ClaudeCodeAdapter; assert isinstance(ClaudeCodeAdapter(), AgentAdapter)"` passes

---

### T016: Refactor sandbox.py — Add stream_agent() with Adapter Parameter

**PRD Reference:** Section 8 (Modified Files — Phase 1, sandbox.py), Section 15 (Deprecation Path)
**Depends on:** T011, T012, T013, T014
**Blocks:** T018
**User Stories:** US-04
**Estimated scope:** 2 hours

#### Description

Add `stream_agent()` method to `SandboxManager` that takes an `AgentAdapter` parameter. The adapter's `build_command()` replaces the hardcoded command construction. Keep `stream_claude()` as a thin wrapper that creates a `ClaudeCodeAdapter` internally and delegates to `stream_agent()`, preserving the **exact current signature** for backwards compatibility with 30+ test mocks.

#### Acceptance Criteria

- [ ] `stream_agent()` accepts `adapter: AgentAdapter` as first parameter plus all existing stream params
- [ ] `stream_agent()` uses `adapter.build_command()` for command construction
- [ ] `stream_agent()` uses `adapter.is_result_event()` for completion detection
- [ ] `stream_claude()` retains its **exact current method signature** (no new required params)
- [ ] `stream_claude()` internally creates `ClaudeCodeAdapter()` and calls `stream_agent()`
- [ ] All existing test mocks that assign `sandbox.stream_claude = mock_stream` continue to work
- [ ] `stream_agent()` yields `dict[str, Any]` (same as current `stream_claude()`)

#### Files to Create/Modify

- `dkmv/core/sandbox.py` — (modify) add stream_agent(), refactor stream_claude()

#### Implementation Notes

**Key constraint:** `stream_claude()` is assigned directly as a mock in 30+ tests (e.g., `sandbox.stream_claude = mock_stream`). This works because it's a regular method, not a property. The wrapper must preserve this — it can be a regular method that creates a `ClaudeCodeAdapter` and delegates.

```python
async def stream_agent(
    self,
    adapter: AgentAdapter,
    session: SandboxSession,
    prompt: str,
    model: str,
    max_turns: int,
    timeout_minutes: int,
    max_budget_usd: float | None = None,
    working_dir: str = "/home/dkmv/workspace",
    env_vars: dict[str, str] | None = None,
    resume_session_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    # Write prompt to file
    await self.write_file(session, "/tmp/dkmv_prompt.md", prompt)

    # Build command using adapter
    cmd = adapter.build_command(
        prompt_file="/tmp/dkmv_prompt.md",
        model=model,
        max_turns=max_turns,
        timeout_minutes=timeout_minutes,
        max_budget_usd=max_budget_usd,
        env_vars=env_vars,
        resume_session_id=resume_session_id,
        working_dir=working_dir,
    )

    # Rest of the streaming logic (tail -f, yield events, etc.) stays the same
    # Use adapter.is_result_event(event) instead of event.get("type") == "result"

async def stream_claude(
    self,
    session: SandboxSession,
    prompt: str,
    model: str,
    max_turns: int,
    timeout_minutes: int,
    max_budget_usd: float | None = None,
    working_dir: str = "/home/dkmv/workspace",
    env_vars: dict[str, str] | None = None,
    resume_session_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    from dkmv.adapters.claude import ClaudeCodeAdapter
    adapter = ClaudeCodeAdapter()
    async for event in self.stream_agent(
        adapter, session, prompt, model, max_turns, timeout_minutes,
        max_budget_usd, working_dir, env_vars, resume_session_id,
    ):
        yield event
```

**Critical:** The `stream_claude()` parameter list must be **identical** to the current one. Do not add or remove any parameters. The `session` parameter name and type must match exactly.

Look at the current `stream_claude()` implementation to identify the streaming loop (tail -f on `/tmp/dkmv_stream.jsonl`), process monitoring, and completion detection. Move all of this into `stream_agent()`, replacing only the command construction and result detection with adapter calls.

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all existing tests pass (zero failures)
- [ ] No test files modified: `git diff --name-only tests/` shows no changes

---

### T017: Refactor stream.py — StreamParser Accepts Optional Adapter

**PRD Reference:** Section 12.2 (Adapter-Based Parsing Flow)
**Depends on:** T013
**Blocks:** T018
**User Stories:** US-04
**Estimated scope:** 45 min

#### Description

Add optional `adapter` parameter to `StreamParser.__init__()`. When an adapter is provided, `parse_line()` delegates to `adapter.parse_event()` after JSON parsing. When no adapter is provided, the existing Claude parsing logic is used (backwards compatibility).

#### Acceptance Criteria

- [ ] `StreamParser(adapter=None)` works identically to current behavior
- [ ] `StreamParser(adapter=claude_adapter)` delegates to `adapter.parse_event()`
- [ ] `parse_line()` still handles JSON parsing and returns `None` for invalid lines
- [ ] All existing tests pass without modification (they use `StreamParser()` without adapter)

#### Files to Create/Modify

- `dkmv/core/stream.py` — (modify) add adapter parameter

#### Implementation Notes

```python
class StreamParser:
    def __init__(self, console: Console | None = None, verbose: bool = False,
                 adapter: AgentAdapter | None = None) -> None:
        self._console = console or Console()
        self._verbose = verbose
        self._adapter = adapter

    def parse_line(self, line: str) -> StreamEvent | None:
        line = line.strip()
        if not line:
            return None
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None

        if self._adapter is not None:
            return self._adapter.parse_event(data)

        # Existing Claude parsing logic (unchanged)
        return self._parse_claude_event(data)
```

Move the current inline parsing logic into a `_parse_claude_event(data)` private method. This keeps the fallback path clean and testable.

Use `from __future__ import annotations` and `TYPE_CHECKING` guard for the `AgentAdapter` import to avoid circular imports:

```python
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from dkmv.adapters.base import AgentAdapter
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all existing tests pass
- [ ] `uv run mypy dkmv/core/stream.py` passes

---

### T018: Refactor tasks/runner.py — Adapter-Based Instructions and Streaming

**PRD Reference:** Section 4 (CP-3: Instructions File), Section 8 (Modified Files — runner.py)
**Depends on:** T015, T016, T017
**Blocks:** T019
**User Stories:** US-04
**Estimated scope:** 2 hours

#### Description

Refactor `TaskRunner` to accept and use an `AgentAdapter` for instructions file writing and agent streaming. `_write_instructions()` uses `adapter.instructions_path` for the file location. `_stream_claude()` is renamed to `_stream_agent()` and uses the adapter for command construction and stream parsing.

#### Acceptance Criteria

- [ ] `TaskRunner.run()` accepts optional `adapter: AgentAdapter | None` parameter (defaults to `ClaudeCodeAdapter()`)
- [ ] `_write_instructions()` uses `adapter.instructions_path` to determine file path
- [ ] `_write_instructions()` creates parent directory (e.g., `mkdir -p .claude`)
- [ ] `_stream_claude()` renamed to `_stream_agent()` (or kept as alias for compatibility)
- [ ] `_stream_agent()` passes adapter to `sandbox.stream_agent()` when available
- [ ] `StreamParser` is created with `adapter` when available
- [ ] All existing tests pass — TaskRunner is called without adapter arg (default applies)

#### Files to Create/Modify

- `dkmv/tasks/runner.py` — (modify) add adapter parameter, update instructions + streaming

#### Implementation Notes

**Instructions path:** Currently hardcoded:
```python
await self._sandbox.execute(session, f"mkdir -p {WORKSPACE_DIR}/.claude")
await self._sandbox.write_file(session, f"{WORKSPACE_DIR}/.claude/CLAUDE.md", content)
```

Change to:
```python
instructions_rel_path = adapter.instructions_path  # e.g., ".claude/CLAUDE.md"
instructions_full_path = f"{WORKSPACE_DIR}/{instructions_rel_path}"
parent_dir = str(Path(instructions_full_path).parent)
await self._sandbox.execute(session, f"mkdir -p {parent_dir}")
await self._sandbox.write_file(session, instructions_full_path, content)
```

**Streaming:** The `_stream_claude()` method calls `self._sandbox.stream_claude(...)`. Change to `self._sandbox.stream_agent(adapter, ...)` when adapter is provided. For backwards compatibility during Phase 1, default to `ClaudeCodeAdapter()`:

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
        from dkmv.adapters.claude import ClaudeCodeAdapter
        adapter = ClaudeCodeAdapter()
    # ... use adapter throughout
```

**Important:** The `adapter` parameter must be optional with a default of `None` so that all existing callers (especially tests) work without modification. The default creates a `ClaudeCodeAdapter`.

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all existing tests pass
- [ ] `uv run mypy dkmv/tasks/runner.py` passes

---

### T019: Refactor tasks/component.py — Adapter-Based Auth and Gitignore

**PRD Reference:** Section 4 (CP-4: Auth, CP-8: .gitignore), Section 8 (Modified Files — component.py)
**Depends on:** T015, T018
**Blocks:** Nothing (within Phase 1)
**User Stories:** US-04
**Estimated scope:** 2 hours

#### Description

Refactor `ComponentRunner._build_sandbox_config()` to delegate auth credential handling to the Claude adapter. Replace hardcoded `.claude/` gitignore entry with adapter's `gitignore_entries`. In Phase 1, the adapter is always `ClaudeCodeAdapter` — behavior must be identical.

#### Acceptance Criteria

- [ ] `_build_sandbox_config()` uses `adapter.get_auth_env_vars(config)` for env vars
- [ ] `_build_sandbox_config()` uses `adapter.get_docker_args(config)` for Docker args + temp creds
- [ ] Workspace gitignore setup uses `adapter.gitignore_entries` instead of hardcoded `.claude/`
- [ ] `ComponentRunner.run()` creates a `ClaudeCodeAdapter` and passes it through
- [ ] `ComponentRunner.run()` passes adapter to `TaskRunner.run()` calls
- [ ] All existing tests pass without modification

#### Files to Create/Modify

- `dkmv/tasks/component.py` — (modify) refactor auth + gitignore

#### Implementation Notes

**Auth refactoring:** Currently `_build_sandbox_config()` has inline Claude auth logic (api_key vs oauth). Replace with adapter calls:

```python
def _build_sandbox_config(
    self, config: DKMVConfig, timeout_minutes: int,
    adapter: AgentAdapter | None = None,
) -> tuple[SandboxConfig, Path | None]:
    if adapter is None:
        from dkmv.adapters.claude import ClaudeCodeAdapter
        adapter = ClaudeCodeAdapter()

    env_vars: dict[str, str] = {}
    docker_args: list[str] = []

    # Auth from adapter
    env_vars.update(adapter.get_auth_env_vars(config))
    extra_args, temp_creds_file = adapter.get_docker_args(config)
    docker_args.extend(extra_args)

    # GitHub token (agent-agnostic)
    if config.github_token:
        env_vars["GITHUB_TOKEN"] = config.github_token

    # ... rest unchanged
```

**Gitignore:** Currently:
```python
"&& (grep -qxF '.claude/' .gitignore 2>/dev/null"
"|| { ... echo '.claude/' >> .gitignore; })"
```

Replace with a loop over `adapter.gitignore_entries`:
```python
for entry in adapter.gitignore_entries:
    gitignore_cmds.append(
        f"(grep -qxF '{entry}' .gitignore 2>/dev/null"
        f" || echo '{entry}' >> .gitignore)"
    )
```

**Critical:** Study the current `_build_sandbox_config()` implementation carefully. The OAuth three-tier fallback must be preserved exactly in `ClaudeCodeAdapter.get_docker_args()`. Verify by running the full test suite.

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all existing tests pass
- [ ] `uv run mypy dkmv/tasks/component.py` passes

---

### T020: Write Adapter Registry Tests

**PRD Reference:** Section 16.1 (Phase 1 Tests)
**Depends on:** T011
**Blocks:** T022
**User Stories:** US-02
**Estimated scope:** 45 min

#### Description

Create `tests/unit/test_adapters/test_base.py` with tests for the adapter registry.

#### Acceptance Criteria

- [ ] Test `get_adapter("claude")` returns `ClaudeCodeAdapter` instance
- [ ] Test `get_adapter("unknown")` raises `ValueError` with registered adapter names
- [ ] Test that `ClaudeCodeAdapter` satisfies `AgentAdapter` Protocol (`isinstance` check)
- [ ] Test that `StreamResult` dataclass has correct defaults

#### Files to Create/Modify

- `tests/unit/test_adapters/__init__.py` — (create) empty package marker
- `tests/unit/test_adapters/test_base.py` — (create) registry tests

#### Implementation Notes

```python
import pytest
from dkmv.adapters import get_adapter, AgentAdapter, StreamResult
from dkmv.adapters.claude import ClaudeCodeAdapter


def test_get_adapter_claude():
    adapter = get_adapter("claude")
    assert isinstance(adapter, ClaudeCodeAdapter)
    assert adapter.name == "claude"


def test_get_adapter_unknown_raises():
    with pytest.raises(ValueError, match="Unknown agent 'unknown'"):
        get_adapter("unknown")


def test_get_adapter_error_lists_available():
    with pytest.raises(ValueError, match="claude"):
        get_adapter("nonexistent")


def test_claude_adapter_satisfies_protocol():
    adapter = ClaudeCodeAdapter()
    assert isinstance(adapter, AgentAdapter)


def test_stream_result_defaults():
    result = StreamResult()
    assert result.cost == 0.0
    assert result.turns == 0
    assert result.session_id == ""
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_adapters/test_base.py -v` — all pass
- [ ] `uv run ruff check tests/unit/test_adapters/` clean

---

### T021: Write Claude Adapter Unit Tests

**PRD Reference:** Section 16.1 (Phase 1 Tests)
**Depends on:** T015
**Blocks:** T022
**User Stories:** US-03
**Estimated scope:** 2 hours

#### Description

Create `tests/unit/test_adapters/test_claude.py` with comprehensive tests for `ClaudeCodeAdapter`.

#### Acceptance Criteria

- [ ] `test_build_command_basic` — verify basic command format
- [ ] `test_build_command_with_budget` — budget flag present
- [ ] `test_build_command_with_env_vars` — env prefix format
- [ ] `test_build_command_resume` — resume flag replaces -p
- [ ] `test_parse_event_system` — system event parsing
- [ ] `test_parse_event_assistant_text` — assistant text event
- [ ] `test_parse_event_assistant_tool_use` — tool use event
- [ ] `test_parse_event_user_tool_result` — tool result event
- [ ] `test_parse_event_result` — result event with cost/turns
- [ ] `test_is_result_event` — True for result, False for others
- [ ] `test_extract_result` — StreamResult fields match event data
- [ ] `test_instructions_path` — returns `.claude/CLAUDE.md`
- [ ] `test_gitignore_entries` — returns `[".claude/"]`
- [ ] `test_validate_model_claude` — True for claude-* models
- [ ] `test_validate_model_non_claude` — False for gpt-*, o3, etc.
- [ ] `test_supports_resume_true` — returns True
- [ ] `test_supports_budget_true` — returns True
- [ ] `test_supports_max_turns_true` — returns True
- [ ] `test_default_model` — returns `claude-sonnet-4-6`
- [ ] `test_prepend_instructions_false` — returns False

#### Files to Create/Modify

- `tests/unit/test_adapters/test_claude.py` — (create) Claude adapter tests

#### Implementation Notes

Test `build_command()` by asserting specific substrings and overall structure:

```python
def test_build_command_basic():
    adapter = ClaudeCodeAdapter()
    cmd = adapter.build_command(
        prompt_file="/tmp/dkmv_prompt.md",
        model="claude-sonnet-4-6",
        max_turns=100,
        timeout_minutes=30,
    )
    assert cmd.startswith("cd /home/dkmv/workspace && ")
    assert 'claude -p "$(cat /tmp/dkmv_prompt.md)"' in cmd
    assert "--dangerously-skip-permissions" in cmd
    assert "--verbose" in cmd
    assert "--output-format stream-json" in cmd
    assert "--model claude-sonnet-4-6" in cmd
    assert "--max-turns 100" in cmd
    assert "< /dev/null > /tmp/dkmv_stream.jsonl" in cmd
    assert "2>/tmp/dkmv_stream.err & echo $!" in cmd
```

Test `parse_event()` with realistic event dicts matching Claude Code's JSONL format:

```python
def test_parse_event_result():
    adapter = ClaudeCodeAdapter()
    event = adapter.parse_event({
        "type": "result",
        "total_cost_usd": 0.15,
        "duration_ms": 45000,
        "num_turns": 5,
        "session_id": "sess-123",
        "is_error": False,
    })
    assert event.type == "result"
    assert event.total_cost_usd == 0.15
    assert event.num_turns == 5
    assert event.session_id == "sess-123"
    assert event.is_error is False
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_adapters/test_claude.py -v` — all pass
- [ ] Coverage of `dkmv/adapters/claude.py` >= 90%

---

### T022: Command Regression Test and Full Test Suite Verification

**PRD Reference:** Section 14 (R1: Claude Code Behavioral Regression), Section 16.1
**Depends on:** T016, T017, T018, T019, T020, T021
**Blocks:** Nothing
**User Stories:** US-04
**Estimated scope:** 1 hour

#### Description

Add a regression test that compares the command generated by `ClaudeCodeAdapter.build_command()` against the expected exact command string (extracted from current `sandbox.py`). Run the full test suite to verify zero regressions.

#### Acceptance Criteria

- [ ] Regression test asserts the exact command string for a standard invocation
- [ ] Regression test asserts the exact command string for a resume invocation
- [ ] Regression test asserts the exact command string with budget flag
- [ ] `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short` — ALL tests pass, coverage >= 80%
- [ ] `git diff --name-only tests/` shows ONLY new files (no modifications to existing tests)
- [ ] All quality gates pass: ruff check, ruff format, mypy

#### Files to Create/Modify

- `tests/unit/test_adapters/test_claude.py` — (modify) add regression tests

#### Implementation Notes

Capture the exact command string from the current `sandbox.py` for regression testing:

```python
def test_build_command_regression_basic():
    """Exact command match against current sandbox.py implementation."""
    adapter = ClaudeCodeAdapter()
    cmd = adapter.build_command(
        prompt_file="/tmp/dkmv_prompt.md",
        model="claude-sonnet-4-6",
        max_turns=100,
        timeout_minutes=30,
    )
    expected = (
        'cd /home/dkmv/workspace && '
        'claude -p "$(cat /tmp/dkmv_prompt.md)" '
        '--dangerously-skip-permissions '
        '--verbose '
        '--output-format stream-json '
        '--model claude-sonnet-4-6 '
        '--max-turns 100'
        ' < /dev/null > /tmp/dkmv_stream.jsonl 2>/tmp/dkmv_stream.err & echo $!'
    )
    assert cmd == expected
```

**Important:** Read the current `sandbox.py` to capture the exact expected string. Pay attention to spacing, flag order, and quoting. The test must match character-for-character.

Run the full quality gate suite to verify Phase 1 is complete:
```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy dkmv/
uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short` — all pass, >= 80% coverage
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy dkmv/` — all clean
- [ ] `git diff --name-only tests/` shows no modifications to existing test files
