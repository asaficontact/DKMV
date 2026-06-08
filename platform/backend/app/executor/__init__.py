"""Executor seam (PRD §8.7; ADR-P008).

Public surface:

* :class:`Executor` — the interface the orchestrator depends on
  (``start``/``stream``/``signal``/``cleanup``; ``stream`` re-attachable by
  ``run_id``). v1 ships :class:`LocalDockerExecutor` only; the interface
  anticipates remote backends (SSH/K8s) but those are out of scope (YAGNI).
* :class:`LocalDockerExecutor` — wraps ``RunService``/``EmbeddedRuntime`` + local
  Docker under gVisor (``runsc`` default — INV-3).
* :class:`RunSpec` / :class:`StreamedEvent` / :class:`Signal` — the seam's data
  types.
* Runtime-isolation policy helpers (gVisor default + OQ-6 weaker-isolation
  warning/fallback).
"""

from __future__ import annotations

from app.executor.egress import (
    DEFAULT_PINNED_DNS,
    EGRESS_NETWORK_NAME,
    EgressPolicy,
    proxy_acl_lines,
)
from app.executor.interface import (
    Executor,
    OnPause,
    RunSpec,
    Signal,
    StreamedEvent,
)
from app.executor.local_docker import LocalDockerExecutor
from app.executor.runtime_policy import (
    GVISOR_RUNTIME,
    RUNSC_UNAVAILABLE_WARNING,
    WEAKER_ISOLATION_WARNING,
    WeakerIsolationError,
    resolve_runtime,
    runtime_available,
    runtime_docker_args,
)

__all__ = [
    "DEFAULT_PINNED_DNS",
    "EGRESS_NETWORK_NAME",
    "GVISOR_RUNTIME",
    "RUNSC_UNAVAILABLE_WARNING",
    "WEAKER_ISOLATION_WARNING",
    "EgressPolicy",
    "Executor",
    "LocalDockerExecutor",
    "OnPause",
    "RunSpec",
    "Signal",
    "StreamedEvent",
    "WeakerIsolationError",
    "proxy_acl_lines",
    "resolve_runtime",
    "runtime_available",
    "runtime_docker_args",
]
