"""Unit tests for the consolidated PRD §8.8 settings surface (AC-0.1-4)."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.config import Settings, get_settings
from pydantic import SecretStr, ValidationError

# The full §8.8 env surface that the typed settings object must expose.
EXPECTED_KEYS = {
    "DKMV_PLATFORM_TOKEN",
    "DKMV_PLATFORM_BIND",
    "DATABASE_URL",
    "OUTPUT_DIR",
    "GITHUB_TOKEN",
    "ANTHROPIC_API_KEY",
    "CODEX_API_KEY",
    "DKMV_IMAGE",
    "MAX_CONCURRENT_RUNS",
    "HOST_MEMORY_BUDGET",
    "DAILY_SPEND_CAP",
    "TICK_INTERVAL_S",
    "STALL_TIMEOUT_S",
    "PAUSE_TIMEOUT_S",
    "SANDBOX_RUNTIME",
    "EGRESS_ALLOWLIST",
}


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Ensure each test parses settings fresh, not the lru-cached instance."""
    get_settings.cache_clear()


def _settings(**env: str) -> Settings:
    """Build a Settings instance ignoring any ambient .env / process env."""
    # _env_file=None disables reading a stray .env; we pass values explicitly.
    return Settings(_env_file=None, **env)  # type: ignore[call-arg]  # DKMVP-ESCAPE: pydantic-settings injected kwarg not in the model signature


def test_exposes_full_8_8_env_surface() -> None:
    """Every key in the consolidated §8.8 table is a settings field."""
    assert EXPECTED_KEYS.issubset(set(Settings.model_fields))


def test_default_bind_is_loopback_8787() -> None:
    """INV-1: default bind is 127.0.0.1:8787 (loopback only)."""
    s = _settings()
    assert s.DKMV_PLATFORM_BIND == "127.0.0.1:8787"
    assert s.bind_host == "127.0.0.1"
    assert s.bind_port == 8787


def test_default_sandbox_runtime_is_runsc() -> None:
    """INV-3: default sandbox runtime is gVisor 'runsc'."""
    assert _settings().SANDBOX_RUNTIME == "runsc"


def test_default_image_and_db_and_concurrency() -> None:
    s = _settings()
    assert s.DKMV_IMAGE == "dkmv-sandbox:latest"
    assert s.DATABASE_URL == "sqlite:///./data/dkmv.db"
    assert s.MAX_CONCURRENT_RUNS == 3
    assert s.TICK_INTERVAL_S == 10
    assert s.STALL_TIMEOUT_S == 300
    assert s.PAUSE_TIMEOUT_S == 3600


def test_secrets_are_secretstr() -> None:
    """Credentials are SecretStr so they never print/log their value."""
    s = _settings(
        DKMV_PLATFORM_TOKEN="tok",
        GITHUB_TOKEN="ghp_x",
        ANTHROPIC_API_KEY="sk-ant-x",
        CODEX_API_KEY="codex-x",
    )
    for value in (
        s.DKMV_PLATFORM_TOKEN,
        s.GITHUB_TOKEN,
        s.ANTHROPIC_API_KEY,
        s.CODEX_API_KEY,
    ):
        assert isinstance(value, SecretStr)
    # repr/str must not leak the underlying secret.
    assert "ghp_x" not in repr(s)
    assert s.GITHUB_TOKEN.get_secret_value() == "ghp_x"


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings read the env keys verbatim (no alias indirection)."""
    monkeypatch.setenv("DKMV_PLATFORM_BIND", "127.0.0.1:9000")
    monkeypatch.setenv("SANDBOX_RUNTIME", "runc")
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "8")
    s = Settings(_env_file=None)  # type: ignore[call-arg]  # DKMVP-ESCAPE: pydantic-settings injected kwarg
    assert s.bind_port == 9000
    assert s.SANDBOX_RUNTIME == "runc"
    assert s.MAX_CONCURRENT_RUNS == 8


def test_output_dir_is_path() -> None:
    assert isinstance(_settings().OUTPUT_DIR, Path)
    assert _settings(OUTPUT_DIR="/srv/runs").OUTPUT_DIR == Path("/srv/runs")


def test_egress_allowlist_defaults_to_github_and_model_apis() -> None:
    """INV-3: default egress allowlist is GitHub + model APIs only."""
    hosts = _settings().egress_hosts
    assert "api.github.com" in hosts
    assert "api.anthropic.com" in hosts
    assert "api.openai.com" in hosts


def test_egress_allowlist_parsing_dedupes_and_strips() -> None:
    s = _settings(EGRESS_ALLOWLIST=" a.com , b.com, a.com ,")
    assert s.egress_hosts == ["a.com", "b.com"]


def test_invalid_bind_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(DKMV_PLATFORM_BIND="not-a-bind")
    with pytest.raises(ValidationError):
        _settings(DKMV_PLATFORM_BIND="127.0.0.1:notaport")


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
