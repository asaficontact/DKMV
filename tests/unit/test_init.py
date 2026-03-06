"""Tests for dkmv init — credential discovery, project detection, Docker check,
filesystem operations, and CLI integration."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import click.exceptions
import pytest
from typer.testing import CliRunner

from dkmv.cli import app
from dkmv.init import (
    check_docker_image,
    detect_default_branch,
    detect_project_name,
    detect_repo,
    discover_anthropic_key,
    discover_codex_key,
    discover_github_token,
    discover_oauth_token,
    update_gitignore,
    write_project_config,
)
from dkmv.config import load_config
from dkmv.project import ProjectConfig

# ── Env vars to clear for isolation ──────────────────────────────────
_ENV_VARS = [
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "CODEX_API_KEY",
    "OPENAI_API_KEY",
    "DKMV_MODEL",
    "DKMV_MAX_TURNS",
    "DKMV_IMAGE",
    "DKMV_OUTPUT_DIR",
    "DKMV_TIMEOUT",
    "DKMV_MEMORY",
    "DKMV_MAX_BUDGET_USD",
]


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every test: CWD in tmp_path, no leaking env vars."""
    monkeypatch.chdir(tmp_path)
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


cli_runner = CliRunner()


# ═══════════════════════════════════════════════════════════════════════
# Group 1: Credential Discovery
# ═══════════════════════════════════════════════════════════════════════


class TestDiscoverAnthropicKey:
    def test_found_in_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        source, found = discover_anthropic_key(tmp_path)
        assert found is True
        assert source == "env"

    def test_found_in_dotenv(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-from-dotenv\n")
        source, found = discover_anthropic_key(tmp_path)
        assert found is True
        assert source == ".env"

    def test_env_var_takes_precedence_over_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-dotenv\n")
        source, found = discover_anthropic_key(tmp_path)
        assert found is True
        assert source == "env"

    def test_not_found(self, tmp_path: Path) -> None:
        source, found = discover_anthropic_key(tmp_path)
        assert found is False
        assert source == "none"


class TestDiscoverGithubToken:
    def test_found_github_token_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp-test")
        source, found = discover_github_token(tmp_path)
        assert found is True
        assert source == "env:GITHUB_TOKEN"

    def test_found_gh_token_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GH_TOKEN", "gho-test")
        source, found = discover_github_token(tmp_path)
        assert found is True
        assert source == "env:GH_TOKEN"

    def test_found_in_dotenv(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("GITHUB_TOKEN=ghp-dotenv\n")
        source, found = discover_github_token(tmp_path)
        assert found is True
        assert source == ".env"

    def test_gh_cli_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "dkmv.init.shutil.which", lambda cmd: "/usr/bin/gh" if cmd == "gh" else None
        )
        mock_result = MagicMock(returncode=0, stdout="gho_token123\n")
        monkeypatch.setattr("dkmv.init.subprocess.run", lambda *a, **kw: mock_result)
        source, found = discover_github_token(tmp_path)
        assert found is True
        assert source == "gh auth token"

    def test_gh_not_installed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("dkmv.init.shutil.which", lambda cmd: None)
        source, found = discover_github_token(tmp_path)
        assert found is False
        assert source == "none"

    def test_gh_timeout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "dkmv.init.shutil.which", lambda cmd: "/usr/bin/gh" if cmd == "gh" else None
        )

        def mock_run(*args: object, **kwargs: object) -> None:
            raise subprocess.TimeoutExpired(cmd="gh", timeout=10)

        monkeypatch.setattr("dkmv.init.subprocess.run", mock_run)
        source, found = discover_github_token(tmp_path)
        assert found is False
        assert source == "none"

    def test_gh_nonzero_exit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "dkmv.init.shutil.which", lambda cmd: "/usr/bin/gh" if cmd == "gh" else None
        )
        mock_result = MagicMock(returncode=1, stdout="")
        monkeypatch.setattr("dkmv.init.subprocess.run", lambda *a, **kw: mock_result)
        source, found = discover_github_token(tmp_path)
        assert found is False
        assert source == "none"

    def test_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("dkmv.init.shutil.which", lambda cmd: None)
        source, found = discover_github_token(tmp_path)
        assert found is False
        assert source == "none"


