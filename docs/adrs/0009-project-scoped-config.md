# Project-Scoped Configuration via `.dkmv/config.json`

## Status

Accepted — Supersedes "Bad: No per-project configuration" limitation from ADR-0007

## Context and Problem Statement

ADR-0007 established environment variables + `.env` as the sole configuration source. This works for single-project use but has limitations:

1. **Repetitive `--repo` on every command** — the most common workflow runs multiple agents against the same repo, requiring the full URL each time
2. **No project context** — run history from different projects mixes together in `./outputs/`
3. **No credential guidance** — new users must manually discover env var names, obtain keys, and create `.env` files with no interactive help
4. **No custom component names** — custom components require full paths every time

A project-scoped configuration layer addresses all of these while preserving the existing env-var-first model from ADR-0007.

## Decision

Introduce `.dkmv/config.json` as a **project-level configuration layer** that sits below environment variables but above built-in defaults in the precedence chain.

**Config cascade (highest to lowest priority):**

```
CLI flags (--model, --max-turns, etc.)
Environment variables (DKMV_MODEL, etc.)
.env file (pydantic-settings reads this)
.dkmv/config.json (project-level defaults)    ← NEW
Built-in defaults (hardcoded in DKMVConfig)
```

**Implementation: compare-against-defaults pattern.** Since pydantic-settings doesn't expose which source provided each field's value, we compare resolved values against a `_BUILTIN_DEFAULTS` dict. If the value equals the built-in default (meaning no env var overrode it), apply the project config override. If it differs, keep the env-provided value.

**Key constraints:**
- `.dkmv/config.json` stores settings and credential *sources*, never secrets
- The entire `.dkmv/` directory is gitignored
- All commands work without `.dkmv/` (backward compatible)
- `find_project_root()` walks up from CWD to find `.dkmv/config.json` for subdirectory support

## Consequences

- Good: Eliminates repetitive `--repo` on every command
- Good: Project-scoped run history in `.dkmv/runs/`
- Good: Guided setup via `dkmv init` discovers credentials and validates the environment
- Good: Fully backward compatible — commands work identically without init
- Good: Environment variables always win over project config (preserves ADR-0007 precedence)
- Bad: Compare-against-defaults has a known edge case: if `DKMV_MODEL` is explicitly set to the same value as the built-in default, project config will override it. Acceptable because the outcome is harmless.
- Bad: `find_project_root()` runs on every `load_config()` call, adding ~20 stat() calls. Negligible for CLI usage.
- Neutral: ADR-0007's "Bad: No per-project configuration" is now resolved

## PRD Reference

PRD: DKMV Init v1 — Sections 5.1, 5.3, 6.2, 6.3
