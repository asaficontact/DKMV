"""The single serialized, token-bucket-paced GitHub write-queue (PRD §8.1).

**Why this exists (binding, §8.1 "Write-side rate limiting").** Every *mutating*
GitHub call — label replace-all (1.3), and later branch/PR/comment writes — hits
GitHub's **content-creation secondary limit (~80/min, 500/hr)**. That limit is
**not** reflected in ``X-RateLimit-Remaining`` (which tracks the *primary* hourly
budget), and exceeding it returns **403 + ``Retry-After``**. A naive "fire writes
as they come, retry-on-403 immediately" loop turns one over-limit response into a
storm of further-throttled retries. The PRD's mitigation is to **route all
mutating calls through a single serialized write-queue with token-bucket pacing**,
handling 403-secondary/``Retry-After`` *distinctly* from primary-limit pressure.

This module is that queue. Its contract:

* **Serialized.** At most one mutation is in flight at a time (an
  :class:`asyncio.Lock` worker draining a FIFO :class:`asyncio.Queue`). Two
  concurrent ``submit(...)`` calls run **in submission order**, never interleaved
  — so a label write and a (later) PR write never race on GitHub's secondary
  budget. (AC-7: "serialized ordering of concurrent mutations".)
* **Token-bucket paced.** A simple bucket (capacity + refill rate, defaulted to
  ~80/min to mirror the secondary limit) gates each mutation so the steady-state
  rate stays under the limit *before* GitHub ever has to 403 us.
* **Secondary-limit aware.** When a mutation raises a
  :class:`SecondaryRateLimitError` (403 + ``Retry-After``), the worker **waits the
  advertised interval** (capped backoff) and **retries the same mutation** —
  without starting the next one and without an immediate hammer-retry. (AC-7: "a
  403/``Retry-After`` is honored, not retried immediately"; "the queue waits the
  advertised interval and does not interleave a second mutation".)
* **Accounting surfaced.** The latest ``X-RateLimit-*`` headroom and the current
  secondary-limit pause state are recorded on :class:`RateLimitState` for the
  later FR-06-2 UI row (built in Phase 3 — the accounting is exposed now).

The queue is **read-free**: GraphQL board reads (1.2) are cheaper points and do
**not** go through it (they use the hash-cache instead). The queue does not edit
``dkmv/`` and constructs no GitHub URL itself — callers pass a coroutine factory
that performs the actual mutating HTTP call (the PAT client's PUT-labels
primitive). It is an in-process, single-event-loop component (the orchestrator
and the API handlers share one loop), so its state needs no cross-thread locking.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

#: GitHub's content-creation **secondary** limit is ~80 writes/min (§8.1). The
#: default token bucket is sized to that so the steady-state write rate stays
#: under the limit without ever provoking a 403. Capacity allows a small burst.
DEFAULT_RATE_PER_MINUTE = 80.0

#: Max seconds we will honor from a ``Retry-After`` before capping the backoff
#: (§8.1 "capped backoff"). A pathological/very large ``Retry-After`` must not
#: wedge the queue indefinitely; we cap and re-evaluate.
DEFAULT_MAX_RETRY_AFTER_SECONDS = 60.0

#: Default fallback wait when a 403-secondary carries no parseable ``Retry-After``
#: header (GitHub usually sends one, but we must not busy-loop if it is absent).
DEFAULT_FALLBACK_RETRY_SECONDS = 1.0


class SecondaryRateLimitError(Exception):
    """A mutating call hit GitHub's **secondary** (content-creation) limit (§8.1).

    Carries the advertised ``Retry-After`` interval (seconds) so the write-queue
    worker can **wait exactly that long** before retrying the *same* mutation —
    the distinct-from-primary handling the PRD mandates. The mutation callable
    (the PAT client's PUT-labels primitive) raises this on a 403 whose body/headers
    indicate the secondary limit, rather than letting it surface as a generic
    error that a caller might blindly retry.

    ``retry_after`` is the seconds to wait; ``None`` means GitHub sent no parseable
    value and the queue should fall back to :data:`DEFAULT_FALLBACK_RETRY_SECONDS`.
    """

    def __init__(
        self,
        message: str = "GitHub secondary rate limit",
        *,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(slots=True)
class RateLimitState:
    """The accounting surfaced for the later rate-limit UI row (FR-06-2, §8.1).

    Records the **primary** budget headroom from the last seen ``X-RateLimit-*``
    headers (these track the hourly *primary* limit, NOT the secondary one — §8.1)
    plus the **secondary** limit pause state. The Phase-3 UI reads this; Phase 1
    only has to *expose* the accounting, which is what this dataclass does.
    """

    #: Last seen ``X-RateLimit-Remaining`` (primary hourly budget), or ``None``.
    primary_remaining: int | None = None
    #: Last seen ``X-RateLimit-Limit`` (primary hourly ceiling), or ``None``.
    primary_limit: int | None = None
    #: Last seen ``X-RateLimit-Reset`` (epoch seconds), or ``None``.
    primary_reset: int | None = None
    #: ``True`` while the queue is paused honoring a 403-secondary ``Retry-After``.
    secondary_limited: bool = False
    #: Seconds the queue is currently waiting on the secondary limit (0 when not).
    secondary_retry_after: float = 0.0
    #: Count of 403-secondary hits observed (diagnostics / the UI badge).
    secondary_hits: int = 0

    def observe_primary_headers(self, headers: Any) -> None:
        """Fold ``X-RateLimit-*`` headers (primary budget) into the accounting.

        Accepts any mapping-ish object exposing ``.get(name)`` (an
        :class:`httpx.Headers`, a plain dict, or a test fake). Non-integer / absent
        values are ignored so a malformed header never crashes a mutation.
        """
        if headers is None:
            return
        getter = getattr(headers, "get", None)
        if getter is None:
            return
        self.primary_remaining = _maybe_int(getter("X-RateLimit-Remaining"))
        self.primary_limit = _maybe_int(getter("X-RateLimit-Limit"))
        self.primary_reset = _maybe_int(getter("X-RateLimit-Reset"))


def _maybe_int(value: Any) -> int | None:
    """Best-effort int parse; ``None`` on a missing/garbage value."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class _TokenBucket:
    """A monotonic-clock token bucket pacing the steady-state write rate (§8.1).

    ``capacity`` tokens accrue at ``refill_per_second``; each mutation consumes
    one. :meth:`time_until_token` returns how long the worker must sleep before a
    token is available (0 when one already is). Lives on the single event loop, so
    no locking is needed around the float arithmetic.
    """

    capacity: float
    refill_per_second: float
    _tokens: float = field(init=False)
    _last: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self._tokens = self.capacity

    def _refill(self, now: float) -> None:
        if self._last == 0.0:
            self._last = now
            return
        elapsed = max(0.0, now - self._last)
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_second)
        self._last = now

    def time_until_token(self, now: float) -> float:
        """Seconds until a token is available (0 if one is now)."""
        self._refill(now)
        if self._tokens >= 1.0:
            return 0.0
        if self.refill_per_second <= 0:  # pragma: no cover - guarded by ctor
            return 0.0
        return (1.0 - self._tokens) / self.refill_per_second

    def consume(self, now: float) -> None:
        """Consume one token (call only when :meth:`time_until_token` returned 0)."""
        self._refill(now)
        self._tokens = max(0.0, self._tokens - 1.0)


