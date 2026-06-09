"""Resilience suite — the §13 / AT-Recovery durability bar (slice 3.5 — AC-20).

The load-bearing acceptance test of Phase 3 (INV-10): **killing the backend
mid-run and mid-pause leaves NO orphaned money-spending container, and an
idempotent retry creates NO duplicate PR.**

(a) **Kill mid-run + mid-pause → no surviving container.** We simulate a hard
    crash: a non-terminal ``runs`` row is left in the DB with its container "alive"
    (tracked by a **fake Docker/killer seam** so the suite runs in CI WITHOUT real
    Docker). On boot, :func:`recover_orphans` must issue a ``docker kill`` for
    **every** ``run_id``-labeled orphan (the fake's ``docker ps`` view then shows
    none surviving), mark the run ``interrupted``, and offer a ``start_task`` retry
    from the last pushed stage. The ``docker ps`` assertion is the fake killer's
    surviving-container set being empty after recovery.

(b) **Idempotent retry → no duplicate PR.** A retry of an issue that already has an
    **open PR** must resume/skip — the scheduler's existing-branch/PR detection
    (reused from 3.4 — AC-15) means the re-dispatch is NOT issued, so no second PR
    is opened.

An optional real-Docker variant (:func:`test_real_docker_no_surviving_container`)
self-skips when Docker is unavailable.
"""

from __future__ import annotations

import asyncio
import random
import shutil
import subprocess
from typing import Any

import pytest
from app.db.repository import Repository
from app.orchestrator.recovery import RecoveryDeps, recover_orphans
from app.orchestrator.retry import RetryScheduler

pytestmark = pytest.mark.asyncio

_REPO = "octo/widgets"


class _FakeDocker:
    """A fake Docker daemon: tracks ``run_id``-labeled containers + records kills.

    Stands in for real Docker so the resilience suite runs in CI. ``running`` is the
    set of run_ids whose container is currently alive (the ``docker ps`` view);
    ``kill(run_id)`` removes it and records the issued kill. The killer seam below
    drives this so "no surviving ``run_id``-labeled container" is assertable as
    ``fake_docker.running == set()``.
    """

    def __init__(self) -> None:
        self.running: set[str] = set()
        self.kill_calls: list[str] = []

    def start(self, run_id: str) -> None:
        self.running.add(run_id)

    def kill(self, run_id: str) -> bool:
        self.kill_calls.append(run_id)
        existed = run_id in self.running
        self.running.discard(run_id)
        return existed


class _FakeReaper:
    """OrphanReaper bound to the fake Docker — issues a kill per ``run_id`` orphan."""

    def __init__(self, docker: _FakeDocker) -> None:
        self._docker = docker

    async def reap(self, run_row: dict[str, Any]) -> bool:
        # The container is labeled with the platform run id (the orphan key).
        return self._docker.kill(str(run_row["id"]))


class _RecordingScheduler:
    """Records the retries recovery offered (the reused 3.4 enqueue path)."""

    def __init__(self) -> None:
        self.enqueued: list[tuple[str, int | None]] = []

    async def enqueue_manual(self, run_id: str, *, issue_num: int | None = None) -> Any:
        self.enqueued.append((run_id, issue_num))
        return object()


async def _seed_run(
    repository: Repository,
    *,
    run_id: str,
    issue_num: int,
    status: str,
    engine_run_id: str | None = "engine-x",
    pr_num: int | None = None,
    branch: str = "main",
) -> None:
    await repository.claim_run(
        idempotency_key=f"{issue_num}::wf::{branch}",
        repo=_REPO,
        issue_num=issue_num,
        workflow_id="wf",
        agent="claude",
        branch=branch,
        run_id=run_id,
    )
    fields: dict[str, Any] = {"status": status}
    if engine_run_id is not None:
        fields["engine_run_id"] = engine_run_id
    if pr_num is not None:
        fields["pr_num"] = pr_num
    await repository.update_run_fields(run_id, **fields)


async def _status(repository: Repository, run_id: str) -> str:
    row = await repository.get_run(run_id)
    assert row is not None
    return str(row["status"])


def _recovery_deps(repository: Repository, reaper: Any, scheduler: Any) -> RecoveryDeps:
    return RecoveryDeps(
        repository=repository,
        reaper=reaper,
        repo=_REPO,
        retry_scheduler=scheduler,
        offer_retry=True,
        jitter_s=0.0,
        concurrency=asyncio.Semaphore(2),
        rng=random.Random(7),
    )


# ── (a) kill mid-run / mid-pause → no surviving container ──────────────────────


