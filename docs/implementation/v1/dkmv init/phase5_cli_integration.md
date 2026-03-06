# Phase 5: CLI Integration + Polish

## Prerequisites

- Phases 1-4 complete
- `dkmv init`, `dkmv components`, `dkmv register`, `dkmv unregister` all working
- Container-side rename complete
- All quality gates passing

## Phase Goal

`--repo` is optional on all commands when project is initialized, run outputs are relocated to `.dkmv/runs/`, documentation is updated, and the `.env.example` uses placeholder values. The full end-to-end flow works: `dkmv init → dkmv run dev --var prd_path=prd.md` (no `--repo`).

## Phase Evaluation Criteria

- `dkmv run dev --var prd_path=prd.md` works without `--repo` when initialized
- `dkmv dev --repo https://... --prd prd.md` works (new named `--repo` option)
- `dkmv dev --prd prd.md` works without `--repo` when initialized
- Missing `--repo` without init shows error: "Run 'dkmv init' to set a default"
- Run outputs stored in `.dkmv/runs/` when initialized
- `dkmv runs` reads from `.dkmv/runs/` when initialized
- `DKMV_OUTPUT_DIR` env var overrides project output dir
- `README.md` documents init, components, register
- `CLAUDE.md` updated with init system
- `.env.example` uses placeholder values
- `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short` — all pass
- `uv run ruff check . && uv run ruff format --check . && uv run mypy dkmv/` — clean

---

## Tasks

### T240: Make `--repo` Optional on `dkmv run`

**PRD Reference:** Section 6.9 (CLI Changes — --repo Optional)
**Depends on:** T205 (get_repo helper)
**Blocks:** Nothing
**User Stories:** US-02, US-08

#### Description

Change `repo` on `dkmv run` from required to optional, with project config fallback.

#### Acceptance Criteria

- [x] `repo` parameter type changes to `str | None` with default `None`
- [x] When `repo` is None, falls back to `get_repo()` (project config)
- [x] When `repo` is None and no project config, exits with helpful error
- [x] When `repo` is provided, it takes precedence over project config
- [x] `resolve_component()` called with `project_root` for registry support

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) `run_component()` function

#### Implementation Notes

Change the `repo` parameter and add project-aware resolution:

```python
@app.command(name="run")
@async_command
async def run_component(
    component: Annotated[str, typer.Argument(help="Component name or path.")],
    repo: Annotated[
        str | None,
        typer.Option("--repo", help="Repository URL (default: from project config)."),
    ] = None,
    # ... other params unchanged ...
) -> None:
    """Run a component (directory of task YAML files)."""
    from dkmv.project import find_project_root, get_repo

    config = load_config()
    project_root = find_project_root()
    resolved_repo = get_repo(repo)  # CLI arg > project config > error

    component_dir = resolve_component(component, project_root=project_root)
    # ... rest unchanged, use resolved_repo instead of repo ...
```

#### Evaluation Checklist

- [x] `dkmv run dev --var prd_path=prd.md` works when initialized (no `--repo`)
- [x] `dkmv run dev --repo https://... --var prd_path=prd.md` still works
- [x] Error message suggests `dkmv init` when repo unavailable

---

### T241: Convert `repo` to `--repo` Option on Wrapper Commands

**PRD Reference:** Section 6.9 (CLI Changes), ADR-0011
**Depends on:** T205 (get_repo helper)
**Blocks:** Nothing
**User Stories:** US-02, US-07

#### Description

Convert `repo` from positional `typer.Argument()` to named `typer.Option("--repo")` on `dev`, `qa`, `judge`, `docs` commands. This is a **breaking change** per ADR-0011.

#### Acceptance Criteria

- [x] All 4 wrapper commands use `--repo` as a named option
- [x] `repo` is optional (`str | None = None`) with project config fallback
- [x] `get_repo()` used for resolution (CLI > project config > error)
- [x] Help text indicates repo comes from project config when omitted
- [x] `resolve_component()` called with `project_root` for registry support

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) All 4 wrapper command functions

#### Implementation Notes

For each wrapper (`dev`, `qa`, `judge`, `docs`), change:

```python
# Before:
repo: Annotated[str, typer.Argument(help="GitHub repository URL or local path.")]

# After:
repo: Annotated[
    str | None,
    typer.Option("--repo", help="Repository URL (default: from project config)."),
] = None
```

Then resolve in the function body:
```python
from dkmv.project import find_project_root, get_repo
resolved_repo = get_repo(repo)
project_root = find_project_root()
component_dir = resolve_component("dev", project_root=project_root)
```

Use `resolved_repo` everywhere `repo` was previously used. Pass `project_root` to `resolve_component()`.

