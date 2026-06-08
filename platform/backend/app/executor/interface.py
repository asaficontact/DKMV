"""The ``Executor`` seam (PRD §8.7; ADR-P008).

The orchestrator depends **only** on this interface — never on Docker or the
engine's local-Docker assumptions directly. v1 ships exactly one implementation,
:class:`~app.executor.local_docker.LocalDockerExecutor`; the interface
*anticipates* remote backends (``SSHRemoteDockerExecutor`` / ``K8sJobExecutor``)
so cloud execution is an additive swap rather than a rewrite, but those remote
implementations are **out of scope for v1** (YAGNI — PRD N2; the phase brief OUT
list).

The contract is deliberately remote-friendly:

* :meth:`Executor.start` takes a :class:`RunSpec` (a serializable launch request,
  not an in-process object) and returns a handle.
* :meth:`Executor.stream` is **re-attachable by ``run_id``** — a caller that has
  only a ``run_id`` (e.g. after a process restart, or a remote worker) can
  resubscribe to a run's event stream without holding the original in-memory
  handle. This is the seam property ADR-P008 calls out so the interface does not
  bake in the in-process assumption.
* :meth:`Executor.signal` (``pause``/``resume``/``cancel``) is specified to work
  "remotely" — i.e. addressed by handle/``run_id``, not by holding a live task.
* :meth:`Executor.cleanup` tears down the container/workspace for a run.

Nothing here imports Docker. The single place that touches Docker is
``LocalDockerExecutor`` (and the brokered socket proxy in ``docker-compose.yml``).
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dkmv.runtime._handle import RunHandle


class Signal(StrEnum):
    """A control action addressable by handle/``run_id`` (ADR-P008).

    ``CANCEL`` maps to a forced engine stop; ``PAUSE``/``RESUME`` are defined by
    the seam for the remote case and for HITL (Phase 2 wires the HITL pause
    primitive through here). v1 ``LocalDockerExecutor`` implements ``CANCEL`` via
    ``RunHandle.stop(force=True)``.
    """

    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"


# A pause callback matches the engine's ``on_pause`` shape
# (``Callable[[PauseRequest], Awaitable[PauseResponse]]``). Typed loosely here so
# the executor seam does not import engine internals into its public signature.
OnPause = Callable[[Any], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class RunSpec:
    """A serializable launch request the orchestrator hands to an ``Executor``.

    Mirrors the engine's ``EmbeddedRuntime.start`` parameter surface but as a
    plain dataclass so a remote executor could ship it over the wire. The
    executor is responsible for translating it into the engine call (local) or a
    remote launch request (later).

    The sandbox *runtime* (gVisor ``runsc`` vs. a weaker fallback) is **not** a
    field here: it is host/executor policy derived from ``settings.SANDBOX_RUNTIME``
    (INV-3), not a per-run knob a caller chooses. See
    :mod:`app.executor.runtime_policy`.
    """

    component: str
    repo: str
    branch: str | None = None
    feature_name: str = ""
    agent: str | None = None
    model: str | None = None
    max_turns: int | None = None
    timeout_minutes: int | None = None
    max_budget_usd: float | None = None
    memory: str | None = None
    variables: dict[str, Any] | None = None
    context_paths: list[Path] | None = None
    start_task: str | None = None
    keep_alive: bool = False


@dataclass(frozen=True, slots=True)
class StreamedEvent:
    """One event yielded by :meth:`Executor.stream` (re-attach path).

    A thin, executor-agnostic envelope: ``sequence`` is the monotonic replay
    cursor (the engine's ``stream.jsonl`` line index, which the Phase 0.3 event
    log mirrors as ``events.id``), ``event`` is the underlying engine
    ``RuntimeEvent``. Kept minimal so the SSE/observer pump (Phase 2) can adapt
    it without importing executor internals.
    """

    run_id: str
    sequence: int
    event: Any
    payload: dict[str, Any] = field(default_factory=dict)


class Executor(abc.ABC):
    """Execution backend the orchestrator depends on (PRD §8.7; ADR-P008).

    All container/sandbox operations go through this interface; the orchestrator
    must **never** call Docker or the engine's deployment directly. v1 provides
    ``LocalDockerExecutor`` only.
    """

    @abc.abstractmethod
    async def start(self, spec: RunSpec, *, on_pause: OnPause | None = None) -> RunHandle:
        """Launch a run described by ``spec`` and return its control handle.

        Implementations apply the host sandbox-isolation policy (gVisor runtime
        + egress allowlist, INV-3) before launching the container.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def stream(
        self,
        handle_or_run_id: RunHandle | str,
        *,
        offset: int = 0,
    ) -> AsyncIterator[StreamedEvent]:
        """Stream a run's events — **re-attachable by ``run_id``** (ADR-P008).

        Accepts either a live :class:`RunHandle` *or* a bare ``run_id`` string so
        a caller that holds only the id (post-restart, or a remote worker) can
        resubscribe without the original in-memory handle. ``offset`` skips
        already-seen events (the replay cursor) so reconnects resume with no gaps
        (NFR-PERF-1). This is the seam property that keeps remote execution an
        additive swap.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def signal(self, handle_or_run_id: RunHandle | str, signal: Signal) -> None:
        """Send a control ``signal`` (``pause``/``resume``/``cancel``) to a run.

        Addressed by handle **or** ``run_id`` so the contract works remotely
        (ADR-P008). v1 implements ``cancel`` via ``RunHandle.stop(force=True)``.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def cleanup(self, handle_or_run_id: RunHandle | str) -> None:
        """Tear down the container/workspace for a run (idempotent)."""
        raise NotImplementedError
