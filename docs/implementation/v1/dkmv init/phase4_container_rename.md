# Phase 4: Container-Side Rename

## Prerequisites

- Phases 1-3 complete
- All existing tests passing
- ADR-0010 (Container-Side Directory Rename) reviewed and accepted

## Phase Goal

All container-side references to `.dkmv/` are renamed to `.agent/`. The rename is consistent across infrastructure code, built-in YAML files, prompt templates, legacy components, tests, and documentation.

## Phase Evaluation Criteria

- `ComponentRunner._setup_workspace()` creates `.agent/` (not `.dkmv/`)
- `BaseComponent._setup_workspace()` creates `.agent/` (not `.dkmv/`)
- All 5 built-in YAML files reference `.agent/` in `inputs[].dest` and `outputs[].path`
- All prompt templates reference `.agent/` (dev, qa, judge — docs has no refs)
- All legacy component files reference `.agent/`
- `.agent/` added to `.gitignore` (not `.dkmv/`) inside containers
- All test snapshots regenerated with `--snapshot-update`
- `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short` — all pass
- `uv run ruff check . && uv run ruff format --check . && uv run mypy dkmv/` — clean
- `grep -r '\.dkmv/' dkmv/builtins/ dkmv/components/ dkmv/tasks/component.py` returns no matches

---

## Tasks

### T230: Update `ComponentRunner._setup_workspace()`

**PRD Reference:** Section 6.7 (Container-Side `.agent/` Rename)
**Depends on:** Nothing
**Blocks:** T235
**User Stories:** N/A (internal)

#### Description

Change `.dkmv/` to `.agent/` in `ComponentRunner._setup_workspace()` — the `mkdir` command and `.gitignore` entry.

#### Acceptance Criteria

- [x] `mkdir -p .agent` instead of `mkdir -p .dkmv`
- [x] `.gitignore` entry: `.agent/` instead of `.dkmv/`
- [x] No other changes to `_setup_workspace()` behavior

#### Files to Create/Modify

- `dkmv/tasks/component.py` — (modify) Lines ~78-82

#### Implementation Notes

In `_setup_workspace()`, change:
```python
# Before:
f"cd {WORKSPACE_DIR} && mkdir -p .dkmv"
" && (grep -qxF '.dkmv/' .gitignore 2>/dev/null || echo '.dkmv/' >> .gitignore)",

# After:
f"cd {WORKSPACE_DIR} && mkdir -p .agent"
" && (grep -qxF '.agent/' .gitignore 2>/dev/null || echo '.agent/' >> .gitignore)",
```

#### Evaluation Checklist

- [x] String replacement correct
- [x] No other behavioral changes

---

### T231: Update `BaseComponent._setup_workspace()` (Legacy)

**PRD Reference:** Section 6.7 (Container-Side `.agent/` Rename)
**Depends on:** Nothing
**Blocks:** T235
**User Stories:** N/A (internal)

#### Description

Change `.dkmv/` to `.agent/` in `BaseComponent._setup_base_workspace()` for consistency with the new naming.

#### Acceptance Criteria

- [x] `mkdir -p .agent` instead of `mkdir -p .dkmv`
- [x] `.gitignore` entry: `.agent/` instead of `.dkmv/`

#### Files to Create/Modify

- `dkmv/components/base.py` — (modify) Workspace setup commands

#### Implementation Notes

Search for `.dkmv/` string in `base.py` and replace with `.agent/`. Same pattern as T230.

#### Evaluation Checklist

- [x] String replacement correct
- [x] Legacy components still functional

---

### T232: Update All Built-in YAML Task Files

**PRD Reference:** Section 6.7 (Container-Side `.agent/` Rename)
**Depends on:** Nothing
**Blocks:** T235
**User Stories:** N/A (internal)

#### Description

Replace all `.dkmv/` references with `.agent/` in all 5 built-in YAML task files.

#### Acceptance Criteria

- [x] `dkmv/builtins/dev/01-plan.yaml` — all `dest:` and `path:` fields updated
- [x] `dkmv/builtins/dev/02-implement.yaml` — all `dest:`, `path:`, instructions, prompt fields
- [x] `dkmv/builtins/qa/01-evaluate.yaml` — all references
- [x] `dkmv/builtins/judge/01-verdict.yaml` — all references
- [x] `dkmv/builtins/docs/01-generate.yaml` — all references (if any)
- [x] No `.dkmv/` references remain in any built-in YAML file

#### Files to Create/Modify

- `dkmv/builtins/dev/01-plan.yaml` — (modify)
- `dkmv/builtins/dev/02-implement.yaml` — (modify)
- `dkmv/builtins/qa/01-evaluate.yaml` — (modify)
- `dkmv/builtins/judge/01-verdict.yaml` — (modify)
- `dkmv/builtins/docs/01-generate.yaml` — (modify, if has refs)

#### Implementation Notes

This is a straightforward search-and-replace in YAML files. Grep first to find all occurrences:

```bash
grep -rn '\.dkmv/' dkmv/builtins/
```

Then replace `.dkmv/` with `.agent/` in all matching lines. The replacement applies to:
- `dest: /home/dkmv/workspace/.dkmv/prd.md` → `dest: /home/dkmv/workspace/.agent/prd.md`
- `path: /home/dkmv/workspace/.dkmv/plan.md` → `path: /home/dkmv/workspace/.agent/plan.md`
- Instruction text and prompt text referencing `.dkmv/` paths

#### Evaluation Checklist

- [x] `grep -r '\.dkmv/' dkmv/builtins/` returns no matches
- [x] All YAML files are valid after replacement
- [x] `TaskLoader.load()` successfully loads all updated YAMLs

---

