from __future__ import annotations

from pathlib import Path

import pytest

from dkmv.tasks.loader import TaskLoadError, TaskLoader


def _write_task_yaml(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


class TestTaskLoaderJinja2:
    def test_simple_variable_resolution(self, tmp_path: Path) -> None:
        yaml_file = _write_task_yaml(
            tmp_path / "task.yaml",
            """
name: test
instructions: "Implement {{ feature_name }}"
prompt: "Go implement {{ feature_name }}"
""",
        )
        loader = TaskLoader()
        task = loader.load(yaml_file, {"feature_name": "auth"})
        assert task.instructions == "Implement auth"
        assert task.prompt == "Go implement auth"

    def test_missing_required_variable_raises(self, tmp_path: Path) -> None:
        yaml_file = _write_task_yaml(
            tmp_path / "task.yaml",
            """
name: test
instructions: "Implement {{ feature_name }}"
prompt: "Go"
""",
        )
        loader = TaskLoader()
        with pytest.raises(TaskLoadError, match="feature_name"):
            loader.load(yaml_file, {})

    def test_default_filter_for_optional_variable(self, tmp_path: Path) -> None:
        yaml_file = _write_task_yaml(
            tmp_path / "task.yaml",
            """
name: test
instructions: "Do stuff"
prompt: "Go {{ extra | default('') }}"
""",
        )
        loader = TaskLoader()
        task = loader.load(yaml_file, {})
        assert task.prompt == "Go "

    def test_if_conditional(self, tmp_path: Path) -> None:
        yaml_file = _write_task_yaml(
            tmp_path / "task.yaml",
            """
name: test
instructions: "Do stuff"
prompt: "Go{% if verbose %} with details{% endif %}"
""",
        )
        loader = TaskLoader()
        task = loader.load(yaml_file, {"verbose": "true"})
        assert task.prompt == "Go with details"

    def test_for_loop(self, tmp_path: Path) -> None:
        yaml_file = _write_task_yaml(
            tmp_path / "task.yaml",
            """
name: test
instructions: "Do stuff"
prompt: "{% for i in items %}{{ i }} {% endfor %}"
""",
        )
        loader = TaskLoader()
        task = loader.load(yaml_file, {"items": ["a", "b", "c"]})
        assert task.prompt == "a b c "


class TestTaskLoaderYAML:
    def test_valid_yaml_parses(self, tmp_path: Path) -> None:
        yaml_file = _write_task_yaml(
            tmp_path / "task.yaml",
            """
name: plan
description: Plan the feature
instructions: Do the planning
prompt: Start planning
model: claude-opus-4-6
max_turns: 50
""",
        )
        loader = TaskLoader()
        task = loader.load(yaml_file, {})
        assert task.name == "plan"
        assert task.model == "claude-opus-4-6"
        assert task.max_turns == 50

    def test_invalid_yaml_syntax_raises(self, tmp_path: Path) -> None:
        yaml_file = _write_task_yaml(
            tmp_path / "task.yaml",
            """
name: test
instructions: "x
  bad: [unmatched
""",
        )
        loader = TaskLoader()
        with pytest.raises(TaskLoadError):
            loader.load(yaml_file, {})

    def test_invalid_pydantic_fields_raises(self, tmp_path: Path) -> None:
        yaml_file = _write_task_yaml(
            tmp_path / "task.yaml",
            """
name: test
prompt: go
prompt_file: also.md
""",
        )
        loader = TaskLoader()
        with pytest.raises(TaskLoadError, match="got both"):
            loader.load(yaml_file, {})

    def test_error_includes_file_path(self, tmp_path: Path) -> None:
        yaml_file = _write_task_yaml(
            tmp_path / "task.yaml",
            """
not_a_valid: thing
""",
        )
        loader = TaskLoader()
        with pytest.raises(TaskLoadError) as exc_info:
            loader.load(yaml_file, {})
        assert str(yaml_file) in str(exc_info.value)


class TestTaskLoaderFileResolution:
    def test_prompt_file_resolved_relative_to_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "prompt.md").write_text("Hello {{ name }}")
        yaml_file = _write_task_yaml(
            tmp_path / "task.yaml",
            """
name: test
instructions: Do stuff
prompt_file: prompt.md
""",
        )
        loader = TaskLoader()
        task = loader.load(yaml_file, {"name": "world"})
        assert task.prompt == "Hello world"
        assert task.prompt_file is None

    def test_instructions_file_resolved(self, tmp_path: Path) -> None:
        (tmp_path / "inst.md").write_text("Step 1: {{ action }}")
        yaml_file = _write_task_yaml(
            tmp_path / "task.yaml",
            """
name: test
instructions_file: inst.md
prompt: go
""",
        )
        loader = TaskLoader()
        task = loader.load(yaml_file, {"action": "build"})
        assert task.instructions == "Step 1: build"
        assert task.instructions_file is None

    def test_missing_prompt_file_raises(self, tmp_path: Path) -> None:
        yaml_file = _write_task_yaml(
            tmp_path / "task.yaml",
            """
name: test
instructions: Do stuff
prompt_file: nonexistent.md
""",
        )
        loader = TaskLoader()
        with pytest.raises(TaskLoadError, match="prompt_file not found"):
            loader.load(yaml_file, {})

    def test_missing_instructions_file_raises(self, tmp_path: Path) -> None:
        yaml_file = _write_task_yaml(
            tmp_path / "task.yaml",
            """
name: test
instructions_file: nonexistent.md
prompt: go
""",
        )
        loader = TaskLoader()
        with pytest.raises(TaskLoadError, match="instructions_file not found"):
            loader.load(yaml_file, {})

    def test_file_content_rendered_with_jinja2(self, tmp_path: Path) -> None:
        (tmp_path / "prompt.md").write_text("{{ greeting }} {{ target }}")
        yaml_file = _write_task_yaml(
            tmp_path / "task.yaml",
            """
name: test
instructions: Do stuff
prompt_file: prompt.md
""",
        )
        loader = TaskLoader()
        task = loader.load(yaml_file, {"greeting": "Hi", "target": "there"})
        assert task.prompt == "Hi there"


