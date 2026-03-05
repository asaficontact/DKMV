# Container-Side Directory Rename: `.dkmv/` → `.agent/`

## Status

Accepted

## Context and Problem Statement

The `.dkmv/` directory name is used for two different purposes:

1. **Host side (new):** Project configuration, component registry, and run output (`.dkmv/config.json`, `.dkmv/runs/`, etc.)
2. **Container side (existing):** Agent workspace for PRDs, plans, reports, and verdicts (`.dkmv/prd.md`, `.dkmv/plan.md`, etc.)

Using the same name for both creates confusion for users and agents, and risks accidental conflicts if the host-side `.dkmv/` directory is mounted into containers.

## Decision

Rename the container-side agent workspace directory from `.dkmv/` to `.agent/`.

**Scope:** All references inside Docker containers — YAML task file `dest:` and `path:` fields, prompt templates, `ComponentRunner._setup_workspace()`, and associated test assertions.

**Rationale:**
- `.agent/` is clear and unambiguous: "this is the agent's working directory"
- It reads naturally in prompts: "Read the PRD at `.agent/prd.md`"
- It eliminates the name collision entirely
- The change is a pure search-and-replace — the directory name appears as a string constant in all locations

### Git Behavior

`.agent/` is **not** added to `.gitignore`. Agent tasks commit `.agent/` files naturally as inter-task data (evaluation reports, analysis results, user decisions). Only `.claude/` is gitignored to prevent Claude Code's internal state from polluting commits. See ADR-0015 for the full git commit safety strategy.

## Consequences

- Good: No naming ambiguity between host `.dkmv/` (config) and container `.agent/` (workspace)
- Good: Container instructions are clearer — "the agent's directory" is self-documenting
- Good: `.agent/` files are committed naturally, enabling inter-task communication via git (see ADR-0008)
- Bad: Existing custom YAML task files referencing `.dkmv/` paths will need updating. Mitigated by the fact that the task system is new and has few external users.

## PRD Reference

PRD: DKMV Init v1 — Sections 5.2, 6.7
