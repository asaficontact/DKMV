# Phase 1: Foundation

## Prerequisites

- Phase 0 complete (test infrastructure in place)

## Phase Goal

A working CLI skeleton: `uv run dkmv --help` shows all subcommands, `dkmv build` builds the Docker image, config loads from env vars, CI pipeline is green.

## Phase Evaluation Criteria

- `uv sync && uv run dkmv --help` shows subcommands
- `uv run dkmv build` builds the dkmv-sandbox image
- `uv run pytest tests/unit/test_config.py -v` passes
- `uv run ruff check .` is clean
- `uv run mypy dkmv/` passes
- CI pipeline (.github/workflows/ci.yml) runs successfully

---

## Tasks

### T010: Create pyproject.toml with All Dependencies

**PRD Reference:** Section 11
**Depends on:** Nothing
**Blocks:** T011, T018
**User Stories:** US-01
**Estimated scope:** 1 hour

#### Description

Replace the placeholder pyproject.toml with the full project configuration including all runtime and dev dependencies, build system, and tool configurations.

#### Acceptance Criteria

- [x] Build system: hatchling
- [x] Runtime deps: typer>=0.15.0, pydantic>=2.0, pydantic-settings>=2.0, swe-rex>=1.4, rich>=13.0
- [x] Dev deps group: pytest, pytest-asyncio, pytest-cov, pytest-timeout, syrupy, polyfactory, ruff, mypy, commitizen, pre-commit
- [x] Entry point: `dkmv = "dkmv.cli:app"`
- [x] `requires-python = ">=3.12"`
- [x] `uv sync` succeeds
- [ ] Hatchling configured to include prompt.md files: `[tool.hatch.build.targets.wheel]` with packages and force-include — **Deferred to Phase 3: prompt.md files don't exist yet**

#### Files to Create/Modify

- `pyproject.toml` — (modify) Replace placeholder with full config

#### Implementation Notes

Use the exact dependency specs from PRD Section 11. Include `[project.scripts]` for the `dkmv` entry point. Configure ruff (`target-version = "py312"`, `line-length = 100`) and pytest in the same file.

IMPORTANT: Hatchling does NOT include non-Python files (.md) in wheels by default.
Add this to pyproject.toml:

```toml
[tool.hatch.build.targets.wheel]
packages = ["dkmv"]

[tool.hatch.build.targets.wheel.force-include]
"dkmv/components/dev/prompt.md" = "dkmv/components/dev/prompt.md"
"dkmv/components/qa/prompt.md" = "dkmv/components/qa/prompt.md"
"dkmv/components/judge/prompt.md" = "dkmv/components/judge/prompt.md"
"dkmv/components/docs/prompt.md" = "dkmv/components/docs/prompt.md"
```

Alternative (simpler, include all .md under dkmv/):
```toml
[tool.hatch.build]
artifacts = ["*.md"]
```

#### Evaluation Checklist

- [x] `uv sync` completes without errors
- [x] All dependencies installable
- [x] `uv run python -c "import typer, pydantic, rich"` succeeds

---

### T011: Create dkmv/ Package Directory Structure

**PRD Reference:** Section 3.1
**Depends on:** T010
**Blocks:** T012, T013, T014, T019, T023
**User Stories:** US-01
**Estimated scope:** 30 min

#### Description

Create the full package directory structure per PRD Section 3.1. All directories get `__init__.py` files. This is the skeleton that all subsequent code lives in.

#### Acceptance Criteria

- [x] Directory tree matches PRD Section 3.1
- [x] All `__init__.py` files exist
- [x] `dkmv/utils/`, `dkmv/core/`, `dkmv/components/` directories created
- [x] Component subdirectories: `dkmv/components/dev/`, `qa/`, `judge/`, `docs/`
- [x] `dkmv/images/` directory exists

#### Files to Create/Modify

- `dkmv/__init__.py` — (create)
- `dkmv/utils/__init__.py` — (create)
- `dkmv/core/__init__.py` — (create)
- `dkmv/components/__init__.py` — (create) Will hold registry in Phase 2
- `dkmv/components/dev/__init__.py` — (create) Empty for now
- `dkmv/components/qa/__init__.py` — (create)
- `dkmv/components/judge/__init__.py` — (create)
- `dkmv/components/docs/__init__.py` — (create)
- `dkmv/images/` — (create) Directory for Dockerfile

