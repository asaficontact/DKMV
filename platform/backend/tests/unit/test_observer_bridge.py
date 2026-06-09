"""Slice 2.3 — sync→async observer bridge + slow-consumer policy (AC-8, INV-12).

Covers the INV-12 binding behaviors of :mod:`app.sse.observer_bridge`:

* ``PlatformEventObserver.on_event`` driven from a **non-loop thread** delivers the
  event onto the run's inbound queue with no loop error — the ``call_soon_threadsafe``
  hand-off (AC-8). The observer never schedules a coroutine.
* The bounded :class:`Subscriber` slow-consumer policy: under back-pressure it
  **coalesces/drops meter frames** (keep-latest) but **never** drops a spine frame
  (``task_completed`` / ``decision`` / lifecycle); a queue full of spine marks the
  consumer disconnected (it reconnects + replays).
"""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from typing import Any

import pytest
from app.sse.observer_bridge import (
    SUBSCRIBER_QUEUE_MAXSIZE,
    RunStreamHub,
    Subscriber,
    is_coalescible,
)
from app.sse.pump import StreamFrame
from dkmv.runtime import RuntimeEvent


def _event(event_type: str = "stream", *, run_id: str = "r1", seq: int = 1) -> RuntimeEvent:
    return RuntimeEvent(
        sequence=seq,
        timestamp=datetime.now(UTC),
        run_id=run_id,
        event_type=event_type,
    )


def _frame(event_type: str, event_id: int) -> StreamFrame:
    return StreamFrame(event_id=event_id, event_type=event_type, body={"event_type": event_type})


@pytest.mark.asyncio
async def test_on_event_from_non_loop_thread_arrives_on_queue() -> None:
    """A non-loop thread driving ``on_event`` delivers via ``call_soon_threadsafe`` (AC-8)."""
    loop = asyncio.get_running_loop()
    hub = RunStreamHub("r1", loop)
    observer = hub.observer()

    errors: list[BaseException] = []

    def drive() -> None:
        # Runs on a DIFFERENT thread than the event loop — the exact INV-12 case.
        try:
            observer.on_event(_event("task_started", seq=1))
            observer.on_event(_event("task_completed", seq=2))
        except BaseException as exc:  # noqa: BLE001 - capture any cross-thread error
            errors.append(exc)

    thread = threading.Thread(target=drive)
    thread.start()
    thread.join()

    assert errors == []  # no error raised on the worker thread
    # The events are scheduled onto the loop; drain them.
    first = await asyncio.wait_for(hub.queue.get(), timeout=1.0)
    second = await asyncio.wait_for(hub.queue.get(), timeout=1.0)
    assert {first.event_type, second.event_type} == {"task_started", "task_completed"}


@pytest.mark.asyncio
async def test_on_event_does_not_block_when_loop_closed() -> None:
    """A late event after loop close is swallowed, never crashing the engine thread."""
    loop = asyncio.get_running_loop()
    hub = RunStreamHub("r1", loop)
    observer = hub.observer()
    # Simulate a closed loop by pointing the observer at one that is not running.
    dead = asyncio.new_event_loop()
    dead.close()
    observer._loop = dead  # noqa: SLF001 - test reaches in to force the shutdown race
    # Must not raise.
    observer.on_event(_event("stream"))


def test_is_coalescible_classification() -> None:
    """Meter/stream frames are droppable; the spine never is (INV-7 / §8.3)."""
    assert is_coalescible("stream") is True
    assert is_coalescible("assistant") is True
    assert is_coalescible("result") is True
    # Spine — never droppable.
    assert is_coalescible("task_completed") is False
    assert is_coalescible("task_failed") is False
    assert is_coalescible("decision") is False
    assert is_coalescible("pause_requested") is False
    assert is_coalescible("lifecycle") is False
    # Unknown defaults to KEPT (we never silently drop an unanticipated type).
    assert is_coalescible("some_new_type") is False


