# DKMV v1 — Master Task List

## How to Use This Document

- Tasks are numbered T001-T095 sequentially
- [P] = parallelizable with other [P] tasks in same phase
- Check off tasks as completed: `- [x] T001 ...`
- Dependencies noted as "depends: T001, T003"
- Each phase has a detailed doc in `docs/implementation/phaseN_*.md`

## Progress Summary

- **Total tasks:** 90
- **Completed:** 26
- **In progress:** 0
- **Blocked:** 0

---

## Phase 0 — Testing Infrastructure (depends: nothing)

→ Detailed specs: [phase0_testing.md](phase0_testing.md)

### Task 0.1: Unit Test Foundation

- [x] T001 Create `tests/` directory structure (unit/, integration/, e2e/, docker/)
- [x] T002 Configure pytest in pyproject.toml (asyncio_mode="auto", e2e marker, coverage)
- [x] T003 Create `tests/conftest.py` with shared fixtures (git_repo, mock_sandbox, make_config)
- [x] T004 Create `tests/factories.py` with polyfactory model factories

### Task 0.2: Integration Test Fixtures

- [x] T005 Create `tests/integration/conftest.py` with SWE-ReX mocks (DockerDeployment, RemoteRuntime)
- [x] T006 Create mock sandbox session helper that records commands
- [x] T007 Create temporary test repo helper with `src/`, `tests/`

---

## Phase 1 — Foundation (depends: Phase 0)

→ Detailed specs: [phase1_foundation.md](phase1_foundation.md)

### Task 1.1: Project Scaffolding (F1)

- [x] T010 Create pyproject.toml with hatchling build system and all dependencies (depends: nothing)
- [x] T011 Create dkmv/ package directory structure per PRD Section 3.1 (depends: T010)
- [x] T012 [P] Create dkmv/cli.py with Typer app skeleton (depends: T011)
- [x] T013 [P] Create dkmv/__init__.py and dkmv/__main__.py (depends: T011)
- [x] T014 [P] Create dkmv/utils/async_support.py with async_command decorator (depends: T011)
- [x] T015 Verify `uv sync && uv run dkmv --help` works (depends: T012, T013, T014)
- [x] T016 Create docs/ directory structure per PRD Section 3.4 (depends: nothing)
- [x] T017 Write ADR-0001 (record architecture decisions) using MADR template (depends: T016)
- [x] T018 Set up .pre-commit-config.yaml, configure ruff + mypy in pyproject.toml, create .gitignore and .env.example (depends: T010)

### Task 1.2: Global Configuration (F1)

- [x] T019 Create dkmv/config.py with DKMVConfig pydantic-settings BaseSettings (depends: T011)
- [x] T020 Implement Typer @app.callback() for global options --verbose, --dry-run (depends: T012, T019)
- [x] T021 Implement API key validation with helpful error message (depends: T019)
- [x] T022 Write tests/unit/test_config.py (depends: T019)

### Task 1.3: Docker Image (F2)

- [x] T023 Move/verify Dockerfile at dkmv/images/Dockerfile (depends: T011)
- [x] T024 Create `dkmv build` CLI command with --no-cache, --claude-version (depends: T012, T023)
- [x] T025 Write tests/docker/test_image.sh with image structure assertions (depends: T023)
- [x] T026 Test `dkmv build` produces working image (depends: T024)

### Task 1.4: CI Pipeline (F1)

- [x] T027 Create .github/workflows/ci.yml (depends: T018)
- [x] T028 [P] Configure CI stages: lint, typecheck, unit, integration, Docker (depends: T027)
- [ ] T029 [P] Verify CI pipeline passes (depends: T028)

---

## Phase 2 — Core Framework (depends: Phase 1)

→ Detailed specs: [phase2_core.md](phase2_core.md)

### Task 2.1: SandboxManager (F3)

- [ ] T030 Create dkmv/core/models.py with SandboxConfig, BaseComponentConfig, BaseResult (depends: T019)
- [ ] T031 Create dkmv/core/sandbox.py with SandboxManager class (depends: T030)
- [ ] T032 Implement start() with SWE-ReX DockerDeployment (depends: T031)
- [ ] T033 Implement execute() with run_in_session() (depends: T032)
- [ ] T034 Implement stream_claude() — file-based streaming workaround (depends: T033)
- [ ] T035 Implement stop() with keep_alive logic (depends: T032)
- [ ] T036 [P] Implement write_file() and read_file() via SWE-ReX (depends: T032)
- [ ] T037 [P] Implement env var forwarding and gh auth setup-git (depends: T032)
- [ ] T038 Implement asyncio timeout wrapper (depends: T034)
- [ ] T039 Write tests/unit/test_sandbox.py and tests/integration/test_sandbox.py (depends: T031-T038)

### Task 2.2: RunManager (F4)

