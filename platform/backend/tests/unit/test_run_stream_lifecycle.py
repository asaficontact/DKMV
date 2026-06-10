"""G5 — the completion supervisor finishes the board lifecycle (FR-04-7 / §5.3.1).

On a run reaching a terminal status the supervisor must complete the board
lifecycle (it never did before — it only wrote the terminal ``runs.status``):

* a **successful** run resolves the open PR for the run's branch via the GitHub
  client, persists ``runs.pr_num``, and moves the issue to ``agent:review`` —
  the label move going THROUGH the serialized write-queue (a replace-all ``PUT``,
  INV-11), never a direct GitHub call;
* a **failed/errored** run is demoted off ``agent:in-progress`` (per §5.3.1) so
  the board never strands a finished issue in "In Progress";
* the work is **best-effort**: a GitHub error must not crash the supervisor (the
  run still records its terminal status).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app.db import Repository
from app.github.write_queue import WriteQueue
from app.secrets import Redactor
from app.sse.run_stream import LifecycleDeps, _complete_board_lifecycle

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _migrate(db_path: Path) -> str:
    url = f"sqlite:///{db_path}"
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> AsyncIterator[Repository]:
    url = _migrate(tmp_path / "lifecycle.db")
    repo = Repository(url, redactor=Redactor())
    await repo.start()
    try:
        yield repo
    finally:
        await repo.close()


class _FakeClient:
    """Records replace_labels (the only GitHub mutation) + answers PR lookups.

    ``replace_labels`` is the replace-all ``PUT`` — recording it proves the
    ``agent:*`` move is a replace-all (INV-11), not a direct/PATCH path.
    ``find_open_pr_for_branch`` returns a fixed PR (or raises, for the error path).
    """

    def __init__(self, *, pr_num: int | None = 42, raise_on_pr: bool = False) -> None:
        self.replace_calls: list[tuple[str, int, list[str]]] = []
        self.pr_lookups: list[tuple[str, str]] = []
        self._pr_num = pr_num
        self._raise_on_pr = raise_on_pr

    async def replace_labels(self, repo: str, num: int, labels: Sequence[str]) -> list[str]:
        body = list(labels)
        self.replace_calls.append((repo, num, body))
        return body

    async def find_open_pr_for_branch(self, repo: str, branch: str) -> int | None:
        self.pr_lookups.append((repo, branch))
        if self._raise_on_pr:
            raise RuntimeError("github down")
        return self._pr_num


def _queue() -> WriteQueue:
    return WriteQueue(rate_per_minute=6000.0)


async def _seed(
    repo: Repository,
    *,
    run_id: str,
    issue_num: int,
    status: str,
    labels: list[str],
    branch: str = "dkmv/issue-1",
) -> None:
    await repo.claim_run(
        idempotency_key=f"{issue_num}::wf::main",
        repo="o/r",
        issue_num=issue_num,
        workflow_id="wf",
        agent="claude",
        branch=branch,
        run_id=run_id,
    )
    await repo.update_run_fields(run_id, status=status)
    await repo.upsert_issue(repo="o/r", num=issue_num, labels=labels)


pytestmark = pytest.mark.asyncio


async def test_successful_run_links_pr_and_sets_review(repository: Repository) -> None:
    """Success: pr_num persisted + agent:review set via the write-queue (not direct)."""
    await _seed(
        repository,
        run_id="r-1",
        issue_num=1,
        status="completed",
        labels=["bug", "agent:in-progress"],
    )
    client = _FakeClient(pr_num=42)
    queue = _queue()
    lifecycle = LifecycleDeps(github_client=client, write_queue=queue)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client

    await _complete_board_lifecycle(
        run_id="r-1", status="completed", repository=repository, lifecycle=lifecycle
    )

    # (a) the run's PR was resolved + persisted (the run-detail link).
    assert client.pr_lookups == [("o/r", "dkmv/issue-1")]
    row = await repository.get_run("r-1")
    assert row is not None and row["pr_num"] == 42

    # (b) the issue moved to agent:review via the replace-all PUT (single-occupancy,
    # non-agent labels preserved) — through the WRITE-QUEUE, never a direct call.
    assert client.replace_calls == [("o/r", 1, ["bug", "agent:review"])]


async def test_failed_run_demoted_off_in_progress(repository: Repository) -> None:
    """Failure: the issue is demoted off agent:in-progress (no stranded In Progress)."""
    await _seed(
        repository,
        run_id="r-2",
        issue_num=2,
        status="failed",
        labels=["agent:in-progress", "p1"],
    )
    client = _FakeClient()
    queue = _queue()
    lifecycle = LifecycleDeps(github_client=client, write_queue=queue)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client

    await _complete_board_lifecycle(
        run_id="r-2", status="failed", repository=repository, lifecycle=lifecycle
    )

    # No PR resolution on a failed run; the issue is stripped of agent:in-progress
    # (target None → Backlog), preserving the non-agent label.
    assert client.pr_lookups == []
    assert client.replace_calls == [("o/r", 2, ["p1"])]
    row = await repository.get_run("r-2")
    assert row is not None and row["pr_num"] is None


async def test_failed_run_not_in_progress_is_noop(repository: Repository) -> None:
    """A failed run whose issue is NOT in-progress needs no demotion (no write)."""
    await _seed(repository, run_id="r-3", issue_num=3, status="failed", labels=["agent:review"])
    client = _FakeClient()
    lifecycle = LifecycleDeps(github_client=client, write_queue=_queue())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client

    await _complete_board_lifecycle(
        run_id="r-3", status="failed", repository=repository, lifecycle=lifecycle
    )

    assert client.replace_calls == []  # nothing stranded → no write


async def test_github_error_does_not_crash_completion(repository: Repository) -> None:
    """Best-effort: a GitHub PR-lookup error must not crash the lifecycle completion."""
    await _seed(
        repository,
        run_id="r-4",
        issue_num=4,
        status="completed",
        labels=["agent:in-progress"],
    )
    client = _FakeClient(raise_on_pr=True)
    lifecycle = LifecycleDeps(github_client=client, write_queue=_queue())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client

    # Does not raise (the PR lookup blew up but is swallowed inside the helper).
    await _complete_board_lifecycle(
        run_id="r-4", status="completed", repository=repository, lifecycle=lifecycle
    )

    # pr_num stays NULL (the lookup failed), but the issue still moves to review.
    row = await repository.get_run("r-4")
    assert row is not None and row["pr_num"] is None
    assert client.replace_calls == [("o/r", 4, ["agent:review"])]


async def test_already_in_review_is_idempotent(repository: Repository) -> None:
    """Idempotent: a re-run on an already-review issue issues no redundant write."""
    await _seed(repository, run_id="r-5", issue_num=5, status="completed", labels=["agent:review"])
    # pre-set pr_num so the PR path is also skipped (idempotent re-run).
    await repository.update_run_fields("r-5", pr_num=7)
    client = _FakeClient()
    lifecycle = LifecycleDeps(github_client=client, write_queue=_queue())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client

    await _complete_board_lifecycle(
        run_id="r-5", status="completed", repository=repository, lifecycle=lifecycle
    )

    assert client.pr_lookups == []  # pr_num already set → no re-lookup
    assert client.replace_calls == []  # already in review → no redundant PUT
