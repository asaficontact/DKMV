# Multi-Agent Adapter Architecture User Stories

## Summary

21 user stories across 6 categories, serving 4 personas: Claude Code Developer, Codex CLI Developer, Multi-Agent Developer, and CI/CD Pipeline Operator.

## Traceability Matrix

| US ID | Title | Feature | Task(s) | Status |
|-------|-------|---------|---------|--------|
| US-01 | Adapter protocol defines extensible agent interface | F1 | T010 | [ ] |
| US-02 | Adapter registry resolves agents by name | F1 | T011, T020 | [ ] |
| US-03 | Claude adapter produces identical behavior | F2 | T012-T015, T021 | [ ] |
| US-04 | Existing tests pass after refactor | F2 | T016-T019, T022 | [ ] |
| US-05 | Codex adapter constructs exec commands | F3 | T030, T033, T044, T046 | [ ] |
| US-06 | Codex adapter parses JSONL stream events | F3 | T031-T032, T046 | [ ] |
| US-07 | Codex adapter handles resume sessions | F3 | T032, T046 | [ ] |
| US-08 | Agent resolved from task YAML field | F4 | T034-T035, T039, T047 | [ ] |
| US-09 | Agent resolved through full 7-level cascade | F4 | T037-T040, T047 | [ ] |
| US-10 | Agent inferred from model prefix | F5 | T041, T048 | [ ] |
| US-11 | Model-agent mismatch produces clear error | F5 | T042, T048, T091 | [ ] |
| US-12 | Docker image contains both agents | F6 | T060-T061, T070 | [ ] |
| US-13 | Build command accepts codex version flag | F6 | T062, T071 | [ ] |
| US-14 | Init discovers Codex credentials | F7 | T063-T064, T072 | [ ] |
| US-15 | Non-interactive init auto-detects credentials | F7 | T065-T066, T072-T073 | [ ] |
| US-16 | Mixed-agent component passes all credentials | F8 | T067-T069, T074 | [ ] |
| US-17 | Per-task adapter instantiation in mixed components | F8 | T040, T074 | [ ] |
| US-18 | Codex events normalized to StreamEvent | F9 | T031-T032, T045, T046 | [ ] |
| US-19 | Stream rendering works for both agents | F9 | T045, T046 | [ ] |
| US-20 | CLI --agent flag selects agent for run | F10 | T043, T049, T094 | [ ] |
| US-21 | Existing CLI commands work without --agent | F10 | T043, T049, T050 | [ ] |

---

## Stories by Category

### Adapter Foundation (US-01 through US-04)

#### US-01: Adapter protocol defines extensible agent interface

> As a developer extending DKMV, I want a formal `AgentAdapter` Protocol so I can implement new agent backends by satisfying a well-defined interface.

**Acceptance Criteria:**
- [ ] `AgentAdapter` Protocol is defined in `dkmv/adapters/base.py` with all required methods: `build_command()`, `parse_event()`, `is_result_event()`, `extract_result()`, `instructions_path`, `gitignore_entries`, `get_auth_env_vars()`, `get_docker_args()`, `supports_resume()`, `supports_budget()`, `supports_max_turns()`, `default_model`, `validate_model()`
- [ ] `StreamResult` dataclass is defined with `cost`, `turns`, and `session_id` fields
- [ ] Protocol uses `typing.Protocol` (structural typing), not ABC inheritance
- [ ] `mypy` validates that concrete adapters satisfy the Protocol at type-check time
- [ ] A class implementing all Protocol methods passes `isinstance` checks when `runtime_checkable` is used (or satisfies structural typing in mypy)

**Feature:** F1 | **Tasks:** T010 | **Priority:** Must-have

#### US-02: Adapter registry resolves agents by name

> As the DKMV orchestration layer, I want a `get_adapter(name)` factory so I can obtain the correct adapter instance from a string identifier.

**Acceptance Criteria:**
- [ ] `get_adapter("claude")` returns a `ClaudeCodeAdapter` instance
- [ ] `get_adapter("codex")` returns a `CodexCLIAdapter` instance (after Phase 2)
- [ ] `get_adapter("unknown")` raises a clear error with the list of registered adapters
- [ ] The registry is defined in `dkmv/adapters/__init__.py`
- [ ] Registry tests cover valid lookups, invalid lookups, and error messages