#### Implementation Notes

Create empty `__init__.py` files. The `dkmv/__init__.py` can export `__version__ = "0.1.0"`. Remove the placeholder `main.py` from the project root.

#### Evaluation Checklist

- [x] `python -c "import dkmv"` succeeds
- [x] All directories exist per PRD structure

---

### T012: Create dkmv/cli.py with Typer App Skeleton

**PRD Reference:** Section 6/F1
**Depends on:** T011
**Blocks:** T015, T020, T024, T069, T076, T081, T086, T090-T093
**User Stories:** US-01
**Estimated scope:** 1 hour

#### Description

Create the main CLI entry point using Typer. This is a skeleton with placeholder subcommands that will be fleshed out in later phases.

#### Acceptance Criteria

- [x] `typer.Typer()` app instance created
- [x] Placeholder subcommands: `build`, `dev`, `qa`, `judge`, `docs`, `runs`, `show`, `attach`, `stop`
- [x] Each command has basic help text
- [x] `uv run dkmv --help` shows all commands

#### Files to Create/Modify

- `dkmv/cli.py` — (create) Typer app with subcommand stubs

#### Implementation Notes

Use `app = typer.Typer(help="DKMV — orchestrate AI agents to implement features")`. Each subcommand can initially just print "Not yet implemented" with a `typer.echo()`. The `@app.callback()` for global options will be added in T020.

#### Evaluation Checklist

- [x] `uv run dkmv --help` shows all commands
- [x] No import errors
- [x] Type check passes: `uv run mypy dkmv/cli.py`

---

### T013: Create dkmv/__init__.py and dkmv/__main__.py

**PRD Reference:** Section 3.1
**Depends on:** T011
**Blocks:** T015
**User Stories:** US-01
**Estimated scope:** 15 min

#### Description

Create the package init and `__main__.py` so `python -m dkmv` works as an alternative entry point.

#### Acceptance Criteria

- [x] `dkmv/__init__.py` exports `__version__`
- [x] `dkmv/__main__.py` calls the Typer app
- [x] `uv run python -m dkmv --help` works

#### Files to Create/Modify

- `dkmv/__init__.py` — (modify) Add version export
- `dkmv/__main__.py` — (create) `from dkmv.cli import app; app()`

#### Implementation Notes

Keep `__main__.py` minimal: just import and call the app.

#### Evaluation Checklist

- [x] `uv run python -m dkmv --help` shows commands

---

### T014: Create dkmv/utils/async_support.py

**PRD Reference:** Section 6/F1
**Depends on:** T011
**Blocks:** T015
**User Stories:** US-01
**Estimated scope:** 30 min

#### Description

Create the async_command decorator that bridges Typer (sync) with async component execution. Typer doesn't natively support async commands, so this wrapper uses `asyncio.run()`.

#### Acceptance Criteria

- [x] `async_command` decorator converts async function to sync
- [x] Preserves function signature for Typer introspection
- [x] Works with `@app.command()` + `@async_command` stack

#### Files to Create/Modify

- `dkmv/utils/__init__.py` — (modify) Export async_command
- `dkmv/utils/async_support.py` — (create) Decorator implementation

#### Implementation Notes

Use the exact pattern from PRD Section 6/F1:
```python
import asyncio, functools
from typing import Any, Callable, Coroutine

def async_command(func: Callable[..., Coroutine]) -> Callable[..., Any]:
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))
    return wrapper
```

#### Evaluation Checklist

- [x] Decorator importable from `dkmv.utils`
- [x] Type check passes

---

### T015: Verify CLI Works End-to-End

**PRD Reference:** Section 6/F1
**Depends on:** T012, T013, T014
**Blocks:** T020
**User Stories:** US-01
**Estimated scope:** 15 min

#### Description

Verify that the full CLI chain works: `uv sync` installs the package, `uv run dkmv --help` shows commands, `uv run python -m dkmv --help` also works.

#### Acceptance Criteria

- [x] `uv sync` completes without errors
- [x] `uv run dkmv --help` shows all subcommands
- [x] `uv run python -m dkmv --help` works
- [x] Each subcommand is accessible: `uv run dkmv build --help`, etc.

