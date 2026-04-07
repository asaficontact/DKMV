"""Tests for dkmv.runtime._capability."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


from dkmv.runtime._capability import (
    CapabilityReport,
    PreflightResult,
    get_capabilities,
    preflight_check,
)
from dkmv.runtime._types import ExecutionSource, ExecutionSourceType, RuntimeConfig


class TestCapabilityReport:
    def test_defaults(self) -> None:
        report = CapabilityReport()
        assert report.embedded_runtime is True
        assert report.event_observer is True
        assert report.pause_callback is True
        assert report.stop_cancel is True
        assert report.introspection is True
        assert report.replay_history is True
        assert report.retention is True
        assert report.telemetry is True
        assert report.docker_available is False
        assert report.docker_version == ""
        assert report.image_exists is False


class TestPreflightResult:
    def test_ready(self) -> None:
        result = PreflightResult(ready=True)
        assert result.ready is True
        assert result.blockers == []
        assert result.warnings == []

    def test_not_ready(self) -> None:
        result = PreflightResult(ready=False, blockers=["no docker"])
        assert result.ready is False
        assert "no docker" in result.blockers


class TestGetCapabilities:
    @patch("dkmv.runtime._capability._check_docker_version", return_value=(True, "24.0.5"))
    @patch("dkmv.runtime._capability._check_image_exists", return_value=True)
    def test_with_docker(self, mock_image: object, mock_docker: object) -> None:
        cfg = RuntimeConfig(anthropic_api_key="sk-test", github_token="gh-tok")
        report = get_capabilities(cfg)
        assert report.docker_available is True
        assert report.docker_version == "24.0.5"
        assert report.image_exists is True
        assert report.has_anthropic_key is True
        assert report.has_github_token is True
        assert "claude" in report.available_agents
        assert "codex" in report.available_agents

    @patch("dkmv.runtime._capability._check_docker_version", return_value=(False, ""))
    def test_without_docker(self, mock_docker: object) -> None:
        report = get_capabilities(RuntimeConfig())
        assert report.docker_available is False
        assert report.docker_version == ""
        assert report.image_exists is False

    @patch("dkmv.runtime._capability._check_docker_version", return_value=(False, ""))
    def test_version_present(self, mock_docker: object) -> None:
        report = get_capabilities()
        assert report.version != ""

    @patch("dkmv.runtime._capability._check_docker_version", return_value=(False, ""))
    def test_no_keys(self, mock_docker: object) -> None:
        report = get_capabilities(RuntimeConfig())
        assert report.has_anthropic_key is False
        assert report.has_github_token is False
        assert report.has_codex_key is False


class TestPreflightCheck:
    @patch("dkmv.runtime._capability._check_docker_version", return_value=(True, "24.0.5"))
    @patch("dkmv.runtime._capability._check_image_exists", return_value=True)
    def test_ready(self, mock_image: object, mock_docker: object) -> None:
        cfg = RuntimeConfig(anthropic_api_key="sk-test")
        source = ExecutionSource(
            type=ExecutionSourceType.REMOTE,
            repo="https://github.com/org/repo",
        )
        result = preflight_check(cfg, "dev", source)
        assert result.ready is True

    @patch("dkmv.runtime._capability._check_docker_version", return_value=(False, ""))
    def test_no_docker(self, mock_docker: object) -> None:
        cfg = RuntimeConfig(anthropic_api_key="sk-test")
        source = ExecutionSource(
            type=ExecutionSourceType.REMOTE,
            repo="https://github.com/org/repo",
        )
        result = preflight_check(cfg, "dev", source)
        assert result.ready is False
        assert any("Docker" in b for b in result.blockers)

    @patch("dkmv.runtime._capability._check_docker_version", return_value=(True, "24.0.5"))
    @patch("dkmv.runtime._capability._check_image_exists", return_value=True)
    def test_no_api_key(self, mock_image: object, mock_docker: object) -> None:
        cfg = RuntimeConfig()  # no keys
        source = ExecutionSource(
            type=ExecutionSourceType.REMOTE,
            repo="https://github.com/org/repo",
        )
        result = preflight_check(cfg, "dev", source)
        assert result.ready is False
        assert any("API_KEY" in b or "OAuth" in b for b in result.blockers)

    @patch("dkmv.runtime._capability._check_docker_version", return_value=(True, "24.0.5"))
    @patch("dkmv.runtime._capability._check_image_exists", return_value=True)
    def test_remote_no_repo(self, mock_image: object, mock_docker: object) -> None:
        cfg = RuntimeConfig(anthropic_api_key="sk-test")
        source = ExecutionSource(type=ExecutionSourceType.REMOTE)
        result = preflight_check(cfg, "dev", source)
        assert result.ready is False
        assert any("repo" in b.lower() for b in result.blockers)

    @patch("dkmv.runtime._capability._check_docker_version", return_value=(True, "24.0.5"))
    @patch("dkmv.runtime._capability._check_image_exists", return_value=True)
    def test_local_path_missing(self, mock_image: object, mock_docker: object) -> None:
        cfg = RuntimeConfig(anthropic_api_key="sk-test")
        source = ExecutionSource(
            type=ExecutionSourceType.LOCAL_SNAPSHOT,
            local_path=Path("/nonexistent/path"),
        )
        result = preflight_check(cfg, "dev", source)
        assert result.ready is False
        assert any("does not exist" in b for b in result.blockers)

    @patch("dkmv.runtime._capability._check_docker_version", return_value=(True, "24.0.5"))
    @patch("dkmv.runtime._capability._check_image_exists", return_value=False)
    def test_image_missing_warning(self, mock_image: object, mock_docker: object) -> None:
        cfg = RuntimeConfig(anthropic_api_key="sk-test")
        source = ExecutionSource(
            type=ExecutionSourceType.REMOTE,
            repo="https://github.com/org/repo",
        )
        result = preflight_check(cfg, "dev", source)
        assert result.ready is True  # warning, not blocker
        assert any("image" in w.lower() for w in result.warnings)

    @patch("dkmv.runtime._capability._check_docker_version", return_value=(True, "24.0.5"))
    @patch("dkmv.runtime._capability._check_image_exists", return_value=True)
    def test_no_github_token_warning(self, mock_image: object, mock_docker: object) -> None:
        cfg = RuntimeConfig(anthropic_api_key="sk-test")
        source = ExecutionSource(
            type=ExecutionSourceType.REMOTE,
            repo="https://github.com/org/repo",
        )
        result = preflight_check(cfg, "dev", source)
        assert any("GitHub" in w for w in result.warnings)

    @patch("dkmv.runtime._capability._check_docker_version", return_value=(True, "24.0.5"))
    @patch("dkmv.runtime._capability._check_image_exists", return_value=True)
    def test_invalid_component(self, mock_image: object, mock_docker: object) -> None:
        cfg = RuntimeConfig(anthropic_api_key="sk-test")
        source = ExecutionSource(
            type=ExecutionSourceType.REMOTE,
            repo="https://github.com/org/repo",
        )
        result = preflight_check(cfg, "nonexistent-component-xyz", source)
        assert result.ready is False
        assert len(result.blockers) > 0
