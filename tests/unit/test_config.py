from pathlib import Path
from unittest.mock import patch

import click
import pytest

from dkmv.config import DKMVConfig, load_config


@pytest.fixture(autouse=True)
def _isolate_from_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent pydantic-settings from reading the project's .env file."""
    monkeypatch.chdir(tmp_path)


class TestDKMVConfig:
    def test_loads_from_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-123")
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-test")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test456")
        monkeypatch.setenv("DKMV_MODEL", "claude-opus-4-20250514")
        monkeypatch.setenv("DKMV_MAX_TURNS", "50")
        monkeypatch.setenv("DKMV_IMAGE", "custom:v2")
        monkeypatch.setenv("DKMV_OUTPUT_DIR", "/tmp/out")
        monkeypatch.setenv("DKMV_TIMEOUT", "60")
        monkeypatch.setenv("DKMV_MEMORY", "16g")
        monkeypatch.setenv("DKMV_MAX_BUDGET_USD", "10.5")

        config = DKMVConfig()

        assert config.anthropic_api_key == "sk-ant-test-123"
        assert config.claude_oauth_token == "sk-ant-oat01-test"
        assert config.github_token == "ghp_test456"
        assert config.default_model == "claude-opus-4-20250514"
        assert config.default_max_turns == 50
        assert config.image_name == "custom:v2"
        assert config.output_dir == Path("/tmp/out")
        assert config.timeout_minutes == 60
        assert config.memory_limit == "16g"
        assert config.max_budget_usd == 10.5

    def test_uses_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("DKMV_MODEL", raising=False)
        monkeypatch.delenv("DKMV_MAX_TURNS", raising=False)
        monkeypatch.delenv("DKMV_IMAGE", raising=False)
        monkeypatch.delenv("DKMV_OUTPUT_DIR", raising=False)
        monkeypatch.delenv("DKMV_TIMEOUT", raising=False)
        monkeypatch.delenv("DKMV_MEMORY", raising=False)
        monkeypatch.delenv("DKMV_MAX_BUDGET_USD", raising=False)

        config = DKMVConfig()

        assert config.anthropic_api_key == ""
        assert config.claude_oauth_token == ""
        assert config.github_token == ""
        assert config.default_model == "claude-sonnet-4-6"
        assert config.default_max_turns == 100
        assert config.image_name == "dkmv-sandbox:latest"
        assert config.output_dir == Path("./outputs")
        assert config.timeout_minutes == 30
        assert config.memory_limit == "8g"
        assert config.max_budget_usd is None

    def test_github_token_defaults_to_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        config = DKMVConfig()
        assert config.github_token == ""

    def test_max_budget_usd_optional(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DKMV_MAX_BUDGET_USD", raising=False)
        config = DKMVConfig()
        assert config.max_budget_usd is None

    def test_output_dir_is_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DKMV_OUTPUT_DIR", "/custom/path")
        config = DKMVConfig()
        assert isinstance(config.output_dir, Path)
        assert config.output_dir == Path("/custom/path")


class TestLoadConfig:
    def test_loads_successfully(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-123")
        config = load_config()
        assert config.anthropic_api_key == "sk-ant-test-123"

    def test_exits_when_api_key_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(click.exceptions.Exit):
            load_config()

    def test_succeeds_without_api_key_when_not_required(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        config = load_config(require_api_key=False)
        assert config.anthropic_api_key == ""


class TestGitHubTokenFallback:
    def test_gh_token_env_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GH_TOKEN set, GITHUB_TOKEN not set → token populated."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GH_TOKEN", "ghp_from_gh_token")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        config = load_config()
        assert config.github_token == "ghp_from_gh_token"

    def test_gh_auth_token_cli_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """gh auth token CLI source in project config → subprocess called → token populated."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

        from dkmv.project import ProjectConfig

        project = ProjectConfig(project_name="test", repo="owner/repo")
        project.credentials.github_token_source = "gh auth token"

        with (
            patch("dkmv.project.load_project_config", return_value=project),
            patch("dkmv.config._fetch_gh_auth_token", return_value="ghp_from_cli"),
        ):
            config = load_config()

        assert config.github_token == "ghp_from_cli"

    def test_no_fallback_when_github_token_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GITHUB_TOKEN already set → GH_TOKEN and subprocess not consulted."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_primary")
        monkeypatch.setenv("GH_TOKEN", "ghp_should_not_use")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        config = load_config()
        assert config.github_token == "ghp_primary"

    def test_gh_auth_token_failure_graceful(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """subprocess fails → token stays empty, no crash."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

        from dkmv.project import ProjectConfig

        project = ProjectConfig(project_name="test", repo="owner/repo")
        project.credentials.github_token_source = "gh auth token"

        with (
            patch("dkmv.project.load_project_config", return_value=project),
            patch("dkmv.config._fetch_gh_auth_token", return_value=""),
        ):
            config = load_config()

        assert config.github_token == ""


class TestOAuthAuthentication:
    def test_oauth_token_loaded_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLAUDE_CODE_OAUTH_TOKEN env var is loaded into config."""
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-test")
        config = DKMVConfig()
        assert config.claude_oauth_token == "sk-ant-oat01-test"

    def test_oauth_token_defaults_to_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        config = DKMVConfig()
        assert config.claude_oauth_token == ""

    def test_oauth_auth_method_succeeds_with_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OAuth auth method with valid token should not require API key."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-test")

        from dkmv.project import ProjectConfig

        project = ProjectConfig(project_name="test", repo="owner/repo")
        project.credentials.auth_method = "oauth"

        with patch("dkmv.project.load_project_config", return_value=project):
            config = load_config()

        assert config.claude_oauth_token == "sk-ant-oat01-test"
        assert config.anthropic_api_key == ""

    def test_oauth_auth_method_fails_without_token_or_creds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OAuth without token, no Keychain, no creds file → exit."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

        from dkmv.project import ProjectConfig

        project = ProjectConfig(project_name="test", repo="owner/repo")
        project.credentials.auth_method = "oauth"

        with (
            patch("dkmv.project.load_project_config", return_value=project),
            patch("dkmv.config._fetch_oauth_credentials", return_value=""),
            patch("dkmv.config.Path.home", return_value=tmp_path),
            pytest.raises(click.exceptions.Exit),
        ):
            load_config()

    def test_oauth_auth_method_succeeds_with_keychain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OAuth without token but with Keychain credentials → no exit."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

        from dkmv.project import ProjectConfig

        project = ProjectConfig(project_name="test", repo="owner/repo")
        project.credentials.auth_method = "oauth"

        with (
            patch("dkmv.project.load_project_config", return_value=project),
            patch(
                "dkmv.config._fetch_oauth_credentials",
                return_value='{"claudeAiOauth":{}}',
            ),
        ):
            config = load_config()

        assert config.auth_method == "oauth"
        assert config.claude_oauth_token == ""

    def test_oauth_auth_method_succeeds_with_credentials_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OAuth without token, no Keychain, but Linux creds file → no exit."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

        from dkmv.project import ProjectConfig

        project = ProjectConfig(project_name="test", repo="owner/repo")
        project.credentials.auth_method = "oauth"

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / ".credentials.json").write_text("{}")

        with (
            patch("dkmv.project.load_project_config", return_value=project),
            patch("dkmv.config._fetch_oauth_credentials", return_value=""),
            patch("dkmv.config.Path.home", return_value=tmp_path),
        ):
            config = load_config()

        assert config.auth_method == "oauth"
        assert config.claude_oauth_token == ""

    def test_api_key_auth_method_ignores_oauth_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """API key auth method still requires ANTHROPIC_API_KEY even if OAuth token is set."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-test")

        with pytest.raises(click.exceptions.Exit):
            load_config()

    def test_no_project_config_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without project config, default auth_method is api_key."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-test")

        with pytest.raises(click.exceptions.Exit):
            load_config()
