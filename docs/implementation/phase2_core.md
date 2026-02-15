# Phase 2: Core Framework

## Prerequisites

- Phase 1 complete (CLI skeleton, config, Docker image, CI)
- `uv run dkmv --help` works
- `dkmv build` produces a working Docker image

## Phase Goal

The core framework is operational: SandboxManager can start/stop containers and run commands, RunManager tracks runs, StreamParser renders output, and BaseComponent defines the shared lifecycle. A mock component can run the full 12-step lifecycle.

## Phase Evaluation Criteria

- Mock component runs full lifecycle (start → setup → prompt → execute → teardown)
- RunManager creates, lists, and shows runs correctly
- StreamParser renders sample stream-json output to terminal
- `uv run pytest tests/unit/test_sandbox.py tests/unit/test_runner.py tests/unit/test_stream.py -v` all pass
- `uv run pytest tests/integration/test_sandbox.py -v` passes
- All core models validate correctly via Pydantic

---

## Tasks

### T030: Create Core Pydantic Models

**PRD Reference:** Section 6/F3 (SandboxConfig), Section 6/F4 (BaseComponentConfig, BaseResult)
**Depends on:** T019 (config.py)
**Blocks:** T031, T040, T046, T050, T051
**User Stories:** N/A (shared models, infrastructure)
**Estimated scope:** 1-2 hours

#### Description

Create the shared Pydantic models that all core components use: SandboxConfig for container settings, BaseComponentConfig for component input, and BaseResult for component output.

#### Acceptance Criteria

- [ ] `SandboxConfig` with: image, env_vars, docker_args, startup_timeout, keep_alive, memory_limit, timeout_minutes
- [ ] `BaseComponentConfig` with: repo, branch, feature_name, model, max_turns, keep_alive, verbose, timeout_minutes, sandbox_config, max_budget_usd
- [ ] `max_budget_usd: float | None = None` (optional cost cap for Claude Code)
- [ ] NOTE: `prd_path` is NOT in BaseComponentConfig — it lives in component-specific configs (DevConfig, QAConfig, JudgeConfig) per PRD Section 6/F4. DocsConfig does not use a PRD.
- [ ] `BaseResult` with: run_id, component, status, repo, branch, feature_name, model, total_cost_usd, duration_seconds, num_turns, timestamp, session_id, error_message
- [ ] `RunStatus` type alias: `RunStatus = Literal["pending", "running", "completed", "failed", "timed_out"]`
- [ ] `status` field on BaseResult uses `RunStatus` type alias
- [ ] All models use modern type hints (`str | None`, not `Optional[str]`)
- [ ] Models serialize/deserialize correctly to/from JSON

#### Files to Create/Modify

- `dkmv/core/models.py` — (create) Shared model definitions

#### Implementation Notes

Use exact field definitions from PRD Section 6/F3 and F4. The `component` field in BaseResult uses `Literal["dev", "qa", "judge", "docs"]`. Use `Field(ge=0)` for numeric constraints. Use `Field(default_factory=...)` for mutable defaults.

IMPORTANT: `prd_path` is intentionally NOT in BaseComponentConfig. Per PRD Section 6/F4:
- DevConfig, QAConfig, JudgeConfig each define `prd_path: Path` (required)
- DocsConfig does NOT have `prd_path` — the Docs component generates docs from code, no PRD needed
- This keeps type-level correctness: components that need a PRD enforce it in their own config

