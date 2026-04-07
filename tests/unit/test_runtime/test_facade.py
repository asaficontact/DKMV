"""Tests for dkmv.runtime._facade."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from dkmv.config import DKMVConfig
from dkmv.runtime._facade import EmbeddedRuntime
from dkmv.runtime._types import (
    ExecutionSource,
    ExecutionSourceType,
    RetentionPolicy,
    RuntimeConfig,
)


class TestEmbeddedRuntimeInit:
    def test_default_config(self) -> None:
        rt = EmbeddedRuntime()
        assert rt._dkmv_config is not None
        assert isinstance(rt._dkmv_config, DKMVConfig)

    def test_custom_config(self) -> None:
        cfg = RuntimeConfig(anthropic_api_key="sk-test", default_model="claude-opus-4-6")
        rt = EmbeddedRuntime(config=cfg)
        assert rt._dkmv_config.anthropic_api_key == "sk-test"
        assert rt._dkmv_config.default_model == "claude-opus-4-6"

    def test_custom_output_dir(self, tmp_path: Path) -> None:
        rt = EmbeddedRuntime(output_dir=tmp_path / "out")
        assert rt._output_dir == tmp_path / "out"

    def test_console_is_quiet(self) -> None:
        rt = EmbeddedRuntime()
        assert rt._console.quiet is True


class TestEmbeddedRuntimeIntrospection:
    def test_inspect_component_delegates(self) -> None:
        rt = EmbeddedRuntime()
        info = rt.inspect_component("dev")
        assert info.is_builtin is True

    def test_validate_component_delegates(self) -> None:
        rt = EmbeddedRuntime()
        result = rt.validate_component("dev")
        assert result.valid is True

    def test_list_components_delegates(self) -> None:
        rt = EmbeddedRuntime()
        components = rt.list_components()
        assert len(components) > 0

    @patch("dkmv.runtime._capability._check_docker_version", return_value=(False, ""))
    def test_get_capabilities_delegates(self, mock_docker: object) -> None:
        rt = EmbeddedRuntime()
        report = rt.get_capabilities()
        assert report.version != ""

    @patch("dkmv.runtime._capability._check_docker_version", return_value=(True, "24.0.5"))
    @patch("dkmv.runtime._capability._check_image_exists", return_value=True)
    def test_preflight_check_delegates(self, mock_image: object, mock_docker: object) -> None:
        cfg = RuntimeConfig(anthropic_api_key="sk-test")
        rt = EmbeddedRuntime(config=cfg)
        source = ExecutionSource(
            type=ExecutionSourceType.REMOTE,
            repo="https://github.com/org/repo",
        )
        result = rt.preflight_check("dev", source)
        assert isinstance(result.ready, bool)


class TestEmbeddedRuntimeHistory:
    def test_list_runs_empty(self, tmp_path: Path) -> None:
        rt = EmbeddedRuntime(output_dir=tmp_path)
        runs = rt.list_runs()
        assert runs == []


class TestEmbeddedRuntimeArtifacts:
    def test_list_artifacts(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        (run_dir / "config.json").write_text("{}")
        (run_dir / "result.json").write_text("{}")

        rt = EmbeddedRuntime(output_dir=tmp_path)
        artifacts = rt.list_artifacts("run-1")
        assert len(artifacts) == 2

    def test_get_artifact(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        (run_dir / "result.json").write_text('{"status": "completed"}')

        rt = EmbeddedRuntime(output_dir=tmp_path)
        content = rt.get_artifact("run-1", "result.json")
        assert "completed" in content


class TestEmbeddedRuntimeTelemetry:
    def test_get_stats_empty(self, tmp_path: Path) -> None:
        rt = EmbeddedRuntime(output_dir=tmp_path)
        stats = rt.get_stats()
        assert stats.total_runs == 0

    def test_get_stats_with_runs(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        (run_dir / "result.json").write_text(
            json.dumps(
                {
                    "component": "dev",
                    "status": "completed",
                    "total_cost_usd": 2.0,
                    "duration_seconds": 100.0,
                }
            )
        )

        rt = EmbeddedRuntime(output_dir=tmp_path)
        stats = rt.get_stats()
        assert stats.total_runs == 1
        assert stats.completed == 1


class TestEmbeddedRuntimeRetention:
    def test_destroy_cleans_completed(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        (run_dir / "result.json").write_text(json.dumps({"status": "completed"}))

        rt = EmbeddedRuntime(output_dir=tmp_path)
        deleted = rt.cleanup_runs(RetentionPolicy.DESTROY)
        assert "run-1" in deleted
        assert not run_dir.exists()

    def test_destroy_skips_running(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        # No result.json = still running
        (run_dir / "config.json").write_text("{}")

        rt = EmbeddedRuntime(output_dir=tmp_path)
        deleted = rt.cleanup_runs(RetentionPolicy.DESTROY)
        assert deleted == []
        assert run_dir.exists()

    def test_retain_manual_noop(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        (run_dir / "result.json").write_text(json.dumps({"status": "completed"}))

        rt = EmbeddedRuntime(output_dir=tmp_path)
        deleted = rt.cleanup_runs(RetentionPolicy.RETAIN_MANUAL)
        assert deleted == []
        assert run_dir.exists()

    def test_retain_ttl_removes_old(self, tmp_path: Path) -> None:
        import os
        import time

        run_dir = tmp_path / "runs" / "run-old"
        run_dir.mkdir(parents=True)
        result_path = run_dir / "result.json"
        result_path.write_text(json.dumps({"status": "completed"}))

        # Set mtime to 60 days ago
        old_time = time.time() - (60 * 86400)
        os.utime(result_path, (old_time, old_time))

        rt = EmbeddedRuntime(output_dir=tmp_path)
        deleted = rt.cleanup_runs(RetentionPolicy.RETAIN_TTL, keep_days=30)
        assert "run-old" in deleted

    def test_retain_ttl_keeps_recent(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-recent"
        run_dir.mkdir(parents=True)
        (run_dir / "result.json").write_text(json.dumps({"status": "completed"}))

        rt = EmbeddedRuntime(output_dir=tmp_path)
        deleted = rt.cleanup_runs(RetentionPolicy.RETAIN_TTL, keep_days=30)
        assert deleted == []

    def test_cleanup_no_runs_dir(self, tmp_path: Path) -> None:
        rt = EmbeddedRuntime(output_dir=tmp_path)
        deleted = rt.cleanup_runs(RetentionPolicy.DESTROY)
        assert deleted == []


class TestEmbeddedRuntimeReplay:
    def test_replay_events(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        (run_dir / "stream.jsonl").write_text(
            json.dumps({"type": "system"})
            + "\n"
            + json.dumps({"type": "result", "total_cost_usd": 1.0})
            + "\n"
        )

        rt = EmbeddedRuntime(output_dir=tmp_path)
        events = rt.replay_events("run-1")
        assert len(events) == 2


class TestEmbeddedRuntimeResolveSource:
    def test_remote_source(self) -> None:
        rt = EmbeddedRuntime()
        source = ExecutionSource(
            type=ExecutionSourceType.REMOTE,
            repo="https://github.com/org/repo",
            branch="feature",
        )
        repo, branch, provenance = rt._resolve_source(source)
        assert repo == "https://github.com/org/repo"
        assert branch == "feature"
        assert provenance is not None
        assert provenance.source_type == "remote"


class TestEmbeddedRuntimeCleanup:
    def test_cleanup_temp_dirs(self, tmp_path: Path) -> None:
        rt = EmbeddedRuntime()
        temp = tmp_path / "temp-snapshot"
        temp.mkdir()
        rt._temp_dirs.append(temp)

        rt.cleanup()
        assert not temp.exists()
        assert rt._temp_dirs == []

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        async with EmbeddedRuntime() as rt:
            assert rt is not None


class TestEmbeddedRuntimeGetHandle:
    def test_get_handle_returns_none(self) -> None:
        rt = EmbeddedRuntime()
        assert rt.get_handle("nonexistent") is None