#### Files to Create/Modify

None — this is a verification task

#### Implementation Notes

Run each command and verify output. Fix any import errors or missing dependencies discovered during verification.

#### Evaluation Checklist

- [x] All commands accessible
- [x] No runtime errors

---

### T016: Create docs/ Directory Structure

**PRD Reference:** Section 3.4
**Depends on:** Nothing
**Blocks:** T017
**User Stories:** N/A
**Estimated scope:** 15 min

#### Description

Create the documentation directory structure per PRD Section 3.4: getting-started/, architecture/, development/, decisions/.

#### Acceptance Criteria

- [x] `docs/getting-started/` exists
- [x] `docs/architecture/` exists
- [x] `docs/development/` exists
- [x] `docs/decisions/` exists

#### Files to Create/Modify

- `docs/getting-started/.gitkeep` — (create)
- `docs/architecture/.gitkeep` — (create)
- `docs/development/.gitkeep` — (create)
- `docs/decisions/.gitkeep` — (create)

#### Implementation Notes

Use `.gitkeep` files so git tracks empty directories. Actual docs will be written incrementally during implementation.

#### Evaluation Checklist

- [x] All directories exist

---

### T017: Write Initial ADRs

**PRD Reference:** Section 3.4
**Depends on:** T016
**Blocks:** Nothing
**User Stories:** N/A
**Estimated scope:** 30 min

#### Description

Write the first Architecture Decision Records using MADR 4.0 template. This establishes the ADR convention for the project and records the v1 agent decision.

#### Acceptance Criteria

- [x] `docs/decisions/0001-record-architecture-decisions.md` exists
- [x] `docs/decisions/0002-claude-code-only-for-v1.md` exists (record decision and rationale for v2 extensibility)
- [x] Follows MADR 4.0 minimal template
- [x] Status: Accepted

NOTE: ADRs 0003-0007 from the PRD can be written as the relevant features are implemented.
Add a note in each relevant phase doc to write the ADR alongside the implementation.

#### Files to Create/Modify

- `docs/decisions/0001-record-architecture-decisions.md` — (create) First ADR

#### Implementation Notes

Research MADR 4.0 template at https://adr.github.io/madr/. Include: Status, Context, Decision Drivers, Considered Options, Decision Outcome, Consequences.

#### Evaluation Checklist

- [x] ADR file exists and follows template

---

### T018: Set Up Linting and Pre-commit

**PRD Reference:** Section 3.4, Section 9.5.3, Section 11
**Depends on:** T010
**Blocks:** T027
**User Stories:** N/A
**Estimated scope:** 1 hour

#### Description

Configure ruff (linting + formatting) and mypy (type checking) in pyproject.toml. Set up .pre-commit-config.yaml with Commitizen commit-msg hook and ruff hooks.

#### Acceptance Criteria

- [x] `[tool.ruff]` configured: target-version="py312", line-length=100
- [x] `[tool.mypy]` configured with strict settings appropriate for the project
- [x] `.pre-commit-config.yaml` exists with ruff and commitizen hooks
- [x] `uv run ruff check .` runs without config errors
- [x] `uv run mypy dkmv/` runs without config errors
- [x] Root .gitignore includes: `outputs/`, `.env`, `__pycache__/`, `*.egg-info/`, `dist/`, `.mypy_cache/`
- [x] `.env.example` created with placeholder values for all env vars

#### Files to Create/Modify

- `pyproject.toml` — (modify) Add ruff and mypy config sections
- `.pre-commit-config.yaml` — (create) Pre-commit hooks
- `.gitignore` — (create) Root .gitignore with standard exclusions
- `.env.example` — (create) Placeholder env vars

#### Implementation Notes

Ruff config from PRD Section 11. For mypy, start with reasonable defaults: `strict = false` initially, enable incrementally. Commitizen config in pyproject.toml: `[tool.commitizen]` section.

#### Evaluation Checklist

- [x] `uv run ruff check dkmv/` passes
- [x] `uv run mypy dkmv/` passes
- [x] Pre-commit config is valid: `uv run pre-commit validate-config`

---

### T019: Create dkmv/config.py with DKMVConfig

