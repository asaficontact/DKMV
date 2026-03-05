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
    "impl_docs_path": "/tmp/impl-docs",
    "repo": "https://github.com/test/repo",
    "branch": "feature/test",
    "feature_name": "test-feature",
    "component": "dev",
    "model": "claude-sonnet-4-6",
    "run_id": "run-test-123",
    "tasks": {},
    "phases": [
        {"phase_number": 1, "phase_name": "foundation", "phase_file": "phase1_foundation.md"},
        {"phase_number": 2, "phase_name": "core", "phase_file": "phase2_core.md"},
    ],
    "item": {"phase_number": 1, "phase_name": "foundation", "phase_file": "phase1_foundation.md"},
    "item_index": 0,
    "pr_base": "",
}

PLAN_SAMPLE_VARS: dict[str, Any] = {
    **SAMPLE_VARS,
    "tasks": {
        "analyze": {
            "status": "completed",
            "cost": "0.50",
            "turns": "10",
            "outputs": {
                "analysis": {
                    "output_dir": "docs/implementation/test-feature",
                    "features": [
                        {"id": "F1", "name": "Auth", "description": "User authentication"},
                        {"id": "F2", "name": "API", "description": "REST API endpoints"},
                    ],
                    "personas": [{"name": "Developer", "description": "API consumer"}],
                    "constraints": ["Must use Python 3.12+", "No external auth providers"],
                    "risks": [
                        {"risk": "Scope creep", "mitigation": "Strict PRD adherence"},
                    ],
                    "non_goals": ["Mobile app", "Admin dashboard"],
                    "architecture_notes": ["Modular design", "Async-first"],
                    "estimated_complexity": "medium",
                    "technology_decisions": [
                        {
                            "area": "HTTP framework",
                            "chosen": "FastAPI",
                            "alternatives_considered": ["Flask", "Starlette"],
                            "rationale": "Best async support for Python",
                        }
                    ],
                }
            },
        },
        "features-stories": {
            "status": "completed",
            "cost": "0.80",
            "turns": "15",
            "outputs": {
                "features_stories_summary": {
                    "feature_count": 2,
                    "story_count": 5,
                    "feature_ids": ["F1", "F2"],
                    "categories": ["Setup", "Core Workflow"],
                }
            },
        },
        "phases": {
            "status": "completed",
            "cost": "1.20",
            "turns": "25",
            "outputs": {
                "phases_summary": {
                    "phase_count": 3,
                    "task_count": 20,
                    "task_id_range": "T010-T059",
                    "phase_filenames": [
                        "phase1_foundation.md",
                        "phase2_core.md",
                        "phase3_polish.md",
                    ],
                }
            },
        },
    },
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

    def test_dev_implement_phase_yaml_loads(self) -> None:
        component_dir = resolve_component("dev")
        loader = TaskLoader()
        task = loader.load(component_dir / "implement-phase.yaml", SAMPLE_VARS)
        assert task.name == "implement-phase-1"
        assert task.commit is True
        assert task.push is True
        assert task.inputs == []  # inputs now in manifest

    def test_qa_evaluate_yaml_loads(self) -> None:
        component_dir = resolve_component("qa")
        loader = TaskLoader()
        task = loader.load(component_dir / "01-evaluate.yaml", SAMPLE_VARS)
        assert task.name == "evaluate"
        assert task.commit is False
        assert task.push is False
        assert len(task.outputs) == 2
        assert task.outputs[0].required is True
        assert task.inputs == []  # now in manifest

    def test_qa_fix_yaml_loads(self) -> None:
        component_dir = resolve_component("qa")
        loader = TaskLoader()
        task = loader.load(component_dir / "02-fix.yaml", SAMPLE_VARS)
        assert task.name == "fix"
        assert task.commit is True
        assert task.push is True

    def test_qa_re_evaluate_yaml_loads(self) -> None:
        component_dir = resolve_component("qa")
        loader = TaskLoader()
        task = loader.load(component_dir / "03-re-evaluate.yaml", SAMPLE_VARS)
        assert task.name == "re-evaluate"
        assert task.commit is False
        assert task.push is False
        assert len(task.outputs) == 2
        assert task.outputs[0].required is True

    def test_docs_update_docs_yaml_loads(self) -> None:
        component_dir = resolve_component("docs")
        loader = TaskLoader()
        task = loader.load(component_dir / "01-update-docs.yaml", SAMPLE_VARS)
        assert task.name == "update-docs"
        assert task.commit is True
        assert task.push is True
        assert len(task.outputs) == 1

    def test_docs_verify_yaml_loads(self) -> None:
        component_dir = resolve_component("docs")
        loader = TaskLoader()
        task = loader.load(component_dir / "02-verify.yaml", SAMPLE_VARS)
        assert task.name == "verify"
        assert task.commit is True
        assert task.push is True
        assert len(task.outputs) == 1

    def test_docs_create_pr_yaml_loads(self) -> None:
        component_dir = resolve_component("docs")
        loader = TaskLoader()
        task = loader.load(component_dir / "03-create-pr.yaml", SAMPLE_VARS)
        assert task.name == "create-pr"
        assert task.commit is True
        assert task.push is True
        assert len(task.outputs) == 1

    def test_docs_create_pr_loads_without_pr_base(self) -> None:
        """pr_base is optional — template must render when the variable is absent."""
        component_dir = resolve_component("docs")
        loader = TaskLoader()
        vars_without_pr_base = {k: v for k, v in SAMPLE_VARS.items() if k != "pr_base"}
        task = loader.load(component_dir / "03-create-pr.yaml", vars_without_pr_base)
        assert task.name == "create-pr"
        assert "default branch" in task.prompt.lower() or "defaultBranchRef" in task.prompt

    def test_plan_analyze_yaml_loads(self) -> None:
        component_dir = resolve_component("plan")
        loader = TaskLoader()
        task = loader.load(component_dir / "01-analyze.yaml", PLAN_SAMPLE_VARS)
        assert task.name == "analyze"
        assert task.commit is True
        assert task.push is True
        assert task.model is None  # now in manifest
        assert task.max_turns is None  # now in manifest
        assert task.inputs == []  # now in manifest
        assert len(task.outputs) == 1

    def test_plan_features_stories_yaml_loads(self) -> None:
        component_dir = resolve_component("plan")
        loader = TaskLoader()
        task = loader.load(component_dir / "02-features-stories.yaml", PLAN_SAMPLE_VARS)
        assert task.name == "features-stories"
        assert task.commit is True
        assert task.push is True
        assert task.model is None  # now in manifest
        assert task.inputs == []  # now in manifest
        assert len(task.outputs) == 2

    def test_plan_phases_yaml_loads(self) -> None:
        component_dir = resolve_component("plan")
        loader = TaskLoader()
        task = loader.load(component_dir / "03-phases.yaml", PLAN_SAMPLE_VARS)
        assert task.name == "phases"
        assert task.commit is True
        assert task.push is True
        assert task.model is None  # now in manifest
        assert task.inputs == []  # now in manifest
        assert len(task.outputs) == 2

    def test_plan_assembly_yaml_loads(self) -> None:
        component_dir = resolve_component("plan")
        loader = TaskLoader()
        task = loader.load(component_dir / "04-assembly.yaml", PLAN_SAMPLE_VARS)
        assert task.name == "assembly"
        assert task.commit is True
        assert task.push is True
        assert task.model is None  # now in manifest
        assert task.inputs == []  # now in manifest
        assert len(task.outputs) == 1

    def test_plan_evaluate_fix_yaml_loads(self) -> None:
        component_dir = resolve_component("plan")
        loader = TaskLoader()
        task = loader.load(component_dir / "05-evaluate-fix.yaml", PLAN_SAMPLE_VARS)
        assert task.name == "evaluate-fix"
        assert task.commit is True
        assert task.push is True
        assert task.model is None  # now in manifest
        assert task.inputs == []  # now in manifest
        assert len(task.outputs) == 1
        assert task.outputs[0].required is False


class TestComponentLoading:
    """Verify component directories have the right number of YAML files (including component.yaml)."""

    def test_dev_component_has_manifest_and_one_task(self) -> None:
        component_dir = resolve_component("dev")
        yaml_files = sorted(component_dir.glob("*.yaml"))
        assert len(yaml_files) == 2  # component.yaml + 1 task YAML
        assert yaml_files[0].name == "component.yaml"
        assert yaml_files[1].name == "implement-phase.yaml"

    def test_qa_component_has_manifest_and_three_tasks(self) -> None:
        component_dir = resolve_component("qa")
        yaml_files = sorted(component_dir.glob("*.yaml"))
        assert len(yaml_files) == 4  # component.yaml + 3 task YAMLs
        assert yaml_files[0].name == "01-evaluate.yaml"
        assert yaml_files[1].name == "02-fix.yaml"
        assert yaml_files[2].name == "03-re-evaluate.yaml"
        assert yaml_files[3].name == "component.yaml"

    def test_docs_component_has_manifest_and_three_tasks(self) -> None:
        component_dir = resolve_component("docs")
        yaml_files = sorted(component_dir.glob("*.yaml"))
        assert len(yaml_files) == 4  # component.yaml + 3 task YAMLs
        assert yaml_files[0].name == "01-update-docs.yaml"
        assert yaml_files[1].name == "02-verify.yaml"
        assert yaml_files[2].name == "03-create-pr.yaml"
        assert yaml_files[3].name == "component.yaml"

    def test_plan_component_has_manifest_and_five_tasks(self) -> None:
        component_dir = resolve_component("plan")
        yaml_files = sorted(component_dir.glob("*.yaml"))
        assert len(yaml_files) == 6  # component.yaml + 5 task YAMLs
        assert yaml_files[0].name == "01-analyze.yaml"
        assert yaml_files[4].name == "05-evaluate-fix.yaml"
        assert yaml_files[5].name == "component.yaml"

    def test_all_builtins_have_component_yaml(self) -> None:
        for name in ("dev", "qa", "docs", "plan"):
            component_dir = resolve_component(name)
            assert (component_dir / "component.yaml").exists(), f"{name} missing component.yaml"


class TestDiscovery:
    """Verify resolve_component finds all built-ins."""

    def test_resolve_all_builtins(self) -> None:
        for name in ("dev", "qa", "docs", "plan"):
            path = resolve_component(name)
            assert path.is_dir()

    def test_dev_yaml_files_exist(self) -> None:
        path = resolve_component("dev")
        assert (path / "implement-phase.yaml").exists()

    def test_plan_yaml_files_exist(self) -> None:
        path = resolve_component("plan")
        assert (path / "01-analyze.yaml").exists()
        assert (path / "02-features-stories.yaml").exists()
        assert (path / "03-phases.yaml").exists()
        assert (path / "04-assembly.yaml").exists()
        assert (path / "05-evaluate-fix.yaml").exists()


class TestCLIWrappers:
    """Verify CLI wrappers correctly translate flags to ComponentRunner.run() args."""

    def test_dev_wrapper_maps_impl_docs_to_variable(self, tmp_path: Path) -> None:
        impl_docs = tmp_path / "my-feature"
        impl_docs.mkdir()
        (impl_docs / "phase1_foundation.md").write_text("# Phase 1\n")

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
                app, ["dev", "--repo", str(tmp_path), "--impl-docs", str(impl_docs)]
            )

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["variables"]["impl_docs_path"] == str(impl_docs.resolve())
        assert isinstance(call_kwargs["variables"]["phases"], list)
        assert len(call_kwargs["variables"]["phases"]) == 1
        assert call_kwargs["variables"]["phases"][0]["phase_number"] == 1

    def test_dev_feature_name_defaults_to_dir_name(self, tmp_path: Path) -> None:
        impl_docs = tmp_path / "my-feature"
        impl_docs.mkdir()
        (impl_docs / "phase1_foundation.md").write_text("# Phase 1\n")

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
                app, ["dev", "--repo", str(tmp_path), "--impl-docs", str(impl_docs)]
            )

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["feature_name"] == "my-feature"

    def test_qa_wrapper_maps_impl_docs_to_variable(self, tmp_path: Path) -> None:
        impl_docs = tmp_path / "impl-docs"
        impl_docs.mkdir()

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
                    "qa",
                    "--repo",
                    str(tmp_path),
                    "--branch",
                    "feat",
                    "--impl-docs",
                    str(impl_docs),
                ],
            )

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["variables"]["impl_docs_path"] == str(impl_docs.resolve())

    def test_docs_wrapper_maps_impl_docs_to_variable(self, tmp_path: Path) -> None:
        impl_docs = tmp_path / "impl-docs"
        impl_docs.mkdir()

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
                    "docs",
                    "--repo",
                    str(tmp_path),
                    "--branch",
                    "feat",
                    "--impl-docs",
                    str(impl_docs),
                ],
            )

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["variables"]["impl_docs_path"] == str(impl_docs.resolve())

    def test_docs_wrapper_includes_pr_base(self, tmp_path: Path) -> None:
        impl_docs = tmp_path / "impl-docs"
        impl_docs.mkdir()

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
                    "docs",
                    "--repo",
                    str(tmp_path),
                    "--branch",
                    "feat",
                    "--impl-docs",
                    str(impl_docs),
                    "--pr-base",
                    "develop",
                ],
            )

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["variables"]["pr_base"] == "develop"

    def test_docs_wrapper_pr_base_omitted_by_default(self, tmp_path: Path) -> None:
        impl_docs = tmp_path / "impl-docs"
        impl_docs.mkdir()

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
                    "docs",
                    "--repo",
                    str(tmp_path),
                    "--branch",
                    "feat",
                    "--impl-docs",
                    str(impl_docs),
                ],
            )

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert "pr_base" not in call_kwargs["variables"]

    def test_plan_wrapper_maps_prd_to_variable(self, tmp_path: Path) -> None:
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
            result = runner.invoke(app, ["plan", "--repo", str(tmp_path), "--prd", str(prd)])

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["variables"]["prd_path"] == str(prd)

    def test_plan_wrapper_maps_optional_design_docs(self, tmp_path: Path) -> None:
        prd = tmp_path / "prd.md"
        prd.write_text("# PRD\n")
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
                ["plan", "--repo", str(tmp_path), "--prd", str(prd), "--design-docs", str(design)],
            )

        assert result.exit_code == 0
        variables = mock_runner.run.call_args[1]["variables"]
        assert "design_docs_path" in variables

    def test_plan_feature_name_defaults_to_prd_stem(self, tmp_path: Path) -> None:
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
            result = runner.invoke(app, ["plan", "--repo", str(tmp_path), "--prd", str(prd)])

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["feature_name"] == "my-feature"

    def test_plan_branch_defaults_to_feature_plan(self, tmp_path: Path) -> None:
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
            result = runner.invoke(app, ["plan", "--repo", str(tmp_path), "--prd", str(prd)])

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["branch"] == "feature/my-feature-plan"

    def test_dev_explicit_feature_name(self, tmp_path: Path) -> None:
        impl_docs = tmp_path / "my-feature"
        impl_docs.mkdir()
        (impl_docs / "phase1_foundation.md").write_text("# Phase 1\n")

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
                    "--repo",
                    str(tmp_path),
                    "--impl-docs",
                    str(impl_docs),
                    "--feature-name",
                    "custom-name",
                ],
            )

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["feature_name"] == "custom-name"


