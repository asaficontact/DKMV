# Multi-Agent Adapter Architecture — Master Task List

## How to Use This Document

- Tasks are numbered T010-T098 sequentially
- [P] = parallelizable with other [P] tasks in same phase
- Check off tasks as completed: `- [x] T010 ...`
- Dependencies noted as "depends: T001, T003"
- Each phase has a detailed doc in `phaseN_*.md`

## Progress Summary

- **Total tasks:** 59
- **Completed:** 0
- **In progress:** 0
- **Blocked:** 0
- **Remaining:** 59

---

## Phase 1 — Adapter Foundation (depends: nothing)

> Detailed specs: [phase1_adapter_foundation.md](phase1_adapter_foundation.md)

Pure refactor — extract all Claude Code-specific logic into `AgentAdapter` Protocol and `ClaudeCodeAdapter` with **zero behavioral changes**. All existing tests pass without modification.

### Task 1.1: Protocol & Registry (F1)

- [ ] T010 Create AgentAdapter Protocol and StreamResult dataclass (depends: nothing)
- [ ] T011 Create adapter registry with get_adapter() factory (depends: T010)

### Task 1.2: ClaudeCodeAdapter Implementation (F2)

- [ ] T012 Create ClaudeCodeAdapter — build_command() (depends: T010)
- [ ] T013 Add parse_event() to ClaudeCodeAdapter (depends: T012)
- [ ] T014 Add is_result_event() and extract_result() to ClaudeCodeAdapter (depends: T013)
- [ ] T015 Complete ClaudeCodeAdapter — properties, auth, and capabilities (depends: T014)

### Task 1.3: Existing Code Refactoring (F2)

- [ ] T016 Refactor sandbox.py — add stream_agent() with adapter parameter (depends: T011, T012, T013, T014)
- [ ] T017 Refactor stream.py — StreamParser accepts optional adapter (depends: T013)
- [ ] T018 Refactor tasks/runner.py — adapter-based instructions and streaming (depends: T015, T016, T017)
- [ ] T019 Refactor tasks/component.py — adapter-based auth and gitignore (depends: T015, T018)

### Task 1.4: Tests & Verification (F1, F2)

- [ ] T020 [P] Write adapter registry tests (depends: T011)
- [ ] T021 [P] Write Claude adapter unit tests (depends: T015)
- [ ] T022 Command regression test and full test suite verification (depends: T016, T017, T018, T019, T020, T021)

---

## Phase 2 — Codex Adapter & Agent Selection (depends: Phase 1)

> Detailed specs: [phase2_codex_agent_selection.md](phase2_codex_agent_selection.md)

Codex CLI adapter fully implemented, agent selection works at all 7 cascade levels, and model-agent validation prevents mismatches.

### Task 2.1: CodexCLIAdapter Implementation (F3)

- [ ] T030 Create CodexCLIAdapter — build_command() (depends: T010)
- [ ] T031 Add parse_event() to CodexCLIAdapter (depends: T030)
- [ ] T032 Add is_result_event() and extract_result() with state tracking (depends: T031)
- [ ] T033 Complete CodexCLIAdapter and register in registry (depends: T032)

### Task 2.2: Agent Resolution Cascade — Data Model (F4)

- [ ] T034 [P] Add `agent` field to TaskDefinition (depends: Phase 1)
- [ ] T035 [P] Add `agent` field to ManifestTaskRef and ComponentManifest (depends: Phase 1)
- [ ] T036 [P] Add `agent` to CLIOverrides (depends: Phase 1)
- [ ] T037 [P] Add `default_agent` and `codex_api_key` to DKMVConfig (depends: Phase 1)
- [ ] T038 [P] Add `agent` to ProjectDefaults and `codex_api_key_source` to CredentialSources (depends: Phase 1)

### Task 2.3: Agent Resolution Cascade — Logic (F4)

- [ ] T039 Implement manifest-level agent resolution in ComponentRunner (depends: T034, T035, T036)
- [ ] T040 Implement runtime agent resolution and adapter creation in TaskRunner (depends: T036, T037, T038, T039)

### Task 2.4: Model Validation & Inference (F5)

