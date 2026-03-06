# PRD: Multi-Agent Adapter Architecture & Codex CLI Integration

**Version:** 1.0
**Date:** 2026-03-05
**Status:** Draft
**Author:** DKMV Team

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Background & Motivation](#2-background--motivation)
3. [Goals & Non-Goals](#3-goals--non-goals)
4. [Current Architecture Analysis](#4-current-architecture-analysis)
5. [Target Architecture](#5-target-architecture)
6. [Agent Adapter Interface](#6-agent-adapter-interface)
7. [Codex CLI Adapter Specification](#7-codex-cli-adapter-specification)
8. [Changes by File](#8-changes-by-file)
9. [Configuration & Credential Changes](#9-configuration--credential-changes)
10. [YAML Schema Changes](#10-yaml-schema-changes)
11. [Dockerfile Changes](#11-dockerfile-changes)
12. [Stream Parsing & Normalization](#12-stream-parsing--normalization)
13. [Feature Parity & Gap Analysis](#13-feature-parity--gap-analysis)
14. [Risk Analysis & Regression Prevention](#14-risk-analysis--regression-prevention)
15. [Migration & Backwards Compatibility](#15-migration--backwards-compatibility)
16. [Testing Strategy](#16-testing-strategy)
17. [Phased Implementation Plan](#17-phased-implementation-plan)
18. [Evaluation Criteria](#18-evaluation-criteria)
19. [Future Extensibility](#19-future-extensibility)
20. [Open Questions](#20-open-questions)
21. [Appendix A: Claude Code vs Codex CLI Reference](#appendix-a-claude-code-vs-codex-cli-reference)
22. [Appendix B: Codex CLI JSONL Event Format](#appendix-b-codex-cli-jsonl-event-format)
23. [Appendix C: AGENTS.md Discovery Algorithm](#appendix-c-agentsmd-discovery-algorithm)
24. [Appendix D: Codex Docker/CI Recommended Configuration](#appendix-d-codex-dockerci-recommended-configuration)

---

## 1. Executive Summary

DKMV currently orchestrates Claude Code as its sole AI coding agent inside Docker containers. This PRD introduces a **multi-agent adapter architecture** that abstracts agent-specific logic behind a common interface, enabling DKMV to seamlessly support multiple AI coding agents — starting with **OpenAI Codex CLI** alongside the existing Claude Code.

Users will be able to specify which agent to use at the CLI, project config, component, or task level. The existing Claude Code functionality must remain **completely unchanged** — the adapter pattern extracts current behavior into a Claude adapter without modifying any semantics.

---

## 2. Background & Motivation

### Why Multi-Agent Support?

The original DKMV architecture document (`docs/core/main_idea.md`) explicitly references "ClaudeCode/Codex" throughout all component diagrams (Dev, QA, Report Eval, Docs). Multi-agent support was always part of the vision but was deferred to ship the initial Claude Code integration first.

### Why Now?

1. **OpenAI Codex CLI** has matured into a production-ready terminal agent with non-interactive execution (`codex exec --json`), making it viable for automated orchestration.
2. **Model diversity** — different tasks benefit from different models. Planning might work better with one model family, while implementation might be better with another.
3. **Cost optimization** — users may want to use subscription-based agents (Codex with ChatGPT Plus) for some tasks and pay-per-token agents (Claude) for others.
4. **Risk reduction** — avoiding vendor lock-in by supporting multiple agent backends.

### What is Codex CLI?

OpenAI's Codex CLI (`@openai/codex`) is an open-source, Rust-based terminal coding agent. Key characteristics:

- **Install:** `npm install -g @openai/codex`
- **Non-interactive execution:** `codex exec "prompt" --json` streams JSONL events
- **Models:** `gpt-5.3-codex` (default), `gpt-5.3-codex-spark`, and earlier GPT-5.x variants
- **Auth:** `CODEX_API_KEY` env var (CI/exec mode), `OPENAI_API_KEY` (general), or ChatGPT OAuth
- **Permissions:** `--full-auto` for autonomous execution (sets `workspace-write` sandbox + auto-approvals)
- **Instructions:** Reads `AGENTS.md` (project root) or `.codex/instructions.md`
- **Config:** TOML format at `~/.codex/config.toml` or `.codex/config.toml`

---

## 3. Goals & Non-Goals

### Goals

| ID | Goal |
|----|------|
| G1 | Introduce an `AgentAdapter` abstraction that encapsulates all agent-specific behavior |
| G2 | Extract existing Claude Code logic into a `ClaudeCodeAdapter` with zero behavioral changes |
| G3 | Implement a `CodexCLIAdapter` that enables full Codex CLI support inside DKMV |
| G4 | Allow agent selection at four levels: task YAML, component manifest, CLI flag, project config |
| G5 | Use a single multi-agent Docker image containing both Claude Code and Codex CLI |
| G6 | Maintain 100% backwards compatibility — existing YAML files, CLI commands, and configs work without modification |
| G7 | All existing 720+ tests pass without modification after the refactor phase |
| G8 | Normalize stream events so the rest of DKMV (run manager, stream display, cost tracking) works identically regardless of agent |
| G9 | Support Codex credential discovery in `dkmv init` |
| G10 | Enable mixed-agent components (e.g., plan with Claude, implement with Codex) within a single run |

### Non-Goals

| ID | Non-Goal | Rationale |
|----|----------|-----------|
| NG1 | Separate Docker images per agent | Deferred — single image is simpler for v1 |
| NG2 | Codex Cloud (remote execution) support | Codex Cloud runs on OpenAI infrastructure, not in DKMV containers |
| NG3 | Local model support (Ollama via Codex `--oss`) | Out of scope; can be added later via adapter |
| NG4 | Agent-specific MCP server configuration | Complex; deferred |
| NG5 | Changing the `.agent/` directory convention inside containers | Existing ADR-0010 stands |
| NG6 | Auto-migration of existing `.dkmv/config.json` files | Config version stays at 1; new fields have defaults |
| NG7 | Changes to the SWE-ReX integration or container lifecycle | The adapter pattern only affects command construction, stream parsing, and instruction files |
| NG8 | Per-agent custom built-in components | Built-in components (plan, dev, qa, docs) remain agent-agnostic |
| NG9 | Changing hardcoded model names in built-in component YAMLs | `dev/component.yaml` etc. specify `model: claude-sonnet-4-6`. These are defaults that get overridden by `--model` / `--agent` at runtime. The YAML files themselves are not changed. |

---

## 4. Current Architecture Analysis

### Claude Code Coupling Points

The current codebase has **11 identified coupling points** with Claude Code:

#### CP-1: Command Construction (`dkmv/core/sandbox.py:177-219`)

```python
# Current: Hardcoded Claude Code CLI command
cmd = (
    f"cd {working_dir} && "
    f"{env_prefix}claude -p \"$(cat /tmp/dkmv_prompt.md)\" "
    "--dangerously-skip-permissions "
    "--verbose "
    "--output-format stream-json "
    f"--model {model} "
    f"--max-turns {max_turns}"
    f"{budget_flag}"
    " < /dev/null > /tmp/dkmv_stream.jsonl 2>/tmp/dkmv_stream.err & echo $!"
)
```

**What's Claude-specific:**
- Binary name: `claude`
- Flags: `--dangerously-skip-permissions`, `--verbose`, `--output-format stream-json`, `--max-turns`, `--max-budget-usd`
- Resume: `--resume <session_id>`
- Prompt delivery: `-p "$(cat /tmp/dkmv_prompt.md)"`

#### CP-2: Stream Parsing (`dkmv/core/stream.py`)

The `StreamParser` parses Claude Code's JSONL event types:
- `system` — session lifecycle (has `session_id`, `message`)
- `assistant` — model output (has `message.content[]` with `text` and `tool_use` blocks)
- `user` — tool results (has `message.content[]` with `tool_result` blocks)
- `result` — final summary (has `total_cost_usd`, `duration_ms`, `num_turns`, `session_id`, `is_error`)

#### CP-3: Instructions File (`dkmv/tasks/runner.py:81-103`)

```python
# Writes to .claude/CLAUDE.md — Claude Code's convention
await self._sandbox.execute(session, f"mkdir -p {WORKSPACE_DIR}/.claude")
await self._sandbox.write_file(session, f"{WORKSPACE_DIR}/.claude/CLAUDE.md", content)
```

#### CP-4: Auth & Credentials (`dkmv/tasks/component.py:60-113`, `dkmv/config.py:50-72`)

```python
# Claude-specific auth handling in component.py
if config.auth_method == "oauth":
    creds_json = _fetch_oauth_credentials()  # macOS Keychain: "Claude Code-credentials"
    # Three-tier fallback:
    #   1. macOS Keychain → write to temp file → bind-mount as .credentials.json
    #   2. Linux: bind-mount ~/.claude/.credentials.json directly
    #   3. Fallback: pass CLAUDE_CODE_OAUTH_TOKEN as env var
    docker_args.extend(["-v", f"{temp_creds_file}:/home/dkmv/.claude/.credentials.json:ro"])
else:
    env_vars["ANTHROPIC_API_KEY"] = config.anthropic_api_key
```

The full OAuth credential discovery chain (`config.py:_fetch_oauth_credentials()`) reads from macOS Keychain via `security find-generic-password -s "Claude Code-credentials" -w`, falling back to the file at `~/.claude/.credentials.json`. This entire chain is Claude-specific and must be encapsulated within the Claude adapter.

#### CP-5: Configuration (`dkmv/config.py`)

```python
anthropic_api_key: str   # ANTHROPIC_API_KEY
claude_oauth_token: str  # CLAUDE_CODE_OAUTH_TOKEN
default_model: str = "claude-sonnet-4-6"  # DKMV_MODEL
auth_method: AuthMethod  # "api_key" | "oauth"
```

#### CP-6: System Context (`dkmv/tasks/system_context.py`)

The `DKMV_SYSTEM_CONTEXT` prompt content is agent-agnostic — it references `.agent/` (the container-side directory per ADR-0010), not `.claude/`. However, the delivery mechanism is Claude-specific: the content is written to `.claude/CLAUDE.md` by `TaskRunner._write_instructions()` (see CP-3). The system context text itself does **not** need changes, but the file it's written to must be adapter-driven.

#### CP-7: Dockerfile (`dkmv/images/Dockerfile`)

```dockerfile
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}
ENV IS_SANDBOX=1
ENV CLAUDE_CODE_DISABLE_NONINTERACTIVE_CHECK=1
RUN echo '{"hasCompletedOnboarding":true}' > /home/dkmv/.claude.json
```

#### CP-8: `.gitignore` in workspace (`dkmv/tasks/component.py:152-158`)

```python
# Only ignores .claude/, not .codex/
"&& (grep -qxF '.claude/' .gitignore 2>/dev/null"
"|| { ... echo '.claude/' >> .gitignore; })"
```

#### CP-9: Error messages and logging

Multiple files reference "Claude Code" in error messages, variable names, and log lines (e.g., `"Failed to launch Claude Code"`, `stream_claude()`, `_stream_claude()`).

#### CP-10: Build command (`dkmv/cli.py:177-221`)

```python
@app.command()
def build(..., claude_version: str = "latest"):
    cmd = [..., "--build-arg", f"CLAUDE_CODE_VERSION={claude_version}"]
```

#### CP-11: Default model in BaseComponentConfig (`dkmv/core/models.py:26`)

```python
class BaseComponentConfig(BaseModel):
    model: str = "claude-sonnet-4-6"  # Hardcoded Claude model default
```

This default is also present in `DKMVConfig` (`config.py:21`). Both must remain as-is (Claude is the default agent), but the model default should be understood as agent-coupled — it only makes sense when `agent="claude"`.

### Summary of All Coupling Points

| CP | Location | What's Coupled | Adapter Responsibility |
|----|----------|---------------|----------------------|
| CP-1 | `sandbox.py:177-219` | CLI command construction | `build_command()` |
| CP-2 | `stream.py` | JSONL event parsing | `parse_event()`, `is_result_event()`, `extract_result()` |
| CP-3 | `tasks/runner.py:81-103` | Instructions file path (`.claude/CLAUDE.md`) | `instructions_path` |
| CP-4 | `component.py:60-113`, `config.py:50-72` | Auth env vars, OAuth Keychain, credential bind-mounts | `get_auth_env_vars()`, `get_docker_args()` |
| CP-5 | `config.py` | `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, default model | Config fields (additive, not adapter) |
| CP-6 | `system_context.py` | Content is agent-agnostic; delivery via CP-3 | No change to content |
| CP-7 | `Dockerfile` | Claude Code install, env vars, onboarding bypass | Dockerfile additions |
| CP-8 | `component.py:152-158` | `.claude/` in `.gitignore` | `gitignore_entries` |
| CP-9 | Multiple files | Error messages, method names | Rename/parameterize |
| CP-10 | `cli.py:177-221` | `--claude-version` build arg | Add `--codex-version` |
| CP-11 | `core/models.py:26` | Default model `claude-sonnet-4-6` | Stays as default (Claude is default agent) |

---

## 5. Target Architecture

### Adapter Pattern Overview

```
┌─────────────────────────────────────────────────────────┐
│            TaskRunner / ComponentRunner                   │
│  Uses adapter to:                                        │
│    - Build CLI commands                                  │
│    - Write instruction files                             │
│    - Parse stream events                                 │
│    - Determine auth env vars                             │
└──────────────────────┬──────────────────────────────────┘
                       │
              ┌────────┴────────┐
              │  AgentAdapter   │  (Protocol)
              │                 │
              │  build_command()│
              │  parse_event()  │
              │  is_result()    │
              │  extract_result()│
              │  instructions_path()│
              │  setup_gitignore()│
              │  get_auth_env()  │
              │  get_docker_args()│
              └────────┬────────┘
               ┌───────┴───────┐
               │               │
     ┌─────────┴───┐   ┌──────┴────────┐   ┌ ─ ─ ─ ─ ─ ─ ┐
     │ ClaudeCode  │   │  CodexCLI     │     FutureAgent
     │  Adapter    │   │  Adapter      │   │  Adapter     │
     └─────────────┘   └───────────────┘   └ ─ ─ ─ ─ ─ ─ ┘
```

### Agent Resolution Cascade

When determining which agent to use for a task, DKMV follows this priority (highest to lowest):

```
1. Task YAML `agent:` field
2. Manifest task_ref `agent:` field
3. Component manifest `agent:` field
4. CLI `--agent` flag
5. Project config `defaults.agent`
6. DKMVConfig `default_agent`
7. Built-in default: "claude"
```

This mirrors the existing model resolution cascade, ensuring consistency.

**Important interaction with built-in components:** The built-in component YAMLs (`dev/component.yaml`, `qa/component.yaml`, etc.) specify `model: claude-sonnet-4-6` as their default. When the resolved agent is `codex` (from CLI `--agent codex` or config), the model cascade checks if the resolved model is compatible with the agent. If the model is from the wrong family (e.g., `claude-sonnet-4-6` with agent `codex`), DKMV **auto-substitutes** the agent's default model (e.g., `gpt-5.3-codex`) and logs an info message. This prevents users from needing to always specify `--model` when using `--agent codex` with built-in components.

### Agent-Model Validation

The adapter knows which model families it supports. When a model string is provided, the adapter validates it belongs to its family:

| Agent | Supported Model Patterns |
|-------|-------------------------|
| `claude` | `claude-*` (e.g., `claude-sonnet-4-6`, `claude-opus-4-6`) |
| `codex` | `gpt-*`, `o` + digit (e.g., `gpt-5.3-codex`, `gpt-5.3-codex-spark`, `o3`, `o4-mini`) |

If a model string is provided without an explicit agent, DKMV infers the agent from the model prefix. If `--model gpt-5.3-codex` is passed without `--agent`, DKMV infers `agent=codex`. This provides ergonomic defaults while keeping explicit agent selection available.

### Adapter Lifecycle & Threading

The adapter instance must be threaded through the full call stack. Here's how the adapter flows from resolution to execution:

```
CLI (--agent flag)
  └→ ComponentRunner.run()
       ├→ _build_sandbox_config(config, timeout, agents_needed)
       │    • Called ONCE before the task loop
       │    • Must pass ALL credentials for ALL agents used in the component
       │    • For mixed-agent: both ANTHROPIC_API_KEY and CODEX_API_KEY go into env_vars
       │    • Docker args include mounts for ALL agents (Claude OAuth creds, etc.)
       │
       ├→ Task loop (sequential):
       │    ├→ Resolve agent for this task (cascade: task → task_ref → manifest → CLI → config)
       │    ├→ adapter = get_adapter(resolved_agent_name)
       │    └→ TaskRunner.run(task, session, ..., adapter=adapter)
       │         ├→ _write_instructions(task, session, adapter)
       │         │    • Uses adapter.instructions_path for file location
       │         │    • Claude: writes .claude/CLAUDE.md
       │         │    • Codex: prepends to AGENTS.md
       │         ├→ _stream_agent(task, session, ..., adapter)
       │         │    • Calls sandbox.stream_agent(adapter=adapter, ...)
       │         │    • adapter.build_command() constructs the CLI command
       │         │    • adapter.is_result_event() detects completion
       │         │    • adapter.extract_result() gets cost/turns/session_id
       │         └→ _collect_outputs() → _retry (if needed, uses adapter.supports_resume())
       │
       └→ _git_teardown()
```

**Key design constraint:** `_build_sandbox_config()` runs once before any tasks execute. It builds the Docker env vars and bind-mount args. Since a component may use different agents across tasks (e.g., task 1 with Claude, task 2 with Codex), the sandbox config must include credentials for **all** agents that will be used.

**Implementation approach:** Before the task loop, scan all task refs in the manifest to determine which agents are needed:

```python
# In ComponentRunner.run(), after loading manifest:
agents_needed: set[str] = set()
for ref in manifest.tasks:
    if ref.agent:
        agents_needed.add(ref.agent)
if manifest.agent:
    agents_needed.add(manifest.agent)
if not agents_needed:
    agents_needed.add(cli_overrides.agent or config.default_agent)

# Pass to _build_sandbox_config so it includes credentials for all agents
sandbox_config, temp_creds_file = self._build_sandbox_config(config, timeout, agents_needed)
```

The adapter is then instantiated per-task (not per-component) because different tasks may use different agents. The adapter is a lightweight object — no state beyond configuration.

---

## 6. Agent Adapter Interface

```python
# dkmv/adapters/base.py

from __future__ import annotations
from typing import Any, Protocol

from dkmv.core.stream import StreamEvent


class StreamResult:
    """Normalized result extracted from agent's completion event."""
    cost: float         # USD cost (0.0 if not reported)
    turns: int          # Number of agent turns (0 if not reported)
    session_id: str     # Session ID for resume (empty if not available)


class AgentAdapter(Protocol):
    """Protocol for agent CLI adapters.

    Each adapter encapsulates all agent-specific behavior:
    command construction, stream parsing, auth configuration,
    instruction file conventions, and Docker requirements.
    """

    @property
    def name(self) -> str:
        """Agent identifier (e.g., 'claude', 'codex')."""
        ...

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
        """Build the full shell command to launch the agent in background.

        Must:
        - Read prompt from prompt_file
        - Output JSONL to /tmp/dkmv_stream.jsonl
        - Redirect stderr to /tmp/dkmv_stream.err
        - Run in background with `& echo $!`
        - Redirect stdin from /dev/null
        """
        ...

    def parse_event(self, raw: dict[str, Any]) -> StreamEvent | None:
        """Parse a raw JSONL event dict into a normalized StreamEvent."""
        ...

    def is_result_event(self, raw: dict[str, Any]) -> bool:
        """Return True if this event signals the agent has finished."""
        ...

    def extract_result(self, raw: dict[str, Any]) -> StreamResult:
        """Extract cost, turns, and session_id from a result event."""
        ...

    @property
    def instructions_path(self) -> str:
        """Relative path for the instructions file from workspace root.

        Claude: '.claude/CLAUDE.md'
        Codex: 'AGENTS.md'
        """
        ...

    @property
    def gitignore_entries(self) -> list[str]:
        """Directories to add to .gitignore in the workspace.

        Claude: ['.claude/']
        Codex: ['.codex/']
        """
        ...

    def get_auth_env_vars(self, config: DKMVConfig) -> dict[str, str]:
        """Return env vars needed for agent authentication.

        Claude: {'ANTHROPIC_API_KEY': ...} or OAuth flow
        Codex: {'CODEX_API_KEY': ...}
        """
        ...

    def get_docker_args(self, config: DKMVConfig) -> tuple[list[str], Path | None]:
        """Return (docker_args, temp_credentials_file) for container setup.

        Claude: bind-mount .credentials.json for OAuth
        Codex: no special mounts needed
        """
        ...

    def get_env_overrides(self) -> dict[str, str]:
        """Return env vars to set inside the container for this agent.

        Claude: {} (IS_SANDBOX and CLAUDE_CODE_DISABLE_NONINTERACTIVE_CHECK are in Dockerfile)
        Codex: {} (no special env needed when using --full-auto)
        """
        ...

    def supports_resume(self) -> bool:
        """Whether this agent supports session resumption."""
        ...

    def supports_budget(self) -> bool:
        """Whether this agent supports --max-budget-usd style limits."""
        ...

    def supports_max_turns(self) -> bool:
        """Whether this agent supports --max-turns style limits."""
        ...

    @property
    def default_model(self) -> str:
        """Default model for this agent.

        Claude: 'claude-sonnet-4-6'
        Codex: 'gpt-5.3-codex'

        Note: Codex model landscape as of March 2026:
        - gpt-5.3-codex — latest, recommended for most coding tasks
        - gpt-5.3-codex-spark — research preview (ChatGPT Pro only)
        - gpt-5.2-codex — previous default for ChatGPT-signed-in users
        - gpt-5-codex — older stable option
        The CLI reference uses 'gpt-5-codex' as its example but
        gpt-5.3-codex is the current recommended model per the
        official Codex Models page.
        """
        ...

    def validate_model(self, model: str) -> bool:
        """Return True if this model string is compatible with this agent."""
        ...
```

---

## 7. Codex CLI Adapter Specification

### 7.1 Command Construction

```bash
# Codex exec command for DKMV
cd /home/dkmv/workspace && \
  env CODEX_API_KEY=<key> \
  codex exec \
    --json \
    --full-auto \
    --sandbox danger-full-access \
    --skip-git-repo-check \
    -m <model> \
    "$(cat /tmp/dkmv_prompt.md)" \
  < /dev/null > /tmp/dkmv_stream.jsonl 2>/tmp/dkmv_stream.err & echo $!
```

**Key flags:**
- `--json` — stream JSONL events to stdout (redirected to file). Without this, Codex streams progress to stderr and prints only the final message to stdout.
- `--full-auto` — shortcut that sets `--ask-for-approval on-request` and `--sandbox workspace-write`. We add explicit `--sandbox danger-full-access` **after** this flag to override the sandbox mode.
- `--sandbox danger-full-access` — overrides `--full-auto`'s default `workspace-write` sandbox. DKMV already provides Docker isolation, so we disable Codex's OS-level sandbox (Landlock/seccomp may not be available inside Docker).
- `--skip-git-repo-check` — allows running even if git repo setup isn't fully recognized
- `-m <model>` — model selection (e.g., `gpt-5.3-codex`)
- No `--max-turns` equivalent (Codex doesn't support this)
- No `--max-budget-usd` equivalent (Codex is subscription-based for most users)

**Why NOT `--yolo`:** Codex has a `--yolo` flag (alias for `--dangerously-bypass-approvals-and-sandbox`) which runs every command without approvals or sandboxing. We intentionally avoid it — `--full-auto --sandbox danger-full-access` achieves the same filesystem/network access while keeping the `--full-auto` approval semantics. The `--yolo` flag is documented as "only use inside an externally hardened environment" and may disable safety features we want to keep.

**`--ephemeral` decision:** Always **omitted**. DKMV containers are already ephemeral (destroyed after each component run unless `--keep-alive`), so session persistence costs nothing meaningful — files are lost with the container anyway. Omitting `--ephemeral` keeps resume working for retry scenarios without conditional logic. If disk usage inside long-running containers becomes a concern, this can be revisited.

**Resume command:**
```bash
codex exec resume <SESSION_ID> --json --full-auto --sandbox danger-full-access \
  "$(cat /tmp/dkmv_prompt.md)" \
  < /dev/null > /tmp/dkmv_stream.jsonl 2>/tmp/dkmv_stream.err & echo $!
```

### 7.2 Instructions File

Codex CLI reads instructions from `AGENTS.md` files, discovered by walking from git root to CWD. At each directory level, it checks for `AGENTS.override.md` → `AGENTS.md` → fallback names. Maximum one file per level, combined limit 32 KiB.

The adapter writes DKMV's instructions to:
```
/home/dkmv/workspace/AGENTS.md
```

**Handling existing `AGENTS.md`:** If the cloned repo already has an `AGENTS.md`, the adapter should **prepend** DKMV's system context + component/task instructions to the existing content (separated by `---`), preserving the project's own instructions. This mirrors how Claude Code's `CLAUDE.md` can have project-level instructions alongside DKMV's.

The content format is identical to what DKMV already generates (system context + component instructions + task instructions). Only the file name and location differ.

### 7.3 Authentication

Codex CLI has multiple auth methods:
1. **`CODEX_API_KEY` env var** — dedicated env var for `codex exec` (CI/non-interactive mode). Documented in the [non-interactive docs](https://developers.openai.com/codex/noninteractive/) as the recommended CI approach.
2. **`OPENAI_API_KEY` env var** — the standard OpenAI API key. Works with Codex via `codex login --api-key` or the `env_key` config setting. This is what most OpenAI users already have.
3. **ChatGPT OAuth** — browser-based login flow. Not practical in Docker.
4. **Device auth** — `codex login --device-auth` (browser-independent). Stores tokens at `~/.codex/auth.json`.

**DKMV v1 approach:** API key via environment variable. DKMV checks for `CODEX_API_KEY` first, then falls back to `OPENAI_API_KEY`. This dual-check ensures:
- CI users who set `CODEX_API_KEY` per the Codex docs work out of the box
- Users who already have `OPENAI_API_KEY` set (the common case) don't need to set a second var
- The adapter passes whichever key is found as `CODEX_API_KEY` to the container (since that's what `codex exec` reads directly)

```python
# In CodexCLIAdapter.get_auth_env_vars():
def get_auth_env_vars(self, config: DKMVConfig) -> dict[str, str]:
    key = config.codex_api_key  # Resolved from CODEX_API_KEY or OPENAI_API_KEY
    if key:
        return {"CODEX_API_KEY": key}
    return {}
```

**Future enhancement (Phase 3 candidate):** Codex supports device-based auth via `codex login --device-auth`, which stores tokens at `~/.codex/auth.json`. A future version could bind-mount this file into the container (similar to Claude's OAuth credential bind-mount), enabling ChatGPT Plus subscription-based usage without an API key. This follows the same pattern as Claude's three-tier OAuth chain (Keychain → file → env var). The `dkmv init` flow would add an option: "Codex — Device Auth (bind-mount ~/.codex/auth.json)".

### 7.4 Stream Event Mapping

Codex CLI `--json` outputs JSONL events with **dot-separated** type names (e.g., `thread.started`, not `thread/started`). Item types use **snake_case** (e.g., `agent_message`, not `agentMessage`). The `thread_id` field is flat on the event object, not nested.

The key events DKMV must handle:

| Codex Event Type | Maps To StreamEvent | Notes |
|------------------|-------------------|-------|
| `thread.started` | `type="system"` | Contains flat `thread_id` field (used as session_id for resume) |
| `turn.started` | (ignored or logged) | Turn boundary — increment internal turn counter |
| `item.started` (agent_message) | `type="assistant", subtype="text"` | Agent begins composing a message |
| `item.completed` (agent_message) | `type="assistant", subtype="text"` | Full agent message: `item.text` |
| `item.started` (command_execution) | `type="assistant", subtype="tool_use"` | Shell command: `item.command` |
| `item.completed` (command_execution) | `type="user", subtype="tool_result"` | Command result: `item.exit_code`, `item.aggregated_output` |
| `item.completed` (file_change) | `type="assistant", subtype="tool_use"` | File edit with diff |
| `turn.completed` | Accumulate `usage` tokens | Per-turn token counts; **not** emitted as result until session ends |
| `turn.failed` | `type="result", is_error=True` | Failed turn = session error |
| `thread.closed` | `type="result"` | Final event — emit accumulated results |
| `error` | `type="result", is_error=True` | Top-level error event |

**Cost tracking:** Codex reports `usage: { input_tokens, cached_input_tokens, output_tokens }` per turn in `turn.completed`, but does **not** report dollar cost (subscription model). The adapter returns `0.0` for `total_cost_usd` and accumulates token counts across turns.

**Session ID:** Codex provides `thread_id` as a flat field on the `thread.started` event (e.g., `{"type":"thread.started","thread_id":"0199a213-..."}`). This is stored as the session_id for potential resume operations.

**Completion detection:** The adapter detects session completion by `thread.closed` event or process exit. Since Codex may emit multiple `turn.completed` events per session (multi-turn conversations), the adapter only emits a `type="result"` StreamEvent when the overall session ends, not after each individual turn.

See **Appendix B** for complete event schemas and sample JSONL output.

### 7.5 Resume Semantics

Codex supports session continuation in exec mode via:
```bash
codex exec resume <SESSION_ID> "follow-up prompt"
# Or resume most recent session:
codex exec resume --last "follow-up prompt"
```

Resume replays the full conversation transcript (turns, plan history, approvals) and continues with the new prompt. Session data is stored in `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`.

**DKMV integration:** The adapter's `build_command()` handles resume when `resume_session_id` is provided. Since `--ephemeral` is always omitted (see section 7.1), session rollout files are written and resume should work. The adapter's `supports_resume()` returns `True`.

If resume doesn't work reliably in the container environment (discovered during Phase 2 testing), the adapter's `supports_resume()` can be changed to `False` and the retry logic re-runs from scratch instead.

### 7.6 Max Turns & Budget

Codex CLI does not have direct `--max-turns` or `--max-budget-usd` flags. The adapter:
- `supports_max_turns()` → `False` — the parameter is accepted but silently ignored
- `supports_budget()` → `False` — same treatment
- DKMV's timeout-based safety net (via `asyncio.timeout(timeout_minutes * 60)`) still applies

---

## 8. Changes by File

### New Files

| File | Purpose |
|------|---------|
| `dkmv/adapters/__init__.py` | Adapter registry, `get_adapter(name)` factory, `infer_agent_from_model()` |
| `dkmv/adapters/base.py` | `AgentAdapter` protocol, `StreamResult` dataclass |
| `dkmv/adapters/claude.py` | `ClaudeCodeAdapter` — extracted from current `sandbox.py` and `stream.py` |
| `dkmv/adapters/codex.py` | `CodexCLIAdapter` — new Codex CLI support |
| `tests/unit/test_adapters/__init__.py` | Test package |
| `tests/unit/test_adapters/test_base.py` | Tests for adapter registry and factory |
| `tests/unit/test_adapters/test_claude.py` | Tests for Claude adapter (ported from existing stream tests) |
| `tests/unit/test_adapters/test_codex.py` | Tests for Codex adapter |

### Modified Files (Phase 1 — Refactor Only)

These changes extract Claude-specific logic into the adapter with **zero behavioral changes**:

| File | Change | Risk |
|------|--------|------|
| `dkmv/core/sandbox.py` | Add `stream_agent()` that takes adapter as parameter. Command construction delegated to `adapter.build_command()`. **`stream_claude()` kept as-is** — it becomes a thin wrapper that creates a `ClaudeCodeAdapter` internally and calls `stream_agent()`. This preserves the existing method signature so all 30+ test mocks (`sandbox.stream_claude = mock_stream`) continue to work without modification. | Medium — core execution path |
| `dkmv/core/stream.py` | `StreamParser` delegates `parse_line()` to adapter when provided. Falls back to current Claude parsing for backwards compatibility. | Low — additive change |
| `dkmv/tasks/runner.py` | `_write_instructions()` uses `adapter.instructions_path`. `_stream_claude()` → `_stream_agent()`. | Medium — instruction delivery |
| `dkmv/tasks/component.py` | `_build_sandbox_config()` delegates auth to adapter. Workspace setup uses adapter's `gitignore_entries`. | Medium — auth and workspace setup |

### Modified Files (Phase 2 — Add Codex + Agent Selection)

| File | Change | Risk |
|------|--------|------|
| `dkmv/tasks/models.py` | Add `agent: str \| None = None` to `TaskDefinition` | Low — additive field |
| `dkmv/tasks/manifest.py` | Add `agent: str \| None = None` to `ComponentManifest` and `ManifestTaskRef` | Low — additive field |
| `dkmv/core/models.py` | Add `agent: str = "claude"` to `BaseComponentConfig` | Low — additive field |
| `dkmv/config.py` | Add `codex_api_key` field, `default_agent` field | Low — new fields with defaults |
| `dkmv/project.py` | Add `agent` to `ProjectDefaults`, `codex_api_key_source` to `CredentialSources` | Low — additive fields |
| `dkmv/init.py` | Add Codex credential discovery (`CODEX_API_KEY`) | Low — new discovery function |
| `dkmv/cli.py` | Add `--agent` option to run commands, `--codex-version` to build command | Low — new CLI flags |
| `dkmv/images/Dockerfile` | Add `npm install -g @openai/codex`, Codex-specific env vars | Low — additive |
| `dkmv/tasks/system_context.py` | Parameterize if any Claude Code references exist (currently agent-agnostic) | Low |

### Files NOT Modified

These files must remain unchanged (per CLAUDE.md `DO NOT CHANGE` section and stability requirements):

| File | Reason |
|------|--------|
| `dkmv/core/runner.py` | RunManager is agent-agnostic (stores JSONL events regardless of source) |
| `dkmv/tasks/loader.py` | YAML loading is agent-agnostic |
| `dkmv/tasks/discovery.py` | Component resolution is agent-agnostic |
| `dkmv/tasks/pause.py` | Pause/resume UX is agent-agnostic |
| `dkmv/registry.py` | Component registry is agent-agnostic |
| All existing test files | Must pass unmodified after Phase 1 |

---

## 9. Configuration & Credential Changes

### 9.1 DKMVConfig Additions

```python
class DKMVConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Existing — Claude Code auth (unchanged)
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    claude_oauth_token: str = Field(default="", validation_alias="CLAUDE_CODE_OAUTH_TOKEN")
    github_token: str = Field(default="", validation_alias="GITHUB_TOKEN")

    # Existing — defaults (unchanged)
    default_model: str = Field(default="claude-sonnet-4-6", validation_alias="DKMV_MODEL")
    default_max_turns: int = Field(default=100, validation_alias="DKMV_MAX_TURNS")
    image_name: str = Field(default="dkmv-sandbox:latest", validation_alias="DKMV_IMAGE")
    output_dir: Path = Field(default=Path("./outputs"), validation_alias="DKMV_OUTPUT_DIR")
    timeout_minutes: int = Field(default=30, validation_alias="DKMV_TIMEOUT")
    memory_limit: str = Field(default="8g", validation_alias="DKMV_MEMORY")
    max_budget_usd: float | None = Field(default=None, validation_alias="DKMV_MAX_BUDGET_USD")
    auth_method: AuthMethod = Field(default="api_key", validation_alias="__DKMV_AUTH_METHOD")

    # NEW — Codex auth (checks CODEX_API_KEY first; fallback to OPENAI_API_KEY in load_config)
    codex_api_key: str = Field(default="", validation_alias="CODEX_API_KEY")

    # NEW — agent selection
    default_agent: str = Field(default="claude", validation_alias="DKMV_AGENT")
```

### 9.2 ProjectConfig Additions

```python
class CredentialSources(BaseModel):
    auth_method: AuthMethod = "api_key"
    anthropic_api_key_source: str = "env"
    oauth_token_source: str = "none"
    github_token_source: str = "env"
    # New
    codex_api_key_source: str = "none"

class ProjectDefaults(BaseModel):
    model: str | None = None
    max_turns: int | None = None
    timeout_minutes: int | None = None
    max_budget_usd: float | None = None
    memory: str | None = None
    # New
    agent: str | None = None
```

### 9.3 `.dkmv/config.json` Evolution

```json
{
  "version": 1,
  "project_name": "my-project",
  "repo": "https://github.com/user/repo",
  "default_branch": "main",
  "credentials": {
    "auth_method": "api_key",
    "anthropic_api_key_source": "env",
    "oauth_token_source": "none",
    "github_token_source": "gh auth token",
    "codex_api_key_source": "none"
  },
  "defaults": {
    "model": "claude-sonnet-4-6",
    "agent": "claude",
    "max_turns": 100,
    "timeout_minutes": 30
  },
  "sandbox": {
    "image": "dkmv-sandbox:latest"
  }
}
```

The `version` field stays at `1`. New fields have defaults (`codex_api_key_source: "none"`, `agent: null`). Existing config files load without errors.

### 9.4 Init Flow Changes

The current `dkmv init` flow (in `init.py`) has a [2/4] "Checking credentials" step that discovers Claude credentials and prompts the user to choose between API key and OAuth auth. This must be extended:

```
[2/4] Checking credentials...
  Authentication methods:
    1. Claude Code — API Key (ANTHROPIC_API_KEY)
    2. Claude Code — OAuth (subscription)
    3. Codex CLI — API Key (CODEX_API_KEY or OPENAI_API_KEY)
    4. Both Claude Code + Codex CLI
  Choose auth method [1]:
```

When "Both" is selected, the init flow discovers/prompts for credentials for both agents. The `CredentialSources` stores sources for both.

For `--yes` (non-interactive) mode, init auto-detects which credentials are available and configures accordingly. It checks `CODEX_API_KEY` first, then `OPENAI_API_KEY` as fallback. If both `ANTHROPIC_API_KEY` and a Codex key are found, both are stored.

The `auth_method` field in `CredentialSources` continues to indicate the **Claude Code** auth method (`"api_key"` or `"oauth"`). Codex auth is tracked separately via `codex_api_key_source`.

### 9.5 Credential Validation

Auth validation in `load_config()` becomes agent-aware. Currently validation happens at config load time and is Claude-only. The new logic:

```python
# Current: always validates Claude credentials
if auth_method == "api_key" and not config.anthropic_api_key: error()

# New: Codex API key resolution with OPENAI_API_KEY fallback
if not config.codex_api_key:
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        config.codex_api_key = openai_key

# New: only validate credentials for the configured default agent
if config.default_agent == "claude":
    # existing Claude validation (unchanged)
elif config.default_agent == "codex":
    if not config.codex_api_key:
        error("CODEX_API_KEY or OPENAI_API_KEY not set")
```

**OPENAI_API_KEY fallback:** Codex CLI in `codex exec` mode reads `CODEX_API_KEY` directly. However, most OpenAI users already have `OPENAI_API_KEY` set. DKMV's `load_config()` checks `CODEX_API_KEY` first (via pydantic-settings), then falls back to `OPENAI_API_KEY` from the environment. The resolved key is passed to the container as `CODEX_API_KEY` regardless of which source it came from.

**Important:** When a component uses a non-default agent, credentials are validated at runtime (when `_build_sandbox_config` is called), not at config load time. This allows a project to have Claude as default but use Codex for specific tasks without requiring both credentials at startup.

---

## 10. YAML Schema Changes

### 10.1 Task YAML

```yaml
# New optional field
name: implement-feature
agent: codex                    # NEW — "claude" | "codex" (default: inherited)
model: gpt-5.3-codex
prompt: |
  Implement the feature...
```

### 10.2 Component Manifest

```yaml
name: my-component
agent: codex                    # NEW — default for all tasks
model: gpt-5.3-codex

tasks:
  - file: plan.yaml
    agent: claude               # NEW — override per task ref
    model: claude-opus-4-6
  - file: implement.yaml
    # Inherits component's agent: codex
```

### 10.3 Agent Resolution in Code

```python
# In ComponentRunner._apply_manifest_defaults():
if task.agent is None:
    if task_ref and task_ref.agent is not None:
        task.agent = task_ref.agent
    elif manifest.agent is not None:
        task.agent = manifest.agent
```

```python
# In TaskRunner._stream_agent() (formerly _stream_claude()):
agent_name = self._resolve_param(task.agent, cli_overrides.agent, config.default_agent)
adapter = get_adapter(agent_name)
model = self._resolve_param(task.model, cli_overrides.model, config.default_model)
```

### 10.4 Agent Inference from Model

When `agent` is not explicitly set but `model` is, DKMV infers the agent:

```python
import re

def infer_agent_from_model(model: str) -> str | None:
    """Infer agent from model string. Returns None if ambiguous."""
    if model.startswith("claude-"):
        return "claude"
    if model.startswith("gpt-"):
        return "codex"
    # Match OpenAI "o-series" models: o1, o3, o3-mini, o4-mini, etc.
    # Requires "o" followed by a digit to avoid false positives
    # (e.g., "openrouter-xxx" should NOT match).
    if re.match(r"^o\d", model):
        return "codex"
    return None
```

This runs as a convenience after the resolution cascade. If `task.agent` is None and `task.model` is `gpt-5.3-codex`, the inferred agent is `codex`.

---

## 11. Dockerfile Changes

### 11.1 Multi-Agent Image

The current Dockerfile uses `node:20-bookworm` as base, installs Claude Code via npm, creates a non-root `dkmv` user (UID 1000), installs SWE-ReX via pipx, and sets critical environment variables.

```dockerfile
# Existing (unchanged)
ARG CLAUDE_CODE_VERSION=2.1.47
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

# New addition — install Codex CLI alongside Claude Code
# Latest version as of March 2026: 0.110.0
ARG CODEX_VERSION=0.110.0
RUN npm install -g @openai/codex@${CODEX_VERSION}
```

**Critical existing config that must NOT change:**
- `ENV NODE_OPTIONS="--max-old-space-size=4096"` — prevents Node.js OOM for Claude Code
- `ENV PATH="/home/dkmv/.local/bin:${PATH}"` — required for SWE-ReX (`swerex-remote`)
- `RUN pipx install swe-rex && pipx ensurepath` — SWE-ReX for remote command execution
- Non-root `dkmv` user at UID 1000 with passwordless sudo

### 11.2 Environment Variables

```dockerfile
# Existing (unchanged — required for Claude Code)
ENV IS_SANDBOX=1
ENV CLAUDE_CODE_DISABLE_NONINTERACTIVE_CHECK=1
ENV NODE_OPTIONS="--max-old-space-size=4096"

# Existing: Claude onboarding bypass (unchanged)
RUN echo '{"hasCompletedOnboarding":true}' > /home/dkmv/.claude.json

# New: Codex-specific
# Codex doesn't need special env vars for headless mode
# The --full-auto and --sandbox flags handle this at runtime
```

### 11.3 Codex Configuration

Codex reads `~/.codex/config.toml`. We may need to pre-create it:

```dockerfile
# Pre-configure Codex for headless Docker usage
RUN mkdir -p /home/dkmv/.codex \
    && echo '[sandbox]\nmode = "danger-full-access"\n\n[network]\naccess = true' \
       > /home/dkmv/.codex/config.toml \
    && chown -R dkmv:dkmv /home/dkmv/.codex
```

### 11.4 Build Command Updates

```python
# dkmv/cli.py build command
@app.command()
def build(
    no_cache: ...,
    claude_version: ... = "latest",
    codex_version: Annotated[
        str, typer.Option("--codex-version", help="Codex CLI version to install.")
    ] = "latest",
):
    cmd = [
        ...,
        "--build-arg", f"CLAUDE_CODE_VERSION={claude_version}",
        "--build-arg", f"CODEX_VERSION={codex_version}",
    ]
```

---

## 12. Stream Parsing & Normalization

### 12.1 Normalized StreamEvent (Unchanged)

The existing `StreamEvent` dataclass remains the canonical internal representation:

```python
@dataclass
class StreamEvent:
    type: str = ""           # "system" | "assistant" | "user" | "result"
    subtype: str = ""        # "text" | "tool_use" | "tool_result" | ""
    content: str = ""
    tool_name: str = ""
    tool_input: str = ""
    total_cost_usd: float = 0.0
    duration_ms: float = 0.0
    num_turns: int = 0
    session_id: str = ""
    is_error: bool = False
    raw: dict[str, Any] = field(default_factory=dict)
```

### 12.2 Adapter-Based Parsing Flow

```
Raw JSONL line → json.loads() → adapter.parse_event(raw) → StreamEvent
                                adapter.is_result_event(raw) → bool
                                adapter.extract_result(raw) → StreamResult
```

The `StreamParser` gains an optional adapter parameter:

```python
class StreamParser:
    def __init__(self, console=None, verbose=False, adapter=None):
        self.adapter = adapter  # AgentAdapter or None

    def parse_line(self, line: str) -> StreamEvent | None:
        data = json.loads(line)
        if self.adapter:
            return self.adapter.parse_event(data)
        # Fallback: existing Claude parsing (for backwards compatibility)
        return self._parse_claude_event(data)
```

### 12.3 Rendering (Unchanged)

`StreamParser.render_event()` operates on `StreamEvent`, which is agent-agnostic. No changes needed — the rendering code works regardless of which adapter produced the event.

---

## 13. Feature Parity & Gap Analysis

### Features Fully Supported by Both Agents

| Feature | Claude Code | Codex CLI |
|---------|------------|-----------|
| Non-interactive execution | `claude -p` | `codex exec` |
| JSONL streaming | `--output-format stream-json` | `--json` |
| Model selection | `--model` | `-m` |
| Autonomous mode | `--dangerously-skip-permissions` | `--full-auto` + `--sandbox danger-full-access` |
| Working directory | `cd path && claude` | `--cd path` or `cd path && codex` |
| Instructions file | `CLAUDE.md` | `AGENTS.md` |
| Environment variable auth | `ANTHROPIC_API_KEY` | `CODEX_API_KEY` |
| Git operations | Full git support | Full git support |
| Tool use (bash, file edit) | Built-in | Built-in |

### Features with Gaps

| Feature | Claude Code | Codex CLI | DKMV Handling |
|---------|------------|-----------|---------------|
| `--max-turns` | Supported | Not available | Adapter returns `supports_max_turns()=False`; timeout is the safety net |
| `--max-budget-usd` | Supported | Not available | Adapter returns `supports_budget()=False`; DKMV logs a warning |
| Session resume | `--resume <id>` | `codex exec resume <id> "prompt"` or `--last` | Adapter implements; `supports_resume()=True` (since `--ephemeral` is omitted) |
| Cost reporting | `total_cost_usd` in result event | May not report USD cost (subscription) | Adapter returns `0.0`; DKMV tracks turns/duration instead |
| OAuth credentials | macOS Keychain + .credentials.json | ChatGPT OAuth (browser) | Codex uses API key only in DKMV; no OAuth support |
| Verbose mode | `--verbose` | Default in `--json` mode | No flag needed for Codex |

### Feature Parity Strategy

1. **Max turns / budget:** Accept silently. DKMV logs an info message: "Agent 'codex' does not support --max-turns; using timeout as safety limit."
2. **Cost tracking:** Display `$0.00` for Codex runs. Users understand subscription costs are not per-run.
3. **Resume:** Try if adapter supports it. If not, re-run the full task (costs more but functionally equivalent).

---

## 14. Risk Analysis & Regression Prevention

### R1: Claude Code Behavioral Changes (Critical)

**Risk:** Refactoring `stream_claude()` into adapter pattern introduces subtle behavioral differences.

**Mitigation:**
- Phase 1 is a pure refactor — the Claude adapter must produce **byte-identical** commands to the current code
- All 720+ existing tests must pass without modification
- `stream_claude()` on `SandboxManager` keeps its exact current signature and creates a `ClaudeCodeAdapter` internally, so the 30+ test mocks that assign `sandbox.stream_claude = mock_stream` continue to work without any changes
- Add a regression test that asserts the exact command string generated by `ClaudeCodeAdapter.build_command()` matches the current hardcoded command

### R2: Stream Event Parsing Drift (High)

**Risk:** Normalizing Codex events into `StreamEvent` may lose information or produce events that downstream code doesn't expect.

**Mitigation:**
- `StreamEvent.raw` always contains the original event dict — no information loss
- `render_event()` only uses normalized fields (`type`, `subtype`, `content`, `tool_name`, etc.)
- Add snapshot tests comparing parsed Codex events to expected `StreamEvent` values

### R3: Auth Credential Leakage (High)

**Risk:** Adding `CODEX_API_KEY` to env vars could leak via logs or error messages.

**Mitigation:**
- Same masking/handling as `ANTHROPIC_API_KEY` — passed via Docker `-e` flag, not logged
- `shlex.quote()` all values in command construction
- Never include API keys in JSONL stream or run artifacts

### R4: Docker Image Size Bloat (Medium)

**Risk:** Adding Codex CLI increases image size.

**Mitigation:**
- Codex CLI is a single Rust binary (~50-100MB) — acceptable for a dev container
- Image size tracked in CI — fail if >5GB
- Future: separate images (NG1) if size becomes problematic

### R5: Codex Sandbox Conflicts in Docker (Medium)

**Risk:** Codex's OS-level sandbox (Seatbelt/Landlock) may conflict with Docker's isolation.

**Mitigation:**
- Use `--sandbox danger-full-access` to disable Codex's sandbox inside Docker
- Docker provides the isolation layer; Codex's sandbox is redundant
- Test this explicitly in integration tests

### R6: Codex CLI Updates Break JSONL Format (Medium)

**Risk:** Codex is newer than Claude Code; its `--json` format may change between versions.

**Mitigation:**
- Pin Codex version in Dockerfile: `@openai/codex@0.110.0` (same pattern as Claude Code `@2.1.47`)
- Adapter's `parse_event()` is defensive — unknown events become `StreamEvent(type=event_type, raw=data)`
- Snapshot tests for known event types
- Event types use dot separators (`thread.started`) and snake_case item types (`agent_message`) — verified against official docs

### R7: Mixed-Agent Runs and Credential Handling (Medium)

**Risk:** A component uses Claude for task 1 and Codex for task 2. Both need different credentials in the same container.

**Mitigation:**
- All credentials are passed as env vars at container start. Both `ANTHROPIC_API_KEY` and `CODEX_API_KEY` can coexist.
- The adapter only selects which env vars to use in the command prefix, not which ones exist in the container.
- `_build_sandbox_config()` passes all available credentials — the adapter's `build_command()` only references its own.

### R8: Model-Agent Mismatch (Low)

**Risk:** User specifies `--agent codex --model claude-opus-4-6`, which makes no sense.

**Mitigation:**
- `adapter.validate_model(model)` returns `False` → DKMV prints a clear error and exits
- This is caught before container startup (fast fail)

### R9: SWE-ReX Background Process Handling (Medium)

**Risk:** Codex CLI, like Claude Code, will be launched as a background process (`&`) inside an interactive bash session via SWE-ReX. Background processes that read from stdin get SIGTTIN (freeze).

**Mitigation:**
- Same pattern as Claude Code: `< /dev/null` redirects stdin
- The adapter's `build_command()` always includes `< /dev/null > /tmp/dkmv_stream.jsonl 2>/tmp/dkmv_stream.err & echo $!`
- This is a hard requirement enforced by the `AgentAdapter` protocol documentation
- Verified to work for Claude Code; must be tested for Codex

### R10: `.gitignore` Conflicts (Low)

**Risk:** Both `.claude/` and `.codex/` entries needed for mixed-agent components.

**Mitigation:**
- Each adapter provides `gitignore_entries`. When setting up workspace, we combine entries from all adapters that will be used in the component.
- For simplicity, we can always add both `.claude/` and `.codex/` entries.

---

## 15. Migration & Backwards Compatibility

### Zero Breaking Changes

| Aspect | Behavior |
|--------|----------|
| Existing YAML files without `agent:` field | Default to `"claude"` — identical behavior |
| Existing `.dkmv/config.json` without `agent`/`codex_api_key_source` | Default values apply (`agent=null`, `codex_api_key_source="none"`) |
| Existing CLI commands without `--agent` | Default to configured agent or `"claude"` |
| `dkmv build` without `--codex-version` | Codex installed at `latest` |
| Stream output | Identical for Claude runs; new format for Codex runs |
| Run artifacts | Same structure; `stream.jsonl` contains agent-specific raw events |

### Config Version

The `ProjectConfig.version` stays at `1`. New fields have sensible defaults. No migration script needed.

### Deprecation Path

- `stream_claude()` on `SandboxManager` kept with its **exact current signature**. Internally it creates a `ClaudeCodeAdapter` and delegates to the new `stream_agent()`. This ensures all 30+ existing test mocks (`sandbox.stream_claude = mock_stream`) work without modification. No deprecation warning yet — the method is still the primary path for Claude-only callers.
- `_stream_claude()` in TaskRunner renamed to `_stream_agent()` with old name as alias
- New code paths (multi-agent) use `stream_agent()` directly
- Removal of `stream_claude()` planned for v3.0 (will add deprecation warnings in v2.x)

---

## 16. Testing Strategy

### 16.1 Phase 1 Tests (Refactor)

**Requirement: All 720+ existing tests pass unmodified.**

New tests:
- `test_adapters/test_claude.py` — Claude adapter unit tests
  - `test_build_command_basic` — verify command matches current output
  - `test_build_command_with_budget` — budget flag present
  - `test_build_command_resume` — resume session
  - `test_parse_event_*` — for each Claude event type
  - `test_is_result_event`
  - `test_extract_result`
  - `test_instructions_path`
  - `test_gitignore_entries`
  - `test_validate_model`
- `test_adapters/test_base.py` — adapter registry tests
  - `test_get_adapter_claude`
  - `test_get_adapter_unknown_raises`
  - `test_infer_agent_from_model`

### 16.2 Phase 2 Tests (Codex)

New tests:
- `test_adapters/test_codex.py` — Codex adapter unit tests
  - Same test patterns as Claude adapter
  - `test_build_command_codex` — verify Codex exec command
  - `test_parse_event_*` — for each Codex event type (using captured samples)
  - `test_supports_max_turns_false`
  - `test_supports_budget_false`
  - `test_validate_model_gpt`
  - `test_validate_model_claude_rejected`
- `test_config.py` additions
  - `test_codex_api_key_from_env`
  - `test_default_agent_from_env`
- `test_init.py` additions
  - `test_discover_codex_api_key`
- `test_project.py` additions
  - `test_project_config_with_agent`
- Model/manifest field tests
  - `test_task_definition_agent_field`
  - `test_manifest_agent_field`
  - `test_manifest_task_ref_agent_field`
- Integration tests (if API keys available)
  - `test_codex_hello_world` — run `codex exec "echo hello" --json` and verify events

### 16.3 Coverage Target

- Maintain >= 80% coverage (current: 91.89%)
- New adapter code must have >= 90% coverage
- All quality gates must pass:
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run mypy dkmv/`
  - `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short`

---

## 17. Phased Implementation Plan

### Phase 1: Adapter Foundation (Pure Refactor)

**Goal:** Extract Claude Code logic into an adapter without changing any behavior.

**Tasks:**

| ID | Task | Files |
|----|------|-------|
| T300 | Create `dkmv/adapters/base.py` with `AgentAdapter` protocol and `StreamResult` | New |
| T301 | Create `dkmv/adapters/claude.py` — extract `build_command()` from `sandbox.py:207-219` | New |
| T302 | Add `parse_event()` to Claude adapter — extract from `stream.py` | New |
| T303 | Add `is_result_event()`, `extract_result()` to Claude adapter | New |
| T304 | Add `instructions_path`, `gitignore_entries`, `get_auth_env_vars()`, `get_docker_args()` to Claude adapter | New |
| T305 | Create `dkmv/adapters/__init__.py` — adapter registry with `get_adapter()` | New |
| T306 | Refactor `sandbox.py` — add `stream_agent()` with adapter param; `stream_claude()` becomes thin wrapper (creates `ClaudeCodeAdapter` internally, preserves exact signature for 30+ test mocks) | Modify |
| T307 | Refactor `stream.py` — `StreamParser` accepts optional adapter | Modify |
| T308 | Refactor `tasks/runner.py` — `_write_instructions()` uses adapter, `_stream_claude()` → `_stream_agent()` | Modify |
| T309 | Refactor `tasks/component.py` — `_build_sandbox_config()` delegates auth to `ClaudeCodeAdapter.get_auth_env_vars()` / `get_docker_args()`. Behavior identical to current code. Multi-agent credential scanning (`agents_needed`) is Phase 2. | Modify |
| T310 | Write Claude adapter tests (`test_adapters/test_claude.py`) | New |
| T311 | Write adapter registry tests (`test_adapters/test_base.py`) | New |
| T312 | Verify all 720+ existing tests pass without modification | Verify |

**Evaluation Criteria:**
- `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short` — all pass, coverage >= 80%
- `uv run ruff check . && uv run ruff format --check . && uv run mypy dkmv/` — clean
- No behavioral changes — Claude adapter produces identical commands
- `stream_claude()` still callable (deprecated alias)

### Phase 2: Codex Adapter & Agent Selection

**Goal:** Add Codex CLI support and agent selection at all levels.

**Tasks:**

| ID | Task | Files |
|----|------|-------|
| T320 | Create `dkmv/adapters/codex.py` — full Codex adapter | New |
| T321 | Add `agent` field to `TaskDefinition` | Modify `tasks/models.py` |
| T322 | Add `agent` field to `ComponentManifest` and `ManifestTaskRef` | Modify `tasks/manifest.py` |
| T323 | Add `agent` to `BaseComponentConfig` | Modify `core/models.py` |
| T324 | Add `codex_api_key`, `default_agent` to `DKMVConfig` | Modify `config.py` |
| T325 | Add `agent` to `ProjectDefaults`, `codex_api_key_source` to `CredentialSources` | Modify `project.py` |
| T326 | Implement agent resolution cascade in `TaskRunner` and `ComponentRunner` | Modify `tasks/runner.py`, `tasks/component.py` |
| T327 | Add `infer_agent_from_model()` to adapter registry | Modify `adapters/__init__.py` |
| T328 | Add `--agent` flag to CLI run commands (dev, qa, docs, plan, run) | Modify `cli.py` |
| T329 | Add `agent: str \| None = None` to `CLIOverrides` dataclass | Modify `tasks/models.py` |
| T330 | Write Codex adapter tests | New `test_adapters/test_codex.py` |
| T331 | Write agent resolution tests | New/modify existing test files |

**Evaluation Criteria:**
- All existing tests still pass
- Codex adapter tests pass
- `dkmv run --agent codex --model gpt-5.3-codex ...` compiles and validates correctly
- Mixed-agent components resolve correctly

### Phase 3: Docker & Init Integration

**Goal:** Codex CLI available in containers, credential discovery in init.

**Tasks:**

| ID | Task | Files |
|----|------|-------|
| T340 | Update Dockerfile — install Codex CLI, pre-configure | Modify `images/Dockerfile` |
| T341 | Add `--codex-version` to `dkmv build` | Modify `cli.py` |
| T342 | Add Codex credential discovery to `dkmv init` (check env `CODEX_API_KEY` → `.env` → prompt) | Modify `init.py` |
| T343 | Update `load_config()` for Codex credential validation | Modify `config.py` |
| T344 | Update workspace `.gitignore` setup for multi-agent | Modify `tasks/component.py` |
| T345 | Write init/config tests for Codex credentials | Modify test files |
| T346 | Integration test: build image with both agents installed | Manual/CI |

**Evaluation Criteria:**
- `docker build` succeeds with both agents
- `dkmv init` discovers Codex API key
- `dkmv build --codex-version latest` works
- All quality gates pass

### Phase 4: Polish & Documentation

**Goal:** Error messages, logging, docs, edge cases.

**Tasks:**

| ID | Task | Files |
|----|------|-------|
| T350 | Update error messages to be agent-aware (not "Claude Code" specific) | Multiple |
| T351 | Add model-agent mismatch validation with clear error | `adapters/__init__.py` |
| T352 | Update `dkmv components` to show agent info | `cli.py` |
| T353 | Update README and docs for multi-agent usage | Docs |
| T354 | Update CLAUDE.md with new adapter conventions | `CLAUDE.md` |
| T355 | Final regression test pass — full test suite | Verify |

---

## 18. Evaluation Criteria

### Overall Success Criteria

| Criterion | Metric |
|-----------|--------|
| Zero regressions | All 720+ existing tests pass without modification after Phase 1 |
| Coverage maintained | >= 80% overall, >= 90% for new adapter code |
| Quality gates | ruff, mypy, format all clean |
| Claude behavior unchanged | Identical CLI commands, stream parsing, auth flow |
| Codex functional | Can build command, parse events, resolve credentials |
| Agent selection works | All 4 levels (task, manifest, CLI, config) resolve correctly |
| Mixed-agent components | Claude task followed by Codex task in same run works |
| Backwards compatible | Existing YAML, config, and CLI work without changes |
| Init supports Codex | `dkmv init` discovers and stores `CODEX_API_KEY` |
| Docker multi-agent | Single image has both agents installed and functional |

### Per-Phase Gates

Each phase must pass before proceeding:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy dkmv/
uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short
```

---

## 19. Future Extensibility

The adapter pattern is designed for easy addition of future agents. To add a new agent:

1. Create `dkmv/adapters/<agent_name>.py` implementing `AgentAdapter`
2. Register it in `dkmv/adapters/__init__.py`
3. Update Dockerfile to install the agent's CLI
4. Add model prefix patterns to `infer_agent_from_model()`
5. Add credential discovery to `init.py`

### Potential Future Agents

| Agent | CLI Tool | Install | Notes |
|-------|----------|---------|-------|
| Aider | `aider` | `pip install aider-chat` | Python-based, supports multiple LLM providers |
| Cursor Agent | N/A | IDE-only currently | Would need API-based invocation |
| Devin CLI | TBD | Not yet available as CLI | Cloud-first agent |
| Custom/Local | User-defined | User-managed | Could wrap any CLI tool |

### Extension Points

- **Custom adapters:** Users could register custom adapters via plugin mechanism (future)
- **Agent capabilities:** Each adapter declares its capabilities (`supports_resume`, `supports_budget`, etc.) — the orchestrator adapts behavior accordingly
- **Agent-specific config:** Adapters can read from agent-specific config sections in `.dkmv/config.json`

---

## 20. Open Questions

### OQ-1: Codex JSONL Event Schema (Resolved)

The Codex `--json` wire format uses **dot separators** (`thread.started`, `turn.completed`, `item.started`, etc.) and **snake_case** item types (`agent_message`, `command_execution`). This is confirmed by the official [Non-interactive mode docs](https://developers.openai.com/codex/noninteractive/) and sample output. The `thread_id` is a flat field, not nested. See Appendix B for the complete verified format. **Action:** During Phase 2, capture real `codex exec --json` output against the pinned Codex version to verify any additional fields or minor variations not shown in the docs.

### OQ-2: Codex Resume in Exec Mode (Resolved)

`codex exec resume <SESSION_ID> "prompt"` is documented as supported. It replays the full conversation transcript and continues. The `--last` flag resumes the most recent session. **Resolution:** `--ephemeral` is always omitted (containers are already ephemeral), so session rollout files are always written and resume should work. **Action:** Verify during Phase 2 integration testing.

### OQ-3: Codex Network Access in Docker

Codex's default sandbox blocks network. When using `--sandbox danger-full-access`, does network work inside Docker? **Action:** Test during Phase 3 integration testing.

### OQ-4: Codex Session Persistence (Resolved)

Codex stores session data in `~/.codex/sessions/`. In DKMV's ephemeral Docker containers, this data is lost when the container is destroyed — which is fine because resume only happens within a single component run (same container). **Resolution:** `--ephemeral` is omitted so session data is written, enabling resume for retry scenarios within the same container lifecycle. No action needed.

### OQ-5: Image Size Impact

What's the size delta from adding Codex CLI? Need to measure. **Action:** Build image with both agents, compare to current size. Acceptable threshold: < 500MB increase.

### OQ-6: AGENTS.md vs Existing Project AGENTS.md (Resolved)

Codex's discovery algorithm walks root-to-CWD, picking one file per directory level. The workspace root `AGENTS.md` is the highest-priority project-level file. **Resolution:** The adapter should **read** the existing `AGENTS.md` (if present), **prepend** DKMV's system context + component/task instructions, and write the combined content back. This preserves project-specific instructions while adding DKMV's context. The `AGENTS.override.md` filename could also be used to take absolute priority, but prepending is cleaner.

### OQ-7: Codex Config File Conflicts

If Codex reads `.codex/config.toml` from the workspace (cloned repo), a project's Codex config could conflict with DKMV's needs. **Action:** Determine if `--config` flag or env var can override. May need to pre-write a DKMV-controlled config.

---

## Appendix A: Claude Code vs Codex CLI Reference

| Aspect | Claude Code | Codex CLI |
|--------|------------|-----------|
| Binary | `claude` | `codex` |
| Install | `npm install -g @anthropic-ai/claude-code` | `npm install -g @openai/codex` |
| Language | TypeScript/Node | Rust |
| Non-interactive | `claude -p "prompt"` | `codex exec "prompt"` |
| JSON streaming | `--output-format stream-json` (`--verbose` required) | `--json` |
| Autonomous mode | `--dangerously-skip-permissions` | `--full-auto` (sets `workspace-write` + auto-approve) |
| Full bypass | N/A | `--yolo` (`--dangerously-bypass-approvals-and-sandbox`) |
| Model flag | `--model <model>` | `-m <model>` or `--model <model>` |
| Max turns | `--max-turns <n>` | Not available |
| Budget limit | `--max-budget-usd <n>` | Not available |
| Resume | `--resume <session_id>` | `codex exec resume <session_id> "prompt"` or `--last` |
| Instructions file | `.claude/CLAUDE.md` | `AGENTS.md` (auto-discovered, root-to-cwd) |
| Config file | `.claude/settings.json` | `.codex/config.toml` (TOML) |
| Auth env var | `ANTHROPIC_API_KEY` | `CODEX_API_KEY` (exec mode) or `OPENAI_API_KEY` (general) |
| OAuth | `CLAUDE_CODE_OAUTH_TOKEN` + Keychain | ChatGPT OAuth (browser) or `--device-auth` |
| Default model | `claude-sonnet-4-6` | `gpt-5.3-codex` |
| Onboarding bypass | `.claude.json` with `hasCompletedOnboarding` | Not needed |
| Sandbox | Docker (DKMV-managed) | OS-level (Seatbelt/Landlock) |
| Sandbox disable | N/A (no built-in sandbox) | `--sandbox danger-full-access` |
| Headless env var | `CLAUDE_CODE_DISABLE_NONINTERACTIVE_CHECK=1` | Not needed |
| Sandbox env var | `IS_SANDBOX=1` | Not needed |
| Output to file | Redirect stdout | `-o <file>` or redirect |
| Structured output | Not built-in | `--output-schema <json>` |
| Ephemeral mode | Not available | `--ephemeral` |
| Working dir | `cd path && claude` | `--cd path` |

---

## Appendix B: Codex CLI JSONL Event Format

> **Source:** [Codex Non-interactive Mode docs](https://developers.openai.com/codex/noninteractive/) and verified sample output. Event types use **dot separators** (e.g., `thread.started`), item types use **snake_case** (e.g., `agent_message`), and top-level fields are flat (e.g., `thread_id`, not `thread: { id }`). Validate against real `codex exec --json` output during Phase 2 (see OQ-1) since minor field additions are possible across Codex versions.

### Core Event Types

The official docs list these event types: `thread.started`, `turn.started`, `turn.completed`, `turn.failed`, `item.*`, and `error`.

### Thread Events

| Event Type | Key Fields | Description |
|------------|-----------|-------------|
| `thread.started` | `{ thread_id }` | Session initialization; `thread_id` is used for resume |
| `thread.closed` | `{ thread_id? }` | Session ended (may not always be emitted if process exits) |

### Turn Events

| Event Type | Key Fields | Description |
|------------|-----------|-------------|
| `turn.started` | `{}` (minimal) | Agent turn begins |
| `turn.completed` | `{ usage: { input_tokens, cached_input_tokens, output_tokens } }` | Agent turn ends with token counts |
| `turn.failed` | `{ error? }` | Turn failed (error result) |

### Item Events

| Event Type | Key Fields | Description |
|------------|-----------|-------------|
| `item.started` | `{ item: { id, type, ... } }` | Item work begins; `type` identifies the item kind |
| `item.completed` | `{ item: { id, type, ... } }` | Final authoritative item state |

### Item Types (in `item.type` field, snake_case)

| Item Type | Key Fields |
|-----------|-----------|
| `agent_message` | `{ id, type: "agent_message", text }` |
| `command_execution` | `{ id, type: "command_execution", command, cwd?, status, exit_code?, duration_ms?, aggregated_output? }` |
| `file_change` | `{ id, type: "file_change", changes: [{ path, kind, diff }], status }` |
| `reasoning` | `{ id, type: "reasoning", summary?, content? }` |
| `plan` | `{ id, type: "plan", text }` |
| `mcp_tool_call` | `{ id, type: "mcp_tool_call", server, tool, status, arguments?, result?, error? }` |
| `web_search` | `{ id, type: "web_search", query }` |

### Error Event

| Event Type | Key Fields | Description |
|------------|-----------|-------------|
| `error` | `{ message?, code? }` | Top-level error (auth failure, crash, etc.) |

### Wire Format Notes

- All event types use **dot separators**: `thread.started`, `turn.completed`, `item.started`, etc.
- All item type values use **snake_case**: `agent_message`, `command_execution`, `file_change`
- `thread_id` is a **flat string field** on `thread.started`, NOT a nested `thread: { id }` object
- Token usage is reported per-turn in `turn.completed` via the `usage` field
- Cost is **not** reported by the CLI (subscription model)
- The adapter should handle unknown event types gracefully (log and skip)

### Sample JSONL Output (from official docs + extended)

```jsonl
{"type":"thread.started","thread_id":"0199a213-81c0-7800-8aa1-bbab2a035a53"}
{"type":"turn.started"}
{"type":"item.started","item":{"id":"item_1","type":"command_execution","command":"bash -lc ls","status":"in_progress"}}
{"type":"item.completed","item":{"id":"item_1","type":"command_execution","command":"bash -lc ls","status":"completed","exit_code":0}}
{"type":"item.started","item":{"id":"item_2","type":"agent_message","text":""}}
{"type":"item.completed","item":{"id":"item_2","type":"agent_message","text":"Repo contains docs, sdk, and examples directories."}}
{"type":"item.started","item":{"id":"item_3","type":"file_change","changes":[{"path":"src/main.py","kind":"edit","diff":"@@ -5,3 +5,4 @@..."}],"status":"completed"}}
{"type":"item.completed","item":{"id":"item_3","type":"file_change","changes":[{"path":"src/main.py","kind":"edit","diff":"..."}],"status":"completed"}}
{"type":"turn.completed","usage":{"input_tokens":24763,"cached_input_tokens":24448,"output_tokens":122}}
```

### Mapping to DKMV StreamEvent

| Codex Event | StreamEvent | Notes |
|-------------|-------------|-------|
| `thread.started` | `type="system", session_id=thread_id` | Session initialization |
| `item.started` (agent_message) | `type="assistant", subtype="text", content=item.text` | Agent text (may be empty initially) |
| `item.completed` (agent_message) | `type="assistant", subtype="text", content=item.text` | Full message |
| `item.started` (command_execution) | `type="assistant", subtype="tool_use", tool_name="shell", tool_input=item.command` | Tool invocation |
| `item.completed` (command_execution) | `type="user", subtype="tool_result", content=item.aggregated_output` | Command output |
| `item.completed` (file_change) | `type="assistant", subtype="tool_use", tool_name="edit_file"` | File edit |
| `turn.completed` | (accumulate usage) | NOT emitted as result — wait for session end |
| `turn.failed` | `type="result", is_error=True` | Error result |
| `thread.closed` | `type="result"` | Emit accumulated results |
| `error` | `type="result", is_error=True, content=message` | Top-level error |

**Result extraction (on session end):**
- `cost` → `0.0` (not reported by Codex CLI)
- `turns` → count of `turn.completed` events seen
- `session_id` → from `thread.started` event's `thread_id` field

**Detecting completion:** The adapter tracks `thread.closed`, `error`, or process exit as session end. Since Codex streams may have multiple turns, the adapter accumulates turn counts and token usage across all `turn.completed` events and emits a single `type="result"` StreamEvent when the session concludes.

---

## Appendix C: AGENTS.md Discovery Algorithm

Codex builds an instruction chain at startup by walking from git root to CWD:

1. **Global scope:** `~/.codex/AGENTS.override.md` → `~/.codex/AGENTS.md`
2. **Per directory (root → CWD):** At each level, first match wins:
   - `AGENTS.override.md` (highest priority)
   - `AGENTS.md`
   - Fallback filenames from config (`project_doc_fallback_filenames`)
3. **Maximum one file per directory level** is included
4. Combined size limit: 32 KiB default (`project_doc_max_bytes` in config)
5. Each file becomes a user-role message: `"# AGENTS.md instructions for <directory>"`

**Implication for DKMV:** Writing `AGENTS.md` to the workspace root is safe — it will be the highest-priority project-level instruction. If the cloned repo already has an `AGENTS.md`, DKMV should **prepend** its system context to the existing content rather than overwriting, preserving project-specific instructions while adding DKMV's agent context.

---

## Appendix D: Codex Docker/CI Recommended Configuration

For running Codex inside DKMV's Docker container:

```bash
codex exec \
  --json \
  --full-auto \
  --sandbox danger-full-access \
  --skip-git-repo-check \
  -m <model> \
  "$(cat /tmp/dkmv_prompt.md)" \
  < /dev/null > /tmp/dkmv_stream.jsonl 2>/tmp/dkmv_stream.err & echo $!
```

Note: `--ephemeral` is intentionally **omitted** — DKMV containers are already ephemeral, and omitting it allows resume to work for retry scenarios (see section 7.1).

**Pre-configured `~/.codex/config.toml` in Dockerfile:**
```toml
# DKMV sandbox configuration for Codex CLI
model = "gpt-5.3-codex"

[sandbox_workspace_write]
network_access = true    # Required for git push, API calls
```

**Network requirements:** Codex needs outbound access to `api.openai.com` (via Cloudflare IPs). Docker container networking must allow this. The `network_access = true` config ensures Codex's sandbox doesn't block network even if `--sandbox danger-full-access` doesn't fully bypass it.

**Session storage:** Session rollout files are written to `~/.codex/sessions/` inside the container. These are lost when the container is destroyed (the normal case), which is fine — resume is only needed within a single component run.

---

*End of PRD*
