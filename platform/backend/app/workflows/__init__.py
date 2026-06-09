"""Workflows viewer service (slice 4.1) — read-only engine introspection.

The Workflows screen (Screen 07, F12) is a **read-only viewer** over the locked
DKMV engine's component-introspection surface (PRD §5.8 FR-07-1v, §6.2). This
package exposes a single seam, :class:`WorkflowService`, that turns the engine's
``list_components`` / ``inspect_component`` / ``preview_execution_plan`` output —
all consumed **in-process via** :class:`~app.runtime.RunService` (INV-13,
ADR-P006) — into the **pipeline summary** (ordered stages, per-stage budget,
pause points, est. total) plus the ``component.yaml`` + task YAML text for the
"compiles to YAML" peek.

It is **read-only** (ADR-P010, N7): there is no write/update endpoint, the service
never writes a component manifest/task file to disk, never adds a component to the
registry, and never validates-to-save. It only *reads* definitions already on the
local disk. The backend never shells the ``dkmv`` CLI and never edits ``dkmv/``.
"""

from __future__ import annotations

from app.workflows.service import (
    PipelineStage,
    WorkflowDetail,
    WorkflowService,
    WorkflowSummary,
    WorkflowYaml,
)

__all__ = [
    "PipelineStage",
    "WorkflowDetail",
    "WorkflowService",
    "WorkflowSummary",
    "WorkflowYaml",
]