- [ ] T040 Create dkmv/core/runner.py with RunManager class (depends: T030)
- [ ] T041 Implement run ID generation and directory creation (depends: T040)
- [ ] T042 Implement save_result(), append_stream() (depends: T041)
- [ ] T043 Implement list_runs(), get_run() (depends: T041)
- [ ] T044 Implement session_id tracking from stream-json result events (depends: T042)
- [ ] T045 Write tests/unit/test_runner.py (depends: T040-T044)

### Task 2.3: StreamParser (F5)

- [ ] T046 Create dkmv/core/stream.py with StreamParser class (depends: T030)
- [ ] T047 Implement line-by-line JSON parsing with event type handling (depends: T046)
- [ ] T048 Implement terminal rendering with rich (depends: T047)
- [ ] T049 Write tests/unit/test_stream.py (depends: T046-T048)

### Task 2.4: BaseComponent (F6)

- [ ] T050 Create dkmv/components/__init__.py with component registry (depends: T030)
- [ ] T051 Create dkmv/components/base.py with BaseComponent ABC (depends: T050, T031, T040, T046)
- [ ] T052 Implement 12-step run() method (depends: T051)
- [ ] T053 Implement _load_prompt_template() with importlib.resources (depends: T051)
- [ ] T054 Implement workspace setup: clone, branch, gh auth, CLAUDE.md, .gitignore (depends: T052)
- [ ] T055 Implement feedback synthesis transformation (depends: T052)
- [ ] T056 Implement shared teardown: git add, commit, push (depends: T052)
- [ ] T057 Write tests for BaseComponent lifecycle using mock component (depends: T050-T056)

---

## Phase 3 — Components (depends: Phase 2)

→ Detailed specs: [phase3_components.md](phase3_components.md)

### Task 3.1: Dev Component (F7)

- [ ] T060 Create dkmv/components/dev/ subpackage structure (depends: T050)
- [ ] T061 Create dev/models.py with DevConfig, DevResult (depends: T030, T060)
- [ ] T062 Create dev/prompt.md prompt template (depends: T060)
- [ ] T063 Create dev/component.py with DevComponent (depends: T051, T061, T062)
- [ ] T064 Register @register_component("dev") (depends: T063)
- [ ] T065 Implement build_prompt() with eval criteria stripping (depends: T063)
- [ ] T066 Implement design docs handling (--design-docs) (depends: T063)
- [ ] T067 Implement feedback injection from synthesized brief (depends: T055, T063)
- [ ] T068 Implement plan-first prompt approach (.dkmv/plan.md) (depends: T063)
- [ ] T069 Register `dkmv dev` command in cli.py with all flags (depends: T064)
- [ ] T070 Implement fresh branch vs existing branch logic (depends: T063)
- [ ] T071 Write unit tests for Dev component (depends: T060-T070)
- [ ] T072 E2E test: run against small test repo with trivial PRD (depends: T071)

### Task 3.2: QA Component (F8)

- [ ] T073 Create dkmv/components/qa/ subpackage (depends: T050)
- [ ] T074 Create qa/models.py, qa/component.py, qa/prompt.md (depends: T051, T073)
- [ ] T075 Implement QA with full PRD (including eval criteria) (depends: T074)
- [ ] T076 Register `dkmv qa` command in cli.py (depends: T075)
- [ ] T077 Write unit tests for QA component (depends: T073-T076)

### Task 3.3: Judge Component (F9)

- [ ] T078 Create dkmv/components/judge/ subpackage (depends: T050)
- [ ] T079 Create judge/models.py, judge/component.py, judge/prompt.md (depends: T051, T078)
- [ ] T080 Implement Judge with full PRD (including eval criteria) (depends: T079)
- [ ] T081 Register `dkmv judge` CLI command and implement verdict display (depends: T080)
- [ ] T082 Write unit tests for Judge component (depends: T078-T081)

### Task 3.4: Docs Component (F10)

- [ ] T083 Create dkmv/components/docs/ subpackage (depends: T050)
- [ ] T084 Create docs/models.py, docs/component.py, docs/prompt.md, register `dkmv docs` CLI command (depends: T051, T083)
- [ ] T085 Implement PR creation via gh pr create (depends: T084)
- [ ] T086 Write unit tests for Docs component (depends: T083-T085)

### Task 3.5: Prompt Snapshot Tests

- [ ] T087 Write syrupy snapshot tests for all 4 prompt templates (depends: T062, T074, T079, T084)
- [ ] T088 Test prompt building with different config combinations (depends: T087)

---

## Phase 4 — Utilities (depends: Phase 2, specifically F4)

→ Detailed specs: [phase4_utilities.md](phase4_utilities.md)

### Task 4.1: Run Management Commands (F11)

- [ ] T090 Implement `dkmv runs` with rich table output (depends: T043)
- [ ] T091 Implement `dkmv show <run-id>` detailed view (depends: T043)
- [ ] T092 Implement `dkmv attach <run-id>` docker exec passthrough (depends: T031)
- [ ] T093 Implement `dkmv stop <run-id>` container cleanup (depends: T035)
- [ ] T094 Write tests for all run management commands (depends: T090-T093)
- [ ] T095 Final integration verification (depends: T094)
