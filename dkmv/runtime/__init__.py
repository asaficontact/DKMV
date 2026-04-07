"""DKMV Public Embedded Runtime API.

Provides a clean facade for embedding DKMV programmatically without
CLI scraping or reaching into internals.
"""

from __future__ import annotations

from dkmv.runtime._artifacts import ArtifactRef, get_artifact, list_artifacts
from dkmv.runtime._capability import (
    CapabilityReport,
    PreflightResult,
    get_capabilities,
    preflight_check,
)
from dkmv.runtime._introspection import (
    ComponentInfo,
    ExecutionPlan,
    ResolvedStep,
    TaskInfo,
    ValidationResult,
    inspect_component,
    inspect_task,
    list_components,
    preview_execution_plan,
    validate_component,
)
from dkmv.runtime._observer import (
    EventBus,
    EventObserver,
    RuntimeEvent,
    replay_events,
)
from dkmv.runtime._telemetry import RunStats, get_run_stats
from dkmv.runtime._types import (
    ContainerStatus,
    ExecutionSource,
    ExecutionSourceType,
    RetentionPolicy,
    RuntimeConfig,
    SourceProvenance,
)

__all__ = [
    # Types
    "ContainerStatus",
    "ExecutionSource",
    "ExecutionSourceType",
    "RetentionPolicy",
    "RuntimeConfig",
    "SourceProvenance",
    # Introspection
    "ComponentInfo",
    "TaskInfo",
    "ValidationResult",
    "inspect_component",
    "inspect_task",
    "list_components",
    "preview_execution_plan",
    "validate_component",
    "ExecutionPlan",
    "ResolvedStep",
    # Capability
    "CapabilityReport",
    "PreflightResult",
    "get_capabilities",
    "preflight_check",
    # Observer
    "EventBus",
    "EventObserver",
    "RuntimeEvent",
    "replay_events",
    # Artifacts
    "ArtifactRef",
    "get_artifact",
    "list_artifacts",
    # Telemetry
    "RunStats",
    "get_run_stats",
    # Facade (lazy-loaded)
    "EmbeddedRuntime",
    "RunHandle",
]


def __getattr__(name: str) -> object:
    """Lazy imports for heavier modules to keep `import dkmv.runtime` fast."""
    if name == "EmbeddedRuntime":
        from dkmv.runtime._facade import EmbeddedRuntime

        return EmbeddedRuntime
    if name == "RunHandle":
        from dkmv.runtime._handle import RunHandle

        return RunHandle
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
