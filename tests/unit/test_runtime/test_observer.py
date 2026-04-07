"""Tests for dkmv.runtime._observer."""

from __future__ import annotations

import json
from pathlib import Path


from dkmv.runtime._observer import (
    EventBus,
    EventObserver,
    RuntimeEvent,
    _raw_to_event,
    replay_events,
)


class SimpleObserver:
    """Test observer that collects events."""

    def __init__(self) -> None:
        self.events: list[RuntimeEvent] = []

    def on_event(self, event: RuntimeEvent) -> None:
        self.events.append(event)


class FailingObserver:
    """Observer that raises on every event."""

    def on_event(self, event: RuntimeEvent) -> None:
        raise ValueError("observer error")


class TestRuntimeEvent:
    def test_defaults(self) -> None:
        from datetime import UTC, datetime

        event = RuntimeEvent(timestamp=datetime.now(UTC))
        assert event.run_id == ""
        assert event.task_name == ""
        assert event.task_index == -1
        assert event.event_type == ""
        assert event.data == {}
        assert event.content == ""
        assert event.cost_usd == 0.0
        assert event.turns == 0

    def test_custom_values(self) -> None:
        from datetime import UTC, datetime

        event = RuntimeEvent(
            timestamp=datetime.now(UTC),
            run_id="run-123",
            task_name="step-1",
            task_index=0,
            event_type="result",
            cost_usd=1.5,
            turns=10,
        )
        assert event.run_id == "run-123"
        assert event.cost_usd == 1.5


class TestRawToEvent:
    def test_stream_event(self) -> None:
        raw = {"type": "assistant", "content_text": "Hello world"}
        event = _raw_to_event(raw, run_id="run-1", task_name="t1", task_index=0)
        assert event.event_type == "assistant"
        assert event.content == "Hello world"
        assert event.run_id == "run-1"
        assert event.task_name == "t1"
        assert event.task_index == 0

    def test_result_event(self) -> None:
        raw = {"type": "result", "total_cost_usd": 2.5, "num_turns": 15}
        event = _raw_to_event(raw)
        assert event.event_type == "result"
        assert event.cost_usd == 2.5
        assert event.turns == 15

    def test_unknown_type(self) -> None:
        raw = {"type": "unknown_thing", "foo": "bar"}
        event = _raw_to_event(raw)
        assert event.event_type == "unknown_thing"
        assert event.data == raw

    def test_missing_type(self) -> None:
        raw = {"some_field": "value"}
        event = _raw_to_event(raw)
        assert event.event_type == "stream"


class TestEventBus:
    def test_emit_dispatches_to_observer(self) -> None:
        bus = EventBus(run_id="run-1")
        observer = SimpleObserver()
        bus.add_observer(observer)

        bus.emit({"type": "assistant", "content_text": "hi"})

        assert len(observer.events) == 1
        assert observer.events[0].event_type == "assistant"
        assert observer.events[0].run_id == "run-1"

    def test_emit_multiple_observers(self) -> None:
        bus = EventBus()
        obs1 = SimpleObserver()
        obs2 = SimpleObserver()
        bus.add_observer(obs1)
        bus.add_observer(obs2)

        bus.emit({"type": "system"})

        assert len(obs1.events) == 1
        assert len(obs2.events) == 1

    def test_remove_observer(self) -> None:
        bus = EventBus()
        observer = SimpleObserver()
        bus.add_observer(observer)
        bus.remove_observer(observer)

        bus.emit({"type": "system"})
        assert len(observer.events) == 0

    def test_remove_nonexistent_observer(self) -> None:
        bus = EventBus()
        observer = SimpleObserver()
        # Should not raise
        bus.remove_observer(observer)

    def test_events_buffer(self) -> None:
        bus = EventBus()
        bus.emit({"type": "a"})
        bus.emit({"type": "b"})
        bus.emit({"type": "c"})

        events = bus.events
        assert len(events) == 3
        assert events[0].event_type == "a"
        assert events[2].event_type == "c"

    def test_events_returns_copy(self) -> None:
        bus = EventBus()
        bus.emit({"type": "a"})
        events1 = bus.events
        bus.emit({"type": "b"})
        events2 = bus.events
        assert len(events1) == 1
        assert len(events2) == 2

    def test_task_context(self) -> None:
        bus = EventBus(run_id="run-1")
        observer = SimpleObserver()
        bus.add_observer(observer)

        bus.set_task_context("task-1", 0)
        bus.emit({"type": "stream"})

        bus.set_task_context("task-2", 1)
        bus.emit({"type": "stream"})

        assert observer.events[0].task_name == "task-1"
        assert observer.events[0].task_index == 0
        assert observer.events[1].task_name == "task-2"
        assert observer.events[1].task_index == 1

    def test_failing_observer_does_not_crash(self) -> None:
        bus = EventBus()
        good = SimpleObserver()
        bad = FailingObserver()
        bus.add_observer(bad)
        bus.add_observer(good)

        bus.emit({"type": "test"})

        # Good observer still received the event
        assert len(good.events) == 1

    def test_observer_protocol(self) -> None:
        obs = SimpleObserver()
        assert isinstance(obs, EventObserver)

    def test_no_observers_does_not_crash(self) -> None:
        bus = EventBus()
        bus.emit({"type": "test"})
        assert len(bus.events) == 1


