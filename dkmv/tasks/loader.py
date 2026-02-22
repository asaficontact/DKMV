from __future__ import annotations

from pathlib import Path
from typing import Any

import jinja2
import yaml
from pydantic import ValidationError

from dkmv.tasks.models import TaskDefinition


class TaskLoadError(Exception):
    def __init__(self, message: str, task_path: Path | None = None):
        self.task_path = task_path
        super().__init__(f"{task_path}: {message}" if task_path else message)


class TaskLoader:
    def __init__(self, jinja_env: jinja2.Environment | None = None):
        self._jinja_env = jinja_env or jinja2.Environment(
            undefined=jinja2.StrictUndefined,
            keep_trailing_newline=True,
        )

    def load(self, task_path: Path, variables: dict[str, Any]) -> TaskDefinition:
        raw = task_path.read_text()

        try:
            rendered = self._jinja_env.from_string(raw).render(variables)
        except jinja2.UndefinedError as e:
            raise TaskLoadError(str(e), task_path) from e

        try:
            data = yaml.safe_load(rendered)
        except yaml.YAMLError as e:
            raise TaskLoadError(str(e), task_path) from e

        try:
            task = TaskDefinition.model_validate(data)
        except ValidationError as e:
            raise TaskLoadError(str(e), task_path) from e

        self._resolve_file_refs(task, task_path.parent, variables)
        return task

    def _resolve_file_refs(
        self, task: TaskDefinition, base_dir: Path, variables: dict[str, Any]
    ) -> None:
        if task.prompt_file is not None:
            path = (base_dir / task.prompt_file).resolve()
            if not path.is_file():
                raise TaskLoadError(f"prompt_file not found: {path}", None)
            content = path.read_text()
            try:
                rendered = self._jinja_env.from_string(content).render(variables)
            except jinja2.UndefinedError as e:
                raise TaskLoadError(f"In prompt_file {path}: {e}", None) from e
            task.prompt = rendered
            task.prompt_file = None

        if task.instructions_file is not None:
            path = (base_dir / task.instructions_file).resolve()
            if not path.is_file():
                raise TaskLoadError(f"instructions_file not found: {path}", None)
            content = path.read_text()
            try:
                rendered = self._jinja_env.from_string(content).render(variables)
            except jinja2.UndefinedError as e:
                raise TaskLoadError(f"In instructions_file {path}: {e}", None) from e
            task.instructions = rendered
            task.instructions_file = None

    def load_component(
        self, component_dir: Path, variables: dict[str, Any]
    ) -> list[TaskDefinition]:
        tasks_subdir = component_dir / "tasks"
        scan_dir = tasks_subdir if tasks_subdir.is_dir() else component_dir
        yaml_files = sorted(
            p for p in scan_dir.iterdir() if p.suffix in (".yaml", ".yml") and p.is_file()
        )
        return [self.load(f, variables) for f in yaml_files]
