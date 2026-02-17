# Claude Code Only for v1

## Status

Accepted

## Context and Problem Statement

DKMV orchestrates AI coding agents inside Docker containers. Multiple LLM-powered coding tools exist (Claude Code, Aider, Cursor, etc.). Which should we support in v1?

## Decision Drivers

- Need a reliable, well-documented headless mode for autonomous operation
- Need structured output format for real-time progress monitoring
- Must work inside Docker containers without a GUI
- Should have a clear abstraction boundary for future extensibility

## Considered Options

- Support multiple AI coding tools from the start
- Lock to Claude Code for v1, design for extensibility in v2
- Build a generic LLM interface without tool-specific integration

## Decision Outcome

Chosen option: "Lock to Claude Code for v1, design for extensibility in v2", because Claude Code's headless mode with stream-json output provides a well-defined interface for orchestration, and supporting multiple tools from the start would spread effort across integration surfaces before the core architecture is proven.

### Integration Architecture

```
┌──────────────────────────────────────────────────┐
│                BaseComponent ABC                  │
│  build_prompt() → prompt string                  │
│  collect_artifacts() → result data               │
│  parse_result() → typed result                   │
└──────────────────────┬───────────────────────────┘
                       │ calls
                       ▼
┌──────────────────────────────────────────────────┐
│              SandboxManager                       │
│  stream_claude()                                 │
│  ┌────────────────────────────────────────────┐  │
│  │  claude -p "$(cat prompt.md)"              │  │
│  │    --dangerously-skip-permissions          │  │
│  │    --output-format stream-json             │  │
│  │    --model <model>                         │  │
│  │    --max-turns <n>                         │  │
│  │  > /tmp/dkmv_stream.jsonl 2> .err          │  │
│  └────────────────────────────────────────────┘  │
└──────────────────────┬───────────────────────────┘
                       │ yields
                       ▼
┌──────────────────────────────────────────────────┐
│              StreamParser                         │
│                                                  │
│  stream-json events:                             │
│  ├── {"type": "system", ...}     → init info     │
│  ├── {"type": "assistant", ...}  → text output   │
│  ├── {"type": "tool_use", ...}   → tool calls    │
│  └── {"type": "result", ...}     → final summary │
│       ├── total_cost_usd                         │
│       ├── duration_ms                            │
│       ├── num_turns                              │
│       └── session_id                             │
└──────────────────────────────────────────────────┘
```

### Extensibility Path (v2+)

The `BaseComponent` ABC and `SandboxManager` provide the abstraction boundary. In v2, alternative runtimes (Codex, Aider, custom Agent SDK agents) can be supported by:

1. Adding a new `stream_<tool>()` method to `SandboxManager`
2. Or swapping `SandboxManager` entirely behind the same interface
3. Components remain unchanged — they only depend on the prompt/result interface

### Consequences

- Good: Focused development effort on a single, well-understood integration.
- Good: stream-json output format provides structured events for real-time parsing.
- Good: BaseComponent ABC can be extended in v2 to support alternative tools.
- Bad: Users who prefer other AI coding tools cannot use DKMV v1.
- Neutral: The Docker-based isolation pattern is tool-agnostic and will transfer to other tools.
