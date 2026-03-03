"""Component registry — manage custom components in .dkmv/components.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from dkmv.tasks.discovery import BUILTIN_COMPONENTS

_BUILTIN_DESCRIPTIONS: dict[str, str] = {
    "dev": "Plan and implement features from a PRD",
    "plan": "Convert a PRD into implementation documents",
    "qa": "Evaluate, fix, and re-evaluate implementation quality",
    "docs": "Generate documentation",
}


@dataclass
class ComponentInfo:
    name: str
    component_type: str  # "built-in" or "custom"
    path: Path | None
    task_count: int
    description: str
    valid: bool = True


class ComponentRegistry:
    @staticmethod
    def load(project_root: Path) -> dict[str, str]:
        """Load component registry. Returns empty dict if not initialized."""
        path = project_root / ".dkmv" / "components.json"
        if not path.exists():
            return {}
        data: dict[str, str] = json.loads(path.read_text())
        return data

    @staticmethod
    def save(project_root: Path, registry: dict[str, str]) -> None:
        """Write component registry to .dkmv/components.json."""
        path = project_root / ".dkmv" / "components.json"
        path.write_text(json.dumps(registry, indent=2) + "\n")

    @staticmethod
    def register(
        project_root: Path,
        name: str,
        component_path: str,
        *,
        force: bool = False,
    ) -> Path:
        """Register a component. Returns resolved path. Raises ValueError on error."""
        if name in BUILTIN_COMPONENTS:
            raise ValueError(f"Cannot register '{name}': conflicts with built-in component.")

        registry = ComponentRegistry.load(project_root)
        if name in registry and not force:
            raise ValueError(f"Component '{name}' is already registered. Use --force to override.")

        # Resolve path
        path = Path(component_path)
        if not path.is_absolute():
            path = (project_root / path).resolve()

        # Prevent path traversal outside project root
        try:
            path.relative_to(project_root.resolve())
        except ValueError:
            raise ValueError(
                f"Component path must be within the project root: {path} "
                f"is outside {project_root.resolve()}"
            )

        if not path.is_dir():
            raise ValueError(f"Not a directory: {path}")

        # Check for YAML files
        yaml_files = list(path.glob("*.yaml")) + list(path.glob("*.yml"))
        tasks_subdir = path / "tasks"
        if tasks_subdir.is_dir():
            yaml_files.extend(tasks_subdir.glob("*.yaml"))
            yaml_files.extend(tasks_subdir.glob("*.yml"))
        if not yaml_files:
            raise ValueError(f"No YAML task files found in: {path}")

        # Store the original path (may be relative)
        registry[name] = component_path
        ComponentRegistry.save(project_root, registry)
        return path

    @staticmethod
    def unregister(project_root: Path, name: str) -> None:
        """Remove a component from the registry."""
        registry = ComponentRegistry.load(project_root)
        if name not in registry:
            raise ValueError(f"Component '{name}' is not registered.")
        del registry[name]
        ComponentRegistry.save(project_root, registry)

    @staticmethod
    def list_all(project_root: Path | None = None) -> list[ComponentInfo]:
        """List all components (built-in + registered)."""
        from dkmv.tasks.discovery import resolve_component

        components: list[ComponentInfo] = []

        # Built-ins (always present)
        for name in sorted(BUILTIN_COMPONENTS):
            try:
                path = resolve_component(name)
                yaml_files = list(path.glob("*.yaml")) + list(path.glob("*.yml"))
                task_count = len(yaml_files)
            except Exception:
                path = None
                task_count = 0
            components.append(
                ComponentInfo(
                    name=name,
                    component_type="built-in",
                    path=path,
                    task_count=task_count,
                    description=_BUILTIN_DESCRIPTIONS.get(name, ""),
                )
            )

        # Registered components (only if project_root provided)
        if project_root:
            registry = ComponentRegistry.load(project_root)
            for name, stored_path in sorted(registry.items()):
                path = Path(stored_path)
                if not path.is_absolute():
                    path = (project_root / path).resolve()

                valid = True
                task_count = 0
                if path.is_dir():
                    yaml_files = list(path.glob("*.yaml")) + list(path.glob("*.yml"))
                    tasks_subdir = path / "tasks"
                    if tasks_subdir.is_dir():
                        yaml_files.extend(tasks_subdir.glob("*.yaml"))
                        yaml_files.extend(tasks_subdir.glob("*.yml"))
                    task_count = len(yaml_files)
                else:
                    valid = False

                components.append(
                    ComponentInfo(
                        name=name,
                        component_type="custom",
                        path=path,
                        task_count=task_count,
                        description=stored_path,
                        valid=valid,
                    )
                )

        return components
