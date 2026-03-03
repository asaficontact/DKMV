# DKMV Init v1 — Implementation Guide

## What We're Implementing

Project-scoped initialization for DKMV: a `dkmv init` command that creates `.dkmv/` with auto-detected config, credential discovery, component registry, and container-side rename from `.dkmv/` to `.agent/`.

- **PRD:** `docs/core/prd_dkmv_init_v1.md` (read-only — do not modify)
- **Implementation docs:** `docs/implementation/v1/dkmv init/`
- **ADRs:** `docs/adrs/` (0009, 0010, 0011)

## Document Map

- `tasks.md` — Master task list. Start here for the current phase.
- `features.md` — Feature registry with dependencies.
- `user_stories.md` — User stories with acceptance criteria.
- `phase1_project_config.md` — Phase 1: Project Config Foundation (T200-T206).
- `phase2_init_command.md` — Phase 2: Init Command + Rich UX (T210-T219).
- `phase3_component_registry.md` — Phase 3: Component Registry (T220-T226).
- `phase4_container_rename.md` — Phase 4: Container-Side Rename (T230-T236).
- `phase5_cli_integration.md` — Phase 5: CLI Integration + Polish (T240-T247).
- `progress.md` — Session log. Update after every session.

## Relevant ADRs

- ADR-0007: Config via environment variables only — existing baseline (project config supersedes the "no per-project config" limitation)
- ADR-0009: Project-scoped configuration cascade — `.dkmv/config.json` as lowest-priority config source
- ADR-0010: Container-side directory rename — `.dkmv/` → `.agent/` inside Docker containers
- ADR-0011: Repo argument to option — breaking change: `repo` becomes `--repo` on wrapper commands

## Current State (All Phases Complete)

**Init v1 implementation is complete (Phases 1-5):**
- 590+ tests passing, 91%+ coverage
- All quality gates green (ruff, mypy, pytest)
- `dkmv init` creates `.dkmv/` with config, credentials, and component registry
- `--repo` is optional on all 5 run commands when initialized
- Container-side rename: `.dkmv/` (host) → `.agent/` (container)
- Run outputs stored in `.dkmv/runs/` when initialized
- Component registry: `dkmv register/unregister/components` commands

## Implementation Process

Work through phases sequentially. For each phase:

### 1. Read the Phase Document

Open `phaseN_*.md`. Read the Prerequisites, Phase Goal, and Phase Evaluation Criteria before touching any code.

### 2. Implement Tasks in Order

Work through each task (T-IDs) in the phase document sequentially. For each task:
- Read the Description, Acceptance Criteria, Files to Create/Modify, and Implementation Notes
- **Verify the implementation notes against actual code** — method signatures, model fields, interfaces may differ from what the doc says. Trust the code, not the doc.
- Implement the task
- Check off the Acceptance Criteria in the phase doc
- Check off the task in `tasks.md`

### 3. Verify the Phase

After all tasks in the phase are complete:
- Run every command in the Phase Evaluation Criteria
- All must pass. If any fail, fix the issue before proceeding.

### 4. Review Pass

Do a second pass:
- Re-read the phase doc and verify nothing was missed
- Run the full test suite to catch regressions
- Check linting and type checking

### 5. Update Progress

Add a session entry to `progress.md` with tasks completed, blockers, discoveries, coverage, and quality gate status.

### 6. Proceed to Next Phase

Only move to the next phase when all tasks are checked off, evaluation criteria pass, and quality gates are green.

## Quality Gates

Every phase must pass these before proceeding:

- `uv run ruff check .` — clean (zero warnings)
- `uv run ruff format --check .` — clean
- `uv run mypy dkmv/` — passes
- `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short` — all tests pass, coverage >= 80%

## Conventions

- Conventional Commits: `<type>[scope]: <description>` (types: feat, fix, test, docs, refactor)
- Scopes: `init`, `project`, `registry`, `config`, `cli`, `sandbox`, `rename`
- Test files mirror source: `dkmv/project.py` → `tests/unit/test_project.py`
- Use `tmp_path` for file I/O, `monkeypatch.setenv()` for env vars, `monkeypatch.chdir()` for CWD
- Python 3.12+, `str | None` not `Optional[str]`, `list[str]` not `List[str]`

## Existing Core Interfaces

### DKMVConfig (`dkmv/config.py`)
```python
class DKMVConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    github_token: str = Field(default="", validation_alias="GITHUB_TOKEN")
    default_model: str = Field(default="claude-sonnet-4-6", validation_alias="DKMV_MODEL")
    default_max_turns: int = Field(default=100, validation_alias="DKMV_MAX_TURNS")
    image_name: str = Field(default="dkmv-sandbox:latest", validation_alias="DKMV_IMAGE")
    output_dir: Path = Field(default=Path("./outputs"), validation_alias="DKMV_OUTPUT_DIR")
    timeout_minutes: int = Field(default=30, validation_alias="DKMV_TIMEOUT")
    memory_limit: str = Field(default="8g", validation_alias="DKMV_MEMORY")
    max_budget_usd: float | None = Field(default=None, validation_alias="DKMV_MAX_BUDGET_USD")

def load_config(require_api_key: bool = True) -> DKMVConfig:
```

### resolve_component (`dkmv/tasks/discovery.py`)
```python
BUILTIN_COMPONENTS = {"dev", "qa", "judge", "docs"}
def resolve_component(name_or_path: str, project_root: Path | None = None) -> Path:
    # Resolves: path → built-in → registry (if project_root) → error
```

### ComponentRunner (`dkmv/tasks/component.py`)
```python
class ComponentRunner:
    async def run(self, component_dir, repo, branch, feature_name, variables,
                  config, cli_overrides, keep_alive, verbose) -> ComponentResult:
```

### CLI Commands (`dkmv/cli.py`)
- Wrapper commands (`dev`, `qa`, `judge`, `docs`): `--repo` is optional `Option` (project config fallback)
- `run_component`: `--repo` is optional `Option` (project config fallback)
- Project commands: `init`, `components`, `register`, `unregister`

## DO NOT CHANGE

The following are stable and must not be modified during implementation (except as specified in phase docs):

- `dkmv/core/sandbox.py` — SandboxManager (no changes needed for init)
- `dkmv/core/runner.py` — RunManager (no changes needed for init)
- `dkmv/core/stream.py` — StreamParser (no changes needed)
- `dkmv/core/models.py` — Shared types (no changes needed)
- `dkmv/tasks/models.py` — Task models (no changes needed)
- `dkmv/tasks/loader.py` — TaskLoader (no changes needed)
- `dkmv/tasks/runner.py` — TaskRunner (no changes needed)
- `dkmv/tasks/component.py` — ComponentRunner (Phase 4 rename complete: `.dkmv/` → `.agent/`)
- `dkmv/components/base.py` — BaseComponent (Phase 4 rename complete: `.dkmv/` → `.agent/`)
- Existing test files — Phase 4 rename assertions updated

## New Files Created by Init

```
dkmv/
  project.py        # NEW — ProjectConfig, find_project_root(), load_project_config(), get_repo()
  init.py           # NEW — dkmv init logic: credential discovery, project detection, Rich UX
  registry.py       # NEW — ComponentRegistry: .dkmv/components.json management
tests/
  unit/
    test_project.py  # NEW — ~38 tests
    test_init.py     # NEW — ~35 tests
    test_registry.py # NEW — ~20 tests
```
