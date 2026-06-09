"""Slice 1.3 — the serialized, token-bucket-paced GitHub write-queue (AC-7, §8.1).

Covers the binding write-side rate-limiting contract:

* **Serialized ordering** of concurrent mutations (at most one in flight; FIFO).
* **403-secondary + ``Retry-After``** is honored: the queue **waits** the advertised
  interval and **does not interleave** a second mutation, then retries the *same*
  one (the distinct-from-primary handling — §8.1).
* **``X-RateLimit-*`` accounting** is surfaced for the later FR-06-2 UI row.

Time is faked: an injected ``sleep`` records the wait intervals (and never actually
sleeps), and a monotonic ``time_source`` is advanced by the fake sleep so the token
bucket behaves deterministically.
"""

from __future__ import annotations

import asyncio

import pytest
from app.github.write_queue import (
    RateLimitState,
    SecondaryRateLimitError,
    WriteQueue,
)


class FakeClock:
    """A monotonic clock advanced explicitly + by the fake sleep (deterministic)."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        # Record the wait, advance virtual time, yield once so other tasks run.
        self.sleeps.append(seconds)
        self.t += seconds
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_serialized_ordering_of_concurrent_mutations() -> None:
    """Concurrent submits run one-at-a-time, in submission order (AC-7)."""
    clock = FakeClock()
    queue = WriteQueue(rate_per_minute=6000.0, sleep=clock.sleep, time_source=clock.now)

    order: list[str] = []
    in_flight = 0
    max_in_flight = 0

    def make(tag: str):
        async def _factory() -> str:
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0)  # give other tasks a chance to (wrongly) interleave
            order.append(tag)
            in_flight -= 1
            return tag

        return _factory

    # Submit three concurrently; their relative submission order is a, b, c.
    results = await asyncio.gather(
        queue.submit(make("a"), label="a"),
        queue.submit(make("b"), label="b"),
        queue.submit(make("c"), label="c"),
    )

    assert results == ["a", "b", "c"]
    assert order == ["a", "b", "c"]  # FIFO submission order preserved
    assert max_in_flight == 1  # never two mutations in flight at once (serialized)


@pytest.mark.asyncio
async def test_secondary_limit_waits_retry_after_and_does_not_interleave() -> None:
    """A 403 + Retry-After waits the advertised interval; no second mutation interleaves (AC-7)."""
    clock = FakeClock()
    queue = WriteQueue(rate_per_minute=6000.0, sleep=clock.sleep, time_source=clock.now)

    events: list[str] = []
    first_attempts = {"n": 0}

    async def first_mutation() -> str:
        first_attempts["n"] += 1
        if first_attempts["n"] == 1:
            # First attempt trips the secondary limit with a 7s Retry-After.
            events.append("first-403")
            raise SecondaryRateLimitError(retry_after=7.0)
        events.append("first-ok")
        return "first"

    async def second_mutation() -> str:
        # If this runs BEFORE the first mutation's retry completes, ordering broke.
        events.append("second-ok")
        return "second"

    # Submit the throttled mutation first, then a second mutation right behind it.
    task1 = asyncio.ensure_future(queue.submit(first_mutation, label="first"))
    task2 = asyncio.ensure_future(queue.submit(second_mutation, label="second"))
    r1, r2 = await asyncio.gather(task1, task2)

    assert r1 == "first"
    assert r2 == "second"
    # The queue waited the advertised 7s (capped backoff did not shorten it).
    assert 7.0 in clock.sleeps
    # The second mutation did NOT interleave: it ran only after the first retried OK.
    assert events == ["first-403", "first-ok", "second-ok"]
    # Accounting recorded the secondary hit and cleared the pause afterward.
    assert queue.rate_limit_state.secondary_hits == 1
    assert queue.rate_limit_state.secondary_limited is False


@pytest.mark.asyncio
async def test_retry_after_is_capped() -> None:
    """A pathological Retry-After is capped to max_retry_after_seconds (§8.1)."""
    clock = FakeClock()
    queue = WriteQueue(
        rate_per_minute=6000.0,
        max_retry_after_seconds=30.0,
        sleep=clock.sleep,
        time_source=clock.now,
    )
    attempts = {"n": 0}

    async def mutation() -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise SecondaryRateLimitError(retry_after=9999.0)  # absurd interval
        return "ok"

    result = await queue.submit(mutation, label="m")
    assert result == "ok"
    assert 30.0 in clock.sleeps  # capped, not 9999
    assert 9999.0 not in clock.sleeps


@pytest.mark.asyncio
async def test_token_bucket_paces_steady_state() -> None:
    """Once the burst is spent, further mutations wait for refill (pacing)."""
    clock = FakeClock()
    # 60/min = 1 token/sec, burst capacity 1 → second back-to-back call waits ~1s.
    queue = WriteQueue(rate_per_minute=60.0, burst=1.0, sleep=clock.sleep, time_source=clock.now)

    async def noop() -> str:
        return "ok"

    await queue.submit(noop)
    await queue.submit(noop)
    # The second submission had to wait for the bucket to refill ~1 token.
    assert any(s > 0 for s in clock.sleeps)


@pytest.mark.asyncio
async def test_graceful_shutdown_flushes_queued_mutation() -> None:
    """A queued ``agent:*`` mutation is FLUSHED on graceful shutdown, not dropped (INV-11).

    Dropping an enqueued (or in-flight) label PUT would leave the GitHub label and
    the active-run DB row inconsistent — the single-occupancy invariant this queue
    protects (§8.1). So ``stop`` must DRAIN: the in-flight job and every queued job
    run to completion before the queue stops.
    """
    clock = FakeClock()
    queue = WriteQueue(rate_per_minute=6000.0, sleep=clock.sleep, time_source=clock.now)

    executed: list[str] = []
    gate = asyncio.Event()

    async def slow_first() -> str:
        # Hold the in-flight slot until released, so a second job is genuinely
        # QUEUED (not yet started) when we call stop().
        await gate.wait()
        executed.append("first")
        return "first"

    async def queued_second() -> str:
        executed.append("second")
        return "second"

    task1 = asyncio.ensure_future(queue.submit(slow_first, label="first"))
    task2 = asyncio.ensure_future(queue.submit(queued_second, label="second"))
    # Let the worker pick up the first job and block on the gate, with the second
    # job sitting in the FIFO behind it.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # Begin a graceful drain in parallel, then release the in-flight job. Both the
    # in-flight AND the queued mutation must FLUSH (execute) before stop returns.
    stop_task = asyncio.ensure_future(queue.stop(grace=5.0))
    gate.set()
    await stop_task

    assert await task1 == "first"
    assert await task2 == "second"
    # BOTH ran, in order — the queued mutation was flushed, not cancelled.
    assert executed == ["first", "second"]


@pytest.mark.asyncio
async def test_graceful_shutdown_rejects_new_submissions_while_draining() -> None:
    """Once draining, a fresh ``submit`` is rejected so the backlog can flush cleanly."""
    clock = FakeClock()
    queue = WriteQueue(rate_per_minute=6000.0, sleep=clock.sleep, time_source=clock.now)

    async def noop() -> str:
        return "ok"

    await queue.submit(noop)
    await queue.stop(grace=1.0)
    with pytest.raises(RuntimeError):
        await queue.submit(noop)


@pytest.mark.asyncio
async def test_graceful_shutdown_bounded_backlog_terminates_within_grace() -> None:
    """An undrainable backlog still terminates within the grace window (no hang).

    The queue is token-bucket-paced, so a graceful shutdown must not block forever
    on a large backlog. A job that never completes (mid-PUT, wedged) must not wedge
    shutdown past the grace window: ``stop`` returns within ``grace`` and fails the
    remainder so awaiting ``submit`` calls unblock.
    """
    # Real time here (no fake sleep) so the grace bound is exercised end-to-end.
    queue = WriteQueue(rate_per_minute=6000.0)

    never = asyncio.Event()  # never set → the in-flight job blocks forever

    async def wedged() -> str:
        await never.wait()
        return "never"

    async def queued() -> str:  # pragma: no cover - never reached (drops on cancel)
        return "queued"

    task1 = asyncio.ensure_future(queue.submit(wedged, label="wedged"))
    task2 = asyncio.ensure_future(queue.submit(queued, label="queued"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    loop = asyncio.get_running_loop()
    start = loop.time()
    await queue.stop(grace=0.2)  # bounded grace
    elapsed = loop.time() - start

    # Terminated within (a small multiple of) the grace window — did NOT hang on
    # the wedged job.
    assert elapsed < 2.0
    # The wedged in-flight job was cancelled and the queued one's future cancelled,
    # so both awaiting submit() calls unblock rather than hanging past shutdown.
    for task in (task1, task2):
        with pytest.raises(asyncio.CancelledError):
            await task


def test_rate_limit_state_observes_primary_headers() -> None:
    """X-RateLimit-* headers fold into the accounting (FR-06-2)."""
    state = RateLimitState()
    state.observe_primary_headers(
        {
            "X-RateLimit-Remaining": "4321",
            "X-RateLimit-Limit": "5000",
            "X-RateLimit-Reset": "1700000000",
        }
    )
    assert state.primary_remaining == 4321
    assert state.primary_limit == 5000
    assert state.primary_reset == 1700000000


def test_rate_limit_state_ignores_garbage_headers() -> None:
    """Malformed header values are ignored, not crashed on."""
    state = RateLimitState()
    state.observe_primary_headers({"X-RateLimit-Remaining": "not-a-number"})
    assert state.primary_remaining is None
    state.observe_primary_headers(None)  # no headers → no-op
    assert state.primary_remaining is None
