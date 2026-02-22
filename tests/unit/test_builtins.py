from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from dkmv.cli import app
from dkmv.tasks.discovery import resolve_component
from dkmv.tasks.loader import TaskLoader

runner = CliRunner()

SAMPLE_VARS: dict[str, Any] = {
    "prd_path": "/tmp/test-prd.md",
    "repo": "https://github.com/test/repo",
    "branch": "feature/test",
    "feature_name": "test-feature",
    "component": "dev",
    "model": "claude-sonnet-4-6",
    "run_id": "run-test-123",
    "tasks": {},
}


def _mock_config() -> MagicMock:
    cfg = MagicMock()
    cfg.default_model = "claude-sonnet-4-6"
    cfg.default_max_turns = 100
    cfg.timeout_minutes = 30
    cfg.max_budget_usd = None
    cfg.output_dir = Path("./outputs")
    cfg.anthropic_api_key = "sk-ant-test"
    cfg.github_token = "ghp_test"
    cfg.image_name = "dkmv-sandbox:latest"
    cfg.memory_limit = "8g"
    return cfg


class TestYAMLValidation:
    """Verify built-in YAML files load and validate correctly."""

    def test_dev_plan_yaml_loads(self) -> None:
        component_dir = resolve_component("dev")
        loader = TaskLoader()
        task = loader.load(component_dir / "01-plan.yaml", SAMPLE_VARS)
        assert task.name == "plan"
        assert task.commit is False
        assert task.push is False
        assert task.model == "claude-sonnet-4-6"

    def test_dev_implement_yaml_loads(self) -> None:
        component_dir = resolve_component("dev")
        loader = TaskLoader()
        task = loader.load(component_dir / "02-implement.yaml", SAMPLE_VARS)
        assert task.name == "implement"
        assert task.commit is True
        assert task.push is True
        assert task.commit_message is not None
        assert "[dkmv-dev]" in task.commit_message

    def test_qa_evaluate_yaml_loads(self) -> None:
        component_dir = resolve_component("qa")
        loader = TaskLoader()
        task = loader.load(component_dir / "01-evaluate.yaml", SAMPLE_VARS)
        assert task.name == "evaluate"
        assert len(task.outputs) == 1
        assert task.outputs[0].required is True

    def test_judge_verdict_yaml_loads(self) -> None:
        component_dir = resolve_component("judge")
        loader = TaskLoader()
        task = loader.load(component_dir / "01-verdict.yaml", SAMPLE_VARS)
        assert task.name == "verdict"
        assert len(task.outputs) == 1
        assert task.outputs[0].required is True

    def test_docs_generate_yaml_loads(self) -> None:
        component_dir = resolve_component("docs")
        loader = TaskLoader()
        task = loader.load(component_dir / "01-generate.yaml", SAMPLE_VARS)
        assert task.name == "generate"
        # Docs has env-type inputs
        env_inputs = [i for i in task.inputs if i.type == "env"]
        assert len(env_inputs) >= 2


class TestComponentLoading:
    """Verify component directories have the right number of YAML files."""

    def test_dev_component_has_two_tasks(self) -> None:
        component_dir = resolve_component("dev")
        yaml_files = sorted(component_dir.glob("*.yaml"))
        assert len(yaml_files) == 2
        assert yaml_files[0].name == "01-plan.yaml"
        assert yaml_files[1].name == "02-implement.yaml"

    def test_qa_component_has_one_task(self) -> None:
        component_dir = resolve_component("qa")
        yaml_files = list(component_dir.glob("*.yaml"))
        assert len(yaml_files) == 1

    def test_judge_component_has_one_task(self) -> None:
        component_dir = resolve_component("judge")
        yaml_files = list(component_dir.glob("*.yaml"))
        assert len(yaml_files) == 1

    def test_docs_component_has_one_task(self) -> None:
        component_dir = resolve_component("docs")
        yaml_files = list(component_dir.glob("*.yaml"))
        assert len(yaml_files) == 1


class TestDiscovery:
    """Verify resolve_component finds all built-ins."""

    def test_resolve_all_builtins(self) -> None:
        for name in ("dev", "qa", "judge", "docs"):
            path = resolve_component(name)
            assert path.is_dir()

    def test_dev_yaml_files_exist(self) -> None:
        path = resolve_component("dev")
        assert (path / "01-plan.yaml").exists()
        assert (path / "02-implement.yaml").exists()


