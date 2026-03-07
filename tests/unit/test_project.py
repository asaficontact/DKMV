from __future__ import annotations

import json
from pathlib import Path

import click
import pytest
from pydantic import ValidationError

from dkmv.config import load_config
from dkmv.project import (
    CredentialSources,
    ProjectConfig,
    ProjectDefaults,
    SandboxSettings,
    find_project_root,
    get_repo,
    load_project_config,
)

# ── Env vars to clear for isolation ──────────────────────────────────────
_ENV_VARS = [
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
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


# ── Helpers ──────────────────────────────────────────────────────────────
def _write_config(root: Path, **overrides: object) -> Path:
    """Write a .dkmv/config.json at *root* and return the config path."""
    data: dict[str, object] = {
        "version": 1,
        "project_name": "test-project",
        "repo": "https://github.com/org/repo",
    }
    data.update(overrides)
    dkmv_dir = root / ".dkmv"
    dkmv_dir.mkdir(parents=True, exist_ok=True)
    config_path = dkmv_dir / "config.json"
    config_path.write_text(json.dumps(data))
    return config_path


# ═══════════════════════════════════════════════════════════════════════
# Group 1: ProjectConfig Model Validation
# ═══════════════════════════════════════════════════════════════════════
class TestProjectConfigModel:
    def test_valid_config_all_fields(self) -> None:
        cfg = ProjectConfig(
            version=1,
            project_name="my-app",
            repo="https://github.com/org/repo",
            default_branch="develop",
            credentials=CredentialSources(
                anthropic_api_key_source="env",
                github_token_source="env",
            ),
            defaults=ProjectDefaults(
                model="claude-opus-4-20250514",
                max_turns=50,
                timeout_minutes=60,
                max_budget_usd=10.5,
                memory="16g",
            ),
            sandbox=SandboxSettings(image="custom:v2"),
        )
        assert cfg.project_name == "my-app"
        assert cfg.repo == "https://github.com/org/repo"
        assert cfg.default_branch == "develop"
        assert cfg.defaults.model == "claude-opus-4-20250514"
        assert cfg.sandbox.image == "custom:v2"

    def test_sandbox_settings_docker_socket_default_false(self) -> None:
        cfg = ProjectConfig(project_name="test", repo="https://github.com/o/r")
        assert cfg.sandbox.docker_socket is False

    def test_sandbox_settings_docker_socket_true(self) -> None:
        cfg = ProjectConfig(
            project_name="test",
            repo="https://github.com/o/r",
            sandbox=SandboxSettings(docker_socket=True),
        )
        assert cfg.sandbox.docker_socket is True

    def test_valid_config_minimal(self) -> None:
        cfg = ProjectConfig(project_name="test", repo="https://github.com/o/r")
        assert cfg.version == 1
        assert cfg.project_name == "test"
        assert cfg.repo == "https://github.com/o/r"

    def test_version_validation_rejects_v2(self) -> None:
        with pytest.raises(ValidationError, match="Unsupported config version 2"):
            ProjectConfig(version=2, project_name="x", repo="r")

    def test_version_validation_rejects_v0(self) -> None:
        with pytest.raises(ValidationError, match="Unsupported config version 0"):
            ProjectConfig(version=0, project_name="x", repo="r")

    def test_round_trip_json(self) -> None:
        original = ProjectConfig(
            project_name="rt",
            repo="https://github.com/org/repo",
            defaults=ProjectDefaults(model="claude-opus-4-20250514", max_turns=42),
        )
        roundtripped = ProjectConfig.model_validate_json(original.model_dump_json())
        assert roundtripped == original

    def test_default_branch_defaults_to_main(self) -> None:
        cfg = ProjectConfig(project_name="t", repo="r")
        assert cfg.default_branch == "main"

    def test_credential_sources_default_to_env(self) -> None:
        cfg = ProjectConfig(project_name="t", repo="r")
        assert cfg.credentials.anthropic_api_key_source == "env"

    def test_auth_method_defaults_to_api_key(self) -> None:
        cfg = ProjectConfig(project_name="t", repo="r")
        assert cfg.credentials.auth_method == "api_key"

    def test_auth_method_oauth(self) -> None:
        cfg = ProjectConfig(
            project_name="t",
            repo="r",
            credentials=CredentialSources(auth_method="oauth"),
        )
        assert cfg.credentials.auth_method == "oauth"

    def test_auth_method_backward_compat(self) -> None:
        """Config JSON without auth_method/oauth_token_source should use defaults."""
        data = {
            "version": 1,
            "project_name": "t",
            "repo": "r",
            "credentials": {
                "anthropic_api_key_source": "env",
                "github_token_source": "env",
            },
        }
        cfg = ProjectConfig.model_validate(data)
        assert cfg.credentials.auth_method == "api_key"
        assert cfg.credentials.oauth_token_source == "none"
        assert cfg.credentials.github_token_source == "env"

    def test_auth_method_invalid_rejected(self) -> None:
        """Invalid auth_method value should be rejected by pydantic validation."""
        with pytest.raises(ValidationError, match="auth_method"):
            CredentialSources(auth_method="oauthh")  # type: ignore[arg-type]

    def test_project_defaults_all_none(self) -> None:
        defaults = ProjectDefaults()
        assert defaults.model is None
        assert defaults.max_turns is None
        assert defaults.timeout_minutes is None
        assert defaults.max_budget_usd is None
        assert defaults.memory is None


# ═══════════════════════════════════════════════════════════════════════
# Group 2: find_project_root()
# ═══════════════════════════════════════════════════════════════════════
class TestFindProjectRoot:
    def test_returns_dir_with_dkmv_config(self, tmp_path: Path) -> None:
        _write_config(tmp_path)
        assert find_project_root() == tmp_path

    def test_walks_up_to_parent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_config(tmp_path)
        subdir = tmp_path / "src"
        subdir.mkdir()
        monkeypatch.chdir(subdir)
        assert find_project_root() == tmp_path

    def test_walks_up_to_grandparent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_config(tmp_path)
        deep = tmp_path / "src" / "lib"
        deep.mkdir(parents=True)
        monkeypatch.chdir(deep)
        assert find_project_root() == tmp_path

    def test_returns_cwd_when_no_dkmv(self, tmp_path: Path) -> None:
        assert find_project_root() == tmp_path

    def test_returns_cwd_when_dkmv_dir_exists_but_no_config_json(self, tmp_path: Path) -> None:
        (tmp_path / ".dkmv").mkdir()
        assert find_project_root() == tmp_path

    def test_deeply_nested_subdirectory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(tmp_path)
        deep = tmp_path / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        monkeypatch.chdir(deep)
        assert find_project_root() == tmp_path

    def test_idempotent(self, tmp_path: Path) -> None:
        _write_config(tmp_path)
        first = find_project_root()
        second = find_project_root()
        assert first == second

    def test_ignores_dkmv_without_config_json(self, tmp_path: Path) -> None:
        (tmp_path / ".dkmv").mkdir()
        (tmp_path / ".dkmv" / "components.json").write_text("{}")
        assert find_project_root() == tmp_path


# ═══════════════════════════════════════════════════════════════════════
# Group 3: load_project_config()
# ═══════════════════════════════════════════════════════════════════════
class TestLoadProjectConfig:
    def test_returns_none_when_no_dkmv(self, tmp_path: Path) -> None:
        assert load_project_config(tmp_path) is None

    def test_returns_config_when_valid(self, tmp_path: Path) -> None:
        _write_config(tmp_path, project_name="hello", repo="https://gh.com/o/r")
        cfg = load_project_config(tmp_path)
        assert cfg is not None
        assert cfg.project_name == "hello"
        assert cfg.repo == "https://gh.com/o/r"

    def test_raises_on_invalid_json(self, tmp_path: Path) -> None:
        dkmv_dir = tmp_path / ".dkmv"
        dkmv_dir.mkdir()
        (dkmv_dir / "config.json").write_text("{bad json")
        with pytest.raises(ValidationError):
            load_project_config(tmp_path)

    def test_raises_on_missing_required_fields(self, tmp_path: Path) -> None:
        dkmv_dir = tmp_path / ".dkmv"
        dkmv_dir.mkdir()
        (dkmv_dir / "config.json").write_text('{"version": 1}')
        with pytest.raises(ValidationError):
            load_project_config(tmp_path)

    def test_accepts_explicit_project_root(self, tmp_path: Path) -> None:
        _write_config(tmp_path)
        cfg = load_project_config(project_root=tmp_path)
        assert cfg is not None
        assert cfg.project_name == "test-project"


# ═══════════════════════════════════════════════════════════════════════
# Group 4: Config Cascade (load_config with project config)
# ═══════════════════════════════════════════════════════════════════════
class TestConfigCascade:
    def test_no_project_config_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        config = load_config()
        assert config.default_model == "claude-sonnet-4-6"
        assert config.default_max_turns == 100
        assert config.output_dir == Path("./outputs")

    def test_project_defaults_applied(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(
            tmp_path,
            defaults={
                "model": "claude-opus-4-20250514",
                "max_turns": 50,
                "timeout_minutes": 60,
                "max_budget_usd": 5.0,
                "memory": "16g",
            },
            sandbox={"image": "custom:v3"},
        )
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        config = load_config()
        assert config.default_model == "claude-opus-4-20250514"
        assert config.default_max_turns == 50
        assert config.timeout_minutes == 60
        assert config.max_budget_usd == 5.0
        assert config.memory_limit == "16g"
        assert config.image_name == "custom:v3"

    def test_env_var_overrides_project_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(
            tmp_path,
            defaults={"model": "claude-opus-4-20250514", "max_turns": 50},
        )
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DKMV_MODEL", "claude-haiku-4-5-20251001")
        monkeypatch.setenv("DKMV_MAX_TURNS", "200")
        config = load_config()
        assert config.default_model == "claude-haiku-4-5-20251001"
        assert config.default_max_turns == 200

    def test_env_var_same_as_default_not_overridden(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When DKMV_MODEL is explicitly set to the built-in default value,
        project config must NOT override it (model_fields_set tracks this)."""
        _write_config(tmp_path, defaults={"model": "claude-opus-4-20250514"})
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DKMV_MODEL", "claude-sonnet-4-6")  # same as built-in
        config = load_config()
        assert config.default_model == "claude-sonnet-4-6"

    def test_output_dir_relocated_to_dkmv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(tmp_path)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        config = load_config()
        assert config.output_dir == tmp_path / ".dkmv"

    def test_output_dir_not_relocated_when_env_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(tmp_path)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DKMV_OUTPUT_DIR", "/custom/output")
        config = load_config()
        assert config.output_dir == Path("/custom/output")

    def test_project_config_all_null_no_change(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(tmp_path, defaults={})
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        config = load_config()
        assert config.default_model == "claude-sonnet-4-6"
        assert config.default_max_turns == 100
        assert config.timeout_minutes == 30
        assert config.max_budget_usd is None
        assert config.memory_limit == "8g"
        assert config.image_name == "dkmv-sandbox:latest"

    def test_each_field_applied_individually(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each project default field applies independently."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        # Only model set
        _write_config(tmp_path, defaults={"model": "claude-opus-4-20250514"})
        config = load_config()
        assert config.default_model == "claude-opus-4-20250514"
        assert config.default_max_turns == 100  # untouched

    def test_env_file_from_subdirectory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When CWD is a subdirectory, .env should be found at project root."""
        _write_config(tmp_path)
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-from-env-file\n")
        subdir = tmp_path / "src" / "lib"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)
        config = load_config()
        assert config.anthropic_api_key == "sk-from-env-file"

    def test_env_file_fallback_when_no_dkmv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without .dkmv/, .env resolution falls back to CWD (current behavior)."""
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-cwd-env\n")
        config = load_config()
        assert config.anthropic_api_key == "sk-cwd-env"


# ═══════════════════════════════════════════════════════════════════════
# Group 5: get_repo()
# ═══════════════════════════════════════════════════════════════════════
class TestGetRepo:
    def test_cli_arg_takes_precedence(self, tmp_path: Path) -> None:
        _write_config(tmp_path, repo="https://github.com/org/project-repo")
        result = get_repo("https://github.com/org/other")
        assert result == "https://github.com/org/other"

    def test_project_config_fallback(self, tmp_path: Path) -> None:
        _write_config(tmp_path, repo="https://github.com/org/fallback")
        result = get_repo(None)
        assert result == "https://github.com/org/fallback"

    def test_error_when_neither_available(self) -> None:
        with pytest.raises(click.exceptions.Exit):
            get_repo(None)

    def test_error_message_suggests_init(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(click.exceptions.Exit):
            get_repo(None)
        captured = capsys.readouterr()
        assert "dkmv init" in captured.err


# ═══════════════════════════════════════════════════════════════════════
# Group 6: Subdirectory .env Resolution
# ═══════════════════════════════════════════════════════════════════════
class TestSubdirectoryEnvResolution:
    def test_credentials_loaded_from_project_root_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(tmp_path)
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-root\nGITHUB_TOKEN=ghp-root\n")
        subdir = tmp_path / "src" / "lib"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)
        config = load_config()
        assert config.anthropic_api_key == "sk-root"
        assert config.github_token == "ghp-root"

    def test_fallback_to_cwd_env_when_no_dkmv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-local\n")
        config = load_config()
        assert config.anthropic_api_key == "sk-local"

    def test_subdirectory_with_own_env_uses_project_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When both project root and subdir have .env, project root wins."""
        _write_config(tmp_path)
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-root-wins\n")
        subdir = tmp_path / "src"
        subdir.mkdir()
        (subdir / ".env").write_text("ANTHROPIC_API_KEY=sk-subdir\n")
        monkeypatch.chdir(subdir)
        config = load_config()
        assert config.anthropic_api_key == "sk-root-wins"
