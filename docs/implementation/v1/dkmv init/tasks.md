# DKMV Init v1 — Master Task List

## How to Use This Document

- Tasks are numbered T200-T247 sequentially (continuing from Tasks v1 T100-T149)
- [P] = parallelizable with other [P] tasks in same phase
- Check off tasks as completed: `- [x] T200 ...`
- Dependencies noted as "depends: T200, T203"
- Each phase has a detailed doc in `phaseN_*.md`

## Progress Summary

- **Total tasks:** 39
- **Completed:** 39
- **In progress:** 0
- **Blocked:** 0
- **Remaining:** 0

---

## Phase 1 — Project Config Foundation (depends: existing Tasks v1 codebase)

> Detailed specs: [phase1_project_config.md](phase1_project_config.md)

### Task 1.1: Project Config Models — F1

- [x] T200 Create `dkmv/project.py` with `ProjectConfig`, `CredentialSources`, `ProjectDefaults`, `SandboxSettings` models (depends: nothing)
- [x] T201 [P] Implement `find_project_root()` — walk up from CWD to find `.dkmv/config.json` (depends: nothing)
- [x] T202 Implement `load_project_config()` — load and validate `.dkmv/config.json` (depends: T200, T201)
- [x] T203 Modify `load_config()` with project config cascade using `model_fields_set` (depends: T200, T201, T202)
- [x] T204 Fix `.env` resolution from subdirectories — verify with dedicated tests (depends: T201, T203)
- [x] T205 [P] Implement `get_repo()` helper — CLI arg > project config > error (depends: T202)

### Task 1.2: Project Config Tests

- [x] T206 Write `tests/unit/test_project.py` — models, find_project_root, cascade, get_repo (38 tests) (depends: T200-T205)

---

## Phase 2 — Init Command + Rich UX (depends: Phase 1)

> Detailed specs: [phase2_init_command.md](phase2_init_command.md)

### Task 2.1: Init Building Blocks

- [x] T210 [P] Implement credential discovery functions (env var, dotenv, gh CLI) (depends: nothing)
- [x] T211 [P] Implement project detection functions (git remote, branch, project name) (depends: nothing)
- [x] T212 [P] Implement Docker image check function (depends: nothing)
- [x] T213 Implement `.dkmv/` directory creation and config writing (depends: T200)
- [x] T214 [P] Implement `.gitignore` update function (depends: nothing)

### Task 2.2: Init Command

- [x] T215 Implement `dkmv init` CLI command with Rich panels and step output (depends: T210-T214)
- [x] T216 Implement `--yes` non-interactive mode (depends: T215)
- [x] T217 Implement reinit behavior — detect existing, preserve runs/components (depends: T215)
- [x] T218 Handle `.env` creation/update for missing credentials (depends: T210, T215)

### Task 2.3: Init Tests

- [x] T219 Write `tests/unit/test_init.py` — discovery, detection, init flow, reinit (~35 tests) (depends: T210-T218)

---

## Phase 3 — Component Registry (depends: Phase 2)

> Detailed specs: [phase3_component_registry.md](phase3_component_registry.md)

### Task 3.1: Registry Core — F3

- [x] T220 Create `dkmv/registry.py` with `ComponentRegistry` class (depends: nothing)
- [x] T221 Modify `resolve_component()` to add registry lookup as step 3 (depends: T220)
- [x] T222 Implement `dkmv components` command — Rich table, built-in + custom (depends: T220)
- [x] T223 Implement `dkmv register` command with validation (depends: T220)
- [x] T224 Implement `dkmv unregister` command (depends: T220)
- [x] T225 Update error messages in `resolve_component()` to include registered names (depends: T221)

### Task 3.2: Registry Tests

- [x] T226 Write `tests/unit/test_registry.py` + update `tests/unit/test_discovery.py` (~30 tests) (depends: T220-T225)

---

## Phase 4 — Container-Side Rename (depends: Phase 3)

> Detailed specs: [phase4_container_rename.md](phase4_container_rename.md)

### Task 4.1: Infrastructure Rename

- [x] T230 [P] Update `ComponentRunner._setup_workspace()` — `.dkmv/` → `.agent/` (depends: nothing)
- [x] T231 [P] Update `BaseComponent._setup_workspace()` — `.dkmv/` → `.agent/` (depends: nothing)

### Task 4.2: YAML and Template Rename

- [x] T232 [P] Update all 5 built-in YAML task files — `dest:` and `path:` fields (depends: nothing)
- [x] T233 [P] Update all prompt template `.md` files — text references (depends: nothing)
- [x] T234 [P] Update all legacy Python component files — path strings (depends: nothing)

### Task 4.3: Tests and Documentation

- [x] T235 Update and regenerate all test files and snapshots (depends: T230-T234)
- [x] T236 Update documentation (`README.md`, `CLAUDE.md`) — container-side references only (depends: T230-T234)

---

## Phase 5 — CLI Integration + Polish (depends: Phase 4)

> Detailed specs: [phase5_cli_integration.md](phase5_cli_integration.md)

### Task 5.1: CLI Repo Optionality

- [x] T240 Make `--repo` optional on `dkmv run` — project config fallback (depends: T205)
- [x] T241 Convert `repo` from positional Argument to named `--repo` Option on wrappers (depends: T205)

### Task 5.2: Run Output Relocation

- [x] T242 Verify run output relocation to `.dkmv/runs/` — add tests (depends: T203)
- [x] T243 Verify `dkmv runs` and `dkmv show` use project-scoped output dir (depends: T242)

### Task 5.3: Documentation & Polish

- [x] T244 [P] Update `README.md` — init docs, new getting-started flow (depends: all previous)
- [x] T245 [P] Update `CLAUDE.md` — init system, project config, registry (depends: all previous)
- [x] T246 Final test suite verification — all quality gates pass (depends: T240-T245)
- [x] T247 Update `.env.example` — placeholder values, `dkmv init` reference (depends: nothing)