class TestDiscoverOauthToken:
    def test_found_in_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-test")
        source, found = discover_oauth_token(tmp_path)
        assert found is True
        assert source == "env"

    def test_found_in_dotenv(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-dotenv\n")
        source, found = discover_oauth_token(tmp_path)
        assert found is True
        assert source == ".env"

    def test_env_var_takes_precedence_over_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-env")
        (tmp_path / ".env").write_text("CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-dotenv\n")
        source, found = discover_oauth_token(tmp_path)
        assert found is True
        assert source == "env"

    def test_not_found(self, tmp_path: Path) -> None:
        source, found = discover_oauth_token(tmp_path)
        assert found is False
        assert source == "none"


# ═══════════════════════════════════════════════════════════════════════
# Group 2: Project Detection
# ═══════════════════════════════════════════════════════════════════════


class TestDetectRepo:
    def test_from_git_remote(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_result = MagicMock(returncode=0, stdout="https://github.com/org/repo.git\n")
        monkeypatch.setattr("dkmv.init.subprocess.run", lambda *a, **kw: mock_result)
        assert detect_repo(tmp_path) == "https://github.com/org/repo.git"

    def test_no_git(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_run(*args: object, **kwargs: object) -> None:
            raise FileNotFoundError

        monkeypatch.setattr("dkmv.init.subprocess.run", mock_run)
        assert detect_repo(tmp_path) is None

    def test_git_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_result = MagicMock(returncode=128, stdout="")
        monkeypatch.setattr("dkmv.init.subprocess.run", lambda *a, **kw: mock_result)
        assert detect_repo(tmp_path) is None


class TestDetectProjectName:
    def test_from_url(self, tmp_path: Path) -> None:
        assert detect_project_name("https://github.com/org/my-project", tmp_path) == "my-project"

    def test_strips_dot_git(self, tmp_path: Path) -> None:
        assert (
            detect_project_name("https://github.com/org/my-project.git", tmp_path) == "my-project"
        )

    def test_from_directory_name(self, tmp_path: Path) -> None:
        assert detect_project_name(None, tmp_path) == tmp_path.name

    def test_trailing_slash(self, tmp_path: Path) -> None:
        assert detect_project_name("https://github.com/org/my-project/", tmp_path) == "my-project"


class TestDetectDefaultBranch:
    def test_from_symbolic_ref(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_result = MagicMock(returncode=0, stdout="refs/remotes/origin/develop\n")
        monkeypatch.setattr("dkmv.init.subprocess.run", lambda *a, **kw: mock_result)
        assert detect_default_branch(tmp_path) == "develop"

    def test_fallback_to_remote_show(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = 0

        def mock_run(*args: object, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # symbolic-ref fails
                return MagicMock(returncode=128, stdout="")
            # remote show origin succeeds
            return MagicMock(
                returncode=0,
                stdout="* remote origin\n  HEAD branch: develop\n  Remote branches:\n",
            )

        monkeypatch.setattr("dkmv.init.subprocess.run", mock_run)
        assert detect_default_branch(tmp_path) == "develop"

    def test_fallback_to_main(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_run(*args: object, **kwargs: object) -> None:
            raise FileNotFoundError

        monkeypatch.setattr("dkmv.init.subprocess.run", mock_run)
        assert detect_default_branch(tmp_path) == "main"


# ═══════════════════════════════════════════════════════════════════════
# Group 3: Docker Image Check
# ═══════════════════════════════════════════════════════════════════════


class TestCheckDockerImage:
    def test_docker_not_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("dkmv.init.shutil.which", lambda cmd: None)
        status = check_docker_image("dkmv-sandbox:latest")
        assert status.docker_available is False
        assert status.image_found is False

    def test_image_found_with_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("dkmv.init.shutil.which", lambda cmd: "/usr/bin/docker")
        # 2.5 GB in bytes
        size_bytes = int(2.5 * 1024**3)
        mock_result = MagicMock(returncode=0, stdout=f"{size_bytes}\n")
        monkeypatch.setattr("dkmv.init.subprocess.run", lambda *a, **kw: mock_result)
        status = check_docker_image("dkmv-sandbox:latest")
        assert status.docker_available is True
        assert status.image_found is True
        assert status.image_size == "2.5GB"

    def test_image_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("dkmv.init.shutil.which", lambda cmd: "/usr/bin/docker")
        mock_result = MagicMock(returncode=1, stdout="")
        monkeypatch.setattr("dkmv.init.subprocess.run", lambda *a, **kw: mock_result)
        status = check_docker_image("dkmv-sandbox:latest")
        assert status.docker_available is True
        assert status.image_found is False


# ═══════════════════════════════════════════════════════════════════════
# Group 4: Filesystem Operations
# ═══════════════════════════════════════════════════════════════════════


class TestWriteProjectConfig:
    def test_creates_directories(self, tmp_path: Path) -> None:
        config = ProjectConfig(project_name="test", repo="https://github.com/org/repo")
        write_project_config(tmp_path, config)
        assert (tmp_path / ".dkmv").is_dir()
        assert (tmp_path / ".dkmv" / "runs").is_dir()

    def test_writes_config_json(self, tmp_path: Path) -> None:
        config = ProjectConfig(project_name="test", repo="https://github.com/org/repo")
        write_project_config(tmp_path, config)
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["project_name"] == "test"
        assert data["repo"] == "https://github.com/org/repo"

    def test_creates_components_json(self, tmp_path: Path) -> None:
        config = ProjectConfig(project_name="test", repo="https://github.com/org/repo")
        write_project_config(tmp_path, config)
        data = json.loads((tmp_path / ".dkmv" / "components.json").read_text())
        assert data == {}

    def test_reinit_preserves_components(self, tmp_path: Path) -> None:
        dkmv_dir = tmp_path / ".dkmv"
        dkmv_dir.mkdir()
        (dkmv_dir / "components.json").write_text('{"custom": "path/to/component"}\n')

        config = ProjectConfig(project_name="test", repo="https://github.com/org/repo")
        write_project_config(tmp_path, config)
        data = json.loads((dkmv_dir / "components.json").read_text())
        assert data == {"custom": "path/to/component"}

    def test_reinit_overwrites_config(self, tmp_path: Path) -> None:
        config1 = ProjectConfig(project_name="old", repo="https://github.com/org/old")
        write_project_config(tmp_path, config1)

        config2 = ProjectConfig(project_name="new", repo="https://github.com/org/new")
        write_project_config(tmp_path, config2)

        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["project_name"] == "new"
        assert data["repo"] == "https://github.com/org/new"


class TestUpdateGitignore:
    def test_creates_if_missing(self, tmp_path: Path) -> None:
        added = update_gitignore(tmp_path, [".dkmv/"])
        assert added == [".dkmv/"]
        assert (tmp_path / ".gitignore").read_text() == ".dkmv/\n"

    def test_appends_to_existing(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("node_modules/\n")
        added = update_gitignore(tmp_path, [".dkmv/"])
        assert added == [".dkmv/"]
        content = (tmp_path / ".gitignore").read_text()
        assert "node_modules/" in content
        assert ".dkmv/" in content

    def test_no_duplicates(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text(".dkmv/\n")
        added = update_gitignore(tmp_path, [".dkmv/"])
        assert added == []

    def test_returns_added_entries(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text(".dkmv/\n")
        added = update_gitignore(tmp_path, [".dkmv/", ".env"])
        assert added == [".env"]

    def test_handles_no_trailing_newline(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("node_modules/")
        added = update_gitignore(tmp_path, [".dkmv/"])
        assert added == [".dkmv/"]
        content = (tmp_path / ".gitignore").read_text()
        assert content == "node_modules/\n.dkmv/\n"

    def test_multiple_entries(self, tmp_path: Path) -> None:
        added = update_gitignore(tmp_path, [".dkmv/", ".env"])
        assert added == [".dkmv/", ".env"]
        content = (tmp_path / ".gitignore").read_text()
        assert ".dkmv/" in content
        assert ".env" in content


# ═══════════════════════════════════════════════════════════════════════
# Group 5: Init CLI Integration
# ═══════════════════════════════════════════════════════════════════════


def _mock_subprocess_for_init(
    monkeypatch: pytest.MonkeyPatch,
    *,
    repo_url: str = "https://github.com/org/test-repo.git",
    branch: str = "main",
    docker_installed: bool = False,
) -> None:
    """Mock subprocess calls for the init flow."""
    call_count = 0

    def mock_run(*args: object, **kwargs: object) -> MagicMock:
        nonlocal call_count
        cmd = args[0] if args else kwargs.get("args", [])
        if isinstance(cmd, list):
            if cmd[:3] == ["git", "remote", "get-url"]:
                return MagicMock(returncode=0, stdout=f"{repo_url}\n")
            if cmd[:3] == ["git", "symbolic-ref", "refs/remotes/origin/HEAD"]:
                return MagicMock(returncode=0, stdout=f"refs/remotes/origin/{branch}\n")
            if cmd[:4] == ["docker", "image", "inspect", "--format"]:
                return MagicMock(returncode=1, stdout="")
        return MagicMock(returncode=1, stdout="")

    monkeypatch.setattr("dkmv.init.subprocess.run", mock_run)
    if docker_installed:
        monkeypatch.setattr("dkmv.init.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
    else:
        monkeypatch.setattr("dkmv.init.shutil.which", lambda cmd: None)


class TestInitCommand:
    def test_help(self) -> None:
        result = cli_runner.invoke(app, ["init", "--help"])
        assert result.exit_code == 0
        assert "--yes" in result.output
        assert "--repo" in result.output
        assert "--name" in result.output

    def test_fresh_init_with_yes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        assert (tmp_path / ".dkmv" / "config.json").exists()
        assert (tmp_path / ".dkmv" / "runs").is_dir()
        assert (tmp_path / ".dkmv" / "components.json").exists()

    def test_autodetect_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        _mock_subprocess_for_init(monkeypatch, repo_url="https://github.com/org/my-app.git")
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["repo"] == "https://github.com/org/my-app.git"
        assert data["project_name"] == "my-app"

    def test_yes_no_repo_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        def mock_run(*args: object, **kwargs: object) -> MagicMock:
            return MagicMock(returncode=128, stdout="")

        monkeypatch.setattr("dkmv.init.subprocess.run", mock_run)
        monkeypatch.setattr("dkmv.init.shutil.which", lambda cmd: None)
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 1
        assert "Could not detect repo" in result.output

    def test_yes_no_auth_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 1
        assert "No authentication found" in result.output

    def test_github_token_optional(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        assert "not found (optional)" in result.output

    def test_name_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init", "--yes", "--name", "custom-name"])
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["project_name"] == "custom-name"

    def test_repo_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(
            app, ["init", "--yes", "--repo", "https://github.com/org/override"]
        )
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["repo"] == "https://github.com/org/override"

    def test_reinit_preserves_runs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        _mock_subprocess_for_init(monkeypatch)

        # First init
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0

        # Add a file in runs/
        (tmp_path / ".dkmv" / "runs" / "run-001.json").write_text("{}")

        # Reinit
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        assert (tmp_path / ".dkmv" / "runs" / "run-001.json").exists()

    def test_gitignore_updated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        gitignore = (tmp_path / ".gitignore").read_text()
        assert ".dkmv/" in gitignore

    def test_gitignore_adds_env_when_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-test\n")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        gitignore = (tmp_path / ".gitignore").read_text()
        assert ".env" in gitignore

    def test_rich_output_present(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        assert "DKMV Project Initialization" in result.output
        assert "[1/4]" in result.output
        assert "[2/4]" in result.output
        assert "[3/4]" in result.output
        assert "[4/4]" in result.output
        assert "initialized successfully" in result.output

    def test_credentials_source_saved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp-test")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["credentials"]["auth_method"] == "api_key"
        assert data["credentials"]["anthropic_api_key_source"] == "env"
        assert data["credentials"]["oauth_token_source"] == "none"
        assert data["credentials"]["github_token_source"] == "env:GITHUB_TOKEN"

    def test_default_branch_detected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        _mock_subprocess_for_init(monkeypatch, branch="develop")
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["default_branch"] == "develop"

    def test_docker_not_found_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        _mock_subprocess_for_init(monkeypatch, docker_installed=False)
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_docker_image_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        def mock_run(*args: object, **kwargs: object) -> MagicMock:
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list):
                if cmd[:3] == ["git", "remote", "get-url"]:
                    return MagicMock(returncode=0, stdout="https://github.com/org/r.git\n")
                if cmd[:3] == ["git", "symbolic-ref", "refs/remotes/origin/HEAD"]:
                    return MagicMock(returncode=0, stdout="refs/remotes/origin/main\n")
                if cmd[:4] == ["docker", "image", "inspect", "--format"]:
                    size = int(2.0 * 1024**3)
                    return MagicMock(returncode=0, stdout=f"{size}\n")
            return MagicMock(returncode=1, stdout="")

        monkeypatch.setattr("dkmv.init.subprocess.run", mock_run)
        monkeypatch.setattr("dkmv.init.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0


class TestInitNestedWarning:
    def test_nested_warning_shown(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When parent has .dkmv/ and CWD doesn't, warn about nested init."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        # Create parent config
        parent = tmp_path / "parent"
        parent.mkdir()
        dkmv_dir = parent / ".dkmv"
        dkmv_dir.mkdir()
        (dkmv_dir / "config.json").write_text(
            json.dumps(
                {"version": 1, "project_name": "parent-proj", "repo": "https://github.com/o/r"}
            )
        )

        # CWD is a subdirectory
        child = parent / "child"
        child.mkdir()
        monkeypatch.chdir(child)

        _mock_subprocess_for_init(monkeypatch)

        # User says "no" to nested init
        result = cli_runner.invoke(app, ["init"], input="n\n")
        assert "already initialized" in result.output or "Aborted" in result.output

    def test_nested_yes_proceeds(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--yes skips nested warning and proceeds."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        parent = tmp_path / "parent"
        parent.mkdir()
        dkmv_dir = parent / ".dkmv"
        dkmv_dir.mkdir()
        (dkmv_dir / "config.json").write_text(
            json.dumps(
                {"version": 1, "project_name": "parent-proj", "repo": "https://github.com/o/r"}
            )
        )

        child = parent / "child"
        child.mkdir()
        monkeypatch.chdir(child)

        _mock_subprocess_for_init(monkeypatch)

        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        assert (child / ".dkmv" / "config.json").exists()


class TestInitOAuth:
    """Tests for OAuth authentication path in dkmv init."""

    def test_yes_oauth_auto_detected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--yes with only CLAUDE_CODE_OAUTH_TOKEN → oauth auth method."""
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-test")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["credentials"]["auth_method"] == "oauth"

    def test_yes_api_key_preferred_over_oauth(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--yes with both API key and OAuth → prefers api_key."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-test")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["credentials"]["auth_method"] == "api_key"

    def test_oauth_config_stored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """OAuth init stores correct credentials in config.json."""
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-test")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp-test")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["credentials"]["auth_method"] == "oauth"
        assert data["credentials"]["anthropic_api_key_source"] == "none"
        assert data["credentials"]["oauth_token_source"] == "env"
        assert data["credentials"]["github_token_source"] == "env:GITHUB_TOKEN"

    def test_interactive_oauth_choice(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Interactive mode: user chooses OAuth (option 2)."""
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-test")
        _mock_subprocess_for_init(monkeypatch)
        # Input: "2" for OAuth auth method
        result = cli_runner.invoke(app, ["init"], input="2\n")
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["credentials"]["auth_method"] == "oauth"

    def test_interactive_api_key_choice(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Interactive mode: user chooses API key (option 1)."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        _mock_subprocess_for_init(monkeypatch)
        # Input: "1" for API key auth method
        result = cli_runner.invoke(app, ["init"], input="1\n")
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["credentials"]["auth_method"] == "api_key"

    def test_interactive_oauth_prompt_for_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Interactive mode: OAuth chosen but no token → prompts and saves to .env."""
        _mock_subprocess_for_init(monkeypatch)
        # Input: "2" for OAuth, then token value
        result = cli_runner.invoke(app, ["init"], input="2\nsk-ant-oat01-pasted\n")
        assert result.exit_code == 0
        env_content = (tmp_path / ".env").read_text()
        assert "CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-pasted" in env_content
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["credentials"]["auth_method"] == "oauth"


# ═══════════════════════════════════════════════════════════════════════
# Group: Codex Credential Discovery (T072)
# ═══════════════════════════════════════════════════════════════════════


class TestDiscoverCodexKey:
    def test_found_in_codex_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CODEX_API_KEY", "sk-codex-test")
        source, found = discover_codex_key(tmp_path)
        assert found is True
        assert source == "env"

    def test_openai_api_key_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CODEX_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        source, found = discover_codex_key(tmp_path)
        assert found is True
        assert source == "env:OPENAI_API_KEY"

    def test_codex_key_takes_precedence_over_openai(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODEX_API_KEY", "sk-codex")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        source, found = discover_codex_key(tmp_path)
        assert found is True
        assert source == "env"

    def test_found_in_dotenv_codex_key(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("CODEX_API_KEY=sk-codex-from-dotenv\n")
        source, found = discover_codex_key(tmp_path)
        assert found is True
        assert source == ".env"

    def test_found_in_dotenv_openai_key(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-openai-from-dotenv\n")
        source, found = discover_codex_key(tmp_path)
        assert found is True
        assert source == ".env:OPENAI_API_KEY"

    def test_not_found_returns_none(self, tmp_path: Path) -> None:
        source, found = discover_codex_key(tmp_path)
        assert found is False
        assert source == "none"

    def test_dotenv_codex_takes_precedence_over_openai_in_file(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("CODEX_API_KEY=sk-codex\nOPENAI_API_KEY=sk-openai\n")
        source, found = discover_codex_key(tmp_path)
        assert found is True
        assert source == ".env"

    def test_env_var_takes_precedence_over_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODEX_API_KEY", "sk-env")
        (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-dotenv\n")
        source, found = discover_codex_key(tmp_path)
        assert found is True
        assert source == "env"

    def test_empty_value_in_dotenv_not_found(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("CODEX_API_KEY=\n")
        source, found = discover_codex_key(tmp_path)
        assert found is False
        assert source == "none"


class TestInitYesModeCodexAutoDetect:
    """Test --yes mode auto-detects Codex credentials (T065)."""

    def test_yes_detects_codex_api_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_subprocess_for_init(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("CODEX_API_KEY", "sk-codex-test")
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["credentials"]["codex_api_key_source"] == "env"

    def test_yes_detects_openai_api_key_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_subprocess_for_init(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["credentials"]["codex_api_key_source"] == "env:OPENAI_API_KEY"

    def test_yes_sets_codex_source_none_when_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_subprocess_for_init(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["credentials"]["codex_api_key_source"] == "none"

    def test_yes_stores_both_claude_and_codex_credentials(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_subprocess_for_init(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("CODEX_API_KEY", "sk-codex-test")
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["credentials"]["auth_method"] == "api_key"
        assert data["credentials"]["anthropic_api_key_source"] == "env"
        assert data["credentials"]["codex_api_key_source"] == "env"


# ═══════════════════════════════════════════════════════════════════════
# Group: Codex-Only Init Flow
# ═══════════════════════════════════════════════════════════════════════


class TestInitCodexOnly:
    """Tests for Codex-only auth path (option 3) in dkmv init."""

    # ── Issue 2: auth_method = "codex" ──

    def test_interactive_option3_sets_codex_auth_method(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Option 3 with existing key → auth_method='codex'."""
        monkeypatch.setenv("CODEX_API_KEY", "sk-codex-test")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init"], input="3\n")
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["credentials"]["auth_method"] == "codex"
        assert data["credentials"]["anthropic_api_key_source"] == "none"
        assert data["credentials"]["oauth_token_source"] == "none"
        assert data["credentials"]["codex_api_key_source"] == "env"

    def test_interactive_option3_no_anthropic_key_required(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Option 3 should NOT require ANTHROPIC_API_KEY."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("CODEX_API_KEY", "sk-codex-test")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init"], input="3\n")
        assert result.exit_code == 0

    # ── Issue 3: default_agent = "codex" ──

    def test_interactive_option3_sets_default_agent_codex(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Option 3 → defaults.agent = 'codex' in config.json."""
        monkeypatch.setenv("CODEX_API_KEY", "sk-codex-test")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init"], input="3\n")
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["defaults"]["agent"] == "codex"

    def test_interactive_option4_does_not_set_default_agent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Option 4 (both) → defaults.agent stays None."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("CODEX_API_KEY", "sk-codex-test")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init"], input="4\n")
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["defaults"]["agent"] is None

    def test_interactive_option1_does_not_set_default_agent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Option 1 (Claude API key) → defaults.agent stays None."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init"], input="1\n")
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["defaults"]["agent"] is None

    # ── Issue 1: Codex key prompt ──

    def test_interactive_option3_prompts_for_codex_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Option 3 with no key found → prompts and saves to .env."""
        monkeypatch.delenv("CODEX_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        _mock_subprocess_for_init(monkeypatch)
        # Input: "3" for auth method, then the API key value
        result = cli_runner.invoke(app, ["init"], input="3\nsk-codex-pasted\n")
        assert result.exit_code == 0
        env_content = (tmp_path / ".env").read_text()
        assert "CODEX_API_KEY=sk-codex-pasted" in env_content
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["credentials"]["codex_api_key_source"] == ".env"
        assert "saved to .env" in result.output

    def test_interactive_option4_prompts_for_codex_key_when_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Option 4 with Anthropic key but no Codex key → prompts for both."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.delenv("CODEX_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        _mock_subprocess_for_init(monkeypatch)
        # Input: "4" for auth method, then codex key
        result = cli_runner.invoke(app, ["init"], input="4\nsk-codex-pasted\n")
        assert result.exit_code == 0
        env_content = (tmp_path / ".env").read_text()
        assert "CODEX_API_KEY=sk-codex-pasted" in env_content

    # ── --yes mode: codex-only fallback ──

    def test_yes_codex_only_succeeds(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--yes with only CODEX_API_KEY → auth_method='codex', agent='codex'."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.setenv("CODEX_API_KEY", "sk-codex-test")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["credentials"]["auth_method"] == "codex"
        assert data["credentials"]["codex_api_key_source"] == "env"
        assert data["credentials"]["anthropic_api_key_source"] == "none"
        assert data["defaults"]["agent"] == "codex"

    def test_yes_openai_key_fallback_codex_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--yes with only OPENAI_API_KEY → codex auth method."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.delenv("CODEX_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["credentials"]["auth_method"] == "codex"
        assert data["credentials"]["codex_api_key_source"] == "env:OPENAI_API_KEY"

    def test_yes_no_credentials_at_all_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--yes with no credentials at all → error with expanded message."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.delenv("CODEX_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 1
        assert "No authentication found" in result.output

    def test_yes_prefers_anthropic_over_codex(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--yes with both Anthropic and Codex → api_key, agent stays None."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("CODEX_API_KEY", "sk-codex-test")
        _mock_subprocess_for_init(monkeypatch)
        result = cli_runner.invoke(app, ["init", "--yes"])
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".dkmv" / "config.json").read_text())
        assert data["credentials"]["auth_method"] == "api_key"
        assert data["defaults"]["agent"] is None


# ═══════════════════════════════════════════════════════════════════════
# Group: load_config with codex auth_method
# ═══════════════════════════════════════════════════════════════════════


class TestLoadConfigCodexAuth:
    """Tests for load_config() with auth_method='codex'."""

    def test_codex_auth_succeeds_with_codex_api_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """auth_method='codex' with CODEX_API_KEY → no error."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("CODEX_API_KEY", "sk-codex-test")

        from dkmv.project import ProjectConfig

        project = ProjectConfig(project_name="test", repo="owner/repo")
        project.credentials.auth_method = "codex"

        with patch("dkmv.project.load_project_config", return_value=project):
            config = load_config()

        assert config.auth_method == "codex"
        assert config.codex_api_key == "sk-codex-test"

    def test_codex_auth_succeeds_with_openai_api_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """auth_method='codex' with OPENAI_API_KEY fallback → no error."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CODEX_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")

        from dkmv.project import ProjectConfig

        project = ProjectConfig(project_name="test", repo="owner/repo")
        project.credentials.auth_method = "codex"

        with patch("dkmv.project.load_project_config", return_value=project):
            config = load_config()

        assert config.auth_method == "codex"
        assert config.codex_api_key == "sk-openai-test"

    def test_codex_auth_fails_without_any_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """auth_method='codex' without CODEX_API_KEY or OPENAI_API_KEY → exit."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CODEX_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        from dkmv.project import ProjectConfig

        project = ProjectConfig(project_name="test", repo="owner/repo")
        project.credentials.auth_method = "codex"

        with (
            patch("dkmv.project.load_project_config", return_value=project),
            pytest.raises(click.exceptions.Exit),
        ):
            load_config()

    def test_codex_auth_does_not_require_anthropic_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """auth_method='codex' should not require ANTHROPIC_API_KEY."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("CODEX_API_KEY", "sk-codex-test")

        from dkmv.project import ProjectConfig

        project = ProjectConfig(project_name="test", repo="owner/repo")
        project.credentials.auth_method = "codex"

        with patch("dkmv.project.load_project_config", return_value=project):
            config = load_config()

        assert config.anthropic_api_key == ""
        assert config.codex_api_key == "sk-codex-test"

    def test_codex_auth_sets_default_agent_from_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """auth_method='codex' with defaults.agent='codex' → config picks it up."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("CODEX_API_KEY", "sk-codex-test")

        from dkmv.project import ProjectConfig, ProjectDefaults

        project = ProjectConfig(
            project_name="test",
            repo="owner/repo",
            defaults=ProjectDefaults(agent="codex"),
        )
        project.credentials.auth_method = "codex"

        with patch("dkmv.project.load_project_config", return_value=project):
            config = load_config()

        assert config.default_agent == "codex"
