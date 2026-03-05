# Multi-Agent Adapter Architecture Feature Registry

## Overview

10 features organized in 4 phases. Features must be built in dependency order. Phase 1 is a pure refactor (zero behavioral change). Phase 2 adds the Codex adapter and agent selection. Phase 3 integrates Docker and init. Phase 4 polishes error handling and documentation.

## Dependency Diagram

```
Phase 1: Adapter Foundation (Pure Refactor)
──────────────────────────────────────────────────────
  F1 ─────────┬──────────────────────────────────────→
  (Protocol)  │                                       │
              ▼                                       │
  F2 ─────────┤                                       │
  (Claude     │                                       │
   Adapter)   │                                       │
              │                                       │
Phase 2: Codex Adapter & Agent Selection              │
──────────────────────────────────────────────────────│
              ▼                                       │
  F3 ────────────────────────────→                    │
  (Codex Adapter)                │                    │
              │                  │                    │
              ▼                  ▼                    │
  F9 ──────────────→  F4 ───────────→                │
  (Stream            (Resolution     │                │
   Normalization)     Cascade)       │                │
                         │           │                │
                         ▼           ▼                │
                      F5 ──────→  F10 ──→            │
                      (Model      (CLI                │
                       Validation) Agent)             │
                                     │                │
Phase 3: Docker & Init Integration   │                │
──────────────────────────────────────────────────────│
                                     ▼                │
                      F6 ◄───────────┤                │
                      (Docker        │                │
                       Image)        │                │
                         │           │                │
                         ▼           ▼                │
                      F7 ──────→  F8 ◄───────────────┘
                      (Init        (Mixed-Agent
                       Creds)       Components)
                                     │
Phase 4: Polish                      │
──────────────────────────────────────────────────────
                         (Error messages, docs, etc.)
```

**Reading the diagram:**
- Arrows point from dependency to dependent (A → B means "B depends on A").
- F1 (Protocol) is the root — everything depends on it.
- F2 (Claude Adapter) depends on F1; validates the protocol with existing behavior.
- F3 (Codex Adapter) depends on F2 (mirrors its structure).
- F8 (Mixed-Agent) depends on F2, F3, F4, and F6 (needs both adapters, resolution, and Docker).

## Feature List

### F1: AgentAdapter Protocol

- **Priority:** 1
- **Phase:** 1 — Adapter Foundation
- **Status:** [ ] Not started
- **Depends on:** None
- **Blocks:** F2, F3, F4, F5, F9, F10
- **User Stories:** US-01, US-02
- **Tasks:** TBD
- **PRD Reference:** Section 5 (Target Architecture), Section 6 (Agent Adapter Interface)
- **Key Deliverables:**
  - `dkmv/adapters/base.py` with `AgentAdapter` Protocol class
  - `StreamResult` dataclass for normalized result extraction
  - `dkmv/adapters/__init__.py` with `get_adapter()` factory and adapter registry
  - Unit tests for registry (`test_adapters/test_base.py`)

### F2: ClaudeCodeAdapter Extraction

- **Priority:** 2
- **Phase:** 1 — Adapter Foundation
- **Status:** [ ] Not started
- **Depends on:** F1
- **Blocks:** F3, F8, F9
- **User Stories:** US-03, US-04
- **Tasks:** TBD
- **PRD Reference:** Section 4 (Current Architecture Analysis — CP-1 through CP-4), Section 8 (Changes by File — Phase 1 modifications)
- **Key Deliverables:**
  - `dkmv/adapters/claude.py` implementing `AgentAdapter` — extracts logic from `sandbox.py`, `stream.py`, `component.py`, `runner.py`
  - `build_command()` produces byte-identical CLI commands to current hardcoded implementation
  - `parse_event()` handles all Claude JSONL event types (system, assistant, user, result)
  - `stream_claude()` on `SandboxManager` preserved as thin wrapper (exact current signature)
  - `StreamParser` accepts optional adapter for delegated parsing
  - `TaskRunner._write_instructions()` uses `adapter.instructions_path`
  - `_build_sandbox_config()` delegates auth to adapter
  - All 720+ existing tests pass without modification
  - Claude adapter tests (`test_adapters/test_claude.py`)

