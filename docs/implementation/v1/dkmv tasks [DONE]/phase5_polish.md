# Phase 5: Polish and Migration

## Prerequisites

- Phase 1-4 complete (all core code and built-ins working)
- `dkmv run dev/qa/judge/docs` works end-to-end
- `dkmv dev/qa/judge/docs` backward compat works
- All tests passing

## Phase Goal

Documentation updated, deprecation notices added, full test suite verified. The task system is production-ready, documented, and coexists cleanly with the existing Python component system.

## Phase Evaluation Criteria

- `CLAUDE.md` includes task system documentation
- `README.md` documents `dkmv run` command
- `dkmv dev --help` shows it's a wrapper (optional deprecation hint)
- All quality gates pass: ruff, mypy, pytest (coverage >= 80%)
- No regressions in any existing tests
- Implementation task list fully checked off

---

## Tasks

### T145: Update CLAUDE.md

**PRD Reference:** Section 7 Phase 5 ("Update CLAUDE.md")
**Depends on:** T132
**Blocks:** T148
**User Stories:** N/A

#### Description

Update the project's `CLAUDE.md` with documentation about the task system: architecture, new directories, new commands.

#### Acceptance Criteria

- [ ] `CLAUDE.md` includes `dkmv/tasks/` in the architecture section
- [ ] `dkmv/builtins/` documented as built-in YAML component definitions
- [ ] `dkmv run` command documented in Quick Reference
- [ ] Task YAML format briefly described
- [ ] Execution parameter cascade mentioned

#### Files to Create/Modify

- `CLAUDE.md` — (modify) Add task system documentation

#### Implementation Notes

Add to the Architecture section:
```
dkmv/
  tasks/               # Task engine: models, loader, runner, component runner, discovery
  builtins/            # Built-in YAML component definitions (dev, qa, judge, docs)
```

Add to Quick Reference:
```bash
uv run dkmv run dev --repo ... --var prd_path=...  # Run built-in component via task system
uv run dkmv run ./my-component --repo ... --var k=v # Run custom component
```

#### Evaluation Checklist

- [ ] Task system documented
- [ ] New directories listed
- [ ] New commands in quick reference

---

### T146: Update README.md

**PRD Reference:** Section 7 Phase 5 ("Documentation")
**Depends on:** T132
**Blocks:** T148
**User Stories:** N/A

#### Description

Update the project README with `dkmv run` command documentation and task system overview.

#### Acceptance Criteria

- [ ] `dkmv run` added to CLI Commands section
- [ ] Brief "Task System" section explaining YAML-based components
- [ ] Example usage: `dkmv run dev --repo ... --var prd_path=...`
- [ ] Link to task_definition.md for full schema reference

#### Files to Create/Modify

- `README.md` — (modify) Add task system documentation

#### Implementation Notes

Add to CLI Commands section:
```bash
# Run a component (new task system)
dkmv run <component> --repo <url> [--var KEY=VALUE ...] [--model <model>]

# Examples:
dkmv run dev --repo https://github.com/org/repo --var prd_path=./auth.md
dkmv run ./custom-component --repo https://github.com/org/repo --var key=value
```

Add to project structure:
```
dkmv/
├── tasks/                 # Task engine (models, loader, runner, discovery)
├── builtins/              # Built-in YAML components (dev, qa, judge, docs)
```

#### Evaluation Checklist

- [ ] README updated
- [ ] Examples accurate

---

### T147: Add Deprecation Notices

**PRD Reference:** Section 9 Phase B ("Mark CLI commands as deprecated")
**Depends on:** T141
**Blocks:** T148
**User Stories:** N/A

#### Description

Add deprecation notices to the `dkmv dev/qa/judge/docs` CLI commands, directing users to `dkmv run`.

#### Acceptance Criteria

- [ ] `dkmv dev --help` shows: "Note: This is a wrapper around `dkmv run dev`. Consider using `dkmv run dev` directly."
- [ ] Same for qa, judge, docs
- [ ] Optional: show a one-time deprecation notice when these commands are invoked
- [ ] No functional changes — commands still work identically

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) Add deprecation notices to help text

#### Implementation Notes

Use Typer's `help` parameter or `epilog` to add the notice without changing functionality:
```python
@app.command(
    help="Implement features from a PRD.\n\nNote: This is a wrapper around `dkmv run dev`.",
)
```

For runtime notice (optional):
```python
console.print("[dim]Tip: You can also use `dkmv run dev --repo ... --var prd_path=...`[/dim]")
```

#### Evaluation Checklist

- [ ] Help text includes wrapper notice
- [ ] No functional changes
- [ ] Commands still work

---

### T148: Final Test Suite Verification

**PRD Reference:** Section 11 ("All tests pass"), Section 7 Phase 5
**Depends on:** T143-T147
**Blocks:** T149
**User Stories:** N/A

#### Description

Run the full test suite and all quality gates to verify everything works together with no regressions.

#### Acceptance Criteria

- [ ] `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short` — all pass, coverage >= 80%
- [ ] `uv run ruff check .` — clean
- [ ] `uv run ruff format --check .` — clean
- [ ] `uv run mypy dkmv/` — clean
- [ ] `uv run dkmv --help` — shows all commands including `run`
- [ ] `uv run dkmv run --help` — shows all options
- [ ] `uv run dkmv dev --help` — shows wrapper notice
- [ ] No regressions: all existing 268+ tests still pass
- [ ] New tests: ~90 additional tests across all phases

#### Files to Create/Modify

- None (verification only)

#### Implementation Notes

Run each check and record the results:
```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy dkmv/
uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short
uv run dkmv --help
uv run dkmv run --help
```

If any failures, fix them before marking complete.

#### Evaluation Checklist

- [ ] All checks pass
- [ ] Coverage meets threshold
- [ ] No regressions

---

### T149: Update Implementation Documentation

**PRD Reference:** N/A (meta-task)
**Depends on:** T148
**Blocks:** Nothing
**User Stories:** N/A

#### Description

Update all implementation documentation to reflect completed status: check off tasks in `tasks.md`, add final session entry to `progress.md`.

#### Acceptance Criteria

- [ ] All tasks T100-T149 checked off in `tasks.md`
- [ ] Progress summary updated with final counts
- [ ] `progress.md` has session entries for all implementation sessions
- [ ] Final metrics recorded: test count, coverage, session count

#### Files to Create/Modify

- `docs/implementation/v1 - dkmv + tasks/tasks.md` — (modify) Check off all tasks
- `docs/implementation/v1 - dkmv + tasks/progress.md` — (modify) Add final entry

#### Evaluation Checklist

- [ ] Documentation reflects completed state
- [ ] All tasks checked off

---

## Phase Completion Checklist

- [ ] All tasks T145-T149 completed
- [ ] Documentation updated (CLAUDE.md, README.md)
- [ ] Deprecation notices added
- [ ] Full test suite passes with coverage >= 80%
- [ ] All quality gates green
- [ ] Implementation documentation complete
- [ ] Task system production-ready
