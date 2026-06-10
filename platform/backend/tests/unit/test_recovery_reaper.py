"""DockerOrphanReaper + recovery degrade paths (slice 3.5 — AC-19, INV-10).

Unit-level coverage of the concrete ``docker kill``-by-run seam and recovery's
error-degrade branches, all without real Docker:

* the reaper resolves the orphan's container name from the engine
  (``get_container_status``) and issues a single ``docker kill`` (a patched
  ``subprocess.run`` records it) — and **never** re-attaches;
* no engine_run_id / no container name / docker-not-on-PATH → no kill issued;
* a status-probe failure degrades to "nothing to kill" (the run is still
  interrupted by the caller);
* the jitter path sleeps a bounded delay before offering the retry.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import pytest
from app.orchestrator import recovery as recovery_mod
from app.orchestrator.recovery import DockerOrphanReaper, RecoveryDeps, recover_orphans

pytestmark = pytest.mark.asyncio

_REPO = "octo/widgets"


class _Status:
    def __init__(self, container_name: str) -> None:
        self.container_name = container_name


class _Runtime:
    def __init__(self, *, name: str = "dkmv-c1", raises: bool = False) -> None:
        self._name = name
        self._raises = raises

    def get_container_status(self, _run_id: str) -> Any:
        if self._raises:
            raise RuntimeError("docker inspect blew up")
        return _Status(self._name)


class _RunService:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime


async def test_reaper_issues_docker_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reaper resolves the container name + issues a single docker kill."""
    calls: list[list[str]] = []

    def _fake_run(argv: list[str], **_: Any) -> Any:
        calls.append(argv)

        class _P:
            returncode = 0

        return _P()

    monkeypatch.setattr(recovery_mod.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(recovery_mod.subprocess, "run", _fake_run)

    reaper = DockerOrphanReaper(_RunService(_Runtime(name="dkmv-c1")))  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed run service
    killed = await reaper.reap({"id": "r-1", "engine_run_id": "e1"})

    assert killed is True
    assert calls == [["docker", "kill", "dkmv-c1"]]  # exactly one kill, never a re-attach


async def test_reaper_no_engine_run_id() -> None:
    """No engine_run_id → nothing to kill (False)."""
    reaper = DockerOrphanReaper(_RunService(_Runtime()))  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed run service
    assert await reaper.reap({"id": "r-1"}) is False


async def test_reaper_no_container_name() -> None:
    """An empty container name (no container.txt) → nothing to kill (False)."""
    reaper = DockerOrphanReaper(_RunService(_Runtime(name="")))  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed run service
    assert await reaper.reap({"id": "r-1", "engine_run_id": "e1"}) is False


async def test_reaper_status_probe_failure_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    """A status-probe failure degrades to no-kill (the caller still interrupts)."""
    reaper = DockerOrphanReaper(_RunService(_Runtime(raises=True)))  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed run service
    assert await reaper.reap({"id": "r-1", "engine_run_id": "e1"}) is False


async def test_reaper_docker_not_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """docker not on PATH → no kill issued (dev box without Docker)."""
    monkeypatch.setattr(recovery_mod.shutil, "which", lambda _: None)
    reaper = DockerOrphanReaper(_RunService(_Runtime(name="c1")))  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed run service
    assert await reaper.reap({"id": "r-1", "engine_run_id": "e1"}) is False


async def test_reaper_docker_kill_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    """A docker kill that raises OSError degrades to False (not a crash)."""

    def _boom(*_: Any, **__: Any) -> Any:
        raise OSError("docker daemon gone")

    monkeypatch.setattr(recovery_mod.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(recovery_mod.subprocess, "run", _boom)
    reaper = DockerOrphanReaper(_RunService(_Runtime(name="c1")))  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed run service
    assert await reaper.reap({"id": "r-1", "engine_run_id": "e1"}) is False


async def test_g3_boot_scan_with_early_persisted_id_kills_orphan(
    repo: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G3 (non-vacuous): a non-terminal run WITH an early-persisted engine_run_id is killed.

    The G3 fix persists ``engine_run_id`` on the first stamped engine frame
    (mid-run, not at completion). This drives the REAL ``DockerOrphanReaper``
    through ``recover_orphans`` over a real DB row that carries the early-persisted
    id, and asserts a single ``docker kill`` of the resolved container is issued and
    the run is marked ``interrupted`` — so the kill path is exercised, not pre-seeded
    into a fake that skips it.
    """
    await repo.claim_run(
        idempotency_key="1::wf::main",
        repo=_REPO,
        issue_num=1,
        workflow_id="wf",
        agent="claude",
        branch="main",
        run_id="r-1",
    )
    # The early-persist write the pump now performs mid-run (G3).
    await repo.update_run_fields("r-1", status="running", engine_run_id="260610-1230-plan")

    calls: list[list[str]] = []

    def _fake_run(argv: list[str], **_: Any) -> Any:
        calls.append(argv)

        class _P:
            returncode = 0

        return _P()

    monkeypatch.setattr(recovery_mod.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(recovery_mod.subprocess, "run", _fake_run)
    reaper = DockerOrphanReaper(_RunService(_Runtime(name="dkmv-r1")))  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed run service

    result = await recover_orphans(
        RecoveryDeps(
            repository=repo,
            reaper=reaper,
            repo=_REPO,
            offer_retry=False,
            jitter_s=0.0,
            concurrency=asyncio.Semaphore(1),
            rng=random.Random(1),
        )
    )

    assert calls == [["docker", "kill", "dkmv-r1"]]  # the orphan was actually killed
    assert result.reaped == ("r-1",)
    assert result.interrupted == ("r-1",)
    row = await repo.get_run("r-1")
    assert row is not None and row["status"] == "interrupted"


async def test_g3_boot_scan_null_engine_id_interrupts_but_cannot_kill(
    repo: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G3 residual window: a NULL engine_run_id orphan is interrupted but NOT killed.

    The crash-before-first-frame residual window (documented in ``recovery.py``):
    with no engine id there is no resolvable container to ``docker kill`` (the
    reaper returns ``False``), but the run must still be reliably marked
    ``interrupted`` — never left stuck non-terminal — and surfaced. Drives the REAL
    reaper so the gap is explicit, not hidden behind a pre-seeded id.
    """
    await repo.claim_run(
        idempotency_key="2::wf::main",
        repo=_REPO,
        issue_num=2,
        workflow_id="wf",
        agent="claude",
        branch="main",
        run_id="r-2",
    )
    await repo.update_run_fields("r-2", status="running")  # NULL engine_run_id

    calls: list[list[str]] = []
    monkeypatch.setattr(recovery_mod.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(recovery_mod.subprocess, "run", lambda argv, **_: calls.append(argv))
    reaper = DockerOrphanReaper(_RunService(_Runtime(name="dkmv-r2")))  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed run service

    result = await recover_orphans(
        RecoveryDeps(
            repository=repo,
            reaper=reaper,
            repo=_REPO,
            offer_retry=False,
            jitter_s=0.0,
            concurrency=asyncio.Semaphore(1),
            rng=random.Random(1),
        )
    )

    assert calls == []  # nothing to kill (residual window — no container handle)
    assert result.reaped == ()  # not reaped
    assert result.interrupted == ("r-2",)  # but still reliably interrupted
    row = await repo.get_run("r-2")
    assert row is not None and row["status"] == "interrupted"


class _FakeReaper:
    async def reap(self, run_row: dict[str, Any]) -> bool:
        return True


class _SlowAwareScheduler:
    def __init__(self) -> None:
        self.enqueued: list[str] = []

    async def enqueue_manual(self, run_id: str, *, issue_num: int | None = None) -> Any:
        self.enqueued.append(run_id)
        return object()


async def test_recovery_jitter_sleeps_before_offer(
    repo: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A positive jitter sleeps a bounded delay before the retry offer (anti-herd)."""
    await repo.claim_run(
        idempotency_key="1::wf::main",
        repo=_REPO,
        issue_num=1,
        workflow_id="wf",
        agent="claude",
        branch="main",
        run_id="r-1",
    )
    await repo.update_run_fields("r-1", status="running", engine_run_id="e1")
    await repo.upsert_stage("r-1", 0, "plan", status="completed")

    slept: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    scheduler = _SlowAwareScheduler()
    result = await recover_orphans(
        RecoveryDeps(
            repository=repo,
            reaper=_FakeReaper(),
            repo=_REPO,
            retry_scheduler=scheduler,
            jitter_s=5.0,  # positive → the jitter path sleeps
            concurrency=asyncio.Semaphore(1),
            rng=random.Random(1),
        )
    )

    assert result.retried == ("r-1",)
    assert scheduler.enqueued == ["r-1"]
    assert len(slept) == 1 and 0.0 <= slept[0] <= 5.0  # a bounded jitter delay
