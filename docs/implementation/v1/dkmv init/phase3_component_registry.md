# Phase 3: Component Registry

## Prerequisites

- Phase 1 complete: `ProjectConfig`, `find_project_root()`, `load_project_config()` working
- Phase 2 complete: `dkmv init` creates `.dkmv/` with `config.json` and `components.json`
- All quality gates passing

## Phase Goal

Custom components can be registered by name, listed alongside built-ins, and resolved by `resolve_component()`. The `dkmv components`, `dkmv register`, and `dkmv unregister` commands are operational.

## Phase Evaluation Criteria

- `dkmv register strict-judge ./path/to/component` adds entry to `.dkmv/components.json`
- `dkmv unregister strict-judge` removes entry
- `dkmv components` shows both built-in and registered components in a Rich table
- `resolve_component("strict-judge", project_root=...)` returns the registered path
- Built-in names (`dev`, `qa`, `judge`, `docs`) cannot be registered
- Invalid paths rejected at registration time
- Stale/missing paths show warnings in `dkmv components`
- `dkmv components` works without init (shows only built-ins)
- `uv run pytest tests/unit/test_registry.py tests/unit/test_discovery.py -v` — all pass
- `uv run ruff check . && uv run ruff format --check . && uv run mypy dkmv/` — clean
- All existing tests still pass

---

## Tasks

### T220: Create `ComponentRegistry` Class

**PRD Reference:** Section 6.4 (Component Registry)
**Depends on:** Nothing (standalone class)
**Blocks:** T221, T222, T223, T224
**User Stories:** US-03

#### Description

Create `ComponentRegistry` class that loads/saves `.dkmv/components.json` and provides register/unregister/list operations.

#### Acceptance Criteria

- [x] `load(project_root)` reads `.dkmv/components.json`, returns `dict[str, str]` (name → path)
- [x] `save(project_root, registry)` writes `.dkmv/components.json`
- [x] `register(project_root, name, path)` adds entry with validation
- [x] `register(..., force=True)` overwrites existing entry without error
- [x] `unregister(project_root, name)` removes entry
- [x] `list_all(project_root)` returns both built-in and registered components
- [x] Validation: name not in built-ins, path is directory, path has YAML files
- [x] Relative paths stored as-is (resolved at runtime relative to project root)

#### Files to Create/Modify

- `dkmv/registry.py` — (create) ComponentRegistry class

#### Implementation Notes

```python
import json
from pathlib import Path
from dataclasses import dataclass
from dkmv.tasks.discovery import BUILTIN_COMPONENTS

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
        return json.loads(path.read_text())

    @staticmethod
    def save(project_root: Path, registry: dict[str, str]) -> None:
        path = project_root / ".dkmv" / "components.json"
        path.write_text(json.dumps(registry, indent=2) + "\n")

    @staticmethod
    def register(
        project_root: Path, name: str, component_path: str, *, force: bool = False,
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
```

#### Evaluation Checklist

- [x] Register/unregister round-trips correctly
- [x] Built-in names rejected
- [x] Invalid paths rejected
- [x] YAML file validation works

---

### T221: Modify `resolve_component()` with Registry Lookup

**PRD Reference:** Section 6.4 (Modified `resolve_component()` cascade)
**Depends on:** T220
**Blocks:** Nothing
**User Stories:** US-03

#### Description

Add registry lookup as step 3 in `resolve_component()` — after path check and built-in check, before error.

#### Acceptance Criteria

- [x] `resolve_component(name, project_root=path)` checks registry after built-ins
- [x] Relative paths in registry resolved relative to project root
- [x] Registry lookup only when `project_root` is provided
- [x] Error message lists registered components alongside built-ins
- [x] Backward compatible: existing callers without `project_root` work unchanged

#### Files to Create/Modify

- `dkmv/tasks/discovery.py` — (modify) Add `project_root` parameter and registry lookup

#### Implementation Notes

Add the optional parameter and registry check:

