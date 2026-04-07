"""Introspection API — inspect components and tasks without execution."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

import yaml

import jinja2

from dkmv.tasks.discovery import BUILTIN_COMPONENTS, resolve_component
from dkmv.tasks.loader import TaskLoadError, TaskLoader
from dkmv.tasks.manifest import ComponentManifest
from dkmv.tasks.models import TaskDefinition

# Lenient Jinja2 env that renders missing variables as empty strings
# instead of raising UndefinedError — used for read-only introspection.
_LENIENT_JINJA = jinja2.Environment(
    undefined=jinja2.Undefined,
    keep_trailing_newline=True,
)


class TaskInfo(BaseModel):
    """Metadata about a single task, extracted from its YAML definition."""

    name: str
    description: str = ""
    agent: str | None = None
    model: str | None = None
    max_turns: int | None = None
    timeout_minutes: int | None = None
    has_prompt: bool = False
    has_instructions: bool = False
    input_count: int = 0
    output_count: int = 0
    commit: bool = True
    push: bool = True
    source_path: Path = Path(".")
    prompt: str | None = None
    instructions: str | None = None
    inputs: list[dict[str, object]] = []
    outputs: list[dict[str, object]] = []
    max_budget_usd: float | None = None


class ComponentInfo(BaseModel):
    """Metadata about a component and its tasks."""

    name: str
    description: str = ""
    path: Path
    is_builtin: bool = False
    agent: str | None = None
    model: str | None = None
    task_count: int = 0
    tasks: list[TaskInfo] = []
    has_manifest: bool = False
    deliverables: list[str] = []
    manifest_inputs: list[dict[str, object]] = []
    workspace_dirs: list[str] = []
    state_files: list[dict[str, object]] = []
    agent_md: str | None = None


class ValidationResult(BaseModel):
    """Result of validating a component or task."""

    valid: bool
    errors: list[str] = []
    warnings: list[str] = []


def _task_def_to_info(task: TaskDefinition, source_path: Path) -> TaskInfo:
    """Convert a loaded TaskDefinition to a TaskInfo."""
    return TaskInfo(
        name=task.name,
        description=task.description,
        agent=task.agent,
        model=task.model,
        max_turns=task.max_turns,
        timeout_minutes=task.timeout_minutes,
        has_prompt=task.prompt is not None or task.prompt_file is not None,
        has_instructions=task.instructions is not None or task.instructions_file is not None,
        input_count=len(task.inputs),
        output_count=len(task.outputs),
        commit=task.commit,
        push=task.push,
        source_path=source_path,
        prompt=task.prompt,
        instructions=task.instructions,
        inputs=[inp.model_dump(mode="json") for inp in task.inputs],
        outputs=[out.model_dump(mode="json") for out in task.outputs],
        max_budget_usd=task.max_budget_usd,
    )


def _load_manifest_raw(manifest_path: Path) -> ComponentManifest | None:
    """Parse manifest YAML without Jinja2/Pydantic validation.

    Used as fallback when the manifest requires variables we don't have.
    Extracts only the fields safe to read without template rendering.
    """
    try:
        raw = yaml.safe_load(manifest_path.read_text()) or {}
    except Exception:
        return None

    from dkmv.tasks.manifest import ManifestDeliverable, ManifestTaskRef

    tasks = []
    for t in raw.get("tasks", []):
        if isinstance(t, dict) and "file" in t:
            tasks.append(
                ManifestTaskRef(
                    file=t["file"],
                    agent=t.get("agent"),
                    model=t.get("model"),
                    max_turns=t.get("max_turns"),
                    timeout_minutes=t.get("timeout_minutes"),
                    max_budget_usd=t.get("max_budget_usd"),
                    pause_after=t.get("pause_after", False),
                    for_each=t.get("for_each"),
                )
            )

    deliverables = []
    for d in raw.get("deliverables", []):
        if isinstance(d, dict) and "path" in d:
            deliverables.append(
                ManifestDeliverable(path=d["path"], required=d.get("required", True))
            )

    return ComponentManifest(
        name=raw.get("name", manifest_path.parent.name),
        description=raw.get("description", ""),
        agent=raw.get("agent"),
        model=raw.get("model"),
        max_turns=raw.get("max_turns"),
        timeout_minutes=raw.get("timeout_minutes"),
        max_budget_usd=raw.get("max_budget_usd"),
        tasks=tasks,
        deliverables=deliverables,
    )


def _make_loader(variables: dict[str, str] | None) -> TaskLoader:
    """Create a TaskLoader, using lenient Jinja2 if no variables provided."""
    if variables:
        return TaskLoader()
    return TaskLoader(jinja_env=_LENIENT_JINJA)


def inspect_task(
    task_path: Path,
    variables: dict[str, str] | None = None,
) -> TaskInfo:
    """Inspect a single task YAML file and return its metadata."""
    loader = _make_loader(variables)
    task = loader.load(task_path, variables or {})
    return _task_def_to_info(task, task_path)


def inspect_component(
    name_or_path: str,
    project_root: Path | None = None,
    variables: dict[str, str] | None = None,
) -> ComponentInfo:
    """Inspect a component and return its metadata including all tasks."""
    component_dir = resolve_component(name_or_path, project_root)
    loader = _make_loader(variables)
    vars_ = variables or {}

    is_builtin = name_or_path in BUILTIN_COMPONENTS

    manifest: ComponentManifest | None = None
    manifest_path = component_dir / "component.yaml"
    if not manifest_path.exists():
        manifest_path = component_dir / "component.yml"
    if manifest_path.exists():
        try:
            manifest = loader.load_manifest(manifest_path, vars_)
        except TaskLoadError:
            # Manifest has Jinja2 variables that need specific values to validate.
            # Fall back to raw YAML parsing for metadata extraction.
            manifest = _load_manifest_raw(manifest_path)

    tasks: list[TaskInfo] = []
    if manifest:
        for ref in manifest.tasks:
            task_path = component_dir / ref.file
            try:
                task_def = loader.load(task_path, vars_)
                tasks.append(_task_def_to_info(task_def, task_path))
            except (TaskLoadError, Exception):
                tasks.append(TaskInfo(name=ref.file, source_path=task_path))
    else:
        task_defs = loader.load_component(component_dir, vars_)
        for td in task_defs:
            tasks.append(_task_def_to_info(td, component_dir))

    deliverables: list[str] = []
    if manifest and manifest.deliverables:
        deliverables = [d.path for d in manifest.deliverables]

    manifest_inputs: list[dict[str, object]] = []
    workspace_dirs: list[str] = []
    state_files: list[dict[str, object]] = []
    agent_md: str | None = None

    if manifest:
        manifest_inputs = [inp.model_dump(mode="json") for inp in manifest.inputs]
        workspace_dirs = list(manifest.workspace_dirs)
        state_files = [sf.model_dump(mode="json") for sf in manifest.state_files]
        agent_md = manifest.agent_md

    return ComponentInfo(
        name=manifest.name if manifest else name_or_path,
        description=manifest.description if manifest else "",
        path=component_dir,
        is_builtin=is_builtin,
        agent=manifest.agent if manifest else None,
        model=manifest.model if manifest else None,
        task_count=len(tasks),
        tasks=tasks,
        has_manifest=manifest is not None,
        deliverables=deliverables,
        manifest_inputs=manifest_inputs,
        workspace_dirs=workspace_dirs,
        state_files=state_files,
        agent_md=agent_md,
    )


def validate_component(
    name_or_path: str,
    project_root: Path | None = None,
    variables: dict[str, str] | None = None,
) -> ValidationResult:
    """Validate a component by attempting to load all its tasks.

    Returns a ValidationResult with errors and warnings.
    """
    errors: list[str] = []
    warnings: list[str] = []

    try:
        component_dir = resolve_component(name_or_path, project_root)
    except Exception as e:
        return ValidationResult(valid=False, errors=[str(e)])

    loader = _make_loader(variables)
    vars_ = variables or {}

    manifest_path = component_dir / "component.yaml"
    if not manifest_path.exists():
        manifest_path = component_dir / "component.yml"

    if manifest_path.exists():
        manifest: ComponentManifest | None = None
        try:
            manifest = loader.load_manifest(manifest_path, vars_)
        except TaskLoadError:
            # Manifest requires variables — fall back to raw parsing
            manifest = _load_manifest_raw(manifest_path)
            if manifest is None:
                return ValidationResult(valid=False, errors=["Cannot parse manifest"])
            if not variables:
                warnings.append(
                    "Manifest uses template variables; full validation requires variables"
                )

        if not manifest.tasks:
            warnings.append("Component manifest has no tasks defined")

        for ref in manifest.tasks:
            task_path = component_dir / ref.file
            if not task_path.exists():
                errors.append(f"Task file not found: {ref.file}")
                continue
            try:
                loader.load(task_path, vars_)
            except TaskLoadError as e:
                cause = e.__cause__
                is_template_error = isinstance(cause, (jinja2.UndefinedError, ValueError))
                if not variables and is_template_error:
                    warnings.append(f"Task '{ref.file}' needs variables for full validation")
                else:
                    errors.append(f"Task '{ref.file}': {e}")
    else:
        warnings.append("No component.yaml manifest found")
        try:
            task_defs = loader.load_component(component_dir, vars_)
            if not task_defs:
                warnings.append("No task YAML files found in component directory")
        except TaskLoadError as e:
            errors.append(str(e))

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def list_components(
    project_root: Path | None = None,
    variables: dict[str, str] | None = None,
) -> list[ComponentInfo]:
    """List all available components (built-in + registered)."""
    from dkmv.registry import ComponentRegistry

    components: list[ComponentInfo] = []
    vars_ = variables or {}

    for name in sorted(BUILTIN_COMPONENTS):
        try:
            info = inspect_component(name, project_root, vars_)
            components.append(info)
        except Exception:
            component_dir = resolve_component(name)
            components.append(ComponentInfo(name=name, path=component_dir, is_builtin=True))

    if project_root:
        registry = ComponentRegistry.load(project_root)
        for name in sorted(registry):
            try:
                info = inspect_component(name, project_root, vars_)
                components.append(info)
            except Exception:
                stored_path = registry[name]
                path = Path(stored_path)
                if not path.is_absolute():
                    path = (project_root / path).resolve()
                components.append(ComponentInfo(name=name, path=path, is_builtin=False))

    return components


class ResolvedStep(BaseModel):
    """A single step in a resolved execution plan."""

    index: int
    task_name: str
    task_file: str
    description: str = ""
    agent: str | None = None
    model: str | None = None
    max_turns: int | None = None
    timeout_minutes: int | None = None
    pause_after: bool = False
    for_each_item: str | None = None
    for_each_index: int | None = None
    skipped: bool = False
    skip_reason: str = ""


class ExecutionPlan(BaseModel):
    """Resolved execution plan showing what will actually run."""

    component_name: str
    component_path: Path
    total_steps: int
    steps: list[ResolvedStep]
    start_offset: int = 0
    warnings: list[str] = []


def preview_execution_plan(
    name_or_path: str,
    variables: dict[str, str] | None = None,
    project_root: Path | None = None,
    start_task: str | None = None,
) -> ExecutionPlan:
    """Preview the resolved execution plan after for_each expansion and start_task offset.

    This shows hosts exactly which steps will run and in what order,
    without actually executing anything.
    """
    component_dir = resolve_component(name_or_path, project_root)
    loader = _make_loader(variables)
    vars_ = variables or {}
    warnings: list[str] = []

    manifest: ComponentManifest | None = None
    manifest_path = component_dir / "component.yaml"
    if not manifest_path.exists():
        manifest_path = component_dir / "component.yml"
    if manifest_path.exists():
        try:
            manifest = loader.load_manifest(manifest_path, vars_)
        except TaskLoadError:
            manifest = _load_manifest_raw(manifest_path)
            if manifest and not variables:
                warnings.append("Manifest uses template variables; plan may be approximate")

    steps: list[ResolvedStep] = []
    step_index = 0

    if manifest and manifest.tasks:
        for ref in manifest.tasks:
            if ref.for_each:
                items: list[str] = vars_.get(ref.for_each, [])  # type: ignore[assignment]
                if isinstance(items, list) and items:
                    for idx, item in enumerate(items):
                        task_info = _try_load_task_info(loader, component_dir / ref.file, vars_)
                        steps.append(
                            ResolvedStep(
                                index=step_index,
                                task_name=task_info.name if task_info else ref.file,
                                task_file=ref.file,
                                description=task_info.description if task_info else "",
                                agent=ref.agent or (manifest.agent if manifest else None),
                                model=ref.model or (manifest.model if manifest else None),
                                max_turns=ref.max_turns,
                                timeout_minutes=ref.timeout_minutes,
                                pause_after=ref.pause_after,
                                for_each_item=str(item),
                                for_each_index=idx,
                            )
                        )
                        step_index += 1
                else:
                    warnings.append(
                        f"for_each '{ref.for_each}' variable not provided or empty; "
                        f"task '{ref.file}' will have 0 instances"
                    )
            else:
                task_info = _try_load_task_info(loader, component_dir / ref.file, vars_)
                steps.append(
                    ResolvedStep(
                        index=step_index,
                        task_name=task_info.name if task_info else ref.file,
                        task_file=ref.file,
                        description=task_info.description if task_info else "",
                        agent=ref.agent or (manifest.agent if manifest else None),
                        model=ref.model or (manifest.model if manifest else None),
                        max_turns=ref.max_turns,
                        timeout_minutes=ref.timeout_minutes,
                        pause_after=ref.pause_after,
                    )
                )
                step_index += 1
    else:
        # No manifest — scan YAML files
        try:
            task_defs = loader.load_component(component_dir, vars_)
            for td in task_defs:
                steps.append(
                    ResolvedStep(
                        index=step_index,
                        task_name=td.name,
                        task_file="",
                        description=td.description,
                        agent=td.agent,
                        model=td.model,
                        max_turns=td.max_turns,
                        timeout_minutes=td.timeout_minutes,
                    )
                )
                step_index += 1
        except TaskLoadError:
            warnings.append("Could not load tasks; variables may be required")

    # Apply start_task offset
    start_offset = 0
    if start_task and steps:
        for i, step in enumerate(steps):
            if step.task_name == start_task or step.task_file == start_task:
                start_offset = i
                break
        else:
            warnings.append(f"start_task '{start_task}' not found in execution plan")

        for i in range(start_offset):
            steps[i].skipped = True
            steps[i].skip_reason = "before start_task"

    return ExecutionPlan(
        component_name=manifest.name if manifest else name_or_path,
        component_path=component_dir,
        total_steps=len([s for s in steps if not s.skipped]),
        steps=steps,
        start_offset=start_offset,
        warnings=warnings,
    )


def _try_load_task_info(
    loader: TaskLoader, task_path: Path, variables: dict[str, str]
) -> TaskInfo | None:
    """Try to load a task for introspection; return None on failure."""
    try:
        task_def = loader.load(task_path, variables)
        return _task_def_to_info(task_def, task_path)
    except Exception:
        return None
