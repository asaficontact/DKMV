"""``LocalDockerExecutor`` — the v1 execution backend (PRD §8.7; ADR-P008).

Wraps the platform :class:`~app.runtime.run_service.RunService` (which owns the
in-process, **locked** ``EmbeddedRuntime`` — INV-13) plus local Docker under
gVisor. It is the **only** component in the backend that owns container/runtime
policy; the orchestrator depends solely on the :class:`~app.executor.interface.Executor`
interface and never reaches Docker or the engine directly.

What it owns:

* **Sandbox isolation policy (INV-3 / NFR-SEC-4 / ADR-P005).** At construction it
  resolves the effective runtime from ``settings.SANDBOX_RUNTIME`` via
  :mod:`app.executor.runtime_policy` — gVisor ``runsc`` by default, with the
  OQ-6 weaker-isolation warning/fail-closed path — and exposes the
  ``--runtime=<name>`` Docker flag through :attr:`runtime_docker_args`.
* **The seam methods** ``start``/``stream``/``signal``/``cleanup`` over the
  engine ``RunHandle``, with ``stream`` re-attachable by ``run_id`` (ADR-P008)
  via the engine's durable ``stream.jsonl`` replay.

Engine-seam caveat (tracked, not worked around): ``EmbeddedRuntime.start`` does
**not** expose a ``docker_args``/runtime passthrough — the engine's
``SandboxManager`` assembles ``docker_args`` internally and hardcodes
``DockerDeployment`` (PRD §8.7 / §11.3 engine ask). So the platform owns the
runtime *policy* + the *flag* at this seam (and applies it host-side via the
brokered daemon, e.g. ``DOCKER_DEFAULT_RUNTIME`` / daemon ``default-runtime``);
threading the per-container ``--runtime`` flag the rest of the way into the
engine is the §11.3 engine ask. INV-13 forbids editing ``dkmv/`` to do it here.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.executor.egress import EgressPolicy
from app.executor.interface import Executor, OnPause, RunSpec, Signal, StreamedEvent
from app.executor.runtime_policy import resolve_runtime, runtime_docker_args

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dkmv.runtime import RunHandle

    from app.config import Settings
    from app.runtime.run_service import RunService

logger = logging.getLogger(__name__)


class LocalDockerExecutor(Executor):
    """Run sandboxes via the in-process engine + local Docker under gVisor.

    Args:
        run_service: The platform seam over the engine (owns ``EmbeddedRuntime``).
        settings: Platform settings; supplies ``SANDBOX_RUNTIME`` (INV-3).
        allow_weaker_isolation: Operator opt-in (OQ-6) to a non-``runsc`` runtime
            or to continuing when ``runsc`` is unavailable. Default ``False``
            (fail-closed — the secure posture).
        check_runtime_available: Probe the Docker daemon for the runtime at
            construction. Default ``True``; disabled in unit tests / when the
            daemon is unreachable.
    """

    def __init__(
        self,
        run_service: RunService,
        settings: Settings,
        *,
        allow_weaker_isolation: bool = False,
        check_runtime_available: bool = True,
    ) -> None:
        self._run_service = run_service
        self._settings = settings
        # Resolve + enforce the isolation policy ONCE, at construction, so a
        # misconfigured host fails fast (fail-closed) rather than at first launch.
        self._runtime: str = resolve_runtime(
            settings.SANDBOX_RUNTIME,
            allow_weaker_isolation=allow_weaker_isolation,
            check_available=check_runtime_available,
        )
        # Default-on, network-enforced egress allowlist (INV-3 / §8.6): GitHub +
        # model APIs only, pinned DNS. Derived from settings.EGRESS_ALLOWLIST and
        # applied at container start via the network-confinement Docker args; an
        # empty allowlist falls back to the secure defaults (never allow-all).
        self._egress: EgressPolicy = EgressPolicy.from_settings(settings)
        logger.info(
            "LocalDockerExecutor sandbox runtime=%r, egress allowlist=%d host(s)",
            self._runtime,
            len(self._egress.hosts),
        )

    @property
    def runtime(self) -> str:
        """The effective sandbox runtime (``runsc`` by default — INV-3)."""
        return self._runtime

    @property
    def runtime_docker_args(self) -> list[str]:
        """The Docker run args pinning the sandbox runtime (``--runtime=runsc``)."""
        return runtime_docker_args(self._runtime)

    @property
    def egress(self) -> EgressPolicy:
        """The default-on egress allowlist applied to every sandbox (INV-3)."""
        return self._egress

    @property
    def sandbox_docker_args(self) -> list[str]:
        """All host-side security Docker args: runtime + egress confinement.

        Combines the gVisor ``--runtime`` flag (INV-3) with the egress
        network-confinement + pinned-DNS flags (INV-3 / §8.6) so the executor
        applies the full sandbox-isolation posture in one place. (Threading these
        the rest of the way into the engine's ``SandboxManager.docker_args`` is
        the §11.3 engine ask; the platform owns the policy + the flags here.)
        """
        return [*self.runtime_docker_args, *self._egress.docker_egress_args()]

    async def start(self, spec: RunSpec, *, on_pause: OnPause | None = None) -> RunHandle:
        """Launch ``spec`` against local Docker and return the engine handle.

        The sandbox-isolation policy is already resolved (gVisor ``runsc`` by
        default; the runtime flag is :attr:`runtime_docker_args`). The launch
        delegates to :class:`RunService` → ``EmbeddedRuntime.start`` in-process
        (INV-13); no Docker call is made here directly.
        """
        return await self._run_service.start(
            component=spec.component,
            repo=spec.repo,
            branch=spec.branch,
            feature_name=spec.feature_name,
            agent=spec.agent,
            model=spec.model,
            max_turns=spec.max_turns,
            timeout_minutes=spec.timeout_minutes,
            max_budget_usd=spec.max_budget_usd,
            memory=spec.memory,
            variables=spec.variables,
            context_paths=spec.context_paths,
            start_task=spec.start_task,
            on_pause=on_pause,
            keep_alive=spec.keep_alive,
        )

    async def stream(
        self,
        handle_or_run_id: RunHandle | str,
        *,
        offset: int = 0,
    ) -> AsyncIterator[StreamedEvent]:
        """Yield a run's events — re-attachable by ``run_id`` (ADR-P008).

        Resolves a bare ``run_id`` to the live in-process handle when one exists
        (same-process subscribe); otherwise falls back to the engine's **durable**
        ``stream.jsonl`` replay (``EmbeddedRuntime.replay_events``) so a caller
        holding only the id — e.g. after a restart — can re-attach with no gaps
        (NFR-PERF-1). ``offset`` is the replay cursor.

        Phase 0 ships the re-attach/replay seam; the live observer→queue pump and
        SSE fan-out are Phase 2 (F8). This async generator currently yields the
        durable history; the live tail is layered on top in Phase 2 without
        changing this signature.
        """
        run_id = self._coerce_run_id(handle_or_run_id)
        runtime = self._run_service.runtime
        events = runtime.replay_events(run_id, offset=offset)
        for idx, event in enumerate(events):
            yield StreamedEvent(
                run_id=run_id,
                sequence=offset + idx + 1,
                event=event,
            )

    async def signal(self, handle_or_run_id: RunHandle | str, signal: Signal) -> None:
        """Send ``signal`` to a run, addressed by handle or ``run_id``.

        v1 implements ``CANCEL`` via ``RunHandle.stop(force=True)`` (the
        Stop-during-pause-safe path, ADR-P007/INV-9). ``PAUSE``/``RESUME`` are
        part of the seam contract for the remote case and are wired to the HITL
        pause primitive in Phase 2; the local executor does not synthesize them
        here (the engine's pause is workflow-driven via ``on_pause``).
        """
        handle = self._resolve_handle(handle_or_run_id)
        if handle is None:
            run_id = self._coerce_run_id(handle_or_run_id)
            logger.warning("signal %s for run %s: no live handle (already gone)", signal, run_id)
            return
        if signal is Signal.CANCEL:
            await handle.stop(force=True)
            return
        # PAUSE/RESUME: the engine's pause is cooperative + workflow-driven
        # (on_pause); the executor does not fabricate it. Phase 2 routes HITL
        # resume through the awaited on_pause callback, not a synthetic signal.
        logger.info(
            "signal %s for run %s is a Phase 2 HITL seam; no-op in 0.4",
            signal,
            handle.run_id,
        )

    async def cleanup(self, handle_or_run_id: RunHandle | str) -> None:
        """Tear down transient runtime resources (idempotent).

        .. warning::
           This is currently **process-global, not per-run.** Despite accepting a
           ``handle_or_run_id`` argument, it delegates to the engine's
           ``EmbeddedRuntime.cleanup()``, which tears down **all** of the
           runtime's temp/snapshot directories for this process — not just the
           resources of the run identified by the argument. The ``handle_or_run_id``
           parameter is therefore **advisory only** here in Phase 0 (it scopes
           nothing today; it preserves the seam signature for a future per-run
           teardown). True per-run container/temp isolation requires an engine
           ``cleanup(run_id=...)`` surface that does not yet exist — that is the
           PRD §11 engine ask (INV-13 forbids adding it under ``dkmv/`` here).

           **Phase 3 recovery callers must not assume per-run isolation.** Calling
           this to reap a single orphaned run would also wipe the temp state of
           any *live* run in the same process — a footgun. The orphan-kill
           recovery path must target the specific container/run via the
           per-container teardown the §11 engine ask will provide, not this hook.

        Container teardown for a *retained* container is the engine's
        responsibility on stop; this method is the platform-side hook the
        orchestrator calls so it never touches Docker directly.
        """
        runtime = self._run_service.runtime
        runtime.cleanup()

    # ── internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _coerce_run_id(handle_or_run_id: RunHandle | str) -> str:
        """Extract a ``run_id`` from a handle or accept a bare id string."""
        if isinstance(handle_or_run_id, str):
            return handle_or_run_id
        # RunHandle.run_id is `str`, but the engine ships no stubs (mypy treats
        # it as Any), so coerce explicitly.
        return str(handle_or_run_id.run_id)

    def _resolve_handle(self, handle_or_run_id: RunHandle | str) -> RunHandle | None:
        """Return the live engine handle for a handle-or-id, or ``None``.

        A bare ``run_id`` is looked up in the engine's in-process handle table
        (``EmbeddedRuntime.get_handle``); ``None`` means no live handle exists in
        this process (e.g. a run started by a now-dead process — INV-10: the
        platform does NOT re-attach an observer to such a container, it kills +
        marks interrupted in Phase 3).
        """
        if not isinstance(handle_or_run_id, str):
            return handle_or_run_id
        return self._run_service.runtime.get_handle(handle_or_run_id)