@pytest.mark.asyncio
async def test_slow_consumer_drops_meter_never_spine() -> None:
    """A slow consumer drops meter frames but keeps every spine frame (AC-8)."""
    sub = Subscriber(maxsize=4)
    # Fill with meter frames, then push spine — the spine must survive by evicting
    # a coalescible meter frame.
    for i in range(4):
        sub.publish(_frame("stream", i))  # fills the queue (ids 0..3)
    assert not sub.disconnected
    # Queue is full of coalescible frames; publishing a spine frame evicts a meter.
    sub.publish(_frame("task_completed", 100))
    assert not sub.disconnected

    drained = sub.drain_nowait()
    types = [f.event_type for f in drained]
    ids = [f.event_id for f in drained]
    # The spine frame is present; exactly one meter frame was coalesced away.
    assert "task_completed" in types
    assert 100 in ids
    assert types.count("stream") == 3  # one of the four meter frames dropped


@pytest.mark.asyncio
async def test_slow_consumer_disconnects_when_full_of_spine() -> None:
    """A queue full of spine frames + another spine frame → mark disconnected."""
    sub = Subscriber(maxsize=3)
    for i in range(3):
        sub.publish(_frame("task_completed", i))  # all spine, fills queue
    assert not sub.disconnected
    # No coalescible frame to evict and the incoming frame is spine → give up.
    sub.publish(_frame("task_failed", 99))
    assert sub.disconnected


@pytest.mark.asyncio
async def test_meter_frame_dropped_when_full_of_spine() -> None:
    """A meter frame arriving on a spine-full queue is dropped (consumer disconnected)."""
    sub = Subscriber(maxsize=2)
    sub.publish(_frame("task_completed", 1))
    sub.publish(_frame("decision", 2))
    assert not sub.disconnected
    # Incoming meter frame: nothing coalescible to evict → disconnect (it replays).
    sub.publish(_frame("stream", 3))
    assert sub.disconnected
    # The spine frames remain intact.
    types = [f.event_type for f in sub.drain_nowait()]
    assert types == ["task_completed", "decision"]


@pytest.mark.asyncio
async def test_hub_publish_removes_disconnected_subscriber() -> None:
    """A hub publish that disconnects a subscriber drops it from the fan-out set."""
    loop = asyncio.get_running_loop()
    hub = RunStreamHub("r1", loop)
    sub = Subscriber(maxsize=1)
    hub.add_subscriber(sub)
    assert hub.subscriber_count == 1
    hub.publish(_frame("task_completed", 1))  # fills the size-1 queue
    hub.publish(_frame("task_failed", 2))  # can't fit, spine → disconnect + remove
    assert sub.disconnected
    assert hub.subscriber_count == 0


def test_subscriber_default_maxsize() -> None:
    """The default subscriber bound matches the module constant (sanity)."""
    sub = Subscriber()
    # Fill to capacity with coalescible frames without disconnecting.
    for i in range(SUBSCRIBER_QUEUE_MAXSIZE):
        sub.publish(_frame("stream", i))
    assert not sub.disconnected


@pytest.mark.asyncio
async def test_inbound_queue_drops_oldest_when_full() -> None:
    """The observer's loop-thread put drops the OLDEST inbound event when full."""
    loop = asyncio.get_running_loop()
    hub = RunStreamHub("r1", loop)
    observer = hub.observer()
    # Shrink the inbound queue to force the full path deterministically.
    hub.queue = asyncio.Queue(maxsize=2)
    observer._queue = hub.queue  # noqa: SLF001 - retarget the observer at the small queue
    observer._put(_event("stream", seq=1))
    observer._put(_event("stream", seq=2))
    observer._put(_event("stream", seq=3))  # full → drops seq=1
    seqs: list[Any] = []
    while not hub.queue.empty():
        seqs.append(hub.queue.get_nowait().sequence)
    assert seqs == [2, 3]