**Important:** The `dev` command passes `repo` to `runner.run(repo=repo)` — update to `runner.run(repo=resolved_repo)`. Note that `resolved_branch` does NOT reference `repo` (it derives from the PRD filename), so it needs no changes.

#### Evaluation Checklist

- [x] `dkmv dev --prd prd.md` works when initialized
- [x] `dkmv dev --repo https://... --prd prd.md` works (new syntax)
- [x] `dkmv qa --branch feature/x --prd prd.md` works when initialized
- [x] All 4 commands show `--repo` in `--help`

---

### T242: Relocate Run Output Dir to `.dkmv/`

**PRD Reference:** Section 6.8 (Run Output Relocation)
**Depends on:** T203 (load_config already handles this)
**Blocks:** T243
**User Stories:** US-05

#### Description

Verify that `load_config()` correctly relocates `output_dir` to `.dkmv/` when project is initialized. The logic was implemented in T203; this task verifies the behavior with tests.

#### Acceptance Criteria

- [x] When initialized: `config.output_dir == project_root / ".dkmv"`
- [x] When not initialized: `config.output_dir == Path("./outputs")` (unchanged)
- [x] When `DKMV_OUTPUT_DIR` is set explicitly, it overrides project config
- [x] `RunManager(output_dir=config.output_dir)` creates runs in `.dkmv/runs/`

#### Files to Create/Modify

- `tests/unit/test_project.py` — (modify) Add output dir relocation tests

#### Implementation Notes

This is primarily a verification task. The output dir relocation logic is in `load_config()` (T203):

```python
if config.output_dir == Path("./outputs"):
    config.output_dir = project_root / ".dkmv"
```

Add tests:
```python
def test_output_dir_relocated_when_initialized(tmp_path, monkeypatch):
    # Create .dkmv/config.json
    # Assert config.output_dir points to .dkmv/

def test_output_dir_unchanged_when_not_initialized(tmp_path, monkeypatch):
    # No .dkmv/
    # Assert config.output_dir == Path("./outputs")

def test_explicit_output_dir_overrides_project(tmp_path, monkeypatch):
    # Create .dkmv/config.json
    # Set DKMV_OUTPUT_DIR=/custom/path
    # Assert config.output_dir == Path("/custom/path")
```

**Important — No migration of legacy runs (PRD Appendix D):** Existing runs in `./outputs/runs/` are NOT migrated automatically when a project is initialized. `dkmv runs` only reads from the active output directory (`.dkmv/runs/` when initialized, `./outputs/runs/` otherwise — not both). Users can manually move runs: `mv ./outputs/runs/* .dkmv/runs/`. A future `dkmv migrate-runs` command is out of scope for v1.

#### Evaluation Checklist

- [x] Tests cover all three scenarios
- [x] Run output actually lands in `.dkmv/runs/`

---

### T243: Update `dkmv runs` and `dkmv show`

**PRD Reference:** Section 6.8 (Run Output Relocation)
**Depends on:** T242
**Blocks:** Nothing
**User Stories:** US-05

#### Description

Verify that `dkmv runs` and `dkmv show` correctly use the project-scoped output directory. These commands already use `config.output_dir` from `load_config()`, so the relocation from T203 should make them work automatically.

#### Acceptance Criteria

- [x] `dkmv runs` reads from `.dkmv/runs/` when initialized
- [x] `dkmv show <id>` reads from `.dkmv/runs/<id>/` when initialized
- [x] Both commands work from subdirectories

#### Files to Create/Modify

- No code changes expected — verify with tests

#### Implementation Notes

Both `runs` and `show` commands call `load_config(require_api_key=False)` and pass `config.output_dir` to `RunManager`. Since `load_config()` now sets `output_dir` to `.dkmv/` when initialized, these commands should work automatically.

Verify with a test:
```python
def test_runs_command_reads_from_dkmv_runs(tmp_path, monkeypatch):
    # Create .dkmv/config.json + .dkmv/runs/ with a run
    # Run dkmv runs via CliRunner
    # Verify it shows the run
```

#### Evaluation Checklist

- [x] `dkmv runs` shows project-scoped runs
- [x] `dkmv show` works with project-scoped runs

---

### T244: Update README.md

**PRD Reference:** Section 6.10, General documentation
**Depends on:** All previous phases
**Blocks:** Nothing
**User Stories:** N/A (documentation)

#### Description

Update `README.md` with init documentation, new getting-started flow, and component registry commands.

#### Acceptance Criteria

- [x] Getting Started section includes `dkmv init` as the first step
- [x] `dkmv init` documented in CLI Commands
- [x] `dkmv components`, `dkmv register`, `dkmv unregister` documented
- [x] `--repo` shown as optional (with note about `dkmv init`)
- [x] `.dkmv/` directory structure explained
- [x] Project Structure updated with new files