- [ ] T041 Add infer_agent_from_model() to adapter registry (depends: T033)
- [ ] T042 Add model-agent validation and auto-substitution logic (depends: T041)

### Task 2.5: CLI Integration (F10)

- [ ] T043 Add --agent flag to CLI run commands (depends: T036)

### Task 2.6: Instructions & Stream Wiring (F3, F9)

- [ ] T044 Implement AGENTS.md prepend behavior for Codex (depends: T033, T039, T040)
- [ ] T045 Wire adapter through StreamParser in task execution (depends: T033, T040)

### Task 2.7: Tests & Verification (F3, F4, F5, F9, F10)

- [ ] T046 [P] Write Codex adapter unit tests (depends: T033)
- [ ] T047 [P] Write agent resolution cascade tests (depends: T039, T040)
- [ ] T048 [P] Write model validation and inference tests (depends: T041, T042)
- [ ] T049 [P] Write CLI --agent flag tests (depends: T043)
- [ ] T050 Full test suite verification (depends: T046, T047, T048, T049)

---

## Phase 3 — Docker & Init Integration (depends: Phase 2)

> Detailed specs: [phase3_docker_init_integration.md](phase3_docker_init_integration.md)

Codex CLI installed in Docker image, `dkmv init` discovers Codex credentials, `dkmv build` accepts `--codex-version`, and mixed-agent components pass all required credentials.

### Task 3.1: Dockerfile Updates (F6)

- [ ] T060 Update Dockerfile — install Codex CLI (depends: Phase 2)
- [ ] T061 Add Codex config file in Dockerfile (depends: T060)
- [ ] T062 Add --codex-version flag to dkmv build command (depends: T060)

### Task 3.2: Init Credential Discovery (F7)

- [ ] T063 Add discover_codex_key() to init.py (depends: Phase 2)
- [ ] T064 Extend init credential step — multi-agent auth options (depends: T063)
- [ ] T065 Update init --yes mode for Codex auto-detection (depends: T063, T064)
- [ ] T066 Update load_config() for OPENAI_API_KEY fallback (depends: T037)

### Task 3.3: Mixed-Agent Components (F8)

- [ ] T067 Implement agents_needed scanning in ComponentRunner (depends: T039)
- [ ] T068 Update _build_sandbox_config() for multi-agent credentials (depends: T067)
- [ ] T069 Update workspace .gitignore for multi-agent (depends: T067)

### Task 3.4: Tests & Verification (F6, F7, F8)

- [ ] T070 [P] Write Dockerfile verification tests (depends: T060, T061)
- [ ] T071 [P] Write build command --codex-version tests (depends: T062)
- [ ] T072 [P] Write init Codex credential discovery tests (depends: T063, T064, T065)
- [ ] T073 [P] Write load_config() OPENAI_API_KEY fallback tests (depends: T066)
- [ ] T074 [P] Write mixed-agent component tests (depends: T067, T068, T069)
- [ ] T075 Full test suite and integration verification (depends: T070, T071, T072, T073, T074)

---

## Phase 4 — Polish & Verification (depends: Phase 3)

> Detailed specs: [phase4_polish_verification.md](phase4_polish_verification.md)

Error messages are agent-aware, model-agent mismatches produce clear errors, capability gaps are logged, and the system passes comprehensive regression testing with >= 90% adapter coverage.

### Task 4.1: Error Handling & UX (F2, F3, F5)

- [ ] T090 Update error messages to be agent-aware (depends: Phase 3)
- [ ] T091 Add clear model-agent mismatch error messaging (depends: T042)
- [ ] T092 Add info logging for capability gaps (depends: Phase 3)

### Task 4.2: Edge Cases & Display (F3, F10)

- [ ] T093 Edge case testing (depends: T090, T091, T092)
- [ ] T094 Update dkmv components display to show agent info (depends: Phase 3)

### Task 4.3: Documentation & Coverage

- [ ] T095 Update CLAUDE.md with adapter conventions (depends: Phase 3)
- [ ] T096 Coverage verification for new adapter code (depends: T093)

### Task 4.4: Final Verification

- [ ] T097 Final regression test pass (depends: T090, T091, T092, T093, T094, T095, T096)
- [ ] T098 Quality gates verification (depends: T097)