### F3: CodexCLIAdapter Implementation

- **Priority:** 3
- **Phase:** 2 — Codex Adapter & Agent Selection
- **Status:** [ ] Not started
- **Depends on:** F1, F2
- **Blocks:** F8, F9
- **User Stories:** US-05, US-06, US-07
- **Tasks:** TBD
- **PRD Reference:** Section 7 (Codex CLI Adapter Specification), Appendix A (Reference), Appendix B (JSONL Format)
- **Key Deliverables:**
  - `dkmv/adapters/codex.py` implementing `AgentAdapter`
  - `build_command()` producing `codex exec` with `--json --full-auto --sandbox danger-full-access --skip-git-repo-check`
  - Resume support via `codex exec resume <session_id>`
  - `parse_event()` handling Codex JSONL (dot-separated types, snake_case items)
  - `supports_max_turns()` → False, `supports_budget()` → False
  - `instructions_path` → `AGENTS.md` with prepend-to-existing behavior
  - `get_auth_env_vars()` returning `CODEX_API_KEY` (with `OPENAI_API_KEY` fallback)
  - Codex adapter tests (`test_adapters/test_codex.py`)

### F4: Agent Resolution Cascade

- **Priority:** 4
- **Phase:** 2 — Codex Adapter & Agent Selection
- **Status:** [ ] Not started
- **Depends on:** F1
- **Blocks:** F5, F8, F10
- **User Stories:** US-08, US-09
- **Tasks:** TBD
- **PRD Reference:** Section 5 (Agent Resolution Cascade — 7 levels), Section 10 (YAML Schema Changes)
- **Key Deliverables:**
  - `agent: str | None = None` field on `TaskDefinition`, `ManifestTaskRef`, `ComponentManifest`
  - `agent: str = "claude"` on `BaseComponentConfig`
  - `default_agent: str` field on `DKMVConfig` (env: `DKMV_AGENT`, default: `"claude"`)
  - `agent: str | None = None` on `ProjectDefaults`
  - `agent: str | None = None` on `CLIOverrides`
  - 7-level resolution in `ComponentRunner`/`TaskRunner`: task YAML > task_ref > manifest > CLI --agent > project config > DKMVConfig > built-in default
  - Agent resolution tests covering all 7 levels

### F5: Agent-Model Validation and Inference

- **Priority:** 5
- **Phase:** 2 — Codex Adapter & Agent Selection
- **Status:** [ ] Not started
- **Depends on:** F1, F3, F4
- **Blocks:** None
- **User Stories:** US-10, US-11
- **Tasks:** TBD
- **PRD Reference:** Section 5 (Agent-Model Validation), Section 10.4 (Agent Inference from Model)
- **Key Deliverables:**
  - `infer_agent_from_model()` in `dkmv/adapters/__init__.py` — infers `claude` from `claude-*`, `codex` from `gpt-*` and `o\d*` prefixes
  - `validate_model()` on each adapter — Claude validates `claude-*`, Codex validates `gpt-*` and `o\d*`
  - Auto-substitution of agent's default model when resolved model is from wrong family (with info log)
  - Clear error on explicit model-agent mismatch (e.g., `--agent codex --model claude-opus-4-6`)
  - Tests for inference, validation, and auto-substitution

### F6: Multi-Agent Docker Image

- **Priority:** 6
- **Phase:** 3 — Docker & Init Integration
- **Status:** [ ] Not started
- **Depends on:** F3
- **Blocks:** F8
- **User Stories:** US-12, US-13
- **Tasks:** TBD
- **PRD Reference:** Section 11 (Dockerfile Changes), Appendix D (Codex Docker/CI Config)
- **Key Deliverables:**
  - Updated `dkmv/images/Dockerfile` installing both `@anthropic-ai/claude-code` and `@openai/codex` with version-pinned build args
  - Pre-configured `~/.codex/config.toml` for headless Docker usage (sandbox mode, network access)
  - `--codex-version` flag on `dkmv build` command
  - All existing Claude Code Dockerfile config unchanged (`IS_SANDBOX`, `NODE_OPTIONS`, onboarding bypass)
  - Image size verification (< 5GB threshold)