```python
def resolve_component(name_or_path: str, project_root: Path | None = None) -> Path:
    # Step 1: Path check (unchanged)
    if "/" in name_or_path or name_or_path.startswith("."):
        # ... existing path resolution ...

    # Step 2: Built-in check (unchanged)
    if name_or_path in BUILTIN_COMPONENTS:
        # ... existing built-in resolution ...

    # Step 3: Registry check (NEW)
    if project_root:
        registry_path = project_root / ".dkmv" / "components.json"
        if registry_path.exists():
            import json
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
                if not yaml_files:
                    raise ComponentNotFoundError(
                        f"Registered component '{name_or_path}' has no YAML files: {path}"
                    )
                return path

    # Step 4: Error with full list
    available = sorted(BUILTIN_COMPONENTS)
    if project_root:
        registry_path = project_root / ".dkmv" / "components.json"
        if registry_path.exists():
            import json
            registry = json.loads(registry_path.read_text())
            available.extend(sorted(registry.keys()))
    raise ComponentNotFoundError(
        f"Unknown component '{name_or_path}'. Available: {', '.join(available)}"
    )
```

#### Evaluation Checklist

- [x] Registered component resolved correctly
- [x] Relative paths resolved from project root
- [x] Error message includes registered names
- [x] Existing callers unaffected (no `project_root`)

---

### T222: Implement `dkmv components` Command

**PRD Reference:** Section 6.5 (`dkmv components` Command)
**Depends on:** T220
**Blocks:** Nothing
**User Stories:** US-06

#### Description

Implement the `dkmv components` CLI command that lists all available components in a Rich table.

#### Acceptance Criteria

- [x] Shows all 4 built-in components (always, even without init)
- [x] Shows registered components when `.dkmv/components.json` exists
- [x] Rich table with columns: Name, Type, Tasks, Description
- [x] Built-in type shows "built-in", custom shows "custom"
- [x] Task count is the number of YAML files in the component directory
- [x] Invalid/missing registered paths show warning indicator
- [x] Footer shows count: "4 built-in, N custom"

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) Add `components` command

#### Implementation Notes

```python
@app.command()
def components() -> None:
    """List all available components (built-in and registered)."""
    from dkmv.registry import ComponentRegistry, ComponentInfo
    from dkmv.project import find_project_root

    project_root = find_project_root()
    # Build component list using registry...
    # Display Rich table...
```

For built-in descriptions, use a constant dict:
```python
_BUILTIN_DESCRIPTIONS = {
    "dev": "Plan and implement features from a PRD",
    "qa": "Test and validate implementation",
    "judge": "Evaluate quality with pass/fail verdict",
    "docs": "Generate documentation",
}
```

#### Evaluation Checklist

- [x] `dkmv components` works without init
- [x] Shows built-in + registered after init
- [x] Rich table formatting correct

---

### T223: Implement `dkmv register` Command

**PRD Reference:** Section 6.6 (`dkmv register`)
**Depends on:** T220
**Blocks:** Nothing
**User Stories:** US-03

#### Description

Implement the `dkmv register <name> <path>` CLI command.

#### Acceptance Criteria

- [x] Validates init required (`.dkmv/` must exist)
- [x] Validates name not a built-in
- [x] Validates path is a directory with YAML files
- [x] Rejects already-registered name unless `--force` is passed
- [x] `--force` overwrites existing registration without error
- [x] Adds to `.dkmv/components.json`
- [x] Shows success message with task count

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) Add `register` command

#### Implementation Notes

```python
@app.command()
def register(
    name: Annotated[str, typer.Argument(help="Short name for the component.")],
    path: Annotated[str, typer.Argument(help="Path to component directory.")],
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite existing registration.")
    ] = False,
) -> None:
    """Register a custom component by name."""
    from dkmv.project import find_project_root
    from dkmv.registry import ComponentRegistry

    project_root = find_project_root()
    if not (project_root / ".dkmv").exists():
        console.print("Error: DKMV not initialized. Run 'dkmv init' first.", style="bold red")
        raise typer.Exit(code=1)

    try:
        resolved_path = ComponentRegistry.register(project_root, name, path, force=force)
    except ValueError as e:
        console.print(f"Error: {e}", style="bold red")
        raise typer.Exit(code=1)

    yaml_files = list(resolved_path.glob("*.yaml")) + list(resolved_path.glob("*.yml"))
    tasks_subdir = resolved_path / "tasks"
    if tasks_subdir.is_dir():
        yaml_files.extend(tasks_subdir.glob("*.yaml"))
        yaml_files.extend(tasks_subdir.glob("*.yml"))
    yaml_count = len(yaml_files)
    console.print(
        f"Registered '{name}' → {resolved_path} ({yaml_count} task{'s' if yaml_count != 1 else ''})"
    )
```

