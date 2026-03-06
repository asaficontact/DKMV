# DKMV Init v1 Feature Registry

## Overview

5 features organized in 5 phases. Features must be built in dependency order — later features depend on earlier ones being complete and stable.

## Dependency Diagram

```
Phase 1: Project Config Foundation
  F1: Project Config Model  ──┬──> F2: Config Loading Integration
                               │
Phase 2: Init Command + Rich UX│
  F2: Init Command  <──────────┘ (depends on F1)
                               │
Phase 3: Component Registry    │
  F3: Component Registry  <────┘ (depends on F1, uses find_project_root)
                               │
Phase 4: Container-Side Rename │
  F4: Container Rename  ←──────┤ (independent — can parallel after F1)
                               │
Phase 5: CLI Integration       │
  F5: CLI Integration  <───────┘ (depends on F1, F2, F3)
```

## Feature List

### F1: Project Config Foundation

- **Priority:** 1 (build first)
- **Phase:** 1 — Project Config Foundation
- **Status:** [ ] Not started
- **Depends on:** None (builds on existing config.py)
- **Blocks:** F2, F3, F5
- **User Stories:** US-01, US-02, US-05, US-08
- **Tasks:** T200-T206
- **PRD Reference:** Section 6.2 (Project Config Model), Section 6.3 (Config Loading Integration)
- **Key Deliverables:**
  - `ProjectConfig`, `CredentialSources`, `ProjectDefaults`, `SandboxSettings` Pydantic models in `dkmv/project.py`
  - `find_project_root()` — walk up from CWD to find `.dkmv/config.json`
  - `load_project_config()` — load and validate `.dkmv/config.json`
  - Modified `load_config()` with compare-against-defaults cascade pattern
  - `.env` resolution from subdirectories via `_env_file` override
  - `get_repo()` helper — resolves repo from CLI arg, project config, or error

---

### F2: Init Command & Rich UX

- **Priority:** 2 (user-facing setup)
- **Phase:** 2 — Init Command + Rich UX
- **Status:** [ ] Not started
- **Depends on:** F1
- **Blocks:** F5
- **User Stories:** US-01, US-04, US-07
- **Tasks:** T210-T219
- **PRD Reference:** Section 6.1 (`dkmv init` Command), Section 6.10 (Rich Init Experience)
- **Key Deliverables:**
  - `dkmv init` CLI command with 5-phase guided flow
  - Credential discovery (env var, dotenv, gh CLI)
  - Project detection (git remote, branch, project name)
  - Docker image check
  - `.dkmv/` directory creation with config.json, runs/, components.json
  - `.gitignore` update
  - Rich panels, step numbers, spinners, status indicators
  - `--yes` non-interactive mode
  - Reinit behavior (preserve runs/components)
  - `.env` creation/update for missing credentials

---

### F3: Component Registry

- **Priority:** 3 (component management)
- **Phase:** 3 — Component Registry
- **Status:** [ ] Not started
- **Depends on:** F1, F2 (F1 provides find_project_root; F2 creates `.dkmv/components.json` during init)
- **Blocks:** F5
- **User Stories:** US-03, US-06
- **Tasks:** T220-T226
- **PRD Reference:** Section 6.4 (Component Registry), Section 6.5 (`dkmv components`), Section 6.6 (`dkmv register`/`unregister`)
- **Key Deliverables:**
  - `ComponentRegistry` class — load/save `.dkmv/components.json`, register/unregister/list
  - Modified `resolve_component()` with registry lookup as step 3
  - `dkmv components` command — Rich table listing built-in + registered
  - `dkmv register <name> <path>` with validation
  - `dkmv unregister <name>`
  - Updated error messages listing registered components

---

### F4: Container-Side Rename

- **Priority:** 4 (cross-cutting rename)
- **Phase:** 4 — Container-Side Rename
- **Status:** [ ] Not started
- **Depends on:** None (independent, but scheduled after F3 to minimize merge conflicts)
- **Blocks:** None
- **User Stories:** N/A (internal improvement)
- **Tasks:** T230-T236
- **PRD Reference:** Section 6.7 (Container-Side `.agent/` Rename)
- **Key Deliverables:**
  - All container-side `.dkmv/` references renamed to `.agent/`
  - Infrastructure: `ComponentRunner._setup_workspace()`, `BaseComponent._setup_workspace()`
  - All 5 built-in YAML task files updated
  - All 3 prompt templates updated (dev, qa, judge — docs has no `.dkmv/` refs)
  - All 3 legacy Python component files updated
  - Test snapshots regenerated
  - Documentation updated (README.md, CLAUDE.md, E2E_TEST_GUIDE.md)

---

### F5: CLI Integration & Run Relocation

- **Priority:** 5 (final integration)
- **Phase:** 5 — CLI Integration + Polish
- **Status:** [ ] Not started
- **Depends on:** F1, F2, F3
- **Blocks:** None
- **User Stories:** US-02, US-05, US-07, US-08
- **Tasks:** T240-T247
- **PRD Reference:** Section 6.8 (Run Output Relocation), Section 6.9 (CLI Changes --repo Optional)
- **Key Deliverables:**
  - `--repo` optional on `dkmv run` when project is initialized
  - `repo` converted from positional Argument to named `--repo` Option on wrapper commands (breaking change — per ADR-0011)
  - Run output relocation to `.dkmv/runs/` when initialized
  - `dkmv runs` and `dkmv show` respect project-scoped output dir
  - Updated README.md, CLAUDE.md, `.env.example`
  - Final test suite verification