### T233: Update Prompt Template Files

**PRD Reference:** Section 6.7 (Container-Side `.agent/` Rename)
**Depends on:** Nothing
**Blocks:** T235
**User Stories:** N/A (internal)

#### Description

Replace `.dkmv/` with `.agent/` in all prompt template `.md` files.

#### Acceptance Criteria

- [x] `dkmv/components/dev/prompt.md` — all `.dkmv/` → `.agent/`
- [x] `dkmv/components/qa/prompt.md` — all `.dkmv/` → `.agent/`
- [x] `dkmv/components/judge/prompt.md` — all `.dkmv/` → `.agent/`
- [x] (docs/prompt.md has no `.dkmv/` references — verify and skip)

#### Files to Create/Modify

- `dkmv/components/dev/prompt.md` — (modify)
- `dkmv/components/qa/prompt.md` — (modify)
- `dkmv/components/judge/prompt.md` — (modify)

#### Implementation Notes

Grep to find all occurrences, then replace:

```bash
grep -rn '\.dkmv/' dkmv/components/*/prompt.md
```

#### Evaluation Checklist

- [x] `grep -r '\.dkmv/' dkmv/components/*/prompt.md` returns no matches

---

### T234: Update Legacy Python Component Files

**PRD Reference:** Section 6.7 (Container-Side `.agent/` Rename)
**Depends on:** Nothing
**Blocks:** T235
**User Stories:** N/A (internal)

#### Description

Replace `.dkmv/` path strings in legacy Python component files.

#### Acceptance Criteria

- [x] `dkmv/components/dev/component.py` — all `.dkmv/` → `.agent/`
- [x] `dkmv/components/qa/component.py` — all `.dkmv/` → `.agent/`
- [x] `dkmv/components/judge/component.py` — all `.dkmv/` → `.agent/`

#### Files to Create/Modify

- `dkmv/components/dev/component.py` — (modify)
- `dkmv/components/qa/component.py` — (modify)
- `dkmv/components/judge/component.py` — (modify)

#### Implementation Notes

```bash
grep -rn '\.dkmv/' dkmv/components/*/component.py
```

Replace all occurrences. These are string literals in path constructions.

#### Evaluation Checklist

- [x] `grep -r '\.dkmv/' dkmv/components/*/component.py` returns no matches

---

### T235: Update and Regenerate Tests and Snapshots

**PRD Reference:** Section 6.7 (Container-Side `.agent/` Rename — Tests)
**Depends on:** T230-T234
**Blocks:** Nothing
**User Stories:** N/A (testing)

#### Description

Update test assertions that reference `.dkmv/` container paths and regenerate all snapshots.

#### Acceptance Criteria

- [x] All test assertions updated: `.dkmv/` → `.agent/`
- [x] Snapshot tests regenerated: `uv run pytest tests/unit/test_prompts.py --snapshot-update`
- [x] All tests pass after regeneration
- [x] No `.dkmv/` references remain in container-context test assertions

#### Files to Create/Modify

- Multiple test files — (modify) Path assertions
- `tests/unit/__snapshots__/test_prompts.ambr` — (regenerate)

#### Implementation Notes

1. Find all test references:
```bash
grep -rn '\.dkmv/' tests/
```

2. Replace `.dkmv/` with `.agent/` in container-context assertions **only**. Do NOT replace host-side `.dkmv/` references (those are project config — Phase 1).

3. Regenerate snapshots:
```bash
uv run pytest tests/unit/test_prompts.py --snapshot-update
```

4. Review snapshot diff to confirm all changes are `.dkmv/` → `.agent/`.

**Critical distinction:** There are now TWO meanings of `.dkmv/`:
- **Host side** (project config): `.dkmv/config.json`, `.dkmv/runs/` — these references stay as `.dkmv/`
- **Container side** (agent workspace): `.dkmv/prd.md`, `.dkmv/plan.md` — these become `.agent/`

Only change the container-side references.

#### Evaluation Checklist

- [x] All tests pass
- [x] Snapshots regenerated and reviewed
- [x] No container-context `.dkmv/` references in tests

---

### T236: Update Documentation

**PRD Reference:** Section 6.7 (Container-Side `.agent/` Rename — Documentation)
**Depends on:** T230-T234
**Blocks:** Nothing
**User Stories:** N/A (documentation)

#### Description

Update documentation to reflect the `.agent/` rename for container-side references.

#### Acceptance Criteria

- [x] `README.md` — container-side `.dkmv/` → `.agent/`
- [x] `CLAUDE.md` — container-side `.dkmv/` → `.agent/`
- [x] `docs/implementation/v1/dkmv tasks [DONE]/` — relevant container references (if any)
- [x] `E2E_TEST_GUIDE.md` — if it exists and has container references

#### Files to Create/Modify

- `README.md` — (modify) Container-side path references
- `CLAUDE.md` — (modify) Container-side path references

#### Implementation Notes

**Be careful:** Documentation now has BOTH host-side `.dkmv/` (project config, keep) and container-side `.dkmv/` (rename to `.agent/`). Only change the container-context occurrences.

Look for patterns like:
- `.dkmv/prd.md` → `.agent/prd.md`
- `.dkmv/plan.md` → `.agent/plan.md`
- `.dkmv/qa_report.json` → `.agent/qa_report.json`
- `.dkmv/verdict.json` → `.agent/verdict.json`
- "Container: `.dkmv/`" → "Container: `.agent/`"

Keep these as `.dkmv/`:
- `.dkmv/config.json`
- `.dkmv/components.json`
- `.dkmv/runs/`

#### Evaluation Checklist

- [x] Container references updated
- [x] Host-side references preserved
- [x] No broken markdown links
