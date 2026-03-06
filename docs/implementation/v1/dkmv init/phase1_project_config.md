# Phase 1: Project Config Foundation

## Prerequisites

- DKMV Tasks v1 complete (461+ tests, 92%+ coverage)
- Existing `dkmv/config.py` with `DKMVConfig` and `load_config()` operational
- All quality gates passing (ruff, mypy, pytest)
- ADR-0009 (Project-Scoped Config) reviewed and accepted

## Phase Goal

The data layer for project-scoped configuration is operational: Pydantic models validate `.dkmv/config.json`, `find_project_root()` discovers project roots from subdirectories, `load_project_config()` loads config, and `load_config()` merges project defaults using the compare-against-defaults pattern. No init command yet — just the loading infrastructure.

## Phase Evaluation Criteria

- `ProjectConfig.model_validate(dict)` validates config.json correctly
- `find_project_root()` walks up from CWD and returns the directory containing `.dkmv/config.json`
- `find_project_root()` returns CWD when no `.dkmv/` exists
- `load_project_config()` returns `None` when not initialized
- `load_project_config()` returns `ProjectConfig` when `.dkmv/config.json` exists
- Modified `load_config()` merges project defaults only where values match `_BUILTIN_DEFAULTS`
- Environment variables always override project config
- `.env` resolution works from subdirectories when `_env_file` is set
- `get_repo()` returns CLI arg > project config > error
- `uv run pytest tests/unit/test_project.py -v` — all pass
- `uv run ruff check . && uv run ruff format --check . && uv run mypy dkmv/` — clean
- All existing 461+ tests still pass (no regressions)

---

## Tasks

### T200: Create Project Config Models

**PRD Reference:** Section 6.2 (Project Config Model)
**Depends on:** Nothing
**Blocks:** T201, T202, T203, T204, T205
**User Stories:** US-01, US-05

#### Description

Create `dkmv/project.py` with Pydantic models: `CredentialSources`, `ProjectDefaults`, `SandboxSettings`, `ProjectConfig`.

#### Acceptance Criteria

- [x] `CredentialSources` model with `anthropic_api_key_source` and `github_token_source` fields
- [x] `ProjectDefaults` model with `model`, `max_turns`, `timeout_minutes`, `max_budget_usd`, `memory` — all `| None = None`
- [x] `SandboxSettings` model with `image: str | None = None`
- [x] `ProjectConfig` model with `version`, `project_name`, `repo`, `default_branch`, `credentials`, `defaults`, `sandbox`
- [x] `version` defaults to `1`, validated to equal `1` (raise clear error if unknown version)
- [x] All models are JSON-serializable via `model_dump_json()` / `model_validate_json()`

#### Files to Create/Modify

- `dkmv/project.py` — (create) All project config models

#### Implementation Notes

Follow the PRD Section 6.2 schema exactly. The models mirror the JSON structure of `.dkmv/config.json`.

**Note on `default_branch`:** This field is detected during init (T211) and stored in `config.json`, but no CLI command currently consumes it. It's included for forward compatibility — future features (e.g., auto-deriving branch names, PR base defaults) may use it. The `credentials` section is similarly informational rather than actively consumed at runtime.

```python
from pydantic import BaseModel, field_validator

class CredentialSources(BaseModel):
    anthropic_api_key_source: str = "env"
    github_token_source: str = "env"

class ProjectDefaults(BaseModel):
    model: str | None = None
    max_turns: int | None = None
    timeout_minutes: int | None = None
    max_budget_usd: float | None = None
    memory: str | None = None

class SandboxSettings(BaseModel):
    image: str | None = None

class ProjectConfig(BaseModel):
    version: int = 1
    project_name: str
    repo: str
    default_branch: str = "main"
    credentials: CredentialSources = CredentialSources()
    defaults: ProjectDefaults = ProjectDefaults()
    sandbox: SandboxSettings = SandboxSettings()

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: int) -> int:
        if v != 1:
            msg = (
                f"Unsupported config version {v}. "
                "This project was initialized with a newer version of DKMV. "
                "Please upgrade DKMV or run 'dkmv init' to reinitialize."
            )
            raise ValueError(msg)
        return v
```

#### Evaluation Checklist

