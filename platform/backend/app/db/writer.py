"""The single serialized writer task (INV-6 / PRD §6.5).

SQLite is single-writer. Rather than fight that with retries, the platform
*embraces* it: **every** write goes through one dedicated :class:`Writer` task
that owns the sole write connection and runs each unit of work inside a short
``BEGIN IMMEDIATE`` … ``COMMIT`` transaction. Callers submit a *write function*
to an :class:`asyncio.Queue`; the writer drains the queue serially and returns
each result through a per-job future.

Why this shape (binding consequences):

* **No two writers ever contend** → ``database is locked`` cannot arise from
  *our* concurrency (the 5-writer×4 Hz load test, AC-0.3-3, proves it). The only
  remaining writer is Alembic, which never runs while the app serves.
* **``BEGIN IMMEDIATE``** takes the write lock at transaction start (not lazily
  on first write), so the idempotency claim-insert (INV-5) and the read-modify
  steps inside a job see a consistent, exclusively-held lock for the whole unit.
* **Reads do NOT go through here.** They open their own connections
  (:func:`app.db.connection.connect`) and run concurrently under WAL — only
  writes are serialized.

Each submitted job is a coroutine ``fn(conn)`` that runs *inside* the
already-open ``BEGIN IMMEDIATE`` transaction; it must not commit/rollback itself.
If it raises, the writer rolls back and propagates the exception to the caller's
future; otherwise the writer commits and returns the job's value.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import aiosqlite

from app.db.connection import connect

T = TypeVar("T")

#: A unit of write work: a coroutine run *inside* a BEGIN IMMEDIATE transaction.
WriteJob = Callable[[aiosqlite.Connection], Awaitable[T]]


class _Job:
    """An enqueued write job paired with the future that delivers its result."""

    __slots__ = ("fn", "future")

    def __init__(
        self,
        fn: WriteJob[object],
        future: asyncio.Future[object],
    ) -> None:
        self.fn = fn
        self.future = future


class Writer:
    """Owns the single write connection and serializes all write transactions.

    Lifecycle::

        writer = Writer(database_url)
        await writer.start()
        result = await writer.submit(lambda conn: do_write(conn))
        await writer.stop()

    ``submit`` is safe to call from any coroutine on the loop; jobs are processed
    strictly in submission order.
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._queue: asyncio.Queue[_Job] = asyncio.Queue()
        self._conn: aiosqlite.Connection | None = None
        self._task: asyncio.Task[None] | None = None
        self._started = asyncio.Event()

    async def start(self) -> None:
        """Open the write connection and launch the drain loop."""
        if self._task is not None:
            return
        self._conn = await connect(self._database_url)
        self._task = asyncio.create_task(self._run(), name="db-writer")
        await self._started.wait()

    async def _run(self) -> None:
        assert self._conn is not None
        self._started.set()
        while True:
            job = await self._queue.get()
            try:
                result = await self._execute(job.fn)
            except asyncio.CancelledError:
                # Re-deliver cancellation to the waiter and stop the loop.
                if not job.future.done():
                    job.future.cancel()
                raise
            except BaseException as exc:  # noqa: BLE001 — surface to the caller
                if not job.future.done():
                    job.future.set_exception(exc)
            else:
                if not job.future.done():
                    job.future.set_result(result)
            finally:
                self._queue.task_done()

    async def _execute(self, fn: WriteJob[object]) -> object:
        """Run one job inside a short BEGIN IMMEDIATE … COMMIT transaction."""
        assert self._conn is not None
        conn = self._conn
        await conn.execute("BEGIN IMMEDIATE")
        try:
            result = await fn(conn)
        except BaseException:
            await conn.execute("ROLLBACK")
            raise
        await conn.execute("COMMIT")
        return result

    async def submit(self, fn: WriteJob[T]) -> T:
        """Enqueue a write job and await its result.

        ``fn`` receives the writer's connection inside an open
        ``BEGIN IMMEDIATE`` transaction and must NOT commit/rollback itself.
        """
        if self._task is None:
            raise RuntimeError("Writer.start() must be called before submit()")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[object] = loop.create_future()
        # The cast is safe: the future resolves with whatever ``fn`` returns.
        self._queue.put_nowait(_Job(fn, future))  # type: ignore[arg-type]  # DKMVP-ESCAPE: heterogeneous job queue, T recovered via the per-call future
        result = await future
        return result  # type: ignore[return-value]  # DKMVP-ESCAPE: future typed as object; bound to T by the submit() signature

    async def stop(self) -> None:
        """Cancel the drain loop and close the write connection."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
        self._started.clear()
