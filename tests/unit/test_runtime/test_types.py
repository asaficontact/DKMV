"""Tests for dkmv.runtime._types."""

from __future__ import annotations

from pathlib import Path

import pytest

from dkmv.config import DKMVConfig
from dkmv.runtime._types import (
    ExecutionSource,
    ExecutionSourceType,
    RetentionPolicy,
    RuntimeConfig,
)


class TestExecutionSourceType:
    def test_remote_value(self) -> None:
        assert ExecutionSourceType.REMOTE == "remote"

    def test_local_snapshot_value(self) -> None:
        assert ExecutionSourceType.LOCAL_SNAPSHOT == "local_snapshot"


class TestExecutionSource:
    def test_remote_source(self) -> None:
        src = ExecutionSource(
            type=ExecutionSourceType.REMOTE,
            repo="https://github.com/org/repo",
            branch="main",
        )
        assert src.repo == "https://github.com/org/repo"
        assert src.branch == "main"
        assert src.local_path is None

    def test_local_snapshot_source(self) -> None:
        src = ExecutionSource(
            type=ExecutionSourceType.LOCAL_SNAPSHOT,
            local_path=Path("/tmp/workspace"),
            include_uncommitted=False,
        )
        assert src.local_path == Path("/tmp/workspace")
        assert src.include_uncommitted is False

    def test_defaults(self) -> None:
        src = ExecutionSource(type=ExecutionSourceType.REMOTE)
        assert src.repo is None
        assert src.branch is None
        assert src.include_uncommitted is True


class TestRuntimeConfig:
    def test_defaults(self) -> None:
        cfg = RuntimeConfig()
        assert cfg.anthropic_api_key == ""
        assert cfg.default_model == "claude-sonnet-4-6"
        assert cfg.default_max_turns == 100
        assert cfg.image_name == "dkmv-sandbox:latest"
        assert cfg.timeout_minutes == 30
        assert cfg.memory_limit == "8g"
        assert cfg.max_budget_usd is None
        assert cfg.default_agent == "claude"

    def test_custom_values(self) -> None:
        cfg = RuntimeConfig(
            anthropic_api_key="sk-test",
            default_model="claude-opus-4-6",
            default_max_turns=50,
            max_budget_usd=10.0,
        )
        assert cfg.anthropic_api_key == "sk-test"
        assert cfg.default_model == "claude-opus-4-6"
        assert cfg.default_max_turns == 50
        assert cfg.max_budget_usd == 10.0

    def test_to_dkmv_config(self) -> None:
        cfg = RuntimeConfig(
            anthropic_api_key="sk-test",
            github_token="gh-token",
            default_model="claude-opus-4-6",
            max_budget_usd=5.0,
            default_agent="codex",
        )
        dkmv_cfg = cfg.to_dkmv_config()
        assert isinstance(dkmv_cfg, DKMVConfig)
        assert dkmv_cfg.anthropic_api_key == "sk-test"
        assert dkmv_cfg.github_token == "gh-token"
        assert dkmv_cfg.default_model == "claude-opus-4-6"
        assert dkmv_cfg.max_budget_usd == 5.0
        assert dkmv_cfg.default_agent == "codex"

    def test_to_dkmv_config_bypasses_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """model_construct should not read env vars or .env files."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
        cfg = RuntimeConfig(anthropic_api_key="explicit-key")
        dkmv_cfg = cfg.to_dkmv_config()
        assert dkmv_cfg.anthropic_api_key == "explicit-key"


class TestRetentionPolicy:
    def test_destroy(self) -> None:
        assert RetentionPolicy.DESTROY == "destroy"

    def test_retain_ttl(self) -> None:
        assert RetentionPolicy.RETAIN_TTL == "retain_ttl"

    def test_retain_manual(self) -> None:
        assert RetentionPolicy.RETAIN_MANUAL == "retain_manual"
