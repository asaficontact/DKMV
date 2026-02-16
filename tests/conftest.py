from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from dkmv.config import DKMVConfig


# --- T003: Shared fixtures ---


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def _git(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            check=True,
        )

    _git("init")
    _git("config", "user.name", "Test User")
    _git("config", "user.email", "test@example.com")

    readme = repo / "README.md"
    readme.write_text("# Test Repo\n")

    _git("add", ".")
    _git("commit", "-m", "Initial commit")

    return repo


@pytest.fixture
def make_config() -> Any:
    """Factory for test-safe DKMVConfig instances."""

    def _make(**overrides: Any) -> DKMVConfig:
        defaults: dict[str, Any] = {
            "anthropic_api_key": "sk-ant-test-key-000",
            "github_token": "ghp_test000000000000000000000000000000",
            "default_model": "claude-sonnet-4-20250514",
            "default_max_turns": 10,
            "image_name": "dkmv-sandbox:latest",
            "output_dir": Path("./outputs"),
            "timeout_minutes": 5,
            "memory_limit": "4g",
        }
        defaults.update(overrides)
        return DKMVConfig.model_construct(**defaults)

    return _make


@pytest.fixture
def mock_sandbox() -> AsyncMock:
    """Mock sandbox with standard SandboxManager interface."""
    sandbox = AsyncMock()
    sandbox.start = AsyncMock()
    sandbox.stop = AsyncMock()

    execute_result = MagicMock()
    execute_result.output = ""
    execute_result.exit_code = 0
    sandbox.execute = AsyncMock(return_value=execute_result)

    sandbox.write_file = AsyncMock()
    sandbox.read_file = AsyncMock(return_value="")

    return sandbox


# --- T007: Test repo helper ---


def create_test_repo(base_path: Path) -> Path:
    """Create a test project with src/, tests/, and git history."""
    repo = base_path / "test-project"
    repo.mkdir()

    def _git(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            check=True,
        )

    # Create project structure
    src = repo / "src"
    src.mkdir()
    (src / "main.py").write_text('def hello() -> str:\n    return "Hello, world!"\n')

    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_main.py").write_text(
        'from src.main import hello\n\n\ndef test_hello():\n    assert hello() == "Hello, world!"\n'
    )

    (repo / "README.md").write_text("# Test Project\n\nA test project for integration tests.\n")

    # Initialize git
    _git("init")
    _git("config", "user.name", "Test User")
    _git("config", "user.email", "test@example.com")
    _git("add", ".")
    _git("commit", "-m", "Initial commit")

    return repo


@pytest.fixture
def test_repo(tmp_path: Path) -> Path:
    """Pytest fixture wrapping create_test_repo."""
    return create_test_repo(tmp_path)
