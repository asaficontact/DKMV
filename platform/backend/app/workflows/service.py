"""``WorkflowService`` — read-only pipeline introspection over ``RunService``.

This is the introspection adapter behind ``GET /workflows`` / ``GET /workflows/{id}``
(slice 4.1, F12 / PRD §5.8 FR-07-1v, §6.2). It consumes the locked DKMV engine
**in-process** through :class:`~app.runtime.RunService` — never the CLI, never a
``dkmv/`` edit (INV-13, ADR-P006) — and is strictly **read-only** (ADR-P010, N7):
no write/update endpoint, no manifest/task file written to disk, no registry add,
no validate-to-save. It only reads definitions already on disk.

Data sources (all read-only introspection):

* ``runtime.list_components()`` — the roster of **built-in + registry-added**
  components (so an on-disk custom component added to the project registry appears).
* ``runtime.inspect_component(id)`` — component name/description + per-task metadata.
* ``runtime.preview_execution_plan(id)`` — the **executed** stage ordering (incl.
  for-each expansion) and which stage **pauses after** (``pause_after``).
* the manifest + task ``*.yaml`` **text** (loaded via ``Path.read_text``) — the
  per-stage / total ``max_budget_usd`` (not surfaced on ``ComponentInfo``) and the
  "compiles to YAML" peek. Reading text is purely a read, never a mutation.

The **pipeline summary** carries: ordered ``stages`` (name, description, pause flag,
per-stage budget), the ``stage_count``, ``pause_count``, the ``pause_points`` (which
stages pause after), and the **est. total** budget. For ``qa`` this is **3 stages /
1 pause (after Evaluate) / $2.00 total** — the component-level ``max_budget_usd:
2.00`` is the authoritative total (PRD §7.2 FR-07-2); the per-stage split is
illustrative only.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dkmv.runtime import ComponentInfo, ExecutionPlan

    from app.runtime import RunService


class PipelineStage(BaseModel):
    """One ordered stage in a component's executed pipeline (a resolved step).

    Mirrors a ``ResolvedStep`` from the engine's execution plan: its display
    ``name``, ``description``, whether the pipeline **pauses after** it (a HITL
    decision point), and the per-stage ``budget_usd`` (illustrative; sourced from
    the task ref / task file when present — ``None`` when the component declares
    only a single component-level total).
    """

    index: int
    name: str
    description: str = ""
    pause_after: bool = False
    budget_usd: float | None = None
    for_each_item: str | None = None


class WorkflowSummary(BaseModel):
    """The pipeline summary for one component (the ``GET /workflows`` list entry).

    ``stages`` is the executed ordering (incl. for-each expansion). ``pause_points``
    lists the stage names that pause after (the HITL decision cards). ``est_total_usd``
    is the authoritative est. total — the component-level ``max_budget_usd`` when
    declared, else the sum of per-stage budgets (or ``None`` when neither is set).
    """

    id: str
    name: str
    description: str = ""
    is_builtin: bool = False
    agent: str | None = None
    model: str | None = None
    stages: list[PipelineStage]
    stage_count: int
    pause_count: int
    pause_points: list[str]
    est_total_usd: float | None = None


class WorkflowYaml(BaseModel):
    """A single read-only YAML document for the "compiles to YAML" peek.

    ``filename`` is the on-disk basename (``component.yaml`` or a task ``*.yaml``);
    ``content`` is its verbatim text. The viewer renders these read-only — there is
    no edit/save path in v1 (ADR-P010).
    """

    filename: str
    content: str


class WorkflowDetail(BaseModel):
    """``GET /workflows/{id}`` payload: the summary + the read-only YAML documents."""

    summary: WorkflowSummary
    component_yaml: WorkflowYaml | None = None
    task_yaml: list[WorkflowYaml]


class WorkflowNotFoundError(Exception):
    """Raised when an unknown component id is requested (maps to a 404 envelope)."""

    def __init__(self, workflow_id: str) -> None:
        super().__init__(f"Workflow {workflow_id!r} not found")
        self.workflow_id = workflow_id


# The two on-disk manifest basenames the engine accepts, in resolution order.
_MANIFEST_NAMES = ("component.yaml", "component.yml")


class WorkflowService:
    """Read-only introspection adapter over :class:`~app.runtime.RunService`.

    All engine access flows through the injected ``RunService`` (the single
    in-process seam, INV-13). The service performs **no** mutation: it lists,
    inspects, and previews components, and reads YAML **text** for the viewer.

    Args:
        run_service: The platform's configured :class:`RunService` (owns the
            in-process ``EmbeddedRuntime``).
        project_root: Optional project root passed to the engine introspection
            calls so on-disk **custom** components added to the project registry
            resolve (built-ins resolve without one).
    """

    def __init__(self, run_service: RunService, project_root: Path | None = None) -> None:
        self._run_service = run_service
        self._project_root = project_root

    # ── List / detail entry points ───────────────────────────────────────────

    def list_workflows(self) -> list[WorkflowSummary]:
        """Return the pipeline summary for every built-in + registry-added component.

        Backed by the engine's ``list_components()`` (built-ins + registry), then
        ``inspect_component`` / ``preview_execution_plan`` per component for the
        summary. Read-only.
        """
        runtime = self._run_service.runtime
        infos: list[ComponentInfo] = runtime.list_components(project_root=self._project_root)
        summaries: list[WorkflowSummary] = []
        for info in infos:
            summaries.append(self._summary_from(info.name, info))
        return summaries

    def get_workflow(self, workflow_id: str) -> WorkflowDetail:
        """Return the summary + read-only ``component.yaml`` + task YAML for one id.

        Raises :class:`WorkflowNotFoundError` (→ 404 ``workflow_not_found``) when
        the id resolves to no component on disk or in the registry.
        """
        runtime = self._run_service.runtime
        try:
            info = runtime.inspect_component(workflow_id, project_root=self._project_root)
        except Exception as exc:  # noqa: BLE001 - any resolution failure is a 404
            raise WorkflowNotFoundError(workflow_id) from exc

        summary = self._summary_from(workflow_id, info)
        component_yaml, task_yaml = self._read_yaml_docs(info)
        return WorkflowDetail(
            summary=summary,
            component_yaml=component_yaml,
            task_yaml=task_yaml,
        )

    # ── Summary assembly ─────────────────────────────────────────────────────

    def _summary_from(self, workflow_id: str, info: ComponentInfo) -> WorkflowSummary:
        """Build a :class:`WorkflowSummary` from inspect + plan + manifest budgets.

        The **executed ordering and pause points** come from
        ``preview_execution_plan`` (the plan applies for-each expansion); the
        per-stage / component-level **budgets** come from the parsed manifest
        (not surfaced on ``ComponentInfo``); the est. total prefers the
        component-level ``max_budget_usd`` (authoritative, §7.2) and otherwise
        sums the per-stage budgets.
        """
        manifest = self._load_manifest_data(info.path)
        component_budget = _as_float(manifest.get("max_budget_usd"))
        per_file_budget = _per_file_budgets(manifest)

        runtime = self._run_service.runtime
        plan: ExecutionPlan = runtime.preview_execution_plan(
            workflow_id, project_root=self._project_root
        )

        # Map task display-name → its task-file budget (from inspect_component).
        per_name_budget: dict[str, float | None] = {
            task.name: task.max_budget_usd for task in info.tasks
        }

        stages: list[PipelineStage] = []
        budget_sum = 0.0
        saw_stage_budget = False
        for step in plan.steps:
            if step.skipped:
                continue
            budget = per_file_budget.get(step.task_file)
            if budget is None:
                budget = per_name_budget.get(step.task_name)
            if budget is not None:
                budget_sum += budget
                saw_stage_budget = True
            stages.append(
                PipelineStage(
                    index=step.index,
                    name=step.task_name,
                    description=step.description,
                    pause_after=step.pause_after,
                    budget_usd=budget,
                    for_each_item=step.for_each_item,
                )
            )

        pause_points = [stage.name for stage in stages if stage.pause_after]
        est_total = component_budget
        if est_total is None and saw_stage_budget:
            est_total = budget_sum

        return WorkflowSummary(
            id=workflow_id,
            name=info.name,
            description=info.description,
            is_builtin=info.is_builtin,
            agent=info.agent,
            model=info.model,
            stages=stages,
            stage_count=len(stages),
            pause_count=len(pause_points),
            pause_points=pause_points,
            est_total_usd=est_total,
        )

    # ── Read-only YAML text (the "compiles to YAML" peek + budget source) ─────

    def _manifest_path(self, component_dir: Path) -> Path | None:
        """Resolve the on-disk manifest path (``component.yaml``/``.yml``) or None."""
        for name in _MANIFEST_NAMES:
            candidate = component_dir / name
            if candidate.is_file():
                return candidate
        return None

    def _load_manifest_data(self, component_dir: Path) -> dict[str, Any]:
        """Parse the manifest YAML to a plain mapping (read-only; budgets only).

        Uses ``yaml.safe_load`` over the **text** (no template rendering) so the
        ``max_budget_usd`` fields are readable even when the manifest carries Jinja
        variables. Returns an empty mapping when there is no manifest.
        """
        path = self._manifest_path(component_dir)
        if path is None:
            return {}
        try:
            data = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError):
            return {}
        return data if isinstance(data, dict) else {}

    def _read_yaml_docs(
        self, info: ComponentInfo
    ) -> tuple[WorkflowYaml | None, list[WorkflowYaml]]:
        """Read the ``component.yaml`` + task ``*.yaml`` text for the YAML peek.

        Read-only: every document is loaded via ``Path.read_text`` (the file is
        only read, never mutated). Task files are de-duplicated by path and kept
        in their on-disk task order (the ``info.tasks`` order).
        """
        component_dir = info.path
        component_yaml: WorkflowYaml | None = None
        manifest_path = self._manifest_path(component_dir)
        if manifest_path is not None:
            text = _safe_read_text(manifest_path)
            if text is not None:
                component_yaml = WorkflowYaml(filename=manifest_path.name, content=text)

        task_docs: list[WorkflowYaml] = []
        seen: set[Path] = set()
        for task in info.tasks:
            task_path = task.source_path
            if task_path == component_dir or task_path in seen:
                continue
            if not task_path.is_file():
                continue
            seen.add(task_path)
            text = _safe_read_text(task_path)
            if text is not None:
                task_docs.append(WorkflowYaml(filename=task_path.name, content=text))
        return component_yaml, task_docs


def _safe_read_text(path: Path) -> str | None:
    """Read a file's text read-only; return ``None`` on any I/O error."""
    try:
        return path.read_text()
    except OSError:
        return None


def _per_file_budgets(manifest: dict[str, Any]) -> dict[str, float | None]:
    """Map each manifest task ref's ``file`` → its ``max_budget_usd`` (per stage)."""
    out: dict[str, float | None] = {}
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list):
        return out
    for ref in tasks:
        if isinstance(ref, dict) and isinstance(ref.get("file"), str):
            out[ref["file"]] = _as_float(ref.get("max_budget_usd"))
    return out


def _as_float(value: Any) -> float | None:
    """Coerce a YAML numeric (int/float/str) to ``float``; ``None`` otherwise."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