- [x] `ProjectConfig(project_name="test", repo="https://...")` validates
- [x] `ProjectConfig(version=2, ...)` raises `ValueError` with helpful message
- [x] `model_dump_json()` → `model_validate_json()` round-trips correctly
- [x] `ProjectDefaults()` — all fields default to `None`

---

### T201: Implement `find_project_root()`

**PRD Reference:** Section 6.3 (Config Loading, `find_project_root()`)
**Depends on:** Nothing (pure function)
**Blocks:** T202, T203, T204
**User Stories:** US-08

#### Description

Implement `find_project_root()` that walks up from CWD to find `.dkmv/config.json`, enabling subdirectory support.

#### Acceptance Criteria

- [x] Walks up from `Path.cwd()` through parent directories
- [x] Returns directory containing `.dkmv/config.json` when found
- [x] Returns `Path.cwd()` when not found (graceful fallback)
- [x] Works from deeply nested subdirectories

#### Files to Create/Modify

- `dkmv/project.py` — (modify) Add `find_project_root()` function

#### Implementation Notes

```python
def find_project_root() -> Path:
    """Walk up from CWD to find .dkmv/config.json. Returns CWD if not found."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / ".dkmv" / "config.json").exists():
            return parent
    return current
```

Performance: at most ~20 `stat()` calls up the filesystem tree. Negligible for CLI usage.

#### Evaluation Checklist

- [x] Returns project root when `.dkmv/config.json` exists in parent
- [x] Returns CWD when no `.dkmv/` found
- [x] Works from nested directories (e.g., `project/src/lib/`)

---

### T202: Implement `load_project_config()`

**PRD Reference:** Section 6.3 (`load_project_config()`)
**Depends on:** T200, T201
**Blocks:** T203
**User Stories:** US-01

#### Description

Implement `load_project_config()` to load and validate `.dkmv/config.json`.

#### Acceptance Criteria

- [x] Returns `ProjectConfig` when `.dkmv/config.json` exists and is valid
- [x] Returns `None` when `.dkmv/config.json` doesn't exist
- [x] Returns `None` when `.dkmv/` directory doesn't exist
- [x] Raises clear error on invalid JSON or invalid schema
- [x] Accepts optional `project_root` parameter (defaults to `find_project_root()`)

#### Files to Create/Modify

- `dkmv/project.py` — (modify) Add `load_project_config()` function

#### Implementation Notes

```python
def load_project_config(project_root: Path | None = None) -> ProjectConfig | None:
    """Load .dkmv/config.json if it exists. Returns None if not initialized."""
    root = project_root or find_project_root()
    config_path = root / ".dkmv" / "config.json"
    if not config_path.exists():
        return None
    return ProjectConfig.model_validate_json(config_path.read_text())
```

#### Evaluation Checklist

- [x] Returns `None` for uninitialized projects
- [x] Returns valid `ProjectConfig` for initialized projects
- [x] Pydantic validation errors propagate clearly

---

### T203: Modify `load_config()` with Project Config Cascade

**PRD Reference:** Section 6.3 (Config Loading Integration), Section 5.3 (Config Cascade)
**Depends on:** T200, T201, T202
**Blocks:** T205
**User Stories:** US-01, US-05, US-08

#### Description

Modify `load_config()` in `dkmv/config.py` to merge project config defaults using the compare-against-defaults pattern. Also implement `.env` resolution from subdirectories.

#### Acceptance Criteria

- [x] ~~`_BUILTIN_DEFAULTS` dict stays in sync with `DKMVConfig` field defaults~~ Replaced with `model_fields_set` — strictly superior, eliminates sync risk and the ADR-0009 edge case
- [x] Project defaults applied only where no env var / .env explicitly set the field
- [x] Environment variables always win over project config
- [x] `output_dir` relocated to `.dkmv/` when project config exists (unless `DKMV_OUTPUT_DIR` explicitly set)
- [x] `.env` resolution uses project root when available (for subdirectory support)
- [x] All existing callers of `load_config()` continue to work without changes
- [x] When no `.dkmv/config.json` exists, behavior is identical to current

#### Files to Create/Modify

- `dkmv/config.py` — (modify) Update `load_config()`, add `_BUILTIN_DEFAULTS` dict

#### Implementation Notes

Per ADR-0009, the cascade is: CLI flags > env vars > .env > .dkmv/config.json > built-in defaults.

