"""Boot crash recovery — kill orphan + interrupt + offer retry (PRD §8.2 — AC-19).

The other half of the durability story (INV-10 / ADR-P007 / R-15, binding). When
the backend process dies (a crash, an ``OOM`` kill, a yanked power cord) the
``runs`` rows of its in-flight runs are left **non-terminal** in the DB, but their
Docker containers were started **out-of-process** and are still **alive and
spending money**. On the next boot — **before** the tick starts dispatching new
work — recovery scans those orphans and, for **each non-terminal ``runs`` row**:

1. **``docker kill`` the orphaned container.** It is unfinishable (the engine task
   that drove it is gone) and budget-burning, so it is killed through the injected
   :class:`OrphanReaper` seam (a ``docker kill`` of the ``run_id``-labeled
   container — routed through the executor/Docker abstraction so a CI test can
   assert the kill was *issued* for every orphan **without** real Docker).
2. **Mark the run ``interrupted``.** The platform-only terminal status the history
   UI maps to the cancel palette (§6.5) and that ``POST /runs/{id}/retry`` accepts.
3. **Offer a retry** — optionally re-launching with ``start_task=<last completed
   stage>`` so the engine reconstructs prior stage outputs **from the pushed
   branch**. Only stages whose outputs were **committed/pushed** can be recovered;
   otherwise the run simply stays ``interrupted`` and a human decides. The retry is
   enqueued through **3.4's existing scheduler** (:meth:`RetryScheduler.enqueue_manual`
   → the tick's idempotent re-dispatch via :func:`launch_run` — ADR-P001), so there
   is **no second launch path** and the existing-branch/PR detection guarantees a
   retry of an issue with an open PR creates **no duplicate PR** (AC-15/20).

**INV-10 — NO re-attach (binding).** The code MUST NOT attempt to re-attach an
observer to, or resume, a container started by a dead process — the engine has no
such API (R-15). Recovery is **kill + interrupt + ``start_task`` retry only**;
``reconcile_stale_runs`` (engine) only writes ``cancelled`` for dead containers and
``replay_events`` only *reads* the persisted ``stream.jsonl`` — neither resumes a
live run.

To avoid a **boot thundering-herd** on Docker + the GitHub API (every orphan
re-dispatching at once), the retry offer is **jittered** (a small per-run
randomized backoff) and routed through the **same** ``settings.MAX_CONCURRENT_RUNS``
semaphore the tick dispatch is bounded by (reusing 3.4's retry path) — so recovery
admits orphans gradually, never in a stampede.

Nothing here shells the ``dkmv`` CLI or edits ``dkmv/`` (INV-13): the container
kill is the :class:`OrphanReaper` seam, the retry is the in-process scheduler.
"""

from __future__ import annotations

import asyncio
import logging
import random
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from app.github.sync import ACTIVE_RUN_STATUSES

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.db.repository import Repository
    from app.orchestrator.retry import RetryScheduler
    from app.runtime import RunService

_log = logging.getLogger(__name__)

#: The platform-only terminal status a crash-orphaned run is stamped with on boot
#: (the same status drain uses for an undrained run). The history UI maps it to the
#: cancel palette + an "Interrupted" label (§6.5), and ``POST /runs/{id}/retry``
#: accepts it for a ``start_task`` retry.
INTERRUPTED_STATUS = "interrupted"

#: Default ceiling (seconds) for the per-orphan recovery-retry jitter. Each offered
#: retry is delayed by a random ``[0, JITTER]`` so a boot with N orphans does not
#: stampede Docker + GitHub all at once (a thundering herd) — the orphans admit
#: gradually, additionally bounded by the shared concurrency semaphore.
DEFAULT_RECOVERY_JITTER_S = 5.0