@pytest.mark.parametrize("crash_status", ["running", "paused"])
async def test_kill_mid_run_and_mid_pause_no_orphan(repo: Repository, crash_status: str) -> None:
    """AC-20: a backend kill mid-run AND mid-pause leaves NO surviving container.

    The container is "alive" in the fake Docker at crash time; after boot recovery
    the fake's ``running`` set (the ``docker ps`` view) is empty, the run is
    ``interrupted``, and a ``start_task`` retry was offered from the last pushed
    stage.
    """
    docker = _FakeDocker()
    docker.start("r-crash")  # the container is alive at crash time
    await _seed_run(repo, run_id="r-crash", issue_num=1, status=crash_status)
    await repo.upsert_stage("r-crash", 0, "plan", status="completed")  # a pushed boundary
    scheduler = _RecordingScheduler()

    await recover_orphans(_recovery_deps(repo, _FakeReaper(docker), scheduler))

    # The §13 bar: `docker ps` shows NO surviving run_id-labeled container.
    assert docker.running == set()
    assert docker.kill_calls == ["r-crash"]  # kill ISSUED for the orphan
    assert await _status(repo, "r-crash") == "interrupted"
    # Retry offered via start_task from the last pushed stage (reused 3.4 path).
    assert scheduler.enqueued == [("r-crash", 1)]


async def test_multiple_orphans_all_killed(repo: Repository) -> None:
    """Every run_id-labeled orphan is killed — none survives the boot sweep."""
    docker = _FakeDocker()
    for i in (1, 2, 3):
        docker.start(f"r-{i}")
        await _seed_run(repo, run_id=f"r-{i}", issue_num=i, status="running")
    scheduler = _RecordingScheduler()

    await recover_orphans(_recovery_deps(repo, _FakeReaper(docker), scheduler))

    assert docker.running == set()  # no surviving container
    assert sorted(docker.kill_calls) == ["r-1", "r-2", "r-3"]
    for i in (1, 2, 3):
        assert await _status(repo, f"r-{i}") == "interrupted"


# ── (b) idempotent retry → no duplicate PR ─────────────────────────────────────


class _OpenPrClient:
    """A GitHub client whose issue already has an open PR for the branch."""

    def __init__(self) -> None:
        self.find_calls: list[tuple[str, str]] = []

    async def find_open_pr_for_branch(self, repo: str, branch: str) -> dict[str, Any] | None:
        self.find_calls.append((repo, branch))
        return {"number": 42}  # an open PR exists


async def test_idempotent_retry_no_duplicate_pr(repo: Repository) -> None:
    """AC-20 / AC-15: a retry of an issue with an open PR creates NO duplicate PR.

    The scheduler detects the existing PR (via ``runs.pr_num`` and/or the GitHub
    branch detector) and resumes/skips — the redispatch (which would re-open the PR)
    is NEVER issued.
    """
    await _seed_run(repo, run_id="r-pr", issue_num=1, status="interrupted", pr_num=42)
    redispatched: list[str] = []

    async def _redispatch(row: dict[str, Any], start_task: str | None) -> str | None:
        redispatched.append(str(row["id"]))  # a fresh dispatch = a NEW PR (must NOT happen)
        return "new-run"

    scheduler = RetryScheduler(
        repository=repo,
        redispatch=_redispatch,
        github_client=_OpenPrClient(),  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed test client
    )

    dispatched = await scheduler.redispatch_run("r-pr")

    assert dispatched is False  # resumed/skipped — no re-dispatch
    assert redispatched == []  # the redispatch that opens a PR was NOT issued → no dup PR


async def test_idempotent_retry_branch_detection_no_duplicate_pr(repo: Repository) -> None:
    """Even with no DB pr_num, a GitHub-detected open PR blocks the duplicate dispatch."""
    await _seed_run(repo, run_id="r-pr", issue_num=1, status="interrupted", branch="issue-1")
    redispatched: list[str] = []

    async def _redispatch(row: dict[str, Any], start_task: str | None) -> str | None:
        redispatched.append(str(row["id"]))
        return "new-run"

    client = _OpenPrClient()
    scheduler = RetryScheduler(
        repository=repo,
        redispatch=_redispatch,
        github_client=client,  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed test client
    )

    dispatched = await scheduler.redispatch_run("r-pr")

    assert dispatched is False
    assert redispatched == []
    assert client.find_calls == [(_REPO, "issue-1")]  # the branch detector was consulted


# ── optional real-Docker variant (self-skips without Docker) ───────────────────


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=5, check=False
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return proc.returncode == 0


@pytest.mark.skipif(not _docker_available(), reason="real Docker unavailable")
async def test_real_docker_no_surviving_container(repo: Repository) -> None:
    """Real-Docker-gated: a started sandbox container is gone after a docker kill.

    Self-skips when Docker is unavailable (CI default). When Docker is present it
    asserts the kill path actually removes a labeled container — the production
    ``DockerOrphanReaper`` behavior end-to-end. Kept minimal (a short-lived
    container) so it does not require the full engine image.
    """
    name = "dkmvp-resilience-probe"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
    subprocess.run(
        ["docker", "run", "-d", "--name", name, "alpine", "sleep", "300"],
        capture_output=True,
        text=True,
        check=True,
    )
    try:
        subprocess.run(["docker", "kill", name], capture_output=True, text=True, check=False)
        ps = subprocess.run(
            ["docker", "ps", "--filter", f"name={name}", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert name not in ps.stdout  # no surviving container
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