The compare-against-defaults approach:
```python
_BUILTIN_DEFAULTS: dict[str, object] = {
    "default_model": "claude-sonnet-4-6",
    "default_max_turns": 100,
    "timeout_minutes": 30,
    "max_budget_usd": None,
    "memory_limit": "8g",
    "image_name": "dkmv-sandbox:latest",
}

def load_config(require_api_key: bool = True) -> DKMVConfig:
    from dkmv.project import find_project_root, load_project_config

    project_root = find_project_root()

    # .env resolution from subdirectories
    env_file = project_root / ".env" if (project_root / ".env").exists() else ".env"
    config = DKMVConfig(_env_file=env_file)

    project = load_project_config(project_root)

    if project:
        # Apply project defaults only where config still has built-in defaults
        if project.defaults.model is not None and config.default_model == _BUILTIN_DEFAULTS["default_model"]:
            config.default_model = project.defaults.model
        if (
            project.defaults.max_turns is not None
            and config.default_max_turns == _BUILTIN_DEFAULTS["default_max_turns"]
        ):
            config.default_max_turns = project.defaults.max_turns
        if (
            project.defaults.timeout_minutes is not None
            and config.timeout_minutes == _BUILTIN_DEFAULTS["timeout_minutes"]
        ):
            config.timeout_minutes = project.defaults.timeout_minutes
        if (
            project.defaults.max_budget_usd is not None
            and config.max_budget_usd == _BUILTIN_DEFAULTS["max_budget_usd"]
        ):
            config.max_budget_usd = project.defaults.max_budget_usd
        if project.defaults.memory is not None and config.memory_limit == _BUILTIN_DEFAULTS["memory_limit"]:
            config.memory_limit = project.defaults.memory
        if project.sandbox.image is not None and config.image_name == _BUILTIN_DEFAULTS["image_name"]:
            config.image_name = project.sandbox.image

        # Relocate output_dir to .dkmv/ (unless DKMV_OUTPUT_DIR was explicitly set)
        if config.output_dir == Path("./outputs"):
            config.output_dir = project_root / ".dkmv"

    if require_api_key and not config.anthropic_api_key:
        typer.echo(
            "Error: ANTHROPIC_API_KEY not set. Set it via environment variable or .env file.",
            err=True,
        )
        raise typer.Exit(code=1)
    return config
```

**Critical:** The `_env_file` parameter override to `DKMVConfig()` is what enables subdirectory `.env` resolution. When CWD is `my-project/src/`, pydantic-settings would normally look for `./src/.env`. By passing `my-project/.env` explicitly, credentials are found from any subdirectory.

**Known limitation:** If `DKMV_MODEL=claude-sonnet-4-6` is explicitly set (same as default), project config overrides it. This is acceptable per ADR-0009.

#### Evaluation Checklist

- [x] No project config → identical to current behavior
- [x] Project config + no env vars → project defaults applied
- [x] Project config + env vars → env vars win
- [x] Output dir → `.dkmv/` when initialized
- [x] `.env` found from subdirectory via `find_project_root()`

---

### T204: Fix `.env` Resolution from Subdirectories

**PRD Reference:** Section 6.3 (`.env` file resolution from subdirectories)
**Depends on:** T201, T203
**Blocks:** Nothing
**User Stories:** US-08

#### Description

This is implicitly handled in T203 via the `_env_file` parameter. This task defines the expected behavior and test cases. The actual tests are written in T206 (test group 6: "Subdirectory .env").

#### Acceptance Criteria

- [x] Running from `project/src/` finds `project/.env` via `find_project_root()`
- [x] Credentials in `.env` are loaded correctly from subdirectories
- [x] If no `.dkmv/` exists, `.env` resolution falls back to CWD (current behavior)

#### Files to Create/Modify

- `tests/unit/test_project.py` — (created in T206) Tests added in T206 test group 6

#### Implementation Notes

No new code — the `.env` resolution logic is in `load_config()` (T203). This task specifies the test cases to include in T206:

```python
def test_load_config_env_file_from_subdirectory(tmp_path, monkeypatch):
    """When CWD is a subdirectory, .env should be found at project root."""
    dkmv_dir = tmp_path / ".dkmv"
    dkmv_dir.mkdir()
    (dkmv_dir / "config.json").write_text(
        '{"version": 1, "project_name": "test", "repo": "https://github.com/org/repo"}'
    )
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-test-key\n")
    subdir = tmp_path / "src" / "lib"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)
    config = load_config()
    assert config.anthropic_api_key == "sk-test-key"
```

#### Evaluation Checklist

- [x] Test passes for subdirectory `.env` resolution
- [x] Fallback behavior preserved when no `.dkmv/` exists

---

### T205: Implement `get_repo()` Helper

**PRD Reference:** Section 6.9 (CLI Changes — --repo Optional)
**Depends on:** T202
**Blocks:** Nothing (used by Phase 5 CLI changes, but can be written now)
**User Stories:** US-02

#### Description

Create a helper function that resolves the repo URL from CLI arg, project config, or raises a helpful error.

#### Acceptance Criteria

- [x] Returns CLI arg when provided
- [x] Returns project config repo when CLI arg is None and project is initialized
- [x] Raises `typer.Exit(1)` with helpful error when repo is None and no project config
- [x] Error message suggests `dkmv init`

#### Files to Create/Modify

- `dkmv/project.py` — (modify) Add `get_repo()` function

#### Implementation Notes

```python
def get_repo(cli_repo: str | None) -> str:
    """Resolve repo from CLI arg or project config. Exits with error if neither available."""
    if cli_repo is not None:
        return cli_repo
    project = load_project_config()
    if project:
        return project.repo
    typer.echo(
        "Error: --repo is required (or run 'dkmv init' to set a default).",
        err=True,
    )
    raise typer.Exit(code=1)
```

#### Evaluation Checklist

- [x] CLI arg takes precedence
- [x] Project config used as fallback
- [x] Helpful error message when neither available

---

### T206: Write Project Config Tests

**PRD Reference:** Section 8 (Testing Strategy)
**Depends on:** T200-T205
**Blocks:** Nothing
**User Stories:** N/A (testing)
**Estimated scope:** 1 hour

#### Description

Write comprehensive tests for project config models, `find_project_root()`, `load_project_config()`, config cascade, and `get_repo()`.

#### Acceptance Criteria

- [x] 38 tests covering all project config functionality
- [x] Model validation (valid, invalid, version mismatch, round-trip)
- [x] `find_project_root()` — CWD fallback, subdirectory walk, nested dirs
- [x] `load_project_config()` — None when missing, valid when present, error on bad schema
- [x] Config cascade — project defaults applied, env vars override, output_dir relocation
- [x] ~~`_BUILTIN_DEFAULTS` sync~~ N/A — replaced by `model_fields_set`; edge case tested via `test_env_var_same_as_default_not_overridden`
- [x] `get_repo()` — CLI arg, project config fallback, error case
- [x] `.env` subdirectory resolution
- [x] All tests use `tmp_path` and `monkeypatch.chdir()` for isolation

#### Files to Create/Modify

- `tests/unit/test_project.py` — (create) ~38 tests

#### Implementation Notes

Follow existing test patterns from `tests/unit/test_models.py` and `tests/unit/test_config.py`. Use `tmp_path` for `.dkmv/` directory creation, `monkeypatch.chdir()` for CWD simulation, and `monkeypatch.setenv()` / `monkeypatch.delenv()` for env var testing.

Key test groups:
1. **ProjectConfig model** (~8 tests): valid config, null defaults, version validation, round-trip
2. **find_project_root** (~8 tests): CWD fallback, direct match, parent match, deep nesting, no config
3. **load_project_config** (~5 tests): None when missing, valid, invalid JSON, invalid schema, explicit root
4. **Config cascade** (~10 tests): no project → unchanged, project defaults applied, env override, output_dir relocation, `_BUILTIN_DEFAULTS` sync verification (assert each key matches `DKMVConfig()` actual defaults)
5. **get_repo** (~3 tests): CLI arg, project fallback, error
6. **Subdirectory .env** (~4 tests): .env found from subdir, fallback when no .dkmv

#### Evaluation Checklist

- [x] `uv run pytest tests/unit/test_project.py -v` — all 38 pass
- [x] Coverage of all functions in `dkmv/project.py` (100%) and modified `dkmv/config.py` (100%)
- [x] No existing test regressions (501 passed, 3 skipped)