class TestLoadComponent:
    """Verify TaskLoader.load_component() loads built-in components correctly."""

    def test_dev_load_component_returns_one_task(self) -> None:
        component_dir = resolve_component("dev")
        loader = TaskLoader()
        tasks = loader.load_component(component_dir, SAMPLE_VARS)
        assert len(tasks) == 1
        assert tasks[0].name == "implement-phase-1"

    def test_qa_load_component_returns_three_tasks(self) -> None:
        component_dir = resolve_component("qa")
        loader = TaskLoader()
        tasks = loader.load_component(component_dir, SAMPLE_VARS)
        assert len(tasks) == 3
        assert tasks[0].name == "evaluate"
        assert tasks[1].name == "fix"
        assert tasks[2].name == "re-evaluate"

    def test_docs_load_component_returns_three_tasks(self) -> None:
        component_dir = resolve_component("docs")
        loader = TaskLoader()
        tasks = loader.load_component(component_dir, SAMPLE_VARS)
        assert len(tasks) == 3
        assert tasks[0].name == "update-docs"
        assert tasks[1].name == "verify"
        assert tasks[2].name == "create-pr"

    def test_plan_load_component_returns_five_tasks(self) -> None:
        component_dir = resolve_component("plan")
        loader = TaskLoader()
        tasks = loader.load_component(component_dir, PLAN_SAMPLE_VARS)
        assert len(tasks) == 5
        assert tasks[0].name == "analyze"
        assert tasks[1].name == "features-stories"
        assert tasks[2].name == "phases"
        assert tasks[3].name == "assembly"
        assert tasks[4].name == "evaluate-fix"