#### Files to Create/Modify

- `README.md` — (modify) Multiple sections

#### Implementation Notes

Key sections to update:
1. **Quick Start** — add `dkmv init` as step 1, simplify subsequent steps (no `--repo`)
2. **CLI Commands** — add `dkmv init`, `dkmv components`, `dkmv register`, `dkmv unregister`
3. **Architecture** — add Config Resolution Layer with cascade diagram
4. **Project Structure** — add `dkmv/project.py`, `dkmv/init.py`, `dkmv/registry.py`
5. **Configuration** — explain `.dkmv/config.json` and cascade

#### Evaluation Checklist

- [x] All new commands documented
- [x] Getting started flow starts with `dkmv init`
- [x] Backward compatibility noted

---

### T245: Update CLAUDE.md

**PRD Reference:** General documentation
**Depends on:** All previous phases
**Blocks:** Nothing
**User Stories:** N/A (documentation)

#### Description

Update `CLAUDE.md` with init system, project config, and component registry information.

#### Acceptance Criteria

- [x] Quick Reference includes `dkmv init`, `dkmv components`, `dkmv register`
- [x] Architecture section includes `dkmv/project.py`, `dkmv/init.py`, `dkmv/registry.py`
- [x] Config cascade documented
- [x] `.dkmv/` directory explained

#### Files to Create/Modify

- `CLAUDE.md` — (modify) Multiple sections

#### Implementation Notes

Add to Quick Reference:
```bash
uv run dkmv init                # Initialize project
uv run dkmv components          # List available components
uv run dkmv register <n> <p>    # Register custom component
```

Add to Architecture:
```
dkmv/
  project.py          # ProjectConfig, find_project_root(), load_project_config()
  init.py             # dkmv init logic — credential discovery, project detection
  registry.py         # ComponentRegistry — .dkmv/components.json management
```

#### Evaluation Checklist

- [x] All new functionality documented
- [x] Architecture section accurate

---

### T246: Final Test Suite Verification

**PRD Reference:** Section 11 (Evaluation Criteria — Overall)
**Depends on:** T240-T245
**Blocks:** T247
**User Stories:** N/A (verification)

#### Description

Run all quality gates and verify the complete test suite passes.

#### Acceptance Criteria

- [x] `uv run ruff check .` — clean
- [x] `uv run ruff format --check .` — clean
- [x] `uv run mypy dkmv/` — clean
- [x] `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short` — all pass, coverage >= 80%
- [x] `dkmv --help` lists all new commands (init, components, register, unregister)
- [x] No regressions in existing commands

#### Files to Create/Modify

- No files — verification only

#### Implementation Notes

Run all gates:
```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy dkmv/
uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short
uv run dkmv --help
uv run dkmv init --help
uv run dkmv components --help
uv run dkmv register --help
uv run dkmv unregister --help
```

#### Evaluation Checklist

- [x] All quality gates clean
- [x] All tests pass
- [x] All CLI commands show in `--help`

---

### T247: Update `.env.example`

**PRD Reference:** Section 6.10 (documentation improvements)
**Depends on:** Nothing
**Blocks:** Nothing
**User Stories:** N/A (documentation)

#### Description

Replace real API keys in `.env.example` with placeholder values and add comments about `dkmv init`.

#### Acceptance Criteria

- [x] `ANTHROPIC_API_KEY` uses placeholder: `sk-ant-your-key-here`
- [x] `GITHUB_TOKEN` uses placeholder: `ghp_your-token-here`
- [x] Comment at top recommending `dkmv init` for guided setup
- [x] No real API keys in the file

#### Files to Create/Modify

- `.env.example` — (modify) Replace real keys with placeholders

#### Implementation Notes

```bash
# Recommended: Run 'dkmv init' for guided setup instead of editing this file manually.

# Required
ANTHROPIC_API_KEY=sk-ant-your-key-here
GITHUB_TOKEN=ghp_your-token-here

# Optional (defaults shown)
# DKMV_MODEL=claude-sonnet-4-6
# DKMV_MAX_TURNS=100
# DKMV_IMAGE=dkmv-sandbox:latest
# DKMV_OUTPUT_DIR=./outputs
# DKMV_TIMEOUT=30
# DKMV_MEMORY=8g
# DKMV_MAX_BUDGET_USD=
```

**CRITICAL:** The current `.env.example` contains what appear to be real API keys. Replace them with obviously-fake placeholders.

#### Evaluation Checklist

- [x] No real keys in `.env.example`
- [x] Comment about `dkmv init`
- [x] All settings documented
