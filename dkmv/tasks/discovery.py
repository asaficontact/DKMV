from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path


BUILTIN_COMPONENTS = {"dev", "qa", "docs", "plan", "ship"}


class ComponentNotFoundError(Exception):
    pass


def resolve_component(name_or_path: str, project_root: Path | None = None) -> Path:
    # Step 1: Path check (unchanged)
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

    # Step 2: Built-in check (unchanged)
    if name_or_path in BUILTIN_COMPONENTS:
        resource = files("dkmv.builtins").joinpath(name_or_path)
        path = Path(str(resource))
        if not path.is_dir():
            raise ComponentNotFoundError(
                f"Built-in component '{name_or_path}' package directory not found: {path}"
            )
        return path

    # Step 3: Registry check (NEW)
    registry: dict[str, str] = {}
    if project_root:
        registry_path = project_root / ".dkmv" / "components.json"
        if registry_path.exists():
            registry = json.loads(registry_path.read_text())
            if name_or_path in registry:
                path = Path(registry[name_or_path])
                if not path.is_absolute():
                    path = (project_root / path).resolve()
                if not path.is_dir():
                    raise ComponentNotFoundError(
                        f"Registered component '{name_or_path}' path not found: {path}"
                    )
                yaml_files = list(path.glob("*.yaml")) + list(path.glob("*.yml"))
                tasks_subdir = path / "tasks"
                if tasks_subdir.is_dir():
                    yaml_files.extend(tasks_subdir.glob("*.yaml"))
                    yaml_files.extend(tasks_subdir.glob("*.yml"))
                if not yaml_files:
                    raise ComponentNotFoundError(
                        f"Registered component '{name_or_path}' has no YAML files: {path}"
                    )
                return path

    # Step 4: Error with full list
    available = sorted(BUILTIN_COMPONENTS)
    available.extend(sorted(registry.keys()))
    raise ComponentNotFoundError(
        f"Unknown component '{name_or_path}'. Available: {', '.join(available)}"
    )