#### Evaluation Checklist

- [x] `dkmv register strict-judge ./path` succeeds
- [x] `dkmv register strict-judge ./new-path --force` overwrites existing
- [x] Error when not initialized
- [x] Error when name is a built-in
- [x] Error when path is invalid
- [x] Error when name already registered (without `--force`)

---

### T224: Implement `dkmv unregister` Command

**PRD Reference:** Section 6.6 (`dkmv unregister`)
**Depends on:** T220
**Blocks:** Nothing
**User Stories:** US-03

#### Description

Implement the `dkmv unregister <name>` CLI command.

#### Acceptance Criteria

- [x] Removes entry from `.dkmv/components.json`
- [x] Error when component not registered
- [x] Error when not initialized
- [x] Shows success message

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) Add `unregister` command

#### Implementation Notes

```python
@app.command()
def unregister(
    name: Annotated[str, typer.Argument(help="Component name to unregister.")],
) -> None:
    """Unregister a custom component."""
    from dkmv.project import find_project_root
    from dkmv.registry import ComponentRegistry

    project_root = find_project_root()
    if not (project_root / ".dkmv").exists():
        console.print("Error: DKMV not initialized. Run 'dkmv init' first.", style="bold red")
        raise typer.Exit(code=1)

    try:
        ComponentRegistry.unregister(project_root, name)
    except ValueError as e:
        console.print(f"Error: {e}", style="bold red")
        raise typer.Exit(code=1)

    console.print(f"Unregistered '{name}'")
```

#### Evaluation Checklist

- [x] Removes component from registry
- [x] Error for unregistered names
- [x] Error when not initialized

---

### T225: Update Error Messages in `resolve_component()`

**PRD Reference:** Section 6.4 (Error messages)
**Depends on:** T221
**Blocks:** Nothing
**User Stories:** US-03

#### Description

This is handled in T221. This task verifies the error messages include registered components.

#### Acceptance Criteria

- [x] Error message for unknown component lists built-ins AND registered names
- [x] Stale registry entries (missing paths) produce clear errors

#### Files to Create/Modify

- `dkmv/tasks/discovery.py` — (verified in T221)

#### Evaluation Checklist

- [x] Error message includes all available component names
- [x] Stale paths produce `ComponentNotFoundError` with path info

---

### T226: Write Registry and Discovery Tests

**PRD Reference:** Section 8 (Testing Strategy)
**Depends on:** T220-T225
**Blocks:** Nothing
**User Stories:** N/A (testing)
**Estimated scope:** 1 hour

#### Description

Write tests for ComponentRegistry, modified `resolve_component()`, and CLI commands.

#### Acceptance Criteria

- [x] ~20 tests for ComponentRegistry
- [x] ~5 tests for modified `resolve_component()`
- [x] ~5 tests for CLI commands (`components`, `register`, `unregister`)
- [x] Registry: register, unregister, list, built-in name rejection, invalid path, missing YAML, --force overwrite
- [x] Discovery: registered component resolved, relative paths, stale paths, error messages
- [x] CLI: CliRunner tests for all 3 commands

#### Files to Create/Modify

- `tests/unit/test_registry.py` — (create) ~20 registry tests
- `tests/unit/test_discovery.py` — (modify) Add ~5 registry-aware tests

#### Implementation Notes

```python
def test_register_component(tmp_path):
    """Register a custom component."""
    dkmv_dir = tmp_path / ".dkmv"
    dkmv_dir.mkdir()
    (dkmv_dir / "components.json").write_text("{}")

    comp_dir = tmp_path / "my-component"
    comp_dir.mkdir()
    (comp_dir / "01-task.yaml").write_text("name: test")

    path = ComponentRegistry.register(tmp_path, "my-comp", str(comp_dir))
    assert path == comp_dir

    registry = ComponentRegistry.load(tmp_path)
    assert "my-comp" in registry

def test_resolve_registered_component(tmp_path, monkeypatch):
    """resolve_component() finds registered components."""
    # Setup .dkmv/components.json with entry
    # Create component dir with YAML file
    path = resolve_component("my-comp", project_root=tmp_path)
    assert path.name == "my-component"
```

#### Evaluation Checklist

- [x] `uv run pytest tests/unit/test_registry.py tests/unit/test_discovery.py -v` — all pass
- [x] Full coverage of registry operations
- [x] No existing test regressions