**PRD Reference:** Section 6/F1, Section 10
**Depends on:** T011
**Blocks:** T020, T021, T022, T030
**User Stories:** US-03
**Estimated scope:** 1 hour

#### Description

Create the global configuration class using pydantic-settings BaseSettings. Configuration comes from env vars and optional .env file — no YAML config.

#### Acceptance Criteria

- [x] DKMVConfig class with all fields from PRD Section 6/F1
- [x] `anthropic_api_key` and `github_token` use standard env var names (no prefix)
- [x] Other fields use `DKMV_` prefix via `validation_alias`
- [x] `.env` file loading via `SettingsConfigDict(env_file=".env")`
- [x] Sensible defaults for all optional fields

#### Files to Create/Modify

- `dkmv/config.py` — (create) DKMVConfig class

#### Implementation Notes

Use the exact model from PRD Section 6/F1:
- `anthropic_api_key: str` with `validation_alias="ANTHROPIC_API_KEY"`
- `github_token: str = ""` with `validation_alias="GITHUB_TOKEN"`
- `default_model: str = "claude-sonnet-4-20250514"` with `validation_alias="DKMV_MODEL"`
- `default_max_turns: int = 100`, `image_name: str = "dkmv-sandbox:latest"`, etc.
- `max_budget_usd: float | None = None` with `validation_alias="DKMV_MAX_BUDGET_USD"` (optional cost cap per invocation)

#### Evaluation Checklist

- [x] Config loadable with env vars set
- [x] Config loadable from .env file
- [x] Defaults work when optional vars not set
- [x] Type check passes

---

### T020: Implement Typer Global Options

**PRD Reference:** Section 6/F1
**Depends on:** T012, T019
**Blocks:** Nothing
**User Stories:** US-03
**Estimated scope:** 30 min

#### Description

Add `@app.callback()` to the Typer app for global options: `--verbose` and `--dry-run`. These are available to all subcommands.

#### Acceptance Criteria

- [x] `dkmv --verbose dev ...` enables verbose mode
- [x] `dkmv --dry-run dev ...` enables dry-run mode
- [x] Global options show in `dkmv --help`

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) Add @app.callback() with global options

#### Implementation Notes

Use Typer's callback pattern. Store verbose/dry-run state in a module-level or context variable accessible to subcommands.

#### Evaluation Checklist

- [x] `dkmv --help` shows --verbose and --dry-run
- [x] Flags are parsed without error

---

### T021: Implement API Key Validation

**PRD Reference:** Section 6/F1
**Depends on:** T019
**Blocks:** Nothing
**User Stories:** US-04
**Estimated scope:** 30 min

#### Description

Validate that `ANTHROPIC_API_KEY` is set before any component command runs. Show a clear, helpful error message if missing.

#### Acceptance Criteria

- [x] Missing API key produces clear error: "ANTHROPIC_API_KEY not set. Set it via environment variable or .env file."
- [x] Validation runs before any component execution
- [x] `dkmv build` does NOT require API key (only Docker needed)

#### Files to Create/Modify

- `dkmv/config.py` — (modify) Add validation logic

#### Implementation Notes

Use Pydantic's `@field_validator` or a separate validation function called at command startup. The `build` command should skip API key validation since it only needs Docker.

#### Evaluation Checklist

- [x] Clear error when API key missing
- [x] No error when API key present
- [x] `dkmv build` works without API key

---

### T022: Write tests/unit/test_config.py

**PRD Reference:** Section 8/Task 0.1, Section 9.5.1
**Depends on:** T019
**Blocks:** Nothing
**User Stories:** US-03
**Estimated scope:** 1 hour

#### Description

Write unit tests for configuration loading: env vars, .env file, defaults, validation.

#### Acceptance Criteria

- [x] Test: config loads from env vars
- [x] Test: config uses defaults when vars not set
- [x] Test: validation error for missing required fields
- [x] Test: API key validation message
- [x] All tests pass: `uv run pytest tests/unit/test_config.py -v`

#### Files to Create/Modify

- `tests/unit/test_config.py` — (create) Config unit tests

#### Implementation Notes

Use `monkeypatch.setenv()` to set env vars in tests. Use `monkeypatch.delenv()` to test missing vars. Don't create actual .env files — use monkeypatch for isolation.