class OrphanReaper(Protocol):
    """Docker-kill-by-``run_id`` seam for a **dead-process** orphan (INV-10 — binding).

    Distinct from the :class:`~app.orchestrator.reconcile.RunKiller` (which stops a
    **live, in-process** run via its engine ``RunHandle.stop(force=True)``): a
    crash-orphaned container has **no live handle in this process** (the process
    that started it is dead), so the only way to stop it is a ``docker kill`` of the
    ``run_id``-labeled container. ``reap(run_row)`` issues that kill and returns
    ``True`` iff a kill was **issued** for the orphan (a CI test injects a fake that
    records the issued kills + asserts ``docker ps`` would show no surviving
    ``run_id``-labeled container — without real Docker). The implementation **MUST
    NOT** re-attach an observer to the container — it only kills it.
    """

    async def reap(self, run_row: dict[str, Any]) -> bool: ...


class DockerOrphanReaper:
    """:class:`OrphanReaper` that ``docker kill``s a crash-orphaned container.

    The v1 (local Docker) reaper. It resolves the orphan's container name from the
    engine — the engine persists ``runs/{engine_run_id}/container.txt`` and exposes
    it via ``EmbeddedRuntime.get_container_status(run_id).container_name`` (consumed
    in-process, INV-13) — and issues a single ``docker kill <name>`` to stop the
    budget-burning orphan. It **never** re-attaches an observer (INV-10): it only
    kills. The ``docker kill`` runs off the event loop (``asyncio.to_thread`` over
    the blocking ``subprocess``) so a slow daemon does not block the boot. Returns
    ``True`` iff a kill was issued for a resolvable orphan container; ``False`` when
    no container name is known (nothing to kill) or ``docker`` is unavailable.

    A CI test injects a **fake** reaper (recording the issued kills) instead of this,
    so the resilience suite asserts "no surviving ``run_id``-labeled container"
    without real Docker; an optional real-Docker-gated variant uses this class.
    """

    def __init__(self, run_service: RunService) -> None:
        self._run_service = run_service

    async def reap(self, run_row: dict[str, Any]) -> bool:
        engine_run_id = run_row.get("engine_run_id")
        if not engine_run_id:
            # No engine run id yet (the run never reached start()) → no container to
            # kill. The row is still marked interrupted by the caller (INV-10).
            return False
        container_name = await asyncio.to_thread(self._resolve_container_name, str(engine_run_id))
        if not container_name:
            return False
        return await asyncio.to_thread(self._docker_kill, container_name)

    def _resolve_container_name(self, engine_run_id: str) -> str | None:
        """Resolve the orphan's container name from the engine (in-process, INV-13)."""
        try:
            status = self._run_service.runtime.get_container_status(engine_run_id)
        except Exception:  # noqa: BLE001 - a status probe failure → nothing to kill here
            _log.warning(
                "orchestrator.recovery container-name resolve failed run=%s",
                engine_run_id,
                exc_info=True,
            )
            return None
        name = getattr(status, "container_name", None)
        return str(name) if name else None

    @staticmethod
    def _docker_kill(container_name: str) -> bool:
        """Issue ``docker kill <name>`` for the orphan (blocking; off the loop).

        Returns ``True`` iff the kill command was issued (``docker`` is present and
        ran); a non-zero exit (the container already gone) still counts as "the
        orphan is not running", so the caller treats the orphan as reaped. ``docker``
        not on PATH → ``False`` (a dev box without Docker; the run is still marked
        interrupted). Never re-attaches — this only kills (INV-10).
        """
        if shutil.which("docker") is None:
            return False
        try:
            subprocess.run(  # noqa: S603,S607 - fixed argv, container name from engine state
                ["docker", "kill", container_name],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (subprocess.SubprocessError, OSError):
            _log.warning("orchestrator.recovery docker kill failed name=%s", container_name)
            return False
        return True


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """Outcome of one :func:`recover_orphans` boot scan (for tests + the boot log).

    ``reaped`` is the run_ids whose orphan container a ``docker kill`` was issued
    for; ``interrupted`` is the run_ids marked ``interrupted`` (every scanned
    orphan); ``retried`` is the run_ids a ``start_task`` retry was **offered** for
    (a subset — only orphans with a committed/pushed stage to resume from, and only
    when a scheduler is wired). ``reaped`` ⊆ ``interrupted`` ⊇ ``retried``.
    """

    reaped: tuple[str, ...] = ()
    interrupted: tuple[str, ...] = ()
    retried: tuple[str, ...] = ()


@dataclass(slots=True)
class RecoveryDeps:
    """Everything the boot scan needs, resolved from the lifespan ``app.state`` seam.

    The lifespan composes this from the single-writer :class:`Repository` (INV-6 —
    the ``interrupted`` status writes go through it), the :class:`OrphanReaper`
    ``docker kill`` seam (INV-10), and **3.4's existing** :class:`RetryScheduler`
    (the retry offer reuses ``enqueue_manual`` → the tick's idempotent re-dispatch —
    no second launch path). ``repo`` is the connected project; ``offer_retry`` gates
    whether boot auto-offers the ``start_task`` retry (vs. leaving every orphan
    ``interrupted`` for a manual *Retry now*). ``jitter_s`` + ``concurrency`` bound
    the recovery dispatch so a boot does not stampede Docker/GitHub. ``rng`` is
    injectable so the jitter is deterministic in tests.
    """

    repository: Repository
    reaper: OrphanReaper
    repo: str
    retry_scheduler: RetryScheduler | None = None
    offer_retry: bool = True
    jitter_s: float = DEFAULT_RECOVERY_JITTER_S
    concurrency: asyncio.Semaphore | None = None
    rng: random.Random = field(default_factory=random.Random)


async def recover_orphans(deps: RecoveryDeps) -> RecoveryResult:
    """Boot scan: kill + interrupt + offer-retry every orphan run (AC-19 — binding).

    Runs **once at startup, before the tick dispatches** (the lifespan calls it
    after composing the singletons and before ``start_orchestrator``). For each
    **non-terminal ``runs`` row** in ``deps.repo`` (a run the dead process left
    in-flight):

    1. ``docker kill`` the orphan container via the :class:`OrphanReaper` seam — it
       is unfinishable + budget-burning. (NO re-attach — INV-10.)
    2. Mark the run **``interrupted``** through the single writer (INV-6).
    3. If ``offer_retry`` and a scheduler is wired and the run has a committed/pushed
       stage to resume from, **offer a jittered, semaphore-bounded ``start_task``
       retry** via 3.4's :meth:`RetryScheduler.enqueue_manual` (→ the tick's
       idempotent re-dispatch; existing-branch/PR detection means no duplicate PR).

    Returns a :class:`RecoveryResult`. Never raises into the lifespan — a per-orphan
    reap/interrupt failure is logged and the scan continues to the next orphan
    (leaving no other orphan unhandled because one row was malformed).
    """
    orphans = await _read_non_terminal_run_rows(deps.repository, deps.repo)
    _log.info("orchestrator.recovery boot scan repo=%s orphans=%d", deps.repo, len(orphans))

    reaped: list[str] = []
    interrupted: list[str] = []
    retried: list[str] = []
    for row in orphans:
        run_id = str(row["id"])
        try:
            killed = await deps.reaper.reap(row)
        except Exception:  # noqa: BLE001 - a reap failure must not skip the OTHER orphans
            _log.exception("orchestrator.recovery reap failed run=%s", run_id)
            killed = False
        if killed:
            reaped.append(run_id)
        # Mark interrupted regardless of the reap outcome: the run is crash-orphaned
        # and unfinishable; the worst case (no container actually alive) just leaves
        # the row correctly terminal. NEVER re-attach to drive it (INV-10).
        try:
            await deps.repository.update_run_fields(run_id, status=INTERRUPTED_STATUS)
            interrupted.append(run_id)
        except Exception:  # noqa: BLE001 - keep scanning the remaining orphans
            _log.exception("orchestrator.recovery mark-interrupted failed run=%s", run_id)
            continue
        _log.warning(
            "orchestrator.recovery orphan run=%s issue=%s docker_killed=%s → interrupted",
            run_id,
            row.get("issue_num"),
            killed,
        )

        if deps.offer_retry and await _offer_retry(deps, row):
            retried.append(run_id)

    _log.info(
        "orchestrator.recovery done repo=%s reaped=%d interrupted=%d retried=%d",
        deps.repo,
        len(reaped),
        len(interrupted),
        len(retried),
    )
    return RecoveryResult(
        reaped=tuple(reaped),
        interrupted=tuple(interrupted),
        retried=tuple(retried),
    )


async def _offer_retry(deps: RecoveryDeps, row: dict[str, Any]) -> bool:
    """Offer a jittered, semaphore-bounded ``start_task`` retry for an orphan (AC-19).

    Reuses **3.4's** :meth:`RetryScheduler.enqueue_manual` (the SAME path ``POST
    /runs/{id}/retry`` and the tick's idempotent re-dispatch use — no second launch
    mechanism). The retry is offered **only** when the orphan has a committed/pushed
    stage to resume from (``_has_recoverable_stage`` — the engine reconstructs prior
    stage outputs from the pushed branch; with none, the run stays ``interrupted``
    and a human decides). The offer is **jittered** (a per-run randomized delay) and
    taken under the **shared concurrency semaphore** so a boot with many orphans
    admits them gradually rather than stampeding Docker + GitHub. Returns ``True``
    iff a retry was enqueued. Never raises — a scheduler failure leaves the orphan
    ``interrupted`` (a human can still hit *Retry now*).
    """
    scheduler = deps.retry_scheduler
    if scheduler is None:
        return False
    run_id = str(row["id"])
    if not await _has_recoverable_stage(deps.repository, run_id):
        _log.info(
            "orchestrator.recovery run=%s has no pushed stage to resume; staying interrupted",
            run_id,
        )
        return False

    async def _enqueue() -> bool:
        # Jitter (AC-19): a small randomized delay before enqueuing so N orphans do
        # not all re-dispatch on the same tick — anti-thundering-herd on Docker +
        # GitHub. A real (positive) jitter sleeps; tests pass jitter_s=0 for no wait.
        delay = deps.rng.uniform(0.0, max(0.0, deps.jitter_s))
        if delay > 0:
            await asyncio.sleep(delay)
        issue_num = row.get("issue_num")
        try:
            await scheduler.enqueue_manual(
                run_id, issue_num=int(issue_num) if issue_num is not None else None
            )
        except Exception:  # noqa: BLE001 - a scheduler failure leaves the orphan interrupted
            _log.exception("orchestrator.recovery retry enqueue failed run=%s", run_id)
            return False
        return True

    # Route the offer through the SAME concurrency semaphore the tick dispatch is
    # bounded by (reusing 3.4's path) so recovery never admits more orphans at once
    # than the configured cap. A None semaphore (a bare test) enqueues directly.
    sem = deps.concurrency
    if sem is None:
        return await _enqueue()
    async with sem:
        return await _enqueue()


async def _has_recoverable_stage(repository: Repository, run_id: str) -> bool:
    """``True`` iff the orphan has a **completed** stage to ``start_task`` from.

    Only a stage whose outputs were committed/pushed can be recovered (the engine
    reconstructs prior stage outputs from the pushed branch — §8.2). We approximate
    "pushed" with a ``completed`` ``run_stages`` row: a completed stage pushed its
    branch boundary. With no completed stage the run stays ``interrupted`` (retry
    from the top is not auto-offered here — a human decides). A read failure degrades
    to ``False`` (no auto-retry) — the conservative choice.
    """
    try:
        stages = await repository.read_run_stages(run_id)
    except Exception:  # noqa: BLE001 - a stage read failure → no auto-retry offer
        return False
    return any(str(s.get("status") or "") == "completed" for s in stages)


async def _read_non_terminal_run_rows(repository: Repository, repo: str) -> list[dict[str, Any]]:
    """Read this repo's **non-terminal** ``runs`` rows on boot (the orphans).

    A non-terminal row (status in :data:`app.github.sync.ACTIVE_RUN_STATUSES`) is a
    run the dead process left in-flight — its container may still be alive. Read
    through the repository's public WAL read seam (INV-6 — the boot scan never opens
    its own connection). The full row (incl. ``engine_run_id``) is needed so the
    :class:`OrphanReaper` can target the ``run_id``-labeled container.
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
    "DEFAULT_RECOVERY_JITTER_S",
    "INTERRUPTED_STATUS",
    "DockerOrphanReaper",
    "OrphanReaper",
    "RecoveryDeps",
    "RecoveryResult",
    "recover_orphans",
]