**Feature:** F1 | **Tasks:** see matrix | **Priority:** Must-have

#### US-03: Claude adapter produces identical behavior

> As a Claude Code Developer, I want the refactored adapter to produce byte-identical CLI commands and stream parsing so my existing workflows are completely unaffected.

**Acceptance Criteria:**
- [ ] `ClaudeCodeAdapter.build_command()` produces the exact same shell command string as the current hardcoded implementation in `sandbox.py:177-219`
- [ ] Command includes `claude -p`, `--dangerously-skip-permissions`, `--verbose`, `--output-format stream-json`, `--model`, `--max-turns`, optional `--max-budget-usd`, stdin redirect, stdout to `/tmp/dkmv_stream.jsonl`, stderr to `/tmp/dkmv_stream.err`, background with `& echo $!`
- [ ] `parse_event()` handles all 4 Claude event types (system, assistant, user, result) identically to current `StreamParser`
- [ ] `instructions_path` returns `.claude/CLAUDE.md`
- [ ] `gitignore_entries` returns `['.claude/']`
- [ ] A regression test asserts the exact command string output

**Feature:** F2 | **Tasks:** see matrix | **Priority:** Must-have

#### US-04: Existing tests pass after refactor

> As a Claude Code Developer, I want all 720+ existing tests to pass without modification after the adapter refactor so I can be confident nothing is broken.