#### Evaluation Checklist

- [x] All tests pass
- [x] No flaky tests
- [x] Good coverage of config edge cases

---

### T023: Move/Verify Dockerfile

**PRD Reference:** Section 6/F2
**Depends on:** T011
**Blocks:** T024, T025
**User Stories:** US-02
**Estimated scope:** 15 min

#### Description

Move the existing Dockerfile from the project root to `dkmv/images/Dockerfile`. The current Dockerfile is already complete per the PRD spec.

#### Acceptance Criteria

- [x] `dkmv/images/Dockerfile` exists with full content
- [x] Root `Dockerfile` removed
- [x] Dockerfile content matches PRD Section 6/F2 spec

#### Files to Create/Modify

- `dkmv/images/Dockerfile` — (create) Move from root
- `Dockerfile` — (delete) Remove from root

#### Implementation Notes

The existing Dockerfile at the project root is already comprehensive and matches the PRD. Move it to `dkmv/images/Dockerfile`.

IMPORTANT: When building from `dkmv/images/Dockerfile`, the build context must still be the
project root (or the image directory if self-contained). Since our Dockerfile is self-contained
(doesn't COPY any local files), set build context to the Dockerfile's directory:

`docker build -f dkmv/images/Dockerfile dkmv/images/`

Or equivalently: `docker build dkmv/images/`

The `dkmv build` command (T024) should handle this path correctly.

#### Evaluation Checklist

- [x] Dockerfile at correct location
- [x] Content unchanged

---

### T024: Create `dkmv build` CLI Command

**PRD Reference:** Section 6/F2
**Depends on:** T012, T023
**Blocks:** T026
**User Stories:** US-02, US-04
**Estimated scope:** 1-2 hours

#### Description

Implement the `dkmv build` command that builds the Docker image using the packaged Dockerfile. Supports `--no-cache` and `--claude-version` flags.

#### Acceptance Criteria

- [x] `dkmv build` runs `docker build` with the correct Dockerfile path
- [x] Tags image as configured name (default: `dkmv-sandbox:latest`)
- [x] `--no-cache` passes `--no-cache` to docker build
- [x] `--claude-version TEXT` passes `--build-arg CLAUDE_CODE_VERSION=X.Y.Z`
- [x] Build context set correctly for `dkmv/images/Dockerfile`
- [x] Command: `docker build -t dkmv-sandbox:latest dkmv/images/`
- [x] Shows build progress
- [x] Graceful error if Docker not installed
- [x] `dkmv build --help` shows all options

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) Replace build stub with implementation

#### Implementation Notes

Use `subprocess.run` or `docker` Python SDK to run docker build. Find the Dockerfile path using `importlib.resources` or `Path(__file__).parent / "images" / "Dockerfile"`. Check for Docker availability with `shutil.which("docker")` before attempting build.

#### Evaluation Checklist

- [x] Command builds image successfully
- [x] Error handling for missing Docker
- [x] All flags work as documented

---

### T025: Write Docker Image Tests

**PRD Reference:** Section 9.5.5
**Depends on:** T023
**Blocks:** Nothing
**User Stories:** US-02
**Estimated scope:** 1 hour

#### Description

Create a shell script that asserts the built Docker image has the correct structure: non-root user, tools available, env vars set.

#### Acceptance Criteria

- [x] Script tests: non-root user `dkmv` at UID 1000
- [x] Script tests: `claude --version`, `gh --version`, `git --version`, `python3 --version`
- [x] Script tests: `swerex-remote` available
- [x] Script tests: `IS_SANDBOX=1` env var set
- [x] Script tests: `NODE_OPTIONS` set
- [x] Script tests: working directory is `/home/dkmv/workspace`

#### Files to Create/Modify

- `tests/docker/test_image.sh` — (create) Image structure assertions

#### Implementation Notes

Use `docker run --rm dkmv-sandbox:latest <command>` for each assertion. Script should exit non-zero on first failure. Consider using `set -euo pipefail`.

#### Evaluation Checklist

- [x] Script runs against built image
- [x] All assertions pass
- [x] Script is executable (`chmod +x`)

---

### T026: Test dkmv build End-to-End

