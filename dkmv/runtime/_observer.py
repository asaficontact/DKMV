"""Event observer protocol, event bus, and replay for the embedded runtime."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class RuntimeEvent(BaseModel):
    """Structured event emitted during a run."""

    sequence: int = 0
    timestamp: datetime
    run_id: str = ""
    task_name: str = ""
    task_index: int = -1
    step_instance: str = ""
    event_type: str = ""
    data: dict[str, Any] = {}
    content: str = ""
    cost_usd: float = 0.0
    turns: int = 0


@runtime_checkable
class EventObserver(Protocol):
    """Protocol for receiving runtime events. Hosts implement this."""

    def on_event(self, event: RuntimeEvent) -> None: ...


class EventBus:
    """Multiplexes raw events to registered observers."""

    def __init__(self, run_id: str = "") -> None:
        self._run_id = run_id
        self._observers: list[EventObserver] = []
        self._events: list[RuntimeEvent] = []
        self._task_name: str = ""
        self._task_index: int = -1
        self._sequence: int = 0

    def add_observer(self, observer: EventObserver) -> None:
        self._observers.append(observer)

    def remove_observer(self, observer: EventObserver) -> None:
        try:
            self._observers.remove(observer)
        except ValueError:
            pass

    def set_task_context(self, task_name: str, task_index: int) -> None:
        """Update current task context for event enrichment."""
        self._task_name = task_name
        self._task_index = task_index

    @property
    def events(self) -> list[RuntimeEvent]:
        return list(self._events)

    def emit(self, raw_event: dict[str, Any]) -> None:
        """Wrap a raw event dict into a RuntimeEvent and dispatch to observers."""
        self._sequence += 1
        event = _raw_to_event(
            raw_event,
            run_id=self._run_id,
            task_name=self._task_name,
            task_index=self._task_index,
            sequence=self._sequence,
        )
        self._events.append(event)
        for observer in self._observers:
            try:
                observer.on_event(event)
            except Exception:
                logger.exception("Observer %r failed on event", observer)


def _raw_to_event(
    raw: dict[str, Any],
    run_id: str = "",
    task_name: str = "",
    task_index: int = -1,
    sequence: int = 0,
) -> RuntimeEvent:
    """Convert a raw stream event dict to a RuntimeEvent."""
    event_type = raw.get("type", "stream")
    content = ""
    cost_usd = 0.0
    turns = 0

    # Lifecycle events carry their own task context
    is_lifecycle = raw.get("lifecycle", False)
    if is_lifecycle:
        task_name = raw.get("task_name", task_name)
        task_index = raw.get("task_index", task_index)
        cost_usd = raw.get("cost_usd", 0.0)
    elif event_type == "result":
        cost_usd = raw.get("total_cost_usd", 0.0)
        turns = raw.get("num_turns", 0)
    elif event_type == "assistant":
        content = raw.get("content_text", "")

    # For non-lifecycle events, read task context from raw dict (injected
    # by ComponentRunner's context-wrapping on_event callback).
    if not is_lifecycle:
        task_name = raw.get("_task_name", task_name)
        task_index = raw.get("_task_idx", task_index)

    # Prefer persisted _ts timestamp over datetime.now(UTC)
    ts_str = raw.get("_ts")
    if ts_str:
        try:
            timestamp = datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            timestamp = datetime.now(UTC)
    else:
        timestamp = datetime.now(UTC)

    # Derive step_instance from raw dict or build from task_name + for_each_index
    step_instance = raw.get("_step_instance", "")
    if not step_instance and task_name:
        for_each_idx = raw.get("for_each_index")
        if for_each_idx is not None:
            step_instance = f"{task_name}__idx_{for_each_idx}"
        else:
            step_instance = task_name

    return RuntimeEvent(
        sequence=sequence,
        timestamp=timestamp,
        run_id=run_id,
        task_name=task_name,
        task_index=task_index,
        step_instance=step_instance,
        event_type=event_type,
        data=raw,
        content=content,
        cost_usd=cost_usd,
        turns=turns,
    )


def replay_events(
    run_id: str,
    output_dir: Path,
    offset: int = 0,
    observer: EventObserver | None = None,
) -> list[RuntimeEvent]:
    """Read stream.jsonl for a run and replay events.

    Args:
        run_id: The run to replay.
        output_dir: Base output directory containing runs/.
        offset: Number of lines to skip from the beginning.
        observer: Optional observer to dispatch events to.

    Returns:
        List of RuntimeEvent objects from the stream.
    """
    stream_path = output_dir / "runs" / run_id / "stream.jsonl"
    if not stream_path.exists():
        return []

    events: list[RuntimeEvent] = []
    seq = 0
    with stream_path.open() as f:
        for i, line in enumerate(f):
            if i < offset:
                seq += 1
                continue
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            seq += 1
            event = _raw_to_event(raw, run_id=run_id, sequence=seq)
            events.append(event)
            if observer is not None:
                try:
                    observer.on_event(event)
                except Exception:
                    logger.exception("Observer failed during replay")

    return events
