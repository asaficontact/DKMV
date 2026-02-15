# Phase 0: Testing Infrastructure

## Prerequisites

- None — this is the first phase

## Phase Goal

Establish the test directory structure, pytest configuration, shared fixtures, and integration test mocks so that all subsequent phases can write tests alongside implementation code.

## Phase Evaluation Criteria

- `uv run pytest tests/ --collect-only` runs without error and shows test structure
- Shared fixtures (`git_repo`, `mock_sandbox`, `make_config`) are importable from conftest
- Factory functions generate valid Pydantic models
- Mock sandbox session records commands for later assertion

---

## Tasks

### T001: Create tests/ Directory Structure

**PRD Reference:** Section 8/Task 0.1, Section 3.1
**Depends on:** Nothing
**Blocks:** T002, T003, T004, T005
**User Stories:** N/A (infrastructure)
**Estimated scope:** 30 min

#### Description

Create the top-level `tests/` directory at the project root (not inside `dkmv/`). This is the foundation for all testing — unit, integration, E2E, and Docker image tests.

#### Acceptance Criteria

- [ ] `tests/` directory exists at project root
- [ ] Subdirectories: `tests/unit/`, `tests/integration/`, `tests/e2e/`, `tests/docker/`
- [ ] Each directory has an `__init__.py` (except `tests/docker/`)
- [ ] `tests/__init__.py` exists

#### Files to Create/Modify

- `tests/__init__.py` — (create) Empty init
- `tests/unit/__init__.py` — (create) Empty init
- `tests/integration/__init__.py` — (create) Empty init
- `tests/e2e/__init__.py` — (create) Empty init
- `tests/docker/` — (create) Directory only (shell scripts, no __init__.py)

#### Implementation Notes

Keep all `__init__.py` files empty. The directory structure mirrors PRD Section 3.1.

#### Evaluation Checklist

- [ ] All directories exist
- [ ] `python -c "import tests"` does not error (from project root)

---

### T002: Configure pytest in pyproject.toml

**PRD Reference:** Section 9.5.1, Section 11
**Depends on:** T001
**Blocks:** T003
**User Stories:** N/A (infrastructure)
**Estimated scope:** 30 min

#### Description

Add pytest configuration to `pyproject.toml` including async mode, test paths, markers, and coverage settings. This must be done before writing any test files.

#### Acceptance Criteria

- [ ] `[tool.pytest.ini_options]` section exists in pyproject.toml
- [ ] `testpaths = ["tests"]`
- [ ] `asyncio_mode = "auto"`
- [ ] `markers = ["e2e: end-to-end tests requiring Docker and API key"]`
- [ ] Coverage configuration excludes `tests/*`, `TYPE_CHECKING`, `__main__.py`

#### Files to Create/Modify

- `pyproject.toml` — (modify) Add pytest, coverage, and dev dependencies sections

#### Implementation Notes

Add the dev dependency group from PRD Section 11: pytest, pytest-asyncio, pytest-cov, pytest-timeout, syrupy, polyfactory, ruff, mypy, commitizen, pre-commit. Use `[dependency-groups]` syntax for uv.

#### Evaluation Checklist

- [ ] `uv sync` installs dev dependencies
- [ ] `uv run pytest --co` runs without configuration errors

---

### T003: Create tests/conftest.py with Shared Fixtures

**PRD Reference:** Section 9.5.6
**Depends on:** T001, T002
**Blocks:** T022 (test_config), T045 (test_runner), T049 (test_stream)
**User Stories:** N/A (infrastructure)
**Estimated scope:** 1 hour

#### Description

Create the root conftest.py with shared pytest fixtures used across all test levels. These fixtures provide consistent test infrastructure.

#### Acceptance Criteria

- [ ] `git_repo` fixture creates a temporary git repo with initial commit
- [ ] `mock_sandbox` fixture returns an AsyncMock SandboxManager
- [ ] `make_config` fixture provides a factory for DKMVConfig with test defaults
- [ ] All fixtures are importable by test files in any subdirectory

#### Files to Create/Modify

- `tests/conftest.py` — (create) Shared fixtures

#### Implementation Notes

- Use `tmp_path` for the `git_repo` fixture: init a git repo, create a dummy file, commit it
- `mock_sandbox` should use `unittest.mock.AsyncMock` — no extra dependency needed
- `make_config` should return a function that creates DKMVConfig with overridable defaults (set `ANTHROPIC_API_KEY` to a test value, etc.)
- These fixtures will be refined as Pydantic models are created in later phases. Start with placeholder types if needed, but structure the fixture signatures correctly.

IMPORTANT: DKMVConfig (T019) and SandboxManager (T031) don't exist yet in Phase 0.

Strategy: Create fixtures as stubs using dictionaries or SimpleNamespace:

```python
@pytest.fixture
def make_config():
    """Factory fixture — returns dict now, will be updated to DKMVConfig in Phase 1."""
    def _make(**overrides):
        defaults = {
            "anthropic_api_key": "test-key-123",
            "github_token": "ghp_test123",
            "model": "claude-sonnet-4-20250514",
            "max_turns": 10,
            "image": "dkmv-sandbox:latest",
            "output_dir": "/tmp/test-outputs",
            "timeout_minutes": 5,
            "memory": "4g",
        }
        defaults.update(overrides)
        return defaults
    return _make

@pytest.fixture
def mock_sandbox():
    """AsyncMock sandbox — will be updated when SandboxManager is defined."""
    mock = AsyncMock()
    mock.execute.return_value = AsyncMock(output="", exit_code=0)
    mock.write_file.return_value = None
    mock.read_file.return_value = ""
    return mock
```