**Acceptance Criteria:**
- [ ] `stream_claude()` on `SandboxManager` retains its exact current method signature
- [ ] All 30+ test mocks that assign `sandbox.stream_claude = mock_stream` continue to work
- [ ] `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short` passes with zero failures and zero modified test files
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy dkmv/` all pass clean
- [ ] Coverage remains >= 80% (current: 91.89%)

**Feature:** F2 | **Tasks:** see matrix | **Priority:** Must-have

### Codex Adapter (US-05 through US-07)

#### US-05: Codex adapter constructs exec commands

> As a Codex CLI Developer, I want DKMV to construct correct `codex exec` commands so the Codex agent runs autonomously inside the Docker container.

**Acceptance Criteria:**
- [ ] `build_command()` produces a command starting with `cd /home/dkmv/workspace && env CODEX_API_KEY=<key> codex exec`
- [ ] Command includes flags: `--json`, `--full-auto`, `--sandbox danger-full-access`, `--skip-git-repo-check`, `-m <model>`
- [ ] Command reads prompt via `"$(cat /tmp/dkmv_prompt.md)"`
- [ ] Command redirects: `< /dev/null > /tmp/dkmv_stream.jsonl 2>/tmp/dkmv_stream.err & echo $!`
- [ ] `--yolo` flag is NOT used (security concern)
- [ ] `--ephemeral` flag is NOT used (preserves resume capability)
- [ ] `supports_max_turns()` returns `False`
- [ ] `supports_budget()` returns `False`

**Feature:** F3 | **Tasks:** see matrix | **Priority:** Must-have

#### US-06: Codex adapter parses JSONL stream events

> As a Codex CLI Developer, I want Codex JSONL events parsed into normalized StreamEvents so the DKMV stream display and cost tracking work correctly.

**Acceptance Criteria:**
- [ ] `thread.started` maps to `StreamEvent(type="system")` with `session_id` from flat `thread_id` field
- [ ] `item.completed` with `type="agent_message"` maps to `StreamEvent(type="assistant", subtype="text")`
- [ ] `item.completed` with `type="command_execution"` maps to `StreamEvent(type="user", subtype="tool_result")`
- [ ] `turn.completed` accumulates token usage across turns (does not emit result per turn)
- [ ] `thread.closed` emits a single `StreamEvent(type="result")` with accumulated turn count and `total_cost_usd=0.0`
- [ ] `error` event maps to `StreamEvent(type="result", is_error=True)`
- [ ] Unknown event types are handled gracefully (logged, not crash)

**Feature:** F3 | **Tasks:** see matrix | **Priority:** Must-have

#### US-07: Codex adapter handles resume sessions

> As a Codex CLI Developer, I want DKMV to resume failed Codex sessions so retry logic works within a single component run.

**Acceptance Criteria:**
- [ ] `supports_resume()` returns `True`
- [ ] When `resume_session_id` is provided, `build_command()` produces `codex exec resume <session_id> --json --full-auto --sandbox danger-full-access "$(cat /tmp/dkmv_prompt.md)"`
- [ ] `extract_result()` captures `thread_id` from `thread.started` for use as session_id
- [ ] Session data persists in container since `--ephemeral` is omitted

**Feature:** F3 | **Tasks:** see matrix | **Priority:** Should-have

### Agent Selection (US-08 through US-11)

#### US-08: Agent resolved from task YAML field

> As a Multi-Agent Developer, I want to specify `agent: codex` in a task YAML file so individual tasks can use a specific agent.

**Acceptance Criteria:**
- [ ] `TaskDefinition` model accepts optional `agent: str | None = None` field
- [ ] `ManifestTaskRef` model accepts optional `agent: str | None = None` field
- [ ] `ComponentManifest` model accepts optional `agent: str | None = None` field
- [ ] Task-level `agent` overrides all other sources (highest priority in cascade)
- [ ] Task-ref `agent` overrides manifest, CLI, config, and defaults
- [ ] Manifest `agent` overrides CLI, config, and defaults
- [ ] Existing YAML files without `agent` field load without errors (defaults to `None`)

**Feature:** F4 | **Tasks:** see matrix | **Priority:** Must-have

#### US-09: Agent resolved through full 7-level cascade

> As any DKMV user, I want agent resolution to follow a clear priority cascade so the most specific configuration always wins.

**Acceptance Criteria:**
- [ ] Resolution cascade follows this exact order: (1) task YAML `agent` > (2) manifest task_ref `agent` > (3) component manifest `agent` > (4) CLI `--agent` > (5) project config `defaults.agent` > (6) DKMVConfig `default_agent` > (7) built-in default `"claude"`
- [ ] When no `agent` is specified at any level, the resolved agent is `"claude"`
- [ ] `DKMVConfig.default_agent` reads from `DKMV_AGENT` env var with default `"claude"`
- [ ] `ProjectDefaults.agent` reads from `.dkmv/config.json` `defaults.agent` field
- [ ] Each level can be independently tested
- [ ] Resolution mirrors the existing model resolution pattern for consistency

**Feature:** F4 | **Tasks:** see matrix | **Priority:** Must-have

#### US-10: Agent inferred from model prefix

> As a Codex CLI Developer, I want DKMV to infer `agent=codex` when I pass `--model gpt-5.3-codex` so I don't have to specify both `--agent` and `--model`.

**Acceptance Criteria:**
- [ ] `infer_agent_from_model("claude-sonnet-4-6")` returns `"claude"`
- [ ] `infer_agent_from_model("claude-opus-4-6")` returns `"claude"`
- [ ] `infer_agent_from_model("gpt-5.3-codex")` returns `"codex"`
- [ ] `infer_agent_from_model("gpt-5.3-codex-spark")` returns `"codex"`
- [ ] `infer_agent_from_model("o3")` returns `"codex"` (o-series models)
- [ ] `infer_agent_from_model("o4-mini")` returns `"codex"`
- [ ] `infer_agent_from_model("unknown-model")` returns `None`
- [ ] Inference only runs when `agent` is not explicitly set

**Feature:** F5 | **Tasks:** see matrix | **Priority:** Must-have

#### US-11: Model-agent mismatch produces clear error

> As any DKMV user, I want a clear error when I specify an incompatible model-agent pair so I can fix my configuration before wasting time on a failed run.

**Acceptance Criteria:**
- [ ] `--agent codex --model claude-opus-4-6` produces an error before container startup
- [ ] Error message names both the agent and the incompatible model
- [ ] Error message lists compatible model patterns for the specified agent
- [ ] When the resolved model is from the wrong family but agent was auto-resolved (not explicit), DKMV auto-substitutes the agent's default model with an info log
- [ ] Auto-substitution example: `agent=codex` (from CLI) + `model=claude-sonnet-4-6` (from YAML default) → model becomes `gpt-5.3-codex` with info message
- [ ] No error when model and agent are compatible

**Feature:** F5 | **Tasks:** see matrix | **Priority:** Must-have

### Docker & Infrastructure (US-12 through US-13)

#### US-12: Docker image contains both agents

> As a CI/CD Pipeline Operator, I want a single Docker image containing both Claude Code and Codex CLI so I can run any agent without rebuilding.

**Acceptance Criteria:**
- [ ] `dkmv/images/Dockerfile` installs `@openai/codex` via npm alongside `@anthropic-ai/claude-code`
- [ ] Codex version is pinned via `ARG CODEX_VERSION` build arg (default: `0.110.0`)
- [ ] `~/.codex/config.toml` is pre-created with `sandbox.mode = "danger-full-access"` and `network.access = true`
- [ ] All existing Claude Code Dockerfile config is unchanged: `IS_SANDBOX=1`, `CLAUDE_CODE_DISABLE_NONINTERACTIVE_CHECK=1`, `NODE_OPTIONS`, `.claude.json` onboarding bypass
- [ ] `codex --version` succeeds inside the built container
- [ ] `claude --version` continues to succeed inside the built container
- [ ] Image size stays under 5GB

**Feature:** F6 | **Tasks:** see matrix | **Priority:** Must-have

#### US-13: Build command accepts codex version flag

> As a CI/CD Pipeline Operator, I want `dkmv build --codex-version 0.110.0` so I can pin the Codex CLI version in my CI pipeline.

**Acceptance Criteria:**
- [ ] `dkmv build` command accepts `--codex-version` option (type: `str`, default: `"latest"`)
- [ ] The flag value is passed as `--build-arg CODEX_VERSION=<value>` to `docker build`
- [ ] Existing `--claude-version` flag continues to work unchanged
- [ ] `dkmv build` without `--codex-version` defaults to `"latest"`

**Feature:** F6 | **Tasks:** see matrix | **Priority:** Should-have

### Credential Discovery (US-14 through US-15)

#### US-14: Init discovers Codex credentials

> As a Codex CLI Developer, I want `dkmv init` to discover my Codex API key so I can use Codex without manual configuration.

**Acceptance Criteria:**
- [ ] `dkmv init` credential step checks for `CODEX_API_KEY` in environment
- [ ] If `CODEX_API_KEY` is not found, checks `OPENAI_API_KEY` as fallback
- [ ] Interactive prompt offers auth methods: Claude-only, Codex-only, or Both
- [ ] When "Both" is selected, credentials for both agents are discovered and stored
- [ ] `CredentialSources.codex_api_key_source` records the source (`"env"`, `"env:OPENAI_API_KEY"`, or `"none"`)
- [ ] `.dkmv/config.json` includes `codex_api_key_source` in the `credentials` section

**Feature:** F7 | **Tasks:** see matrix | **Priority:** Must-have

#### US-15: Non-interactive init auto-detects credentials

> As a CI/CD Pipeline Operator, I want `dkmv init --yes` to auto-detect all available credentials so my CI pipeline initializes without prompts.

**Acceptance Criteria:**
- [ ] `dkmv init --yes` checks `ANTHROPIC_API_KEY`, `CODEX_API_KEY`, and `OPENAI_API_KEY` without prompting
- [ ] If both Claude and Codex credentials are found, both are stored automatically
- [ ] If only Claude credentials are found, `codex_api_key_source` is set to `"none"`
- [ ] If only Codex credentials are found, Claude auth fields remain at their defaults
- [ ] `load_config()` resolves `codex_api_key` from `CODEX_API_KEY` first, then `OPENAI_API_KEY`

**Feature:** F7 | **Tasks:** see matrix | **Priority:** Must-have

### Mixed-Agent Components (US-16 through US-17)

#### US-16: Mixed-agent component passes all credentials

> As a Multi-Agent Developer, I want DKMV to pass credentials for all agents used in a component so mixed-agent runs don't fail on credential errors.

**Acceptance Criteria:**
- [ ] Before the task loop, `ComponentRunner` scans all task refs to determine `agents_needed` set
- [ ] `_build_sandbox_config()` receives the `agents_needed` set
- [ ] Container env vars include `ANTHROPIC_API_KEY` when any task uses Claude
- [ ] Container env vars include `CODEX_API_KEY` when any task uses Codex
- [ ] Docker args include Claude OAuth credential bind-mount when Claude tasks use OAuth
- [ ] Both `.claude/` and `.codex/` are added to workspace `.gitignore` for mixed-agent components

**Feature:** F8 | **Tasks:** see matrix | **Priority:** Must-have

#### US-17: Per-task adapter instantiation in mixed components

> As a Multi-Agent Developer, I want the adapter to be instantiated per-task so I can use Claude for planning and Codex for implementation within the same component.

**Acceptance Criteria:**
- [ ] Adapter is created fresh for each task in the task loop (not reused across tasks)
- [ ] Task 1 with `agent: claude` uses `ClaudeCodeAdapter` for command construction and stream parsing
- [ ] Task 2 with `agent: codex` uses `CodexCLIAdapter` for command construction and stream parsing
- [ ] Each task writes instructions to the correct file (`.claude/CLAUDE.md` vs `AGENTS.md`)
- [ ] Stream parsing uses the correct adapter for each task's output

**Feature:** F8 | **Tasks:** see matrix | **Priority:** Must-have

### Stream Normalization (US-18 through US-19)

#### US-18: Codex events normalized to StreamEvent

> As the DKMV orchestration layer, I want Codex JSONL events normalized to the existing `StreamEvent` dataclass so downstream code (run manager, cost tracking, stream display) works without changes.

**Acceptance Criteria:**
- [ ] `StreamParser` accepts optional `adapter` parameter in constructor
- [ ] When `adapter` is set, `parse_line()` delegates to `adapter.parse_event()`
- [ ] When `adapter` is None, falls back to current Claude parsing (backwards compatibility)
- [ ] `StreamEvent.raw` always contains the original event dict (no information loss)
- [ ] Codex `total_cost_usd` is always `0.0` (subscription model — no per-run cost)
- [ ] Token counts are accumulated across multiple `turn.completed` events
- [ ] Snapshot tests verify Codex event → StreamEvent mapping for all documented event types

**Feature:** F9 | **Tasks:** see matrix | **Priority:** Must-have

#### US-19: Stream rendering works for both agents

> As any DKMV user, I want the stream display to render correctly regardless of which agent produced the events so my terminal output is consistent.

**Acceptance Criteria:**
- [ ] `render_event()` operates only on `StreamEvent` fields (agent-agnostic)
- [ ] Claude runs display cost as `$X.XX` (actual cost from result event)
- [ ] Codex runs display cost as `$0.00` with a note about subscription pricing
- [ ] Assistant messages, tool use, and tool results render for both agents
- [ ] No changes needed to `render_event()` (validates the normalization is correct)

**Feature:** F9 | **Tasks:** see matrix | **Priority:** Must-have

### CLI Integration (US-20 through US-21)

#### US-20: CLI --agent flag selects agent for run

> As a Codex CLI Developer, I want to run `dkmv dev --agent codex --repo myrepo` so I can use Codex for development tasks.

**Acceptance Criteria:**
- [ ] `--agent` option is available on all 5 run commands: `dev`, `qa`, `docs`, `plan`, `run_component`
- [ ] `--agent` accepts string values (e.g., `"claude"`, `"codex"`)
- [ ] The flag value is stored in `CLIOverrides.agent`
- [ ] Agent flag is priority level 4 in the resolution cascade (below task/manifest, above project config)
- [ ] Invalid agent names produce a clear error with the list of registered agents
- [ ] `--agent` and `--model` can be used together; model-agent compatibility is validated

**Feature:** F10 | **Tasks:** see matrix | **Priority:** Must-have

#### US-21: Existing CLI commands work without --agent

> As a Claude Code Developer, I want all existing CLI commands to work exactly as before when I don't specify `--agent` so my workflows are not disrupted.

**Acceptance Criteria:**
- [ ] `dkmv dev --repo myrepo` without `--agent` resolves to `agent="claude"` (built-in default)
- [ ] `dkmv qa --repo myrepo` without `--agent` resolves to `agent="claude"`
- [ ] All existing CLI help text is unchanged (new `--agent` option appears in help but doesn't change existing behavior)
- [ ] Default model remains `claude-sonnet-4-6` when no agent override is specified
- [ ] Existing `--model` flag continues to work independently of `--agent`

**Feature:** F10 | **Tasks:** see matrix | **Priority:** Must-have
