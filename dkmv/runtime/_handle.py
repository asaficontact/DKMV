"""RunHandle — async control surface for a running execution."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from dkmv.core.models import RunStatus
from dkmv.runtime._observer import EventBus, EventObserver

logger = logging.getLogger(__name__)


class RunHandle:
    """Control surface for a single DKMV run.

    Provides status inspection, event observation, and stop/cancel controls.
    """

    def __init__(
        self,
        run_id: str,
        event_bus: EventBus,
    ) -> None:
        self._run_id = run_id
        self._event_bus = event_bus
        self._status: RunStatus = "pending"
        self._result: Any = None  # ComponentResult once completed
        self._task: asyncio.Task[Any] | None = None
        self._cancel_requested = False
        self._cancel_event = asyncio.Event()

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def cancel_event(self) -> asyncio.Event:
        """Event that signals cooperative cancellation to the component runner."""
        return self._cancel_event

    @property
    def status(self) -> RunStatus:
        return self._status

    @property
    def result(self) -> Any:
        """The ComponentResult, or None if not yet completed."""
        return self._result

    @property
    def events(self) -> list[Any]:
        """All events emitted so far."""
        return self._event_bus.events

    def add_observer(self, observer: EventObserver) -> None:
        self._event_bus.add_observer(observer)

    def remove_observer(self, observer: EventObserver) -> None:
        self._event_bus.remove_observer(observer)

    def _set_run_id(self, run_id: str) -> None:
        """Set the run_id once it's known (after ComponentRunner creates it)."""
        self._run_id = run_id
        self._event_bus._run_id = run_id

    def _set_task(self, task: asyncio.Task[Any]) -> None:
        """Attach the asyncio.Task that drives execution."""
        self._task = task
        self._status = "running"

    def _set_result(self, result: Any) -> None:
        """Set the final result and update status."""
        self._result = result
        if result is not None:
            self._status = result.status
        elif self._cancel_requested:
            self._status = "cancelled"
        else:
            self._status = "failed"

    async def wait(self, timeout: float | None = None) -> Any:
        """Wait for the run to complete and return the ComponentResult.

        Raises:
            TimeoutError: If timeout is exceeded.
            RuntimeError: If no task is attached.
        """
        if self._task is None:
            if self._result is not None:
                return self._result
            raise RuntimeError("RunHandle has no attached task")
        try:
            return await asyncio.wait_for(self._task, timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Run {self._run_id} did not complete within {timeout}s")

    async def stop(self, *, force: bool = False) -> None:
        """Stop the run.

        Args:
            force: If True, cancel the asyncio.Task immediately.
                   If False, set a flag for cooperative cancellation.
        """
        self._cancel_requested = True
        self._cancel_event.set()
        if self._task is None:
            self._status = "cancelled"
            return
        if force:
            self._task.cancel()
            self._status = "cancelled"
        else:
            self._status = "stopping"

    def inspect(self) -> dict[str, Any]:
        """Return current state as a dict."""
        info: dict[str, Any] = {
            "run_id": self._run_id,
            "status": self._status,
            "event_count": len(self._event_bus.events),
            "cancel_requested": self._cancel_requested,
        }
        if self._result is not None:
            info["result"] = self._result.model_dump()
        return info
