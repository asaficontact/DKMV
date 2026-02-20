from pathlib import Path

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
