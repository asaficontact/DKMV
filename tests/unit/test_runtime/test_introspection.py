"""Tests for dkmv.runtime._introspection."""

from __future__ import annotations

from pathlib import Path

import pytest

from dkmv.runtime._introspection import (
    ComponentInfo,
    TaskInfo,
    ValidationResult,
    inspect_component,
    inspect_task,
    list_components,
    validate_component,
)
from dkmv.tasks.discovery import BUILTIN_COMPONENTS


class TestTaskInfo:
    def test_defaults(self) -> None:
        info = TaskInfo(name="test-task")
        assert info.name == "test-task"
        assert info.description == ""
        assert info.agent is None
        assert info.model is None
        assert info.has_prompt is False
        assert info.has_instructions is False
        assert info.input_count == 0
        assert info.output_count == 0
        assert info.commit is True
        assert info.push is True


class TestComponentInfo:
    def test_defaults(self) -> None:
        info = ComponentInfo(name="test", path=Path("/tmp/test"))
        assert info.name == "test"
        assert info.is_builtin is False
        assert info.task_count == 0
        assert info.tasks == []
        assert info.has_manifest is False
        assert info.deliverables == []


class TestValidationResult:
    def test_valid(self) -> None:
        result = ValidationResult(valid=True)
        assert result.valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_invalid(self) -> None:
        result = ValidationResult(valid=False, errors=["missing file"])
        assert result.valid is False
        assert "missing file" in result.errors


class TestInspectTask:
    def test_inspect_simple_task(self, tmp_path: Path) -> None:
        task_yaml = tmp_path / "task.yaml"
        task_yaml.write_text(
            "name: my-task\n"
            "description: A test task\n"
            "prompt: Do something\n"
            "commit: false\n"
            "push: false\n"
        )
        info = inspect_task(task_yaml)
        assert info.name == "my-task"
        assert info.description == "A test task"
        assert info.has_prompt is True
        assert info.commit is False
        assert info.push is False

    def test_inspect_task_with_inputs_outputs(self, tmp_path: Path) -> None:
        task_yaml = tmp_path / "task.yaml"
        task_yaml.write_text(
            "name: io-task\n"
            "prompt: Do it\n"
            "inputs:\n"
            "  - name: src\n"
            "    type: file\n"
            "    src: foo.txt\n"
            "    dest: bar.txt\n"
            "outputs:\n"
            "  - path: result.json\n"
            "    required: true\n"
        )
        info = inspect_task(task_yaml)
        assert info.input_count == 1
        assert info.output_count == 1

    def test_inspect_task_with_agent_model(self, tmp_path: Path) -> None:
        task_yaml = tmp_path / "task.yaml"
        task_yaml.write_text(
            "name: agent-task\n"
            "prompt: Do it\n"
            "agent: codex\n"
            "model: gpt-5.4\n"
            "max_turns: 50\n"
            "timeout_minutes: 15\n"
        )
        info = inspect_task(task_yaml)
        assert info.agent == "codex"
        assert info.model == "gpt-5.4"
        assert info.max_turns == 50
        assert info.timeout_minutes == 15

    def test_inspect_task_with_variables(self, tmp_path: Path) -> None:
        task_yaml = tmp_path / "task.yaml"
        task_yaml.write_text("name: {{ task_name }}\nprompt: Work on {{ feature }}\n")
        info = inspect_task(task_yaml, variables={"task_name": "dynamic", "feature": "auth"})
        assert info.name == "dynamic"
        assert info.has_prompt is True

    def test_inspect_task_with_instructions(self, tmp_path: Path) -> None:
        task_yaml = tmp_path / "task.yaml"
        task_yaml.write_text("name: inst-task\nprompt: Do it\ninstructions: Follow these rules\n")
        info = inspect_task(task_yaml)
        assert info.has_instructions is True

    def test_inspect_nonexistent_task(self, tmp_path: Path) -> None:
        with pytest.raises(Exception):
            inspect_task(tmp_path / "missing.yaml")


