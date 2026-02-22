from __future__ import annotations

from importlib.resources import files
from pathlib import Path


BUILTIN_COMPONENTS = {"dev", "qa", "judge", "docs"}


class ComponentNotFoundError(Exception):
    pass


def resolve_component(name_or_path: str) -> Path:
    if "/" in name_or_path or name_or_path.startswith("."):
        path = Path(name_or_path).resolve()
        if not path.is_dir():
            raise ComponentNotFoundError(f"Directory not found: {path}")
        tasks_subdir = path / "tasks"
        scan_dir = tasks_subdir if tasks_subdir.is_dir() else path
        yaml_files = list(scan_dir.glob("*.yaml")) + list(scan_dir.glob("*.yml"))
        if not yaml_files:
            raise ComponentNotFoundError(f"No task YAML files in: {path}")
        return path

    if name_or_path in BUILTIN_COMPONENTS:
        resource = files("dkmv.builtins").joinpath(name_or_path)
        path = Path(str(resource))
        if not path.is_dir():
            raise ComponentNotFoundError(
                f"Built-in component '{name_or_path}' package directory not found: {path}"
            )
        return path

    raise ComponentNotFoundError(
        f"Unknown component '{name_or_path}'. "
        f"Available built-ins: {', '.join(sorted(BUILTIN_COMPONENTS))}"
    )