### F7: Codex Credential Discovery in Init

- **Priority:** 7
- **Phase:** 3 — Docker & Init Integration
- **Status:** [ ] Not started
- **Depends on:** F3, F4
- **Blocks:** None
- **User Stories:** US-14, US-15
- **Tasks:** TBD
- **PRD Reference:** Section 9.4 (Init Flow Changes), Section 9.5 (Credential Validation)
- **Key Deliverables:**
  - Extended `dkmv init` credential discovery: detect `CODEX_API_KEY` and `OPENAI_API_KEY`
  - Auth method prompt: Claude-only, Codex-only, or Both
  - `codex_api_key_source` in `CredentialSources`
  - `codex_api_key: str` field on `DKMVConfig` (env: `CODEX_API_KEY`)
  - `OPENAI_API_KEY` fallback in `load_config()`
  - Non-interactive `--yes` mode auto-detects available credentials
  - Init and config tests for Codex credential discovery

### F8: Mixed-Agent Components

- **Priority:** 8
- **Phase:** 3 — Docker & Init Integration
- **Status:** [ ] Not started
- **Depends on:** F2, F3, F4, F6
- **Blocks:** None
- **User Stories:** US-16, US-17
- **Tasks:** TBD
- **PRD Reference:** Section 5 (Adapter Lifecycle & Threading), Section 14 (R7: Mixed-Agent Credential Handling)
- **Key Deliverables:**
  - `_build_sandbox_config()` scans all task refs to determine `agents_needed` set
  - Credentials for ALL agents passed into container env vars
  - Docker args include mounts for ALL agents (Claude OAuth creds when needed)
  - Adapter instantiated per-task (not per-component)
  - Multi-agent `.gitignore` setup (both `.claude/` and `.codex/` entries)
  - Tests for mixed-agent credential scanning and per-task adapter instantiation

### F9: Stream Event Normalization

- **Priority:** 4
- **Phase:** 2 — Codex Adapter & Agent Selection
- **Status:** [ ] Not started
- **Depends on:** F1, F2, F3
- **Blocks:** None
- **User Stories:** US-18, US-19
- **Tasks:** TBD
- **PRD Reference:** Section 12 (Stream Parsing & Normalization), Appendix B (Codex JSONL Format)
- **Key Deliverables:**
  - `StreamParser` gains optional `adapter` parameter for delegated parsing
  - Codex JSONL events normalized to existing `StreamEvent` dataclass
  - Codex adapter accumulates turn counts and token usage across `turn.completed` events
  - Single `result` StreamEvent emitted on `thread.closed`
  - `total_cost_usd` = 0.0 for Codex runs (subscription model)
  - `render_event()` works identically regardless of source agent
  - Snapshot tests comparing parsed Codex events to expected StreamEvent values

### F10: CLI Agent Selection

- **Priority:** 5
- **Phase:** 2 — Codex Adapter & Agent Selection
- **Status:** [ ] Not started
- **Depends on:** F1, F4
- **Blocks:** None
- **User Stories:** US-20, US-21
- **Tasks:** TBD
- **PRD Reference:** Section 8 (Changes by File — Phase 2 CLI), Section 10.3 (Agent Resolution in Code)
- **Key Deliverables:**
  - `--agent` option on all 5 run commands (`dev`, `qa`, `docs`, `plan`, `run_component`)
  - `agent` field on `CLIOverrides` dataclass
  - Agent flag participates in resolution cascade at priority level 4
  - Existing commands work unchanged when `--agent` is not specified
  - CLI tests for `--agent` flag integration