@dataclass(slots=True)
class _Job[T]:
    """One queued mutation: the coroutine factory + its result future."""

    factory: Callable[[], Awaitable[T]]
    future: asyncio.Future[T]
    label: str


class WriteQueue:
    """The single serialized, token-bucket-paced GitHub write-queue (§8.1, INV-11).

    All mutating GitHub calls (``set_agent_state`` now; branch/PR/comment later)
    are submitted here via :meth:`submit`, which returns a future resolving to the
    mutation's result. A single worker drains the FIFO so:

    * mutations run **one at a time, in submission order** (serialized; AC-7),
    * each is paced by the token bucket (steady-state under the secondary limit),
    * a :class:`SecondaryRateLimitError` (403 + ``Retry-After``) **pauses the
      worker** for the advertised interval (capped) and **retries the same
      mutation** before the next one is dequeued (no interleave; AC-7).

    Args:
        rate_per_minute: token-bucket refill rate (default ~80/min, the secondary
            limit, §8.1).
        burst: bucket capacity (small burst allowed); defaults to one minute's
            worth of tokens capped to a sane small number.
        max_retry_after_seconds: cap on a honored ``Retry-After`` (§8.1 capped
            backoff).
        sleep: injectable async sleep (tests pass a fake to assert the wait
            without real time passing).
        time_source: injectable monotonic clock for the bucket.
    """

    def __init__(
        self,
        *,
        rate_per_minute: float = DEFAULT_RATE_PER_MINUTE,
        burst: float | None = None,
        max_retry_after_seconds: float = DEFAULT_MAX_RETRY_AFTER_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        time_source: Callable[[], float] | None = None,
    ) -> None:
        import time as _time

        refill = max(0.0, rate_per_minute) / 60.0
        capacity = burst if burst is not None else min(max(1.0, rate_per_minute), 10.0)
        self._bucket = _TokenBucket(capacity=capacity, refill_per_second=refill)
        self._max_retry_after = max_retry_after_seconds
        self._sleep = sleep
        self._now = time_source or _time.monotonic
        self._queue: asyncio.Queue[_Job[Any]] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._state = RateLimitState()

    @property
    def rate_limit_state(self) -> RateLimitState:
        """The current rate-limit accounting (FR-06-2 UI row reads this)."""
        return self._state

    def _ensure_worker(self) -> None:
        """Lazily start the single drain worker on the running loop."""
        if self._worker is None or self._worker.done():
            self._worker = asyncio.ensure_future(self._run())

    async def submit[T](self, factory: Callable[[], Awaitable[T]], *, label: str = "mutation") -> T:
        """Enqueue a mutating call; await its result (serialized + paced).

        ``factory`` is a **coroutine factory** (a zero-arg callable returning the
        awaitable that performs the actual mutating GitHub HTTP call), so the
        worker can *re-invoke* it on a secondary-limit retry. It must raise
        :class:`SecondaryRateLimitError` on a 403-secondary so the queue can wait
        the ``Retry-After`` rather than surfacing a blind error. ``label`` is for
        diagnostics only.

        Returns the mutation's result once the worker has run it (after any pacing
        wait and any honored ``Retry-After`` retries). Re-raises any other
        exception the mutation raised.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        await self._queue.put(_Job(factory=factory, future=future, label=label))
        self._ensure_worker()
        return await future

    async def _run(self) -> None:
        """Drain the FIFO one job at a time (the single serialized worker)."""
        while True:
            job = await self._queue.get()
            try:
                result = await self._run_one(job)
            except asyncio.CancelledError:  # pragma: no cover - shutdown path
                if not job.future.done():
                    job.future.cancel()
                raise
            except Exception as exc:  # noqa: BLE001 - propagate to the awaiting submit()
                if not job.future.done():
                    job.future.set_exception(exc)
            else:
                if not job.future.done():
                    job.future.set_result(result)
            finally:
                self._queue.task_done()
            # Exit when idle so a fresh submit() respawns a worker on the live loop
            # (tests build a queue, submit, and let the loop close between cases).
            if self._queue.empty():
                return

    async def _run_one[T](self, job: _Job[T]) -> T:
        """Pace, run, and honor a 403-secondary ``Retry-After`` for one job (§8.1)."""
        while True:
            await self._wait_for_token()
            self._bucket.consume(self._now())
            try:
                result = await job.factory()
            except SecondaryRateLimitError as exc:
                # Distinct-from-primary handling (§8.1): wait the advertised
                # interval (capped), do NOT start the next mutation, then retry
                # THIS same mutation. No immediate hammer-retry.
                wait = self._capped_retry_after(exc.retry_after)
                self._state.secondary_limited = True
                self._state.secondary_retry_after = wait
                self._state.secondary_hits += 1
                await self._sleep(wait)
                self._state.secondary_limited = False
                self._state.secondary_retry_after = 0.0
                continue
            return result

    async def _wait_for_token(self) -> None:
        """Sleep until the token bucket yields a token (steady-state pacing)."""
        wait = self._bucket.time_until_token(self._now())
        if wait > 0:
            await self._sleep(wait)

    def _capped_retry_after(self, retry_after: float | None) -> float:
        """Clamp a ``Retry-After`` to ``[fallback, max]`` (§8.1 capped backoff)."""
        if retry_after is None or retry_after <= 0:
            value = DEFAULT_FALLBACK_RETRY_SECONDS
        else:
            value = retry_after
        return min(value, self._max_retry_after)
