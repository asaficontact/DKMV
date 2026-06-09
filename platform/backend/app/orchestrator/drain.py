"""Graceful drain on SIGTERM — stop dispatch + stop containers (PRD §8.2 — AC-18).

A ``docker compose restart`` (and a laptop shutdown) is **routine**. The load-
bearing fact this module exists for (INV-10, binding): **cancelling a run's
``asyncio.Task`` does NOT stop its Docker container** — the engine spawns the
container out-of-process, so a bare task-cancel leaves an orphaned 8 GB
money-spending container behind. Graceful drain therefore, on SIGTERM:

1. **Stops dispatching new runs** — it sets the tick loop's ``stop`` event so the
   cadence loop wakes and exits; no new candidate is launched while draining.
2. **For each LIVE run, stops its container** via ``RunHandle.stop(force=True)``
   (the engine's ``finally`` then stops the container — the *only* correct kill;
   never a bare cancel) within a **drain deadline**. The deadline is a
   **UTC-persisted** comparison (:mod:`app.orchestrator.deadlines`) re-evaluated
   against a fresh ``now()`` — never an ``asyncio.sleep`` until-due — so a drain
   that races a suspend still honors its budget the instant the loop resumes.
3. **Marks any run it could not cleanly stop ``interrupted``** and records it for
   the boot sweep (:mod:`app.orchestrator.recovery`), so the next boot
   ``docker kill``s any container the in-process stop did not reach.

The container kill goes through the **same** :class:`~app.orchestrator.reconcile.RunKiller`
seam reconcile/3.3 uses (the tick binds it to the in-process engine
``RunHandle.stop(force=True)``), so there is exactly one "stop a live container"
implementation; a test injects a recording fake and asserts every live run's
container was stopped (none left running) and any undrained run was marked
``interrupted``. Nothing here shells the ``dkmv`` CLI or edits ``dkmv/`` (INV-13).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.github.sync import ACTIVE_RUN_STATUSES
from app.orchestrator.deadlines import Clock, due_at_from_now, is_due, utc_now

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.db.repository import Repository
    from app.orchestrator.reconcile import RunKiller

_log = logging.getLogger(__name__)

#: The ``interrupted`` terminal status a drain stamps on a run whose container it
#: could not cleanly stop within the deadline — the platform-only status the boot
#: sweep (recovery.py) keys on and the history UI maps to the cancel palette (§6.5).
INTERRUPTED_STATUS = "interrupted"

#: Default seconds the drain has to stop every live container before it gives up
#: and marks the remainder ``interrupted`` for the boot sweep. A persisted UTC
#: ``due_at`` (never a slept timer) bounds the SIGTERM handler so a hung engine
#: stop cannot wedge shutdown forever (NFR-REL-1).
DEFAULT_DRAIN_DEADLINE_S = 30.0


@dataclass(frozen=True, slots=True)
class DrainResult:
    """Outcome of one :func:`drain` pass (for tests + the shutdown log).

    ``stopped`` is the run_ids whose container the in-process ``stop(force=True)``
    actually stopped; ``interrupted`` is the run_ids the drain could **not** cleanly
    stop (no live handle, a stop error, or the deadline elapsed) and therefore
    marked ``interrupted`` + recorded for the boot sweep. Their union is every live
    run the drain considered — none is left running-and-unaccounted.
    """

    stopped: tuple[str, ...] = ()
    interrupted: tuple[str, ...] = ()

    @property
    def considered(self) -> int:
        """Total live runs this drain considered (stopped + interrupted)."""
        return len(self.stopped) + len(self.interrupted)


@dataclass(slots=True)
class DrainDeps:
    """Everything a drain pass needs, resolved from the lifespan ``app.state`` seam.

    The lifespan composes this from the single-writer :class:`Repository` (INV-6 —
    the status writes go through it) and the **same** :class:`RunKiller` the tick
    binds to the in-process engine handle (``RunHandle.stop(force=True)`` — INV-10),
    so the drain reuses the one correct "stop a live container" path. ``repo`` scopes
    the live-run query to the connected project's board (§8.8). ``deadline_s`` is the
    drain budget; ``now`` is injectable so a frozen-clock test drives the
    UTC-persisted deadline deterministically (AC-13/18).
    """

    repository: Repository
    killer: RunKiller
    repo: str
    deadline_s: float = DEFAULT_DRAIN_DEADLINE_S
    now: Clock = field(default=utc_now)


async def drain(deps: DrainDeps) -> DrainResult:
    """Stop every live run's container within the deadline; interrupt the rest (AC-18).

    The SIGTERM body (the lifespan calls it before tearing the singletons down). For
    each **active** run in ``deps.repo``:

    * while the **UTC-persisted drain deadline** has not elapsed
      (:func:`app.orchestrator.deadlines.is_due` against a fresh ``now()`` — never a
      slept timer, AC-13), ask the :class:`RunKiller` to ``stop(force=True)`` the
      run's container (the engine ``finally`` stops it — never a bare task-cancel,
      INV-10). A run actually stopped is recorded as ``stopped``;
    * a run with **no live handle** (already gone / started by another process), a
      run whose stop **raised**, or any run **remaining after the deadline** is
      marked **``interrupted``** (so the boot sweep ``docker kill``s any container
      the in-process stop did not reach) and recorded as ``interrupted``.

    Returns a :class:`DrainResult`. Never raises into the lifespan — a per-run stop
    failure degrades that run to ``interrupted`` (the conservative, container-reaping
    choice) rather than aborting the whole drain and leaking the *other* containers.
    """
    deadline = due_at_from_now(max(0.0, deps.deadline_s), now=deps.now)
    live = await _read_active_run_rows(deps.repository, deps.repo)
    _log.info(
        "orchestrator.drain starting repo=%s live_runs=%d deadline_s=%.0f",
        deps.repo,
        len(live),
        deps.deadline_s,
    )

    stopped: list[str] = []
    interrupted: list[str] = []
    for row in live:
        run_id = str(row["id"])
        # Re-evaluate the persisted deadline against a fresh now() each iteration
        # (AC-13): a drain that overran its budget interrupts the remainder rather
        # than blocking shutdown forever — the boot sweep docker-kills them.
        if is_due(deadline, now=deps.now):
            _log.warning("orchestrator.drain deadline elapsed; interrupting run=%s", run_id)
            await _mark_interrupted(deps.repository, run_id)
            interrupted.append(run_id)
            continue
        try:
            killed = await deps.killer.kill(row)
        except Exception:  # noqa: BLE001 - a stop failure must not leak the OTHER containers
            _log.exception("orchestrator.drain stop failed run=%s; marking interrupted", run_id)
            await _mark_interrupted(deps.repository, run_id)
            interrupted.append(run_id)
            continue
        if killed:
            # The in-process stop(force=True) stopped the container cleanly.
            await deps.repository.update_run_fields(run_id, status="cancelled")
            stopped.append(run_id)
            _log.info("orchestrator.drain stopped container run=%s", run_id)
        else:
            # No live handle in THIS process — do NOT re-attach (INV-10). Mark
            # interrupted so the boot sweep docker-kills the orphan container.
            await _mark_interrupted(deps.repository, run_id)
            interrupted.append(run_id)
            _log.info(
                "orchestrator.drain no live handle for run=%s; marked interrupted for boot sweep",
                run_id,
            )

    _log.info(
        "orchestrator.drain done repo=%s stopped=%d interrupted=%d",
        deps.repo,
        len(stopped),
        len(interrupted),
    )
    return DrainResult(stopped=tuple(stopped), interrupted=tuple(interrupted))


async def drain_with_stop(deps: DrainDeps, *, stop: asyncio.Event) -> DrainResult:
    """Stop dispatch (set the tick ``stop`` event) **then** drain (AC-18 step 1+2).

    The full SIGTERM sequence: first **stop dispatching new runs** by setting the
    orchestrator's ``stop`` event (the tick loop's cadence wait wakes and the loop
    exits — no new candidate is launched mid-drain), then run :func:`drain` to stop
    every live container within the deadline. Splitting "stop dispatch" out keeps the
    drain testable without an event, while the lifespan/SIGTERM handler uses this
    ordered form so a draining process never admits new work it would then orphan.
    """
    stop.set()
    return await drain(deps)


async def _mark_interrupted(repository: Repository, run_id: str) -> None:
    """Stamp a run ``interrupted`` (the boot-sweep + history-palette status).

    The single status write for an undrained run (INV-6 — through the single
    writer). ``interrupted`` (not ``cancelled``) so the boot sweep keys on it as a
    *crash-orphaned* run to ``docker kill`` + offer a ``start_task`` retry, distinct
    from a cleanly user-cancelled run.
    """
    await repository.update_run_fields(run_id, status=INTERRUPTED_STATUS)


async def _read_active_run_rows(repository: Repository, repo: str) -> list[dict[str, Any]]:
    """Read this repo's non-terminal ``runs`` rows (full row) for the drain.

    Through the repository's public WAL read seam (INV-6 — the drain never opens its
    own connection). The full row (incl. ``engine_run_id``) is needed so the
    :class:`RunKiller` can resolve the engine handle to ``stop(force=True)`` the
    container. Mirrors reconcile's active-run read so drain and reconcile agree on
    "which runs are live".
    """
    statuses = sorted(ACTIVE_RUN_STATUSES)
    placeholders = ", ".join("?" for _ in statuses)
    async with repository.read_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT * FROM runs "  # noqa: S608 — placeholders only, statuses bound
            f"WHERE repo = ? AND status IN ({placeholders}) ORDER BY started_at",
            (repo, *statuses),
        )
        return [dict(r) for r in rows]


__all__ = [
    "DEFAULT_DRAIN_DEADLINE_S",
    "INTERRUPTED_STATUS",
    "DrainDeps",
    "DrainResult",
    "drain",
    "drain_with_stop",
]