class TestCLIWrappers:
    """Verify CLI wrappers correctly translate flags to ComponentRunner.run() args."""

    def test_dev_wrapper_maps_prd_to_variable(self, tmp_path: Path) -> None:
        prd = tmp_path / "prd.md"
        prd.write_text("# PRD\n")

        mock_runner = MagicMock()
        mock_result = MagicMock(run_id="r1", status="completed", error_message="")
        mock_runner.run = AsyncMock(return_value=mock_result)

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config()),
            patch("dkmv.tasks.ComponentRunner", return_value=mock_runner),
            patch("dkmv.core.runner.RunManager"),
            patch("dkmv.core.sandbox.SandboxManager"),
            patch("dkmv.core.stream.StreamParser"),
            patch("dkmv.tasks.loader.TaskLoader"),
            patch("dkmv.tasks.runner.TaskRunner"),
        ):
            result = runner.invoke(app, ["dev", str(tmp_path), "--prd", str(prd)])

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["variables"]["prd_path"] == str(prd)

    def test_dev_wrapper_maps_optional_flags(self, tmp_path: Path) -> None:
        prd = tmp_path / "prd.md"
        prd.write_text("# PRD\n")
        feedback = tmp_path / "feedback.json"
        feedback.write_text("{}")
        design = tmp_path / "design"
        design.mkdir()

        mock_runner = MagicMock()
        mock_result = MagicMock(run_id="r1", status="completed", error_message="")
        mock_runner.run = AsyncMock(return_value=mock_result)

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config()),
            patch("dkmv.tasks.ComponentRunner", return_value=mock_runner),
            patch("dkmv.core.runner.RunManager"),
            patch("dkmv.core.sandbox.SandboxManager"),
            patch("dkmv.core.stream.StreamParser"),
            patch("dkmv.tasks.loader.TaskLoader"),
            patch("dkmv.tasks.runner.TaskRunner"),
        ):
            result = runner.invoke(
                app,
                [
                    "dev",
                    str(tmp_path),
                    "--prd",
                    str(prd),
                    "--feedback",
                    str(feedback),
                    "--design-docs",
                    str(design),
                ],
            )

        assert result.exit_code == 0
        variables = mock_runner.run.call_args[1]["variables"]
        assert "feedback_path" in variables
        assert "design_docs_path" in variables

    def test_dev_feature_name_defaults_to_prd_stem(self, tmp_path: Path) -> None:
        prd = tmp_path / "my-feature.md"
        prd.write_text("# PRD\n")

        mock_runner = MagicMock()
        mock_result = MagicMock(run_id="r1", status="completed", error_message="")
        mock_runner.run = AsyncMock(return_value=mock_result)

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config()),
            patch("dkmv.tasks.ComponentRunner", return_value=mock_runner),
            patch("dkmv.core.runner.RunManager"),
            patch("dkmv.core.sandbox.SandboxManager"),
            patch("dkmv.core.stream.StreamParser"),
            patch("dkmv.tasks.loader.TaskLoader"),
            patch("dkmv.tasks.runner.TaskRunner"),
        ):
            result = runner.invoke(app, ["dev", str(tmp_path), "--prd", str(prd)])

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["feature_name"] == "my-feature"

    def test_qa_wrapper_maps_prd_to_variable(self, tmp_path: Path) -> None:
        prd = tmp_path / "prd.md"
        prd.write_text("# PRD\n")

        mock_runner = MagicMock()
        mock_result = MagicMock(run_id="r1", status="completed", error_message="")
        mock_runner.run = AsyncMock(return_value=mock_result)

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config()),
            patch("dkmv.tasks.ComponentRunner", return_value=mock_runner),
            patch("dkmv.core.runner.RunManager"),
            patch("dkmv.core.sandbox.SandboxManager"),
            patch("dkmv.core.stream.StreamParser"),
            patch("dkmv.tasks.loader.TaskLoader"),
            patch("dkmv.tasks.runner.TaskRunner"),
        ):
            result = runner.invoke(
                app, ["qa", str(tmp_path), "--branch", "feat", "--prd", str(prd)]
            )

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["variables"]["prd_path"] == str(prd)

    def test_docs_wrapper_maps_create_pr_flag(self, tmp_path: Path) -> None:
        mock_runner = MagicMock()
        mock_result = MagicMock(run_id="r1", status="completed", error_message="")
        mock_runner.run = AsyncMock(return_value=mock_result)

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config()),
            patch("dkmv.tasks.ComponentRunner", return_value=mock_runner),
            patch("dkmv.core.runner.RunManager"),
            patch("dkmv.core.sandbox.SandboxManager"),
            patch("dkmv.core.stream.StreamParser"),
            patch("dkmv.tasks.loader.TaskLoader"),
            patch("dkmv.tasks.runner.TaskRunner"),
        ):
            result = runner.invoke(app, ["docs", str(tmp_path), "--branch", "feat", "--create-pr"])

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["variables"]["create_pr"] == "true"

    def test_docs_wrapper_includes_pr_base(self, tmp_path: Path) -> None:
        mock_runner = MagicMock()
        mock_result = MagicMock(run_id="r1", status="completed", error_message="")
        mock_runner.run = AsyncMock(return_value=mock_result)

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config()),
            patch("dkmv.tasks.ComponentRunner", return_value=mock_runner),
            patch("dkmv.core.runner.RunManager"),
            patch("dkmv.core.sandbox.SandboxManager"),
            patch("dkmv.core.stream.StreamParser"),
            patch("dkmv.tasks.loader.TaskLoader"),
            patch("dkmv.tasks.runner.TaskRunner"),
        ):
            result = runner.invoke(
                app, ["docs", str(tmp_path), "--branch", "feat", "--pr-base", "develop"]
            )

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["variables"]["pr_base"] == "develop"

    def test_judge_wrapper_maps_prd_to_variable(self, tmp_path: Path) -> None:
        prd = tmp_path / "prd.md"
        prd.write_text("# PRD\n")

        mock_runner = MagicMock()
        mock_result = MagicMock(run_id="r1", status="completed", error_message="")
        mock_runner.run = AsyncMock(return_value=mock_result)

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config()),
            patch("dkmv.tasks.ComponentRunner", return_value=mock_runner),
            patch("dkmv.core.runner.RunManager"),
            patch("dkmv.core.sandbox.SandboxManager"),
            patch("dkmv.core.stream.StreamParser"),
            patch("dkmv.tasks.loader.TaskLoader"),
            patch("dkmv.tasks.runner.TaskRunner"),
        ):
            result = runner.invoke(
                app, ["judge", str(tmp_path), "--branch", "feat", "--prd", str(prd)]
            )

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["variables"]["prd_path"] == str(prd)

    def test_dev_explicit_feature_name(self, tmp_path: Path) -> None:
        prd = tmp_path / "my-feature.md"
        prd.write_text("# PRD\n")

        mock_runner = MagicMock()
        mock_result = MagicMock(run_id="r1", status="completed", error_message="")
        mock_runner.run = AsyncMock(return_value=mock_result)

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config()),
            patch("dkmv.tasks.ComponentRunner", return_value=mock_runner),
            patch("dkmv.core.runner.RunManager"),
            patch("dkmv.core.sandbox.SandboxManager"),
            patch("dkmv.core.stream.StreamParser"),
            patch("dkmv.tasks.loader.TaskLoader"),
            patch("dkmv.tasks.runner.TaskRunner"),
        ):
            result = runner.invoke(
                app,
                ["dev", str(tmp_path), "--prd", str(prd), "--feature-name", "custom-name"],
            )

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["feature_name"] == "custom-name"


class TestLoadComponent:
    """Verify TaskLoader.load_component() loads built-in components correctly."""

    def test_dev_load_component_returns_two_tasks(self) -> None:
        component_dir = resolve_component("dev")
        loader = TaskLoader()
        tasks = loader.load_component(component_dir, SAMPLE_VARS)
        assert len(tasks) == 2
        assert tasks[0].name == "plan"
        assert tasks[1].name == "implement"

    def test_qa_load_component_returns_one_task(self) -> None:
        component_dir = resolve_component("qa")
        loader = TaskLoader()
        tasks = loader.load_component(component_dir, SAMPLE_VARS)
        assert len(tasks) == 1
        assert tasks[0].name == "evaluate"

    def test_judge_load_component_returns_one_task(self) -> None:
        component_dir = resolve_component("judge")
        loader = TaskLoader()
        tasks = loader.load_component(component_dir, SAMPLE_VARS)
        assert len(tasks) == 1
        assert tasks[0].name == "verdict"

    def test_docs_load_component_returns_one_task(self) -> None:
        component_dir = resolve_component("docs")
        loader = TaskLoader()
        tasks = loader.load_component(component_dir, SAMPLE_VARS)
        assert len(tasks) == 1
        assert tasks[0].name == "generate"