These fixtures will be updated to use actual types once Phase 1 and 2 are complete.
Mark the fixtures with a `# TODO: update to use DKMVConfig/SandboxManager` comment.

#### Evaluation Checklist

- [ ] `uv run pytest tests/ --collect-only` shows fixtures
- [ ] No import errors from conftest

---

### T004: Create tests/factories.py with Model Factories

**PRD Reference:** Section 9.5.6
**Depends on:** T002
**Blocks:** T045, T049, T057
**User Stories:** N/A (infrastructure)
**Estimated scope:** 1 hour

#### Description

Create polyfactory-based model factories for all Pydantic models. These generate valid test data with sensible defaults that can be overridden per-test.

#### Acceptance Criteria

- [ ] Factory classes exist for future models (stubs initially, filled in Phase 2)
- [ ] Each factory produces valid Pydantic model instances
- [ ] Factories are importable from `tests.factories`

#### Files to Create/Modify

- `tests/factories.py` — (create) Model factory definitions

#### Implementation Notes

Start with an empty-ish factories file. Actual polyfactory factories require Pydantic models
that don't exist until T030. Include a clear TODO:

```python
"""Model factories for testing. Populated as models are created."""
# from polyfactory.factories.pydantic_factory import ModelFactory
# Factories added in T030 when core models are created.
```

#### Evaluation Checklist

- [ ] `uv run python -c "from tests.factories import *"` succeeds
- [ ] File is ready to receive factory classes

---

### T005: Create tests/integration/conftest.py with SWE-ReX Mocks

**PRD Reference:** Section 9.5.6, Section 8/Task 0.2
**Depends on:** T001
**Blocks:** T039 (test_sandbox integration)
**User Stories:** N/A (infrastructure)
**Estimated scope:** 1 hour

#### Description

Create integration-level conftest with mocks for SWE-ReX components (DockerDeployment, RemoteRuntime). These allow testing SandboxManager without actually starting Docker containers.

#### Acceptance Criteria

- [ ] Mock DockerDeployment that simulates container lifecycle
- [ ] Mock RemoteRuntime that records executed commands
- [ ] Fixtures are scoped to integration tests only

#### Files to Create/Modify

- `tests/integration/conftest.py` — (create) SWE-ReX mock fixtures

#### Implementation Notes

SWE-ReX API (v1.4.0) — mock these interfaces:
- `DockerDeployment` — async context manager (__aenter__, __aexit__)
- `RemoteRuntime.run_in_session(BashAction)` → returns `BashObservation`
- `RemoteRuntime.write_file(path, content)` → direct method
- `RemoteRuntime.read_file(path)` → direct method, returns string
- `RemoteRuntime.create_session(CreateBashSessionRequest())` → creates bash session
Do NOT mock WriteFileRequest/ReadFileRequest — these don't exist.
- Start with stubs that will be refined once SandboxManager is implemented in Phase 2.

#### Evaluation Checklist

- [ ] Fixtures importable from integration tests
- [ ] No dependency on Docker being installed

---

### T006: Create Mock Sandbox Session Helper

**PRD Reference:** Section 8/Task 0.2
**Depends on:** T005
**Blocks:** T057 (BaseComponent tests)
**User Stories:** N/A (infrastructure)
**Estimated scope:** 30 min

#### Description

Create a helper class that acts as a fake sandbox session, recording all commands executed against it for later assertion in tests.

#### Acceptance Criteria

- [ ] MockSandboxSession records execute() calls with arguments
- [ ] Supports configurable return values per command
- [ ] Can assert specific commands were called in order

#### Files to Create/Modify

- `tests/integration/conftest.py` — (modify) Add MockSandboxSession class

#### Implementation Notes

Pattern:
```python
class MockSandboxSession:
    def __init__(self):
        self.commands: list[str] = []
        self.responses: dict[str, str] = {}

    async def execute(self, command: str) -> str:
        self.commands.append(command)
        return self.responses.get(command, "")
```

#### Evaluation Checklist

- [ ] MockSandboxSession usable in tests
- [ ] Commands are recorded and assertable

---

### T007: Create Temporary Test Repo Helper

**PRD Reference:** Section 9.5.6
**Depends on:** T001
**Blocks:** T072 (E2E tests)
**User Stories:** N/A (infrastructure)
**Estimated scope:** 30 min

#### Description

Create a helper function that creates a minimal git repository with `src/` and `tests/` directories, suitable for E2E testing of components.

#### Acceptance Criteria

- [ ] Helper creates a git repo in a tmp directory
- [ ] Repo has: `src/main.py`, `tests/test_main.py`, initial commit
- [ ] Repo is a valid git repository with at least one commit

#### Files to Create/Modify

- `tests/conftest.py` — (modify) Add `create_test_repo` helper function

#### Implementation Notes

Use `subprocess.run` for git commands (init, add, commit). Keep the test repo minimal — just enough to validate component workflows.

#### Evaluation Checklist

- [ ] Helper creates valid git repo
- [ ] Repo has expected file structure

---

## Phase Completion Checklist

- [ ] All tasks T001-T007 completed
- [ ] `uv run pytest tests/ --collect-only` shows test structure without errors
- [ ] All fixtures importable from conftest files
- [ ] Factory module importable
- [ ] No lint errors: `uv run ruff check tests/`
- [ ] Progress updated in tasks.md and progress.md