class TestInspectComponent:
    def test_inspect_builtin(self) -> None:
        info = inspect_component("dev")
        assert info.name is not None
        assert info.is_builtin is True
        assert info.path.exists()
        assert info.task_count > 0

    def test_inspect_with_manifest(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "mycomp"
        comp_dir.mkdir()
        tasks_dir = comp_dir / "tasks"
        tasks_dir.mkdir()

        (tasks_dir / "step1.yaml").write_text("name: step-1\nprompt: Do step 1\n")
        (tasks_dir / "step2.yaml").write_text("name: step-2\nprompt: Do step 2\n")
        (comp_dir / "component.yaml").write_text(
            "name: my-component\n"
            "description: Test component\n"
            "tasks:\n"
            "  - file: tasks/step1.yaml\n"
            "  - file: tasks/step2.yaml\n"
            "deliverables:\n"
            "  - path: output.md\n"
        )

        info = inspect_component(str(comp_dir))
        assert info.name == "my-component"
        assert info.description == "Test component"
        assert info.has_manifest is True
        assert info.task_count == 2
        assert len(info.tasks) == 2
        assert info.tasks[0].name == "step-1"
        assert info.tasks[1].name == "step-2"
        assert info.deliverables == ["output.md"]

    def test_inspect_without_manifest(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "simple"
        comp_dir.mkdir()
        (comp_dir / "task1.yaml").write_text("name: t1\nprompt: Do t1\n")
        (comp_dir / "task2.yaml").write_text("name: t2\nprompt: Do t2\n")

        info = inspect_component(str(comp_dir))
        assert info.has_manifest is False
        assert info.task_count == 2

    def test_inspect_component_agent_model(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "agentcomp"
        comp_dir.mkdir()
        (comp_dir / "task.yaml").write_text("name: t\nprompt: Do\n")
        (comp_dir / "component.yaml").write_text(
            "name: agent-comp\nagent: codex\nmodel: gpt-5.4\ntasks:\n  - file: task.yaml\n"
        )

        info = inspect_component(str(comp_dir))
        assert info.agent == "codex"
        assert info.model == "gpt-5.4"


class TestValidateComponent:
    def test_validate_valid_component(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "valid"
        comp_dir.mkdir()
        (comp_dir / "task.yaml").write_text("name: t\nprompt: Do it\n")
        (comp_dir / "component.yaml").write_text("name: valid-comp\ntasks:\n  - file: task.yaml\n")

        result = validate_component(str(comp_dir))
        assert result.valid is True
        assert result.errors == []

    def test_validate_missing_task_file(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "broken"
        comp_dir.mkdir()
        (comp_dir / "component.yaml").write_text(
            "name: broken-comp\ntasks:\n  - file: missing.yaml\n"
        )

        result = validate_component(str(comp_dir))
        assert result.valid is False
        assert any("missing.yaml" in e for e in result.errors)

    def test_validate_nonexistent_component(self) -> None:
        result = validate_component("/nonexistent/path")
        assert result.valid is False
        assert len(result.errors) > 0

    def test_validate_no_manifest_warning(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "nomanifest"
        comp_dir.mkdir()
        (comp_dir / "task.yaml").write_text("name: t\nprompt: Do\n")

        result = validate_component(str(comp_dir))
        assert result.valid is True
        assert any("No component.yaml" in w for w in result.warnings)

    def test_validate_empty_tasks_warning(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "empty"
        comp_dir.mkdir()
        (comp_dir / "component.yaml").write_text("name: empty-comp\ntasks: []\n")

        result = validate_component(str(comp_dir))
        assert result.valid is True
        assert any("no tasks" in w for w in result.warnings)

    def test_validate_invalid_task_yaml(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "badtask"
        comp_dir.mkdir()
        (comp_dir / "task.yaml").write_text("invalid: yaml: content: [")
        (comp_dir / "component.yaml").write_text("name: bad\ntasks:\n  - file: task.yaml\n")

        result = validate_component(str(comp_dir))
        assert result.valid is False

    def test_validate_builtin(self) -> None:
        result = validate_component("dev")
        assert result.valid is True


class TestListComponents:
    def test_lists_builtins(self) -> None:
        components = list_components()
        # At least some builtins should be present
        assert len(components) >= len(BUILTIN_COMPONENTS)
        assert any(c.is_builtin for c in components)

    def test_includes_registered(self, tmp_path: Path) -> None:
        # Create a mock project with registered component
        dkmv_dir = tmp_path / ".dkmv"
        dkmv_dir.mkdir()
        comp_dir = tmp_path / "custom"
        comp_dir.mkdir()
        (comp_dir / "task.yaml").write_text("name: custom-task\nprompt: Do\n")

        import json

        (dkmv_dir / "components.json").write_text(json.dumps({"custom": str(comp_dir)}))

        components = list_components(project_root=tmp_path)
        names = [c.name for c in components]
        assert "custom" in names
