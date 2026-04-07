"""Tests for dkmv.runtime._handle."""

from __future__ import annotations

import asyncio

import pytest

from dkmv.runtime._handle import RunHandle
from dkmv.runtime._observer import EventBus, RuntimeEvent


class SimpleObserver:
    def __init__(self) -> None:
        self.events: list[RuntimeEvent] = []

    def on_event(self, event: RuntimeEvent) -> None:
        self.events.append(event)


class TestRunHandle:
    def test_initial_state(self) -> None:
        bus = EventBus(run_id="run-1")
        handle = RunHandle(run_id="run-1", event_bus=bus)
        assert handle.run_id == "run-1"
        assert handle.status == "pending"
        assert handle.result is None
        assert handle.events == []

    def test_set_task_changes_status_to_running(self) -> None:
        bus = EventBus()
        handle = RunHandle(run_id="run-1", event_bus=bus)

        async def noop() -> None:
            pass

        loop = asyncio.new_event_loop()
        task = loop.create_task(noop())
        handle._set_task(task)
        assert handle.status == "running"
        loop.run_until_complete(task)
        loop.close()

    def test_set_result_updates_status(self) -> None:
        from unittest.mock import MagicMock

        bus = EventBus()
        handle = RunHandle(run_id="run-1", event_bus=bus)

        mock_result = MagicMock()
        mock_result.status = "completed"
        handle._set_result(mock_result)

        assert handle.status == "completed"
        assert handle.result is mock_result

    def test_set_result_none_with_cancel(self) -> None:
        bus = EventBus()
        handle = RunHandle(run_id="run-1", event_bus=bus)
        handle._cancel_requested = True
        handle._set_result(None)
        assert handle.status == "cancelled"

    def test_set_result_none_without_cancel(self) -> None:
        bus = EventBus()
        handle = RunHandle(run_id="run-1", event_bus=bus)
        handle._set_result(None)
        assert handle.status == "failed"

    @pytest.mark.asyncio
    async def test_wait_returns_result(self) -> None:
        bus = EventBus()
        handle = RunHandle(run_id="run-1", event_bus=bus)

        async def complete() -> str:
            return "done"

        task = asyncio.create_task(complete())
        handle._set_task(task)
        result = await handle.wait()
        assert result == "done"

    @pytest.mark.asyncio
    async def test_wait_timeout(self) -> None:
        bus = EventBus()
        handle = RunHandle(run_id="run-1", event_bus=bus)

        async def slow() -> None:
            await asyncio.sleep(10)

        task = asyncio.create_task(slow())
        handle._set_task(task)

        with pytest.raises(TimeoutError):
            await handle.wait(timeout=0.01)

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_wait_no_task_with_result(self) -> None:
        from unittest.mock import MagicMock

        bus = EventBus()
        handle = RunHandle(run_id="run-1", event_bus=bus)
        handle._result = MagicMock()
        result = await handle.wait()
        assert result is handle._result

    @pytest.mark.asyncio
    async def test_wait_no_task_no_result_raises(self) -> None:
        bus = EventBus()
        handle = RunHandle(run_id="run-1", event_bus=bus)
        with pytest.raises(RuntimeError, match="no attached task"):
            await handle.wait()

    @pytest.mark.asyncio
    async def test_stop_force(self) -> None:
        bus = EventBus()
        handle = RunHandle(run_id="run-1", event_bus=bus)

        async def slow() -> None:
            await asyncio.sleep(10)

        task = asyncio.create_task(slow())
        handle._set_task(task)

        await handle.stop(force=True)
        assert handle.status == "cancelled"
        assert handle._cancel_requested is True

        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_stop_cooperative(self) -> None:
        bus = EventBus()
        handle = RunHandle(run_id="run-1", event_bus=bus)

        async def slow() -> None:
            await asyncio.sleep(10)

        task = asyncio.create_task(slow())
        handle._set_task(task)

        await handle.stop(force=False)
        assert handle.status == "stopping"
        assert handle._cancel_requested is True

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_stop_no_task(self) -> None:
        bus = EventBus()
        handle = RunHandle(run_id="run-1", event_bus=bus)
        await handle.stop()
        assert handle.status == "cancelled"

    def test_add_remove_observer(self) -> None:
        bus = EventBus()
        handle = RunHandle(run_id="run-1", event_bus=bus)
        observer = SimpleObserver()

        handle.add_observer(observer)
        bus.emit({"type": "test"})
        assert len(observer.events) == 1

        handle.remove_observer(observer)
        bus.emit({"type": "test2"})
        assert len(observer.events) == 1  # no new events

    def test_events_property(self) -> None:
        bus = EventBus()
        handle = RunHandle(run_id="run-1", event_bus=bus)
        bus.emit({"type": "a"})
        bus.emit({"type": "b"})
        assert len(handle.events) == 2

    def test_inspect(self) -> None:
        bus = EventBus()
        handle = RunHandle(run_id="run-1", event_bus=bus)
        info = handle.inspect()
        assert info["run_id"] == "run-1"
        assert info["status"] == "pending"
        assert info["event_count"] == 0
        assert info["cancel_requested"] is False

    def test_inspect_with_result(self) -> None:
        from unittest.mock import MagicMock

        bus = EventBus()
        handle = RunHandle(run_id="run-1", event_bus=bus)
        mock_result = MagicMock()
        mock_result.status = "completed"
        mock_result.model_dump.return_value = {"status": "completed"}
        handle._set_result(mock_result)

        info = handle.inspect()
        assert "result" in info
        assert info["result"]["status"] == "completed"