**PRD Reference:** Section 6/F2
**Depends on:** T024
**Blocks:** Nothing
**User Stories:** US-02
**Estimated scope:** 30 min

#### Description

Verify `dkmv build` produces a working Docker image by running the command and then running the image test script.

#### Acceptance Criteria

- [x] `uv run dkmv build` completes successfully
- [x] `tests/docker/test_image.sh` passes against the built image
- [x] Image can start a container and run basic commands

#### Files to Create/Modify

None — verification task

#### Implementation Notes

Run `uv run dkmv build` then `bash tests/docker/test_image.sh`. This requires Docker to be installed and running.

#### Evaluation Checklist

- [x] Image builds successfully
- [x] All image assertions pass

---

### T027: Create CI Pipeline

**PRD Reference:** Section 9.5.4
**Depends on:** T018
**Blocks:** T028
**User Stories:** N/A
**Estimated scope:** 1-2 hours

#### Description

Create the GitHub Actions CI pipeline with lint, typecheck, unit test, and Docker build stages.

#### Acceptance Criteria

- [x] `.github/workflows/ci.yml` exists
- [x] Triggers on: push to main, pull requests
- [x] Uses `astral-sh/setup-uv` action
- [x] Python 3.12 matrix

#### Files to Create/Modify

- `.github/workflows/ci.yml` — (create) CI pipeline

#### Implementation Notes

Research `astral-sh/setup-uv` action for the latest usage pattern. Structure:
- Lint job: `uv run ruff check . && uv run ruff format --check .`
- Type check job: `uv run mypy dkmv/` (parallel with lint)
- Unit test job: `uv run pytest tests/unit/ --cov --cov-fail-under=80` (depends on lint + typecheck)
- Integration test job: `uv run pytest tests/integration/` (depends on lint + typecheck)
- Docker build job: `docker build -f dkmv/images/Dockerfile .` (parallel with tests)
- E2E job: only on main merge (needs API key secret)

#### Evaluation Checklist

- [x] YAML is valid
- [x] Pipeline stages are correctly ordered
- [x] Dependencies between jobs are correct

---

### T028: Configure CI Stages

**PRD Reference:** Section 9.5.4
**Depends on:** T027
**Blocks:** T029
**User Stories:** N/A
**Estimated scope:** 1 hour

#### Description

Fill in the CI pipeline stages with proper commands, artifact caching, and conditional logic for E2E tests.

#### Acceptance Criteria

- [x] Lint and typecheck run in parallel
- [x] Unit tests depend on lint + typecheck
- [x] Docker build runs in parallel with tests
- [x] E2E tests only on main merge / nightly
- [x] uv cache configured for speed

#### Files to Create/Modify

- `.github/workflows/ci.yml` — (modify) Fill in stage details

#### Implementation Notes

Use `needs: [lint, typecheck]` for the test job dependency. Use `if: github.ref == 'refs/heads/main'` for E2E gating.

#### Evaluation Checklist

- [x] All jobs configured correctly
- [x] Conditional logic works

---

### T029: Verify CI Pipeline

**PRD Reference:** Section 9.5.4
**Depends on:** T028
**Blocks:** Nothing
**User Stories:** N/A
**Estimated scope:** 30 min

#### Description

Push a test commit and verify the CI pipeline runs correctly on GitHub Actions.

#### Acceptance Criteria

- [ ] CI pipeline triggers on push
- [ ] All stages pass (or fail gracefully if expected)
- [ ] Job dependency ordering works correctly

#### Files to Create/Modify

None — verification task

#### Implementation Notes

This requires pushing to GitHub. If the repo isn't on GitHub yet, defer this task until it is.

#### Evaluation Checklist

- [ ] Pipeline runs without infrastructure errors

---

## Phase Completion Checklist

- [ ] All tasks T010-T029 completed — T029 (CI verification) pending: requires push to GitHub
- [x] `uv sync && uv run dkmv --help` shows all subcommands
- [x] `uv run dkmv build` builds the Docker image
- [x] `uv run pytest tests/unit/test_config.py -v` passes
- [x] Lint clean: `uv run ruff check .`
- [x] Type check clean: `uv run mypy dkmv/`
- [x] CI pipeline configured and valid
- [x] Progress updated in tasks.md and progress.md