**STATUS VALUES — INTENTIONAL DEVIATION FROM PRD:**
The PRD (Section 6/F4) defines `status: Literal["success", "failure", "error"]`.
We use `RunStatus = Literal["pending", "running", "completed", "failed", "timed_out"]` instead because:
- `"pending"` — tracks unstarted runs (useful for `dkmv runs` to show queued work)
- `"running"` — tracks active runs (the PRD's F11 also needs this for `--status running`)
- `"completed"` — clearer than `"success"` (a run that completes may still have test failures)
- `"failed"` — clearer than `"failure"` (standard convention)
- `"timed_out"` — specific failure mode that warrants its own status for debugging
The PRD's `"error"` is subsumed by `"failed"` (with `error_message` providing details).

Define as a type alias for clean reuse across the codebase:
```python
from typing import Literal
RunStatus = Literal["pending", "running", "completed", "failed", "timed_out"]
```
Do NOT use `StrEnum` — Pydantic v2 has [known serialization issues](https://github.com/pydantic/pydantic/issues/9790) with StrEnum in Literal union fields. Plain `Literal` strings are the recommended approach.

Update `tests/factories.py` (T004) to add factories for these models.

Create `dkmv/core/__init__.py` with a clean public API:
```python
from dkmv.core.models import SandboxConfig, BaseComponentConfig, BaseResult
from dkmv.core.sandbox import SandboxManager
from dkmv.core.runner import RunManager
from dkmv.core.stream import StreamParser
```

NOTE: Import SandboxManager, RunManager, StreamParser only after they are created (T031, T040, T046).
For T030, just export the models. Add the others as they are built.

#### Evaluation Checklist

- [ ] All models instantiate with valid data
- [ ] JSON round-trip works: `model.model_dump_json()` → `Model.model_validate_json()`
- [ ] Validation rejects invalid data (negative cost, invalid component name)
- [ ] Type check passes: `uv run mypy dkmv/core/models.py`
- [ ] `dkmv/core/__init__.py` exports key classes: SandboxConfig, BaseComponentConfig, BaseResult, SandboxManager, RunManager, StreamParser

---

### T031: Create SandboxManager Class

**PRD Reference:** Section 6/F3
**Depends on:** T030
**Blocks:** T032, T033, T034, T035, T036, T037, T051, T092
**User Stories:** US-22, US-23, US-24
**Estimated scope:** 1 hour

#### Description

Create the SandboxManager class skeleton with all method signatures. This wraps SWE-ReX DockerDeployment to provide container lifecycle management.

#### Acceptance Criteria

- [ ] Class with methods: start(), execute(), stream_claude(), stop(), write_file(), read_file(), get_container_name(), _create_session()
- [ ] All methods have correct type signatures
- [ ] Class accepts DKMVConfig in constructor
- [ ] SandboxManager supports multiple bash sessions for file-based streaming

#### Files to Create/Modify

- `dkmv/core/sandbox.py` — (create) SandboxManager class

#### Implementation Notes

Research SWE-ReX API at https://swe-rex.com/latest/usage/ for DockerDeployment and RemoteRuntime interfaces. Start with method stubs that raise `NotImplementedError`, then implement in subsequent tasks.

#### Evaluation Checklist

- [ ] Class importable from `dkmv.core.sandbox`
- [ ] Type check passes
- [ ] Method signatures match PRD Section 6/F3

---

### T032: Implement start()

**PRD Reference:** Section 6/F3
**Depends on:** T031
**Blocks:** T033, T034, T035, T036, T037
**User Stories:** US-06
**Estimated scope:** 2 hours

#### Description

Implement `SandboxManager.start()` using SWE-ReX DockerDeployment. This starts a Docker container and returns a session handle.

#### Acceptance Criteria

- [ ] Creates DockerDeployment with configured image and docker_args
- [ ] Adds `--memory=Xg --memory-swap=Xg` to docker_args from config
- [ ] Names container `dkmv-<component>-<short-uuid>`
- [ ] Creates persistent bash session via CreateBashSessionRequest
- [ ] Returns a session handle usable by other methods
- [ ] Handles startup timeout

#### Files to Create/Modify

- `dkmv/core/sandbox.py` — (modify) Implement start()

#### Implementation Notes

SWE-ReX API (v1.4.0):
- Config: `DockerDeploymentConfig(image="dkmv-sandbox:latest", docker_args=[...], startup_timeout=60, remove_container=True)`
- Deployment: `DockerDeployment(config)` as async context manager
- Session: `runtime.create_session(CreateBashSessionRequest())`
- Create a `SandboxSession` dataclass to hold: deployment, runtime, session_name, container_name

#### Evaluation Checklist

- [ ] Method implements SWE-ReX lifecycle correctly
- [ ] Container naming convention followed
- [ ] Memory limits applied

---

### T033: Implement execute()

**PRD Reference:** Section 6/F3
**Depends on:** T032
**Blocks:** T034
**User Stories:** US-06
**Estimated scope:** 1 hour

#### Description

Implement `SandboxManager.execute()` that runs a command inside the container via SWE-ReX runtime.

#### Acceptance Criteria

- [ ] Runs command via `runtime.run_in_session(BashAction(command=...))`
- [ ] Returns result with output and exit_code (from BashObservation)
- [ ] Supports configurable timeout per command
- [ ] Handles command failures gracefully

#### Files to Create/Modify

- `dkmv/core/sandbox.py` — (modify) Implement execute()

#### Implementation Notes

SWE-ReX API: `runtime.run_in_session(BashAction(command="ls -la"))` returns `BashObservation(output="...", exit_code=0)`.
Create a local `CommandResult` dataclass wrapping BashObservation for cleaner internal API.

#### Evaluation Checklist

- [ ] Commands execute and return results
- [ ] Timeout works correctly
- [ ] Error cases handled

---

### T034: Implement stream_claude() — File-Based Streaming Workaround

**PRD Reference:** Section 6/F3, Section 6/F5
**Depends on:** T033
**Blocks:** T038
**User Stories:** US-06, US-22
**Estimated scope:** 3-4 hours

#### Description

Implement `SandboxManager.stream_claude()` that runs Claude Code headless in the container and yields stream-json events in real-time.

**CRITICAL DESIGN NOTE:** SWE-ReX's `run_in_session(BashAction(...))` blocks until the command completes — it does NOT support streaming stdout. Since Claude Code can run for 5-30+ minutes, we use a file-based streaming workaround:

1. Launch Claude Code as a background process, redirecting stdout to a file
2. Create a second bash session to tail that file
3. Yield lines as they appear
4. Detect completion via process monitoring

#### Acceptance Criteria

- [ ] Runs Claude Code as background process: `claude -p "$(cat /tmp/dkmv_prompt.md)" --dangerously-skip-permissions --output-format stream-json --model <model> --max-turns <max_turns> > /tmp/dkmv_stream.jsonl 2>&1 &`
- [ ] Uses a second SWE-ReX session to poll/tail the output file
- [ ] Yields StreamEvent objects via AsyncIterator as lines appear
- [ ] Detects Claude Code completion (background process exits)
- [ ] Handles non-JSON lines gracefully (log them, don't crash)
- [ ] Includes `--max-budget-usd` flag when configured
- [ ] Prompt is written to file first (avoids shell escaping issues with complex prompts)
- [ ] Handles CLI hang: kills background process if still running 10s after result event

#### Files to Create/Modify

- `dkmv/core/sandbox.py` — (modify) Implement stream_claude()

#### Implementation Notes

The file-based streaming pattern:

```python
async def stream_claude(self, session, prompt: str, model: str, max_turns: int, max_budget_usd: float | None = None) -> AsyncIterator[dict]:
    # Step 1: Write prompt to file inside container (avoids shell escaping)
    await self.write_file(session, "/tmp/dkmv_prompt.md", prompt)

    # Step 2: Build Claude Code command
    cmd = 'claude -p "$(cat /tmp/dkmv_prompt.md)" --dangerously-skip-permissions'
    cmd += f' --output-format stream-json --model {model} --max-turns {max_turns}'
    if max_budget_usd:
        cmd += f' --max-budget-usd {max_budget_usd}'
    cmd += ' > /tmp/dkmv_stream.jsonl 2>&1 & echo $!'

    # Step 3: Launch as background process, capture PID
    result = await self.execute(session, cmd)
    pid = result.output.strip()

    # Step 4: Create a second bash session for tailing
    tail_session = await self._create_session()

    # Step 5: Poll the output file, yielding new lines
    lines_read = 0
    while True:
        # Check if process is still running
        check = await self.execute(session, f"kill -0 {pid} 2>/dev/null; echo $?")
        is_running = check.output.strip() == "0"

        # Read new lines from file
        tail_result = await self.execute(tail_session, f"tail -n +{lines_read + 1} /tmp/dkmv_stream.jsonl 2>/dev/null")
        new_lines = tail_result.output.strip().split('\n') if tail_result.output.strip() else []

        for line in new_lines:
            lines_read += 1
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                logger.warning(f"Non-JSON line: {line}")

        if not is_running and not new_lines:
            break  # Process done and all lines read

        await asyncio.sleep(0.5)  # Poll interval
```

Key considerations:
- Write prompt to file first — this completely avoids shell escaping issues
- The background process PID lets us detect completion
- `tail -n +N` reads from line N onward (1-indexed), so we track `lines_read`
- Poll interval of 0.5s balances responsiveness with overhead
- The second bash session is needed because SWE-ReX blocks on each command

Research: SWE-ReX `BashAction` blocks until completion. There is no streaming or callback API.

KNOWN ISSUE: Claude Code CLI may hang after emitting the final "result" event in
stream-json mode. The file-based streaming workaround naturally handles this:
- Once we see a `type: "result"` event, we know Claude is done
- We can kill the background process if it hasn't exited after a grace period
- Add a post-result timeout: if process still running 10s after result event, `kill {pid}`

NOTE: Claude Code also supports `--include-partial-messages` which emits token-by-token
content_block_delta events. For v1, we do NOT use this flag — we only process complete
message events. This keeps the StreamParser simpler. Add as a v2 option if real-time
typing display is desired.

v2 EXTENSIBILITY NOTE: In v1, stream_claude() is the only agent execution method.
In v2, consider extracting an AgentExecutor protocol:

```python
class AgentExecutor(Protocol):
    async def execute(self, session, prompt, config) -> AsyncIterator[dict]: ...

class ClaudeCodeExecutor(AgentExecutor): ...  # v1
class CodexExecutor(AgentExecutor): ...       # v2
```

For now, keep stream_claude() in SandboxManager but:
1. Keep the method focused (only Claude Code invocation + streaming)
2. Don't mix agent-specific logic with container lifecycle
3. Parameters should be agent-agnostic where possible (prompt, model, max_turns)

StreamEvent type should be defined in `dkmv/core/models.py` or `dkmv/core/stream.py`.

#### Evaluation Checklist

- [ ] Claude Code launched as background process
- [ ] Lines yielded in real-time (not blocked until completion)
- [ ] Process completion detected correctly
- [ ] Prompt written to file (no shell escaping issues)
- [ ] Non-JSON lines handled gracefully
- [ ] `--max-budget-usd` flag included when configured

---

### T035: Implement stop()

**PRD Reference:** Section 6/F3
**Depends on:** T032
**Blocks:** T093
**User Stories:** US-23, US-24
**Estimated scope:** 30 min

#### Description

Implement `SandboxManager.stop()` with keep_alive logic. If `keep_alive=True`, skip container removal.

#### Acceptance Criteria

- [ ] Default behavior: stop and remove container
- [ ] `keep_alive=True`: leave container running
- [ ] Clean up SWE-ReX resources in both cases
- [ ] Safe to call multiple times (idempotent)

#### Files to Create/Modify

- `dkmv/core/sandbox.py` — (modify) Implement stop()

#### Implementation Notes

Use SWE-ReX's deployment cleanup. For keep_alive, skip the `remove_container` step but still close the runtime session.

#### Evaluation Checklist

- [ ] Container removed when keep_alive=False
- [ ] Container kept when keep_alive=True
- [ ] Idempotent (no error on double-stop)

---

### T036: Implement write_file() and read_file()

**PRD Reference:** Section 6/F3
**Depends on:** T032
**Blocks:** T054
**User Stories:** N/A (infrastructure)
**Estimated scope:** 30 min

#### Description

Implement file I/O inside the container using SWE-ReX's direct runtime methods.

#### Acceptance Criteria

- [ ] `write_file(path, content)` calls `runtime.write_file(path, content)`
- [ ] `read_file(path)` calls `runtime.read_file(path)` and returns content string
- [ ] Handles missing files gracefully

#### Files to Create/Modify

- `dkmv/core/sandbox.py` — (modify) Implement write_file() and read_file()

#### Implementation Notes

SWE-ReX API (v1.4.0): `runtime.write_file(path, content)` and `runtime.read_file(path)` are direct methods on the runtime — NOT request objects. Do NOT use WriteFileRequest or ReadFileRequest (these don't exist).

#### Evaluation Checklist

- [ ] Write then read returns same content
- [ ] Error on read of nonexistent file

---

### T037: Implement Env Var Forwarding and Git Auth

**PRD Reference:** Section 6/F3
**Depends on:** T032
**Blocks:** T054
**User Stories:** US-03
**Estimated scope:** 1 hour

#### Description

Implement environment variable forwarding (ANTHROPIC_API_KEY, GITHUB_TOKEN) to the container, and git authentication setup inside the container.

#### Acceptance Criteria

- [ ] ANTHROPIC_API_KEY forwarded via docker_args `-e`
- [ ] GITHUB_TOKEN forwarded via docker_args `-e`
- [ ] Git auth setup: `echo "$GITHUB_TOKEN" | gh auth login --with-token && gh auth setup-git`
- [ ] Works for both public and private repos

#### Files to Create/Modify

- `dkmv/core/sandbox.py` — (modify) Add env forwarding to start(), add git auth helper

#### Implementation Notes

Env vars should be added to `docker_args` as `["-e", "ANTHROPIC_API_KEY=...", "-e", "GITHUB_TOKEN=..."]`. Git auth should be executed as a command after container start, before any git operations.

#### Evaluation Checklist

- [ ] Env vars available inside container
- [ ] Git auth configured correctly
- [ ] Private repo clone works (when GITHUB_TOKEN has repo scope)

---

### T038: Implement Asyncio Timeout Wrapper

**PRD Reference:** Section 6/F3, Section 9
**Depends on:** T034
**Blocks:** T052
**User Stories:** US-11
**Estimated scope:** 30 min

#### Description

Implement an asyncio timeout wrapper around Claude Code execution, based on the `timeout_minutes` configuration.

#### Acceptance Criteria

- [ ] Wraps stream_claude() with `asyncio.wait_for()` or `asyncio.timeout()`
- [ ] Raises a clear timeout error with duration info
- [ ] Default timeout from config (30 minutes)

#### Files to Create/Modify

- `dkmv/core/sandbox.py` — (modify) Add timeout wrapper

#### Implementation Notes

Use `asyncio.timeout()` (Python 3.11+) for cleaner syntax. The timeout should apply to the entire Claude Code execution, not individual lines.

#### Evaluation Checklist

- [ ] Timeout triggers after configured duration
- [ ] Clear error message on timeout
- [ ] No timeout when set to 0 or None

---

### T039: Write SandboxManager Tests

**PRD Reference:** Section 8/Task 2.1, Section 9.5.1
**Depends on:** T031-T038
**Blocks:** Nothing
**User Stories:** N/A
**Estimated scope:** 2 hours

#### Description

Write unit tests (with mocked SWE-ReX) and integration tests for SandboxManager.

#### Acceptance Criteria

- [ ] Unit tests mock DockerDeployment and test lifecycle
- [ ] Unit tests verify container naming convention
- [ ] Unit tests verify env var forwarding
- [ ] Integration tests use mock fixtures from T005/T006
- [ ] All tests pass

#### Files to Create/Modify

- `tests/unit/test_sandbox.py` — (create) Unit tests
- `tests/integration/test_sandbox.py` — (create) Integration tests

#### Implementation Notes

Use AsyncMock for SWE-ReX mocks. Test the happy path and error cases (startup failure, command failure, timeout).

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_sandbox.py -v` passes
- [ ] `uv run pytest tests/integration/test_sandbox.py -v` passes
- [ ] Good coverage of error paths

---

### T040: Create RunManager Class

**PRD Reference:** Section 6/F4
**Depends on:** T030
**Blocks:** T041, T042, T043, T044, T051
**User Stories:** US-25
**Estimated scope:** 1 hour

#### Description

Create the RunManager class that tracks every component execution with a unique run ID, directory structure, and result files.

#### Acceptance Criteria

- [ ] Class with methods: start_run(), save_result(), append_stream(), list_runs(), get_run()
- [ ] Constructor accepts output_dir from DKMVConfig
- [ ] Creates run directories under `outputs/runs/<run-id>/`
- [ ] `RunStatus` type alias defined in models.py (see T030): `Literal["pending", "running", "completed", "failed", "timed_out"]`
- [ ] `start_run()` sets status to "running"
- [ ] `save_result()` updates status to "completed" or "failed"
- [ ] Status persisted in result.json

#### Files to Create/Modify

- `dkmv/core/runner.py` — (create) RunManager class

#### Implementation Notes

Run directory structure from PRD Section 6/F4:
```
outputs/runs/<run-id>/
├── config.json
├── result.json
├── stream.jsonl
├── prompt.md
└── logs/
    └── run.log
```

#### Evaluation Checklist

- [ ] Class importable from `dkmv.core.runner`
- [ ] Type check passes

---

### T041: Implement Run ID Generation and Directory Creation

**PRD Reference:** Section 6/F4
**Depends on:** T040
**Blocks:** T042, T043
**User Stories:** US-20
**Estimated scope:** 30 min

#### Description

Implement `start_run()` which generates a unique run ID, creates the run directory structure, and saves initial config.

#### Acceptance Criteria

- [ ] Run ID is short and human-readable (e.g., 8-char hex from uuid4)
- [ ] Creates directory: `outputs/runs/<run-id>/`
- [ ] Creates subdirectory: `outputs/runs/<run-id>/logs/`
- [ ] Saves `config.json` with the component configuration

#### Files to Create/Modify

- `dkmv/core/runner.py` — (modify) Implement start_run()

#### Implementation Notes

Use `uuid.uuid4().hex[:8]` for short, collision-resistant IDs. Include timestamp in the config for ordering.

#### Evaluation Checklist

- [ ] Run ID is unique across calls
- [ ] Directory structure created correctly
- [ ] config.json written and valid

---

### T042: Implement save_result() and append_stream()

**PRD Reference:** Section 6/F4
**Depends on:** T041
**Blocks:** T044
**User Stories:** US-25
**Estimated scope:** 1 hour

#### Description

Implement `save_result()` to write the final result.json, and `append_stream()` to append stream-json events to stream.jsonl.

#### Acceptance Criteria

- [ ] `save_result()` writes BaseResult as JSON to `result.json`
- [ ] `append_stream()` appends a JSON line to `stream.jsonl`
- [ ] Prompt saved to `prompt.md` (add save_prompt method if needed)
- [ ] session_id included in result.json when available
- [ ] File I/O is atomic where possible (write to temp then rename)

#### Files to Create/Modify

- `dkmv/core/runner.py` — (modify) Implement save_result(), append_stream()

#### Implementation Notes

Use `model.model_dump_json(indent=2)` for result.json. Use `json.dumps()` + newline for JSONL. Consider adding a `save_prompt()` method for the prompt.md file.

#### Evaluation Checklist

- [ ] result.json is valid JSON and deserializable back to model
- [ ] stream.jsonl has one JSON object per line
- [ ] prompt.md content matches what was saved

---

### T043: Implement list_runs() and get_run()

**PRD Reference:** Section 6/F4
**Depends on:** T041
**Blocks:** T090, T091
**User Stories:** US-20, US-21
**Estimated scope:** 1 hour

#### Description

Implement `list_runs()` to scan the output directory and return summaries, and `get_run()` to load full details for a specific run.

#### Acceptance Criteria

- [ ] `list_runs()` returns RunSummary objects sorted by timestamp (newest first)
- [ ] Supports optional filters: component, feature name, limit
- [ ] `get_run()` loads result.json into a RunDetail object
- [ ] Handles missing or corrupted run directories gracefully

#### Files to Create/Modify

- `dkmv/core/runner.py` — (modify) Implement list_runs(), get_run()
- `dkmv/core/models.py` — (modify) Add RunSummary, RunDetail models if needed

#### Implementation Notes

Create RunSummary (lightweight) and RunDetail (full) models. list_runs scans `outputs/runs/*/result.json`. Handle the case where result.json doesn't exist (run in progress or crashed).

#### Evaluation Checklist

- [ ] List returns correct runs in order
- [ ] Filters work correctly
- [ ] Missing runs return empty, not errors

---

### T044: Implement session_id Tracking

**PRD Reference:** Section 6/F4
**Depends on:** T042
**Blocks:** Nothing
**User Stories:** US-25
**Estimated scope:** 30 min

#### Description

Extract and save `session_id` from the stream-json `type: "result"` event into result.json. This enables potential resume in v2+.

#### Acceptance Criteria

- [ ] session_id extracted from stream-json result event
- [ ] Saved in BaseResult.session_id field
- [ ] Works when result event is present
- [ ] Gracefully handles missing session_id

#### Files to Create/Modify

- `dkmv/core/runner.py` — (modify) Add session_id extraction logic

#### Implementation Notes

The `type: "result"` event in stream-json includes `session_id`. Parse this from the final event during stream processing.

#### Evaluation Checklist

- [ ] session_id saved when available
- [ ] No error when missing

---

### T045: Write RunManager Tests

**PRD Reference:** Section 8/Task 0.1, Section 9.5.1
**Depends on:** T040-T044
**Blocks:** Nothing
**User Stories:** N/A
**Estimated scope:** 1-2 hours

#### Description

Write unit tests for RunManager: file I/O, JSON round-trips, listing, filtering.

#### Acceptance Criteria

- [ ] Test: start_run creates directory and config.json
- [ ] Test: save_result writes valid JSON
- [ ] Test: append_stream creates valid JSONL
- [ ] Test: list_runs returns correct results
- [ ] Test: get_run loads full details
- [ ] Test: session_id tracked correctly
- [ ] All tests use `tmp_path` for isolation

#### Files to Create/Modify

- `tests/unit/test_runner.py` — (create) RunManager unit tests

#### Implementation Notes

Use pytest `tmp_path` fixture for all file operations. Create RunManager with `output_dir=tmp_path / "outputs"`.

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_runner.py -v` passes
- [ ] All edge cases covered

---

### T046: Create StreamParser Class

**PRD Reference:** Section 6/F5
**Depends on:** T030
**Blocks:** T047, T048, T051
**User Stories:** US-06
**Estimated scope:** 1 hour

#### Description

Create the StreamParser class that handles parsing and rendering of Claude Code's stream-json output.

#### Acceptance Criteria

- [ ] Class with methods for parsing and rendering
- [ ] Accepts verbose flag for full JSON mode
- [ ] Defines StreamEvent types for different event categories

#### Files to Create/Modify

- `dkmv/core/stream.py` — (create) StreamParser class

#### Implementation Notes

Define StreamEvent as a Pydantic model or dataclass with fields: type, subtype, content, raw. Event types from PRD Section 6/F5: "system", "assistant", "user", "result".

v2 EXTENSIBILITY NOTE: StreamParser is coupled to Claude Code's stream-json format.
In v2, consider a StreamParser protocol:

```python
class StreamParser(Protocol):
    def parse_line(self, line: str) -> StreamEvent | None: ...
    def render_event(self, event: StreamEvent) -> None: ...
```

For v1, keep the single implementation but use clean interfaces.

#### Evaluation Checklist

- [ ] Class importable from `dkmv.core.stream`
- [ ] Type check passes

---

### T047: Implement Line-by-Line JSON Parsing

**PRD Reference:** Section 6/F5
**Depends on:** T046
**Blocks:** T048
**User Stories:** US-06
**Estimated scope:** 1 hour

#### Description

Implement parsing of stream-json lines into typed StreamEvent objects, handling each event type appropriately.

#### Acceptance Criteria

- [ ] Parses `type: "system"` with `subtype: "init"` (session start, session_id)
- [ ] Parses `type: "assistant"` (text content, tool_use blocks)
- [ ] Parses `type: "user"` (tool results)
- [ ] Parses `type: "result"` (final: cost, duration, turns, session_id, is_error)
- [ ] Handles malformed JSON gracefully (logs warning, continues)

#### Files to Create/Modify

- `dkmv/core/stream.py` — (modify) Implement parsing logic

#### Implementation Notes

Use `json.loads()` per line. Extract relevant fields based on `type` field. For assistant events, extract text content from the message content blocks.

#### Evaluation Checklist

- [ ] All event types parsed correctly
- [ ] Malformed lines don't crash
- [ ] Final result extracted correctly

---

### T048: Implement Terminal Rendering with Rich

**PRD Reference:** Section 6/F5
**Depends on:** T047
**Blocks:** Nothing
**User Stories:** US-06
**Estimated scope:** 1-2 hours

#### Description

Implement real-time terminal rendering using the `rich` library, with color-coding for different event types.

#### Acceptance Criteria

- [ ] Assistant text: default color
- [ ] Tool use (bash commands): cyan with `$ ` prefix
- [ ] Tool results: dim/gray
- [ ] Errors: red
- [ ] Cost/timing: green at end
- [ ] Verbose mode: shows full JSON events

#### Files to Create/Modify

- `dkmv/core/stream.py` — (modify) Add rendering logic

#### Implementation Notes

Use `rich.console.Console` for output. Use `rich.text.Text` with styles for coloring. Consider `rich.live.Live` for updating output in place for long-running operations.

#### Evaluation Checklist

- [ ] Output is readable and color-coded
- [ ] Verbose mode shows raw JSON
- [ ] No crashes on unexpected event types

---

### T049: Write StreamParser Tests

**PRD Reference:** Section 8/Task 0.1, Section 9.5.1
**Depends on:** T046-T048
**Blocks:** Nothing
**User Stories:** N/A
**Estimated scope:** 1-2 hours

#### Description

Write unit tests for StreamParser: parse hardcoded stream-json lines, verify event extraction and rendering.

#### Acceptance Criteria

- [ ] Test: parse each event type correctly
- [ ] Test: handle malformed JSON
- [ ] Test: extract final result (cost, duration, turns, session_id)
- [ ] Test: verbose mode shows full events

#### Files to Create/Modify

- `tests/unit/test_stream.py` — (create) StreamParser unit tests

#### Implementation Notes

Create sample stream-json lines as test fixtures. Test parsing logic separately from rendering (rendering can be tested by capturing console output).

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_stream.py -v` passes
- [ ] Good coverage of event types and edge cases

---

### T050: Create Component Registry

**PRD Reference:** Section 6/F6
**Depends on:** T030
**Blocks:** T051, T060, T073, T078, T083
**User Stories:** N/A (infrastructure)
**Estimated scope:** 30 min

#### Description

Create the component registry in `dkmv/components/__init__.py` with `register_component()`, `get_component()`, and `list_components()`.

#### Acceptance Criteria

- [ ] `register_component(name)` decorator registers a component class
- [ ] `get_component(name)` returns the registered class
- [ ] `list_components()` returns sorted list of registered names
- [ ] `get_component("unknown")` raises KeyError with helpful message

#### Files to Create/Modify

- `dkmv/components/__init__.py` — (modify) Add registry code

#### Implementation Notes

Use the exact registry pattern from PRD Section 6/F6. Module-level `_REGISTRY` dict.

#### Evaluation Checklist

- [ ] Registry works with decorator pattern
- [ ] Error message is helpful

---

### T051: Create BaseComponent ABC

**PRD Reference:** Section 6/F6
**Depends on:** T050, T031, T040, T046
**Blocks:** T052, T053, T063, T074, T079, T084
**User Stories:** All component stories
**Estimated scope:** 1-2 hours

#### Description

Create the BaseComponent abstract base class with Generic[C, R] type parameters, abstract methods, and constructor.

#### Acceptance Criteria

- [ ] `BaseComponent(ABC, Generic[C, R])` class
- [ ] Constructor accepts: global_config, sandbox, run_manager, stream_parser
- [ ] Abstract property: `name -> str`
- [ ] Abstract methods: `build_prompt(config: C) -> str`, `parse_result(raw: dict, config: C) -> R`
- [ ] Hook method: `setup_workspace(session, config: C) -> None` (default no-op)
- [ ] `_load_prompt_template() -> str` method

#### Files to Create/Modify

- `dkmv/components/base.py` — (create) BaseComponent ABC

#### Implementation Notes

Use the exact interface from PRD Section 6/F6. TypeVars `C` bound to BaseComponentConfig, `R` bound to BaseResult.

v2 EXTENSIBILITY: BaseComponent.run() step 7 calls sandbox.stream_claude().
If v2 adds other agents, this step should dispatch to the right executor
based on a config field (e.g., config.agent_type = "claude" | "codex").
For v1, hardcode to stream_claude(). Leave a comment marking the extension point.

#### Evaluation Checklist

- [ ] Cannot instantiate directly (ABC)
- [ ] Type check passes with concrete subclass
- [ ] All abstract methods enforced

---

### T052: Implement 12-step run() Method

**PRD Reference:** Section 6/F6
**Depends on:** T051
**Blocks:** T054, T055, T056
**User Stories:** All component stories
**Estimated scope:** 2-3 hours

#### Description

Implement the standard `run()` method that all components share. This is the 12-step lifecycle from PRD Section 6/F6.

#### Acceptance Criteria

- [ ] Step 1: Validate inputs
- [ ] Step 2: Create run via RunManager
- [ ] Step 3: Start sandbox container
- [ ] Step 4: Set up workspace (clone, branch, inject files)
- [ ] Step 5: Write CLAUDE.md for agent context
- [ ] Step 6: Build prompt (calls abstract method)
- [ ] Step 7: Run Claude Code, stream output
- [ ] Step 8: Collect results from git state + stream-json
- [ ] Step 9: Git commit + push
- [ ] Step 10: Save run result (including session_id)
- [ ] Step 11: Tear down container (unless keep_alive)
- [ ] Step 12: Return typed result
- [ ] Error handling at each step with proper cleanup
- [ ] On error: save partial result with status="failed" and error_message
- [ ] On timeout: save partial result with status="timed_out"
- [ ] Container stopped even on error (try/finally)
- [ ] Partial stream.jsonl preserved (whatever was captured before failure)

#### Files to Create/Modify

- `dkmv/components/base.py` — (modify) Implement run()

#### Implementation Notes

Use try/finally for cleanup (step 11). Save partial results on error. The prompt (step 6) should be saved to the run directory before execution. Each step should log its progress.

Error recovery pattern:
```python
try:
    ... run lifecycle ...
    result.status = "completed"
except asyncio.TimeoutError:
    result.status = "timed_out"
    result.error_message = f"Timed out after {timeout_minutes} minutes"
except Exception as e:
    result.status = "failed"
    result.error_message = str(e)
finally:
    run_manager.save_result(result)  # Always save, even partial
    await sandbox.stop(session)       # Always clean up
```

#### Evaluation Checklist

- [ ] Full lifecycle executes in order
- [ ] Cleanup runs even on error
- [ ] Partial results saved on failure

---

### T053: Implement _load_prompt_template()

**PRD Reference:** Section 6/F6
**Depends on:** T051
**Blocks:** T065, T075, T080, T085
**User Stories:** N/A (infrastructure)
**Estimated scope:** 30 min

#### Description

Implement the prompt template loader that reads the co-located `prompt.md` from each component's subpackage using `importlib.resources`.

#### Acceptance Criteria

- [ ] Reads `prompt.md` from `dkmv.components.{name}` package
- [ ] Returns template content as string
- [ ] Raises clear error if template file missing
- [ ] Verify prompt.md is accessible via importlib.resources after `uv build`

#### Files to Create/Modify

- `dkmv/components/base.py` — (modify) Implement _load_prompt_template()

#### Implementation Notes

Use `importlib.resources.files(pkg).joinpath("prompt.md").read_text()` as shown in PRD Section 6/F6. The `pkg` is constructed from `self.name`.

NOTE: This depends on prompt.md files being included in the wheel build.
Verify pyproject.toml has hatchling force-include config (see T010).
Test with: `uv build && uv run python -c "from importlib.resources import files; print(files('dkmv.components.dev').joinpath('prompt.md').read_text()[:50])"`

#### Evaluation Checklist

- [ ] Template loaded correctly
- [ ] Error message helpful when template missing

---

### T054: Implement Workspace Setup

**PRD Reference:** Section 6/F6, Section 6/F7
**Depends on:** T052, T036, T037
**Blocks:** Nothing
**User Stories:** US-05, US-08
**Estimated scope:** 2 hours

#### Description

Implement the workspace setup logic in BaseComponent.run(): clone repo, checkout/create branch, configure git auth, write CLAUDE.md, add .dkmv/ to .gitignore.

#### Acceptance Criteria

- [ ] Clones repo inside container
- [ ] Creates new branch (`feature/<name>-dev`) or checks out existing branch
- [ ] Runs `gh auth login` and `gh auth setup-git`
- [ ] Writes `.claude/CLAUDE.md` with agent context (template is conditional — PRD reference only included when component has a PRD)
- [ ] Adds `.dkmv/` to `.gitignore`
- [ ] PRD copying is NOT in base setup — components with `prd_path` (Dev, QA, Judge) copy the PRD in their own `setup_workspace()` override. Docs component has no PRD.

#### Files to Create/Modify

- `dkmv/components/base.py` — (modify) Implement workspace setup in run()

#### Implementation Notes

CLAUDE.md template from PRD Section 6/F6. The template is built dynamically — the PRD
reference line is only included when the component has a PRD:

```python
claude_md = f"# DKMV Agent Context\n\nYou are running as part of the DKMV pipeline ({self.name} stage).\n"
if hasattr(config, 'prd_path') and config.prd_path:
    claude_md += "The PRD for this feature is at .dkmv/prd.md.\n"
claude_md += "\n## Guidelines\n- Follow existing code patterns and conventions\n"
claude_md += "- All work should be committed with meaningful messages\n"
claude_md += f"- Tag commits with [dkmv-{self.name}]\n"
```

Use `sandbox.execute()` for git commands and `sandbox.write_file()` for CLAUDE.md.

PRD copying strategy:
- Base `setup_workspace()` handles: clone, branch, git auth, CLAUDE.md, .gitignore
- Components with `prd_path` (Dev, QA, Judge) override `setup_workspace()` to also copy the PRD to `.dkmv/prd.md` via `sandbox.write_file()`. Call `super().setup_workspace()` first.
- Docs component does NOT copy a PRD — it has no `prd_path`

.gitignore strategy varies by component:
- Dev component: adds `.dkmv/` to .gitignore (artifacts are internal)
- QA component: adds `.dkmv/` to .gitignore BUT uses `git add -f .dkmv/qa_report.json` (force-add)
- Judge component: adds `.dkmv/` to .gitignore BUT uses `git add -f .dkmv/verdict.json` (force-add)
- Docs component: adds `.dkmv/` to .gitignore (no artifacts to commit)

The `git add -f` flag bypasses .gitignore for specific files. This keeps the workspace clean while allowing QA/Judge artifacts to be committed.

#### Evaluation Checklist

- [ ] Repo cloned successfully
- [ ] Branch created/checked out
- [ ] CLAUDE.md present in workspace (with PRD reference only when component has prd_path)
- [ ] .gitignore updated
- [ ] PRD is NOT copied by base setup (components handle it in their own setup_workspace)

---

### T055: Implement Feedback Synthesis

**PRD Reference:** Section 6/F6 (Feedback Synthesis)
**Depends on:** T052
**Blocks:** T067
**User Stories:** US-09
**Estimated scope:** 1 hour

#### Description

Implement the feedback synthesis transformation that converts raw Judge verdict JSON into a developer-oriented feedback brief.

#### Acceptance Criteria

- [ ] Extracts issues from verdict JSON
- [ ] Sorts by severity (critical → major → minor)
- [ ] Converts to actionable instructions
- [ ] Strips Judge reasoning and confidence scores
- [ ] Outputs structured `.dkmv/feedback.json` format

#### Files to Create/Modify

- `dkmv/components/base.py` — (modify) Add feedback synthesis method

#### Implementation Notes

Output format from PRD:
```json
{
  "summary": "3 issues found: 1 critical, 2 minor",
  "action_items": [
    {"priority": 1, "file": "src/auth.py", "line": 42, "instruction": "...", "severity": "critical"}
  ]
}
```

This is a Python-only transformation — no LLM call.

#### Evaluation Checklist

- [ ] Synthesis produces valid JSON
- [ ] Issues sorted by severity
- [ ] No Judge reasoning leaked to Dev

---

### T056: Implement Shared Teardown

**PRD Reference:** Section 6/F6
**Depends on:** T052
**Blocks:** Nothing
**User Stories:** N/A (infrastructure)
**Estimated scope:** 30 min

#### Description

Implement the shared teardown logic: git add, commit with component tag, push to remote.

#### Acceptance Criteria

- [ ] `git add -A` stages all changes
- [ ] `git commit -m "feat: implement <feature> [dkmv-<component>]"` commits
- [ ] `git push origin <branch>` pushes to remote
- [ ] Handles case where nothing to commit (no error)
- [ ] `.dkmv/` in .gitignore keeps workspace clean
- [ ] Component-specific artifacts committed via `git add -f` (QA: qa_report.json, Judge: verdict.json)

#### Files to Create/Modify

- `dkmv/components/base.py` — (modify) Implement teardown in run()

#### Implementation Notes

Use `sandbox.execute()` for git commands. Check exit code of `git status --porcelain` to detect changes before committing. Components can override this behavior (QA/Judge explicitly add .dkmv/ artifacts).

Teardown should support an optional `artifacts_to_commit` list that components can specify.
For QA/Judge, this would be `[".dkmv/qa_report.json"]` or `[".dkmv/verdict.json"]`.
The teardown code: `git add -f <artifact>` for each, then `git add -A && git commit ...`

#### Evaluation Checklist

- [ ] Commit created with correct message format
- [ ] Push succeeds
- [ ] No error when nothing to commit

---

### T057: Write BaseComponent Lifecycle Tests

**PRD Reference:** Section 8/Task 2.4
**Depends on:** T050-T056
**Blocks:** Nothing
**User Stories:** N/A
**Estimated scope:** 2 hours

#### Description

Write tests for the full BaseComponent lifecycle using a mock concrete component.

#### Acceptance Criteria

- [ ] Create a `MockComponent(BaseComponent[MockConfig, MockResult])` for testing
- [ ] Test: full 12-step lifecycle with mocked sandbox
- [ ] Test: error handling and cleanup
- [ ] Test: prompt template loading
- [ ] Test: workspace setup (git clone, branch, CLAUDE.md)
- [ ] Test: feedback synthesis
- [ ] Test: component registry

#### Files to Create/Modify

- `tests/unit/test_base_component.py` — (create) BaseComponent lifecycle tests

#### Implementation Notes

Create a minimal MockComponent that implements abstract methods. Use AsyncMock for sandbox. Verify each step is called in order.

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_base_component.py -v` passes
- [ ] All lifecycle steps tested
- [ ] Error paths covered

---

## Phase Completion Checklist

- [ ] All tasks T030-T057 completed
- [ ] Mock component runs full lifecycle
- [ ] RunManager creates/lists/shows runs
- [ ] StreamParser renders stream-json correctly
- [ ] All tests passing: `uv run pytest tests/unit/ tests/integration/ -v`
- [ ] Lint clean: `uv run ruff check .`
- [ ] Type check clean: `uv run mypy dkmv/`
- [ ] Progress updated in tasks.md and progress.md
