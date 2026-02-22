from __future__ import annotations

import json
from pathlib import Path

import pytest

from dkmv.core.models import BaseComponentConfig, BaseResult, RunDetail, RunSummary
from dkmv.core.runner import RunManager


@pytest.fixture
def run_manager(tmp_path: Path) -> RunManager:
    return RunManager(output_dir=tmp_path)


@pytest.fixture
def config() -> BaseComponentConfig:
    return BaseComponentConfig(
        repo="https://github.com/test/repo.git",
        branch="feature/auth",
        feature_name="user-auth",
    )


@pytest.fixture
def result() -> BaseResult:
    return BaseResult(
        run_id="test1234",
        component="dev",
        status="completed",
        repo="https://github.com/test/repo.git",
        branch="feature/auth",
        feature_name="user-auth",
        total_cost_usd=0.05,
        duration_seconds=120.0,
        num_turns=5,
    )


class TestStartRun:
    def test_creates_run_directory(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        run_id = run_manager.start_run("dev", config)
        run_dir = run_manager._runs_dir / run_id
        assert run_dir.exists()
        assert (run_dir / "logs").exists()

    def test_writes_config_json_with_metadata(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        run_id = run_manager.start_run("dev", config)
        config_path = run_manager._runs_dir / run_id / "config.json"
        data = json.loads(config_path.read_text())
        assert data["_run_id"] == run_id
        assert data["_component"] == "dev"
        assert "_started_at" in data
        assert data["repo"] == "https://github.com/test/repo.git"

    def test_generates_unique_ids(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        id1 = run_manager.start_run("dev", config)
        id2 = run_manager.start_run("dev", config)
        assert id1 != id2
        assert len(id1) == 8


class TestSaveResult:
    def test_saves_result_json(
        self, run_manager: RunManager, config: BaseComponentConfig, result: BaseResult
    ) -> None:
        run_id = run_manager.start_run("dev", config)
        result.run_id = run_id
        run_manager.save_result(run_id, result)

        result_path = run_manager._runs_dir / run_id / "result.json"
        assert result_path.exists()
        data = json.loads(result_path.read_text())
        assert data["run_id"] == run_id
        assert data["status"] == "completed"

    def test_atomic_write_no_tmp_left(
        self, run_manager: RunManager, config: BaseComponentConfig, result: BaseResult
    ) -> None:
        run_id = run_manager.start_run("dev", config)
        result.run_id = run_id
        run_manager.save_result(run_id, result)

        tmp_path = run_manager._runs_dir / run_id / "result.json.tmp"
        assert not tmp_path.exists()

    def test_json_round_trip(
        self, run_manager: RunManager, config: BaseComponentConfig, result: BaseResult
    ) -> None:
        run_id = run_manager.start_run("dev", config)
        result.run_id = run_id
        run_manager.save_result(run_id, result)

        result_path = run_manager._runs_dir / run_id / "result.json"
        restored = BaseResult.model_validate_json(result_path.read_text())
        assert restored.run_id == run_id
        assert restored.total_cost_usd == 0.05


class TestAppendStream:
    def test_appends_jsonl(self, run_manager: RunManager, config: BaseComponentConfig) -> None:
        run_id = run_manager.start_run("dev", config)
        run_manager.append_stream(run_id, {"type": "system", "msg": "init"})
        run_manager.append_stream(run_id, {"type": "result", "cost": 0.01})

        stream_path = run_manager._runs_dir / run_id / "stream.jsonl"
        lines = stream_path.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["type"] == "system"
        assert json.loads(lines[1])["type"] == "result"


class TestSavePrompt:
    def test_saves_prompt_md(self, run_manager: RunManager, config: BaseComponentConfig) -> None:
        run_id = run_manager.start_run("dev", config)
        run_manager.save_prompt(run_id, "# Implement feature X")

        prompt_path = run_manager._runs_dir / run_id / "prompt.md"
        assert prompt_path.read_text() == "# Implement feature X"


class TestListRuns:
    def test_list_runs_returns_summaries(
        self, run_manager: RunManager, config: BaseComponentConfig, result: BaseResult
    ) -> None:
        run_id = run_manager.start_run("dev", config)
        result.run_id = run_id
        run_manager.save_result(run_id, result)

        runs = run_manager.list_runs()
        assert len(runs) == 1
        assert isinstance(runs[0], RunSummary)
        assert runs[0].run_id == run_id

    def test_list_runs_filter_by_component(
        self, run_manager: RunManager, config: BaseComponentConfig, result: BaseResult
    ) -> None:
        run_id = run_manager.start_run("dev", config)
        result.run_id = run_id
        run_manager.save_result(run_id, result)

        assert len(run_manager.list_runs(component="dev")) == 1
        assert len(run_manager.list_runs(component="qa")) == 0

    def test_list_runs_filter_by_feature(
        self, run_manager: RunManager, config: BaseComponentConfig, result: BaseResult
    ) -> None:
        run_id = run_manager.start_run("dev", config)
        result.run_id = run_id
        run_manager.save_result(run_id, result)

        assert len(run_manager.list_runs(feature="auth")) == 1
        assert len(run_manager.list_runs(feature="payment")) == 0

    def test_list_runs_limit(
        self, run_manager: RunManager, config: BaseComponentConfig, result: BaseResult
    ) -> None:
        for i in range(5):
            rid = run_manager.start_run("dev", config)
            result.run_id = rid
            run_manager.save_result(rid, result)

        assert len(run_manager.list_runs(limit=3)) == 3

    def test_list_runs_empty(self, run_manager: RunManager) -> None:
        assert run_manager.list_runs() == []

    def test_list_runs_skips_corrupt_json(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        run_id = run_manager.start_run("dev", config)
        result_path = run_manager._runs_dir / run_id / "result.json"
        result_path.write_text("not valid json{{{")

        assert len(run_manager.list_runs()) == 0

    def test_list_runs_in_progress_from_config(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        run_manager.start_run("dev", config)
        # No result saved — should show as "running" from config
        runs = run_manager.list_runs()
        assert len(runs) == 1
        assert runs[0].status == "running"


class TestContainerName:
    def test_save_and_get_container_name(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        run_id = run_manager.start_run("dev", config)
        run_manager.save_container_name(run_id, "dkmv-dev-abc123")
        assert run_manager.get_container_name(run_id) == "dkmv-dev-abc123"

    def test_get_container_name_missing(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        run_id = run_manager.start_run("dev", config)
        assert run_manager.get_container_name(run_id) is None

    def test_get_container_name_empty_file(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        run_id = run_manager.start_run("dev", config)
        (run_manager._runs_dir / run_id / "container.txt").write_text("  \n")
        assert run_manager.get_container_name(run_id) is None


class TestListRunsStatusFilter:
    def test_list_runs_filter_by_status(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        # Create a completed run
        rid1 = run_manager.start_run("dev", config)
        result1 = BaseResult(run_id=rid1, component="dev", status="completed")
        run_manager.save_result(rid1, result1)

        # Create a running run (no result saved)
        run_manager.start_run("dev", config)

        assert len(run_manager.list_runs(status="completed")) == 1
        assert len(run_manager.list_runs(status="running")) == 1
        assert len(run_manager.list_runs(status="failed")) == 0


class TestGetRun:
    def test_get_run_returns_full_detail(
        self, run_manager: RunManager, config: BaseComponentConfig, result: BaseResult
    ) -> None:
        run_id = run_manager.start_run("dev", config)
        result.run_id = run_id
        run_manager.save_result(run_id, result)
        run_manager.save_prompt(run_id, "test prompt")
        run_manager.append_stream(run_id, {"type": "event"})

        detail = run_manager.get_run(run_id)
        assert isinstance(detail, RunDetail)
        assert detail.run_id == run_id
        assert detail.prompt == "test prompt"
        assert detail.stream_events_count == 1
        assert detail.config  # config dict should be populated

    def test_get_run_missing_raises(self, run_manager: RunManager) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            run_manager.get_run("nonexistent")

    def test_session_id_preserved(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        run_id = run_manager.start_run("dev", config)
        result = BaseResult(
            run_id=run_id,
            component="dev",
            session_id="sess-abc-123",
        )
        run_manager.save_result(run_id, result)

        detail = run_manager.get_run(run_id)
        assert detail.session_id == "sess-abc-123"

    def test_get_run_in_progress_uses_config_component(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        """L2: get_run should read component from config, not hardcode 'dev'."""
        run_id = run_manager.start_run("qa", config)
        # No result saved — should fall back to config
        detail = run_manager.get_run(run_id)
        assert detail.component == "qa"
        assert detail.status == "running"


class TestGetRunFallbacks:
    def test_get_run_result_missing_component_uses_config(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        """R-2: When result.json exists but missing component key, use config."""
        run_id = run_manager.start_run("qa", config)
        # Write result.json without component key
        result_path = run_manager._runs_dir / run_id / "result.json"
        result_path.write_text(
            json.dumps({"run_id": run_id, "status": "completed", "repo": "test"})
        )

        detail = run_manager.get_run(run_id)
        assert detail.component == "qa"  # Should come from config, not "dev"

    def test_get_run_no_config_no_result_uses_dev_fallback(self, run_manager: RunManager) -> None:
        """N1: When neither config nor result has component, fallback should be valid."""
        run_id = "manual123"
        run_dir = run_manager._runs_dir / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "logs").mkdir()
        # No config.json, no result.json — should still not crash
        detail = run_manager.get_run(run_id)
        assert detail.component == "dev"  # Valid ComponentName fallback
        assert detail.status == "running"

    def test_get_run_preserves_timestamp(
        self, run_manager: RunManager, config: BaseComponentConfig, result: BaseResult
    ) -> None:
        """N2: get_run should pass timestamp from result, not use default."""
        run_id = run_manager.start_run("dev", config)
        result.run_id = run_id
        run_manager.save_result(run_id, result)

        detail = run_manager.get_run(run_id)
        assert detail.timestamp == result.timestamp

    def test_get_run_in_progress_uses_config_started_at(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        """N2: In-progress run should use _started_at from config as timestamp."""
        run_id = run_manager.start_run("dev", config)
        # No result saved — timestamp should come from config's _started_at
        config_data = json.loads((run_manager._runs_dir / run_id / "config.json").read_text())
        detail = run_manager.get_run(run_id)
        # The timestamp should be sourced from config's _started_at, not datetime.now()
        assert config_data["_started_at"] in detail.timestamp.isoformat()


class TestGetRunCorruptData:
    def test_get_run_with_invalid_pydantic_data(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        """Corrupt result.json should return degraded RunDetail, not crash."""
        run_id = run_manager.start_run("qa", config)
        result_path = run_manager._runs_dir / run_id / "result.json"
        # Write valid JSON but with invalid data (negative cost violates ge=0)
        result_path.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "component": "qa",
                    "status": "completed",
                    "total_cost_usd": -5.0,
                }
            )
        )

        detail = run_manager.get_run(run_id)
        assert detail.status == "failed"
        assert detail.error_message == "Corrupt run data"
        assert detail.component == "qa"


class TestCustomComponentName:
    def test_start_run_custom_component_name(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        run_id = run_manager.start_run("my-custom-component", config)
        run_dir = run_manager._runs_dir / run_id
        assert run_dir.exists()
        config_data = json.loads((run_dir / "config.json").read_text())
        assert config_data["_component"] == "my-custom-component"


class TestSaveArtifact:
    def test_saves_artifact_file(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        run_id = run_manager.start_run("dev", config)
        run_manager.save_artifact(run_id, "task_result.json", '{"status": "ok"}')

        artifact_path = run_manager._runs_dir / run_id / "task_result.json"
        assert artifact_path.exists()
        assert artifact_path.read_text() == '{"status": "ok"}'


class TestSaveTaskPrompt:
    def test_saves_task_prompt_with_name(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        run_id = run_manager.start_run("dev", config)
        run_manager.save_task_prompt(run_id, "plan", "# Plan the feature")

        prompt_path = run_manager._runs_dir / run_id / "prompt_plan.md"
        assert prompt_path.exists()
        assert prompt_path.read_text() == "# Plan the feature"

    def test_multiple_task_prompts_coexist(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        run_id = run_manager.start_run("dev", config)
        run_manager.save_task_prompt(run_id, "plan", "# Plan")
        run_manager.save_task_prompt(run_id, "implement", "# Implement")

        run_dir = run_manager._runs_dir / run_id
        assert (run_dir / "prompt_plan.md").read_text() == "# Plan"
        assert (run_dir / "prompt_implement.md").read_text() == "# Implement"


class TestListRunsSortOrder:
    def test_sorts_by_timestamp_not_id(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        """H4: Runs should be sorted by timestamp, not by hex directory name."""
        import time

        results = []
        for _ in range(3):
            rid = run_manager.start_run("dev", config)
            result = BaseResult(run_id=rid, component="dev", status="completed")
            run_manager.save_result(rid, result)
            results.append(rid)
            time.sleep(0.01)

        runs = run_manager.list_runs()
        # Most recent should be first
        assert runs[0].run_id == results[-1]

    def test_limit_applied_after_sort(
        self, run_manager: RunManager, config: BaseComponentConfig
    ) -> None:
        """Limit should apply after sorting by timestamp."""
        import time

        results = []
        for _ in range(5):
            rid = run_manager.start_run("dev", config)
            result = BaseResult(run_id=rid, component="dev", status="completed")
            run_manager.save_result(rid, result)
            results.append(rid)
            time.sleep(0.01)

        runs = run_manager.list_runs(limit=2)
        assert len(runs) == 2
        # Should be the 2 most recent
        assert runs[0].run_id == results[-1]
        assert runs[1].run_id == results[-2]