class TestReplayEvents:
    def test_replay_from_file(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs" / "run-123"
        runs_dir.mkdir(parents=True)
        stream_file = runs_dir / "stream.jsonl"
        stream_file.write_text(
            json.dumps({"type": "system", "message": "started"})
            + "\n"
            + json.dumps({"type": "assistant", "content_text": "hello"})
            + "\n"
            + json.dumps({"type": "result", "total_cost_usd": 1.0, "num_turns": 5})
            + "\n"
        )

        events = replay_events("run-123", tmp_path)
        assert len(events) == 3
        assert events[0].event_type == "system"
        assert events[1].event_type == "assistant"
        assert events[1].content == "hello"
        assert events[2].event_type == "result"
        assert events[2].cost_usd == 1.0
        assert events[2].turns == 5

    def test_replay_with_offset(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs" / "run-1"
        runs_dir.mkdir(parents=True)
        stream_file = runs_dir / "stream.jsonl"
        lines = [json.dumps({"type": f"event-{i}"}) for i in range(5)]
        stream_file.write_text("\n".join(lines) + "\n")

        events = replay_events("run-1", tmp_path, offset=3)
        assert len(events) == 2
        assert events[0].event_type == "event-3"
        assert events[1].event_type == "event-4"

    def test_replay_with_observer(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs" / "run-1"
        runs_dir.mkdir(parents=True)
        stream_file = runs_dir / "stream.jsonl"
        stream_file.write_text(json.dumps({"type": "test"}) + "\n")

        observer = SimpleObserver()
        events = replay_events("run-1", tmp_path, observer=observer)
        assert len(events) == 1
        assert len(observer.events) == 1

    def test_replay_nonexistent_run(self, tmp_path: Path) -> None:
        events = replay_events("missing-run", tmp_path)
        assert events == []

    def test_replay_skips_invalid_json(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs" / "run-1"
        runs_dir.mkdir(parents=True)
        stream_file = runs_dir / "stream.jsonl"
        stream_file.write_text(
            json.dumps({"type": "good"})
            + "\n"
            + "not valid json\n"
            + json.dumps({"type": "also-good"})
            + "\n"
        )

        events = replay_events("run-1", tmp_path)
        assert len(events) == 2

    def test_replay_skips_empty_lines(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs" / "run-1"
        runs_dir.mkdir(parents=True)
        stream_file = runs_dir / "stream.jsonl"
        stream_file.write_text(
            json.dumps({"type": "a"}) + "\n" + "\n" + "  \n" + json.dumps({"type": "b"}) + "\n"
        )

        events = replay_events("run-1", tmp_path)
        assert len(events) == 2

    def test_replay_observer_failure_isolated(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs" / "run-1"
        runs_dir.mkdir(parents=True)
        stream_file = runs_dir / "stream.jsonl"
        stream_file.write_text(json.dumps({"type": "a"}) + "\n" + json.dumps({"type": "b"}) + "\n")

        failing = FailingObserver()
        events = replay_events("run-1", tmp_path, observer=failing)
        # Should still return all events despite observer failures
        assert len(events) == 2