class TestTaskLoaderComponent:
    def test_load_component_returns_sorted(self, tmp_path: Path) -> None:
        _write_task_yaml(
            tmp_path / "02-implement.yaml",
            "name: implement\ninstructions: impl\nprompt: go\n",
        )
        _write_task_yaml(
            tmp_path / "01-plan.yaml",
            "name: plan\ninstructions: plan\nprompt: go\n",
        )
        loader = TaskLoader()
        tasks = loader.load_component(tmp_path, {})
        assert [t.name for t in tasks] == ["plan", "implement"]

    def test_empty_directory_returns_empty_list(self, tmp_path: Path) -> None:
        loader = TaskLoader()
        tasks = loader.load_component(tmp_path, {})
        assert tasks == []

    def test_mixes_yaml_and_yml(self, tmp_path: Path) -> None:
        _write_task_yaml(
            tmp_path / "01-plan.yaml",
            "name: plan\ninstructions: p\nprompt: go\n",
        )
        _write_task_yaml(
            tmp_path / "02-impl.yml",
            "name: impl\ninstructions: i\nprompt: go\n",
        )
        loader = TaskLoader()
        tasks = loader.load_component(tmp_path, {})
        assert len(tasks) == 2
        assert tasks[0].name == "plan"
        assert tasks[1].name == "impl"

    def test_ignores_non_yaml_files(self, tmp_path: Path) -> None:
        _write_task_yaml(
            tmp_path / "01-plan.yaml",
            "name: plan\ninstructions: p\nprompt: go\n",
        )
        (tmp_path / "readme.md").write_text("# README")
        (tmp_path / "__init__.py").write_text("")
        loader = TaskLoader()
        tasks = loader.load_component(tmp_path, {})
        assert len(tasks) == 1

    def test_tasks_subdirectory_preferred_over_root(self, tmp_path: Path) -> None:
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        _write_task_yaml(
            tasks_dir / "01-plan.yaml",
            "name: plan\ninstructions: p\nprompt: go\n",
        )
        # YAML at root should be ignored when tasks/ subdirectory exists
        _write_task_yaml(
            tmp_path / "other.yaml",
            "name: other\ninstructions: o\nprompt: go\n",
        )
        loader = TaskLoader()
        tasks = loader.load_component(tmp_path, {})
        assert len(tasks) == 1
        assert tasks[0].name == "plan"

    def test_falls_back_to_root_when_no_tasks_subdir(self, tmp_path: Path) -> None:
        _write_task_yaml(
            tmp_path / "01-plan.yaml",
            "name: plan\ninstructions: p\nprompt: go\n",
        )
        loader = TaskLoader()
        tasks = loader.load_component(tmp_path, {})
        assert len(tasks) == 1
        assert tasks[0].name == "plan"

    def test_variables_passed_to_each_task(self, tmp_path: Path) -> None:
        _write_task_yaml(
            tmp_path / "01-task.yaml",
            "name: t1\ninstructions: '{{ repo }}'\nprompt: go\n",
        )
        _write_task_yaml(
            tmp_path / "02-task.yaml",
            "name: t2\ninstructions: '{{ repo }}'\nprompt: go\n",
        )
        loader = TaskLoader()
        tasks = loader.load_component(tmp_path, {"repo": "myrepo"})
        assert tasks[0].instructions == "myrepo"
        assert tasks[1].instructions == "myrepo"
