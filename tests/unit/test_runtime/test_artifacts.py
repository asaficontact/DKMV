"""Tests for dkmv.runtime._artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest

from dkmv.runtime._artifacts import _classify, get_artifact, list_artifacts


class TestClassify:
    def test_config_json(self) -> None:
        assert _classify("config.json") == "config"

    def test_result_json(self) -> None:
        assert _classify("result.json") == "result"

    def test_stream_jsonl(self) -> None:
        assert _classify("stream.jsonl") == "stream"

    def test_container_txt(self) -> None:
        assert _classify("container.txt") == "config"

    def test_prompts_log(self) -> None:
        assert _classify("prompts_log.md") == "log"

    def test_prompt_file(self) -> None:
        assert _classify("prompt_step1.md") == "prompt"

    def test_instructions_file(self) -> None:
        assert _classify("claude_md_step1.md") == "instructions"

    def test_log_file(self) -> None:
        assert _classify("agent.log") == "log"

    def test_output_file(self) -> None:
        assert _classify("GUIDE.md") == "output"
        assert _classify("plan.json") == "output"


class TestListArtifacts:
    def test_list_run_artifacts(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-123"
        run_dir.mkdir(parents=True)
        (run_dir / "config.json").write_text("{}")
        (run_dir / "result.json").write_text("{}")
        (run_dir / "stream.jsonl").write_text("")
        (run_dir / "prompt_step1.md").write_text("prompt")
        (run_dir / "GUIDE.md").write_text("guide")

        artifacts = list_artifacts("run-123", tmp_path)
        assert len(artifacts) == 5
        names = {a.filename for a in artifacts}
        assert "config.json" in names
        assert "result.json" in names
        assert "GUIDE.md" in names

        # Check types
        types = {a.filename: a.artifact_type for a in artifacts}
        assert types["config.json"] == "config"
        assert types["result.json"] == "result"
        assert types["stream.jsonl"] == "stream"
        assert types["prompt_step1.md"] == "prompt"
        assert types["GUIDE.md"] == "output"

    def test_list_includes_logs_subdir(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        logs_dir = run_dir / "logs"
        logs_dir.mkdir()
        (run_dir / "config.json").write_text("{}")
        (logs_dir / "agent.log").write_text("log content")

        artifacts = list_artifacts("run-1", tmp_path)
        names = {a.filename for a in artifacts}
        assert "config.json" in names
        assert "logs/agent.log" in names

    def test_list_nonexistent_run(self, tmp_path: Path) -> None:
        artifacts = list_artifacts("missing", tmp_path)
        assert artifacts == []

    def test_artifact_size(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        content = "hello world"
        (run_dir / "test.txt").write_text(content)

        artifacts = list_artifacts("run-1", tmp_path)
        assert artifacts[0].size_bytes == len(content)

    def test_artifacts_sorted(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        (run_dir / "z_file.txt").write_text("")
        (run_dir / "a_file.txt").write_text("")

        artifacts = list_artifacts("run-1", tmp_path)
        assert artifacts[0].filename == "a_file.txt"
        assert artifacts[1].filename == "z_file.txt"


class TestGetArtifact:
    def test_get_artifact_content(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        (run_dir / "result.json").write_text('{"status": "completed"}')

        content = get_artifact("run-1", "result.json", tmp_path)
        assert '"status"' in content

    def test_get_artifact_subdir(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-1"
        logs_dir = run_dir / "logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "agent.log").write_text("log line")

        content = get_artifact("run-1", "logs/agent.log", tmp_path)
        assert content == "log line"

    def test_get_missing_artifact(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-1"
        run_dir.mkdir(parents=True)

        with pytest.raises(FileNotFoundError, match="Artifact not found"):
            get_artifact("run-1", "missing.txt", tmp_path)
