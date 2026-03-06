# Convert `repo` from Positional Argument to Named `--repo` Option

## Status

Accepted

## Context and Problem Statement

The wrapper commands (`dkmv dev`, `dkmv qa`, `dkmv docs`, `dkmv plan`) take `repo` as a positional `typer.Argument()`, while `dkmv run` takes it as a named `typer.Option("--repo")`. With the introduction of project-scoped configuration, `repo` needs to be optional on all commands (it can come from `.dkmv/config.json`).

Optional positional arguments create ambiguous CLI parsing — Typer/Click can't reliably distinguish between an omitted positional and the next argument. Named options handle optionality cleanly.

## Decision

Convert `repo` from a positional `Argument()` to a named `--repo` `Option()` on all wrapper commands. This is a **breaking change** to the CLI interface.

**Old syntax:**
```bash
dkmv dev https://github.com/org/repo --prd prd.md
```

**New syntax:**
```bash
dkmv dev --repo https://github.com/org/repo --prd prd.md  # explicit
dkmv dev --prd prd.md                                       # from project config
```

## Consequences

- Good: Consistent `--repo` syntax across all commands (`dkmv run` and wrappers)
- Good: Clean optional behavior — omit `--repo` when project config provides it
- Good: Better error messages suggesting `dkmv init` when repo is missing
- Bad: Breaking change — scripts using positional `repo` will break. Acceptable because DKMV is pre-1.0 and the user base is small.
- Neutral: The `dkmv run` command already uses `--repo` as an option — this makes wrappers consistent with it.

## PRD Reference

PRD: DKMV Init v1 — Section 6.9
