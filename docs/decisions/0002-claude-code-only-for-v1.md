# Claude Code Only for v1

## Status

Accepted

## Context and Problem Statement

DKMV orchestrates AI coding agents inside Docker containers. Multiple LLM-powered coding tools exist (Claude Code, Aider, Cursor, etc.). Which should we support in v1?

## Considered Options

- Support multiple AI coding tools from the start
- Lock to Claude Code for v1, design for extensibility in v2
- Build a generic LLM interface without tool-specific integration

## Decision Outcome

Chosen option: "Lock to Claude Code for v1, design for extensibility in v2", because Claude Code's headless mode with stream-json output provides a well-defined interface for orchestration, and supporting multiple tools from the start would spread effort across integration surfaces before the core architecture is proven.

### Consequences

- Good: Focused development effort on a single, well-understood integration.
- Good: stream-json output format provides structured events for real-time parsing.
- Good: BaseComponent ABC can be extended in v2 to support alternative tools.
- Bad: Users who prefer other AI coding tools cannot use DKMV v1.
- Neutral: The Docker-based isolation pattern is tool-agnostic and will transfer to other tools.
