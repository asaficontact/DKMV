# DKMV Tasks v1 — Master Task List

## How to Use This Document

- Tasks are numbered T100-T149 sequentially (continuing from v1 DKMV T001-T095)
- [P] = parallelizable with other [P] tasks in same phase
- Check off tasks as completed: `- [x] T100 ...`
- Dependencies noted as "depends: T100, T103"
- Each phase has a detailed doc in `docs/implementation/v1 - dkmv + tasks/phaseN_*.md`

## Progress Summary

- **Total tasks:** 50
- **Completed:** 50
- **In progress:** 0
- **Blocked:** 0
- **Remaining:** 0

---

## Phase 1 — Foundation (depends: existing v1 DKMV codebase)

> Detailed specs: [phase1_foundation.md](phase1_foundation.md)

### Task 1.1: Package Setup

- [x] T100 Create `dkmv/tasks/` package with `__init__.py` (depends: nothing)
- [x] T101 Add `jinja2` and `pyyaml` to pyproject.toml runtime dependencies (depends: nothing)

### Task 1.2: Task Model — F1

- [x] T102 Create `dkmv/tasks/models.py` with `TaskInput` model + type-field validators (depends: T100)
- [x] T103 [P] Add `TaskOutput` model to models.py (depends: T100)
- [x] T104 Add `TaskDefinition` model with identity, execution, data, instructions, prompt fields + XOR validators (depends: T102, T103)
- [x] T105 [P] Add `TaskResult` model with status Literal (depends: T100)
- [x] T106 [P] Add `ComponentResult` model with task_results list (depends: T105)

### Task 1.3: Task Model Tests

- [x] T107 Write `tests/unit/test_task_models.py` — valid, invalid, edge cases (~30 tests) (depends: T102-T106)

### Task 1.4: Task Loader — F2

- [x] T108 Create `dkmv/tasks/loader.py` with `TaskLoader` class + Jinja2 rendering with `StrictUndefined` (depends: T104)
- [x] T109 Implement YAML parsing + Pydantic validation pipeline in TaskLoader (depends: T108)
- [x] T110 Implement `prompt_file` / `instructions_file` resolution (relative to task file) (depends: T109)
- [x] T111 Implement `load_component()` — scan directory, sort by filename, load all tasks (depends: T110)
- [x] T112 Write `tests/unit/test_task_loader.py` (~20 tests) (depends: T108-T111)

### Task 1.5: Component Discovery — F3

- [x] T113 [P] Create `dkmv/tasks/discovery.py` with `resolve_component()` (depends: T100)
- [x] T114 Implement explicit path resolution (relative/absolute) (depends: T113)
- [x] T115 Implement built-in name resolution via `importlib.resources.files("dkmv.builtins")` (depends: T113)
- [x] T116 Write `tests/unit/test_discovery.py` (~10 tests) (depends: T113-T115)

---

## Phase 2 — TaskRunner (depends: Phase 1)

> Detailed specs: [phase2_taskrunner.md](phase2_taskrunner.md)

### Task 2.1: TaskRunner Core — F4

- [x] T117 Create `dkmv/tasks/runner.py` with `TaskRunner` class skeleton (depends: T104)
- [x] T118 Implement Step 1: Input injection — file copy, text write, env set (depends: T117)
- [x] T119 Implement Step 2: Write instructions to `.claude/CLAUDE.md` (depends: T117)
- [x] T120 Implement Step 3: Save prompt to run directory (depends: T117)
- [x] T121 Implement Step 4: Stream Claude Code with execution parameter cascade (depends: T119, T120)
- [x] T122 Implement Step 5: Collect and validate outputs (required/save) (depends: T121)
- [x] T123 Implement Step 6: Git teardown — force-add declared outputs, commit, push (depends: T122)
- [x] T124 Implement error handling: missing inputs, missing outputs, Claude errors, timeouts (depends: T118-T123)
- [x] T125 Write `tests/unit/test_task_runner.py` (~20 tests) (depends: T117-T124)

---

## Phase 3 — ComponentRunner and CLI (depends: Phase 2)

> Detailed specs: [phase3_component_and_cli.md](phase3_component_and_cli.md)

### Task 3.1: ComponentRunner — F5

- [x] T126 Create `dkmv/tasks/component.py` with `ComponentRunner` class skeleton (depends: T117, T108)
- [x] T127 Implement container lifecycle — start, workspace setup (git clone, `.dkmv/`, `.gitignore`), stop (depends: T126)
- [x] T128 Implement task sequencing with fail-fast — mark remaining as skipped on failure (depends: T127)
- [x] T129 Implement variable propagation — built-in vars, CLI vars, previous task vars (depends: T128)
- [x] T130 Implement cost/duration aggregation + run result saving via RunManager (depends: T129)
- [x] T131 Write `tests/unit/test_component_runner.py` (~15 tests) (depends: T126-T130)

### Task 3.2: CLI `dkmv run` Command — F6

- [x] T132 Add `dkmv run` command to `dkmv/cli.py` with all options (depends: T126)
- [x] T133 Implement `--var KEY=VALUE` parsing and variable mapping (depends: T132)
- [x] T134 Write `tests/unit/test_cli_run.py` (~10 tests) (depends: T132-T133)

---

## Phase 4 — Built-in Components (depends: Phase 3)

> Detailed specs: [phase4_builtins.md](phase4_builtins.md)

### Task 4.1: Built-in Conversion — F7

- [x] T135 Create `dkmv/builtins/` package with `__init__.py` (depends: T115)
- [x] T136 Convert dev component to YAML: `01-plan.yaml`, `02-implement.yaml` (depends: T135)
- [x] T137 [P] Convert qa component to YAML: `01-evaluate.yaml` (depends: T135)
- [x] T138 [P] Convert judge component to YAML: `01-verdict.yaml` (depends: T135)
- [x] T139 [P] Convert docs component to YAML: `01-generate.yaml` (depends: T135)
- [x] T140 Update `pyproject.toml` for built-in YAML packaging (depends: T135)

### Task 4.2: Backward Compatibility — F8

- [x] T141 Update `dkmv dev` CLI wrapper to call `ComponentRunner.run()` with option-to-variable mapping (depends: T136, T132)
- [x] T142 [P] Update `dkmv qa`, `dkmv judge`, `dkmv docs` wrappers similarly (depends: T137-T139, T132)

### Task 4.3: Built-in Tests

- [x] T143 Write `tests/unit/test_builtins.py` — validate all built-in YAMLs load + backward compat (~15 tests) (depends: T136-T142)
- [x] T144 Write `tests/integration/test_run_e2e.py` — E2E with Docker container (~2 tests, @pytest.mark.e2e) (depends: T143)

---

## Phase 5 — Polish and Migration (depends: Phase 4)

> Detailed specs: [phase5_polish.md](phase5_polish.md)

### Task 5.1: Documentation & Cleanup

- [x] T145 Update `CLAUDE.md` with tasks system documentation (depends: T132)
- [x] T146 [P] Update `README.md` with `dkmv run` command documentation (depends: T132)
- [x] T147 [P] Add deprecation notices to `dkmv dev/qa/judge/docs` help text (depends: T141)

### Task 5.2: Final Verification

- [x] T148 Final test suite verification — all quality gates pass (ruff, mypy, pytest, coverage) (depends: T143-T147)
- [x] T149 Update implementation task list + progress log (depends: T148)
