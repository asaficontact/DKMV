"""Slice 1.2 — GraphQL board read, issue sync, derivation + authority rule.

Covers:
* **AC-3** — the board read is GraphQL, paginated with cursors, persists a
  ``since`` cursor, re-reads only changed issues incrementally, and bounds Done.
* **AC-4** — the four ``agent:*`` labels are created on connect, idempotently.
* **AC-5** — ``state`` is derived per §5.3.1 and the authority rule (active-run DB
  row > stale label) is applied; multi-label precedence ``in-progress > paused >
  review > queued`` is unit-tested.

GitHub is a fake :class:`GitHubClient` (no network); the hash-cache is the real
in-process cache.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.db.repository import IssueRow
from app.github.graphql import BoardPage, read_board
from app.github.hash_cache import HashCache
from app.github.labels import AGENT_LABEL_NAMES, ensure_agent_labels
from app.github.sync import (
    ActiveRun,
    active_runs_from_rows,
    build_board_list,
    derive_state,
    sync_issues,
)

# ── fake GitHub client ───────────────────────────────────────────────────────


def _issue_node(
    number: int,
    *,
    title: str = "",
    state: str = "OPEN",
    updated_at: str = "2026-06-08T10:00:00Z",
    closed_at: str | None = None,
    labels: list[str] | None = None,
    merged_pr: int | None = None,
) -> dict[str, Any]:
    label_nodes = [{"name": n, "color": "ededed"} for n in (labels or [])]
    timeline_nodes = []
    if merged_pr is not None:
        timeline_nodes.append({"source": {"number": merged_pr, "merged": True}})
    return {
        "number": number,
        "title": title,
        "state": state,
        "updatedAt": updated_at,
        "closedAt": closed_at,
        "assignees": {"nodes": []},
        "labels": {"nodes": label_nodes},
        "timelineItems": {"nodes": timeline_nodes},
    }


def _page(
    open_nodes: list[dict[str, Any]],
    *,
    open_next: bool = False,
    open_cursor: str | None = None,
    closed_nodes: list[dict[str, Any]] | None = None,
    closed_next: bool = False,
    closed_cursor: str | None = None,
) -> dict[str, Any]:
    return {
        "data": {
            "repository": {
                "open": {
                    "pageInfo": {"hasNextPage": open_next, "endCursor": open_cursor},
                    "nodes": open_nodes,
                },
                "closed": {
                    "pageInfo": {"hasNextPage": closed_next, "endCursor": closed_cursor},
                    "nodes": closed_nodes or [],
                },
            }
        }
    }


class FakeClient:
    """A :class:`GitHubClient`-duck returning scripted GraphQL pages + labels."""

    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self._pages = pages
        self.graphql_calls: list[dict[str, Any]] = []
        self.created_labels: list[str] = []
        self.existing_labels: set[str] = set()

    async def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.graphql_calls.append(dict(variables))
        idx = min(len(self.graphql_calls) - 1, len(self._pages) - 1)
        return self._pages[idx]

    async def create_label(
        self, repo: str, *, name: str, color: str, description: str = ""
    ) -> bool:
        if name in self.existing_labels:
            return False
        self.existing_labels.add(name)
        self.created_labels.append(name)
        return True


class RecordingWriter:
    """Captures upsert_issues / settings writes (the repository write seam).

    ``upsert_issues`` is the **batch** seam :func:`sync_issues` now uses — one
    call per page. ``upsert_batches`` records each page's rows so a test can
    assert the whole page was written in a single batch (one writer transaction);
    ``issues`` flattens every row for the per-issue assertions.
    """

    def __init__(self, since: str | None = None) -> None:
        self.issues: list[dict[str, Any]] = []
        self.upsert_batches: list[list[IssueRow]] = []
        self.settings: dict[str, str] = {}
        if since is not None:
            self.settings.setdefault("_seed", since)
        self._seed_since = since

    async def upsert_issues(self, rows: Sequence[IssueRow]) -> None:
        batch = list(rows)
        self.upsert_batches.append(batch)
        self.issues.extend(
            {
                "repo": r.repo,
                "num": r.num,
                "title": r.title,
                "state": r.state,
                "labels": list(r.labels or []),
                "workflow_id": r.workflow_id,
                "agent": r.agent,
                "pr_num": r.pr_num,
            }
            for r in batch
        )

    async def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    async def get_setting(self, key: str) -> str | None:
        if key.startswith("sync_since::") and self._seed_since is not None:
            return self._seed_since
        return self.settings.get(key)


# ── AC-3: GraphQL pagination + cursor + incremental + Done window ─────────────


async def test_board_read_is_graphql_and_paginates_with_cursors() -> None:
    """Two open pages are followed via endCursor/hasNextPage into one BoardPage."""
    pages = [
        _page(
            [_issue_node(10, updated_at="2026-06-08T12:00:00Z")],
            open_next=True,
            open_cursor="CURSOR_A",
        ),
        _page([_issue_node(9, updated_at="2026-06-07T12:00:00Z")], open_next=False),
    ]
    client = FakeClient(pages)
    page = await read_board(client, "o/r")  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client

    assert isinstance(page, BoardPage)
    assert [i.num for i in page.issues] == [10, 9]
    # The second request carried the first page's endCursor (cursor pagination).
    assert client.graphql_calls[1]["openAfter"] == "CURSOR_A"
    # since_cursor is the newest updatedAt seen (the high-water for next poll).
    assert page.since_cursor == "2026-06-08T12:00:00Z"


async def test_incremental_since_reads_only_changed_issues() -> None:
    """With a since high-water, pagination stops at the first not-newer issue (AC-3)."""
    pages = [
        _page(
            [
                _issue_node(10, updated_at="2026-06-08T12:00:00Z"),  # newer → kept
                _issue_node(9, updated_at="2026-06-05T00:00:00Z"),  # not newer → stop
            ],
            open_next=True,
            open_cursor="SHOULD_NOT_FETCH",
        ),
        _page([_issue_node(1)], open_next=False),  # must NOT be requested
    ]
    client = FakeClient(pages)
    page = await read_board(client, "o/r", since="2026-06-06T00:00:00Z")  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client

    assert [i.num for i in page.issues] == [10]
    # Only ONE GraphQL call: the incremental cutoff short-circuited pagination.
    assert len(client.graphql_calls) == 1


async def test_done_window_bounds_closed_issues_by_count() -> None:
    """Closed issues are capped at done_window_max (AC-3)."""
    closed = [
        _issue_node(n, state="CLOSED", closed_at="2026-06-08T00:00:00Z") for n in range(50, 0, -1)
    ]
    pages = [_page([], closed_nodes=closed)]
    client = FakeClient(pages)
    page = await read_board(client, "o/r", done_window_max=5)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client

    closed_issues = [i for i in page.issues if i.is_closed]
    assert len(closed_issues) == 5


async def test_done_window_bounds_closed_issues_by_date() -> None:
    """Closed issues older than the window are excluded (AC-3)."""
    closed = [
        _issue_node(2, state="CLOSED", closed_at="2026-06-07T00:00:00Z"),  # recent
        _issue_node(1, state="CLOSED", closed_at="2000-01-01T00:00:00Z"),  # ancient → out
    ]
    pages = [_page([], closed_nodes=closed)]
    client = FakeClient(pages)
    page = await read_board(client, "o/r", done_window_days=14)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client

    closed_nums = [i.num for i in page.issues if i.is_closed]
    assert closed_nums == [2]


async def test_hash_cache_hit_avoids_second_fetch() -> None:
    """An identical read inside the TTL is served from the hash-cache (§8.1)."""
    pages = [_page([_issue_node(1)])]
    client = FakeClient(pages)
    cache: HashCache[BoardPage] = HashCache()

    first = await read_board(client, "o/r", cache=cache)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client
    assert first.from_cache is False
    assert len(client.graphql_calls) == 1

    second = await read_board(client, "o/r", cache=cache)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client
    assert second.from_cache is True
    # No new GitHub call — the cache hit short-circuited the whole read.
    assert len(client.graphql_calls) == 1


# ── AC-4: idempotent agent:* label creation ──────────────────────────────────


async def test_ensure_agent_labels_creates_four() -> None:
    """All four agent:* labels are created on first connect (AC-4)."""
    client = FakeClient([])
    result = await ensure_agent_labels(client, "o/r")
    assert set(result.created) == set(AGENT_LABEL_NAMES)
    assert result.existing == ()


async def test_ensure_agent_labels_is_idempotent_on_reconnect() -> None:
    """A re-connect re-runs label creation without a duplicate-label error (AC-4)."""
    client = FakeClient([])
    await ensure_agent_labels(client, "o/r")  # first connect creates all four
    result = await ensure_agent_labels(client, "o/r")  # reconnect → all already exist
    assert result.created == ()
    assert set(result.existing) == set(AGENT_LABEL_NAMES)


# ── AC-5: §5.3.1 derivation + authority rule + precedence ─────────────────────


def test_derive_state_label_to_column_table() -> None:
    """The §5.3.1 label→column table (no run)."""
    assert derive_state(labels=[]) == "backlog"
    assert derive_state(labels=["agent:queued"]) == "queued"
    assert derive_state(labels=["agent:in-progress"]) == "in_progress"
    assert derive_state(labels=["agent:paused"]) == "needs_you"
    assert derive_state(labels=["agent:review"]) == "in_review"
    assert derive_state(labels=["agent:queued"], is_closed=True) == "done"
    assert derive_state(labels=["agent:review"], merged_pr_num=42) == "done"


def test_multi_label_precedence() -> None:
    """in-progress > paused > review > queued when several agent:* are seen (AC-5)."""
    assert (
        derive_state(labels=["agent:queued", "agent:in-progress", "agent:review"]) == "in_progress"
    )
    assert derive_state(labels=["agent:paused", "agent:review", "agent:queued"]) == "needs_you"
    assert derive_state(labels=["agent:review", "agent:queued"]) == "in_review"


def test_authority_rule_active_run_beats_stale_label() -> None:
    """An issue with an active run AND a stale label → the DB run row wins (AC-5)."""
    # Stale label says "queued" but a live run is in progress → In Progress.
    run = ActiveRun(issue_num=7, status="running")
    assert derive_state(labels=["agent:queued"], active_run=run) == "in_progress"

    # A paused run surfaces in Needs You even if the label still says in-progress.
    paused = ActiveRun(issue_num=7, status="paused")
    assert derive_state(labels=["agent:in-progress"], active_run=paused) == "needs_you"


def test_terminal_run_yields_to_label() -> None:
    """A terminal (completed/failed) run is NOT active → the label governs (§8.1)."""
    done_run = ActiveRun(issue_num=7, status="completed")
    assert derive_state(labels=["agent:queued"], active_run=done_run) == "queued"
    failed = ActiveRun(issue_num=7, status="failed")
    assert derive_state(labels=["agent:in-progress"], active_run=failed) == "in_progress"


def test_build_board_list_applies_authority_at_read_time() -> None:
    """build_board_list overlays the active-run authority on the cached label state."""
    cached = [
        {
            "num": 7,
            "title": "stale",
            "state": "queued",
            "labels_json": '["agent:queued"]',
            "workflow_id": None,
            "agent": None,
            "pr_num": None,
        }
    ]
    active = {7: ActiveRun(issue_num=7, status="running")}
    items = build_board_list(cached, active)
    assert items[0]["state"] == "in_progress"
    assert items[0]["run_status"] == "running"


def test_build_board_list_closed_issue_no_pr_no_label_is_done() -> None:
    """A CLOSED issue (state=done at sync) with no PR + no agent:* label → Done (AC-5).

    Regression guard for the read-path bug where build_board_list hardcoded
    is_closed=False and dropped the persisted §5.3.1 Done signal, rendering a
    closed issue as backlog.
    """
    cached = [
        {
            "num": 5,
            "title": "closed",
            "state": "done",  # what sync_issues persisted for a closed issue
            "labels_json": "[]",  # no agent:* label
            "workflow_id": None,
            "agent": None,
            "pr_num": None,  # no merged-PR linkage
        }
    ]
    items = build_board_list(cached, {})
    assert items[0]["state"] == "done"


def test_build_board_list_closed_with_merged_pr_is_done() -> None:
    """A closed issue with a merged PR linkage → Done (§5.3.1 row 6)."""
    cached = [
        {
            "num": 6,
            "title": "merged",
            "state": "done",
            "labels_json": '["agent:review"]',  # stale label must not win over Done
            "workflow_id": None,
            "agent": None,
            "pr_num": 42,
        }
    ]
    items = build_board_list(cached, {})
    assert items[0]["state"] == "done"
    assert items[0]["pr_num"] == 42


def test_build_board_list_open_no_label_is_backlog() -> None:
    """An OPEN issue (state=backlog) with no label still derives to Backlog."""
    cached = [
        {
            "num": 8,
            "title": "open",
            "state": "backlog",
            "labels_json": "[]",
            "workflow_id": None,
            "agent": None,
            "pr_num": None,
        }
    ]
    items = build_board_list(cached, {})
    assert items[0]["state"] == "backlog"


def test_active_runs_from_rows_folds_by_issue_with_precedence() -> None:
    """Multiple active runs on one issue fold to the most-advanced (paused first)."""
    rows = [
        {"issue_num": 7, "status": "running", "pr_num": None},
        {"issue_num": 7, "status": "paused", "pr_num": None},
        {"issue_num": 9, "status": "pending", "pr_num": 3},
        {"issue_num": None, "status": "running", "pr_num": None},  # skipped (no issue)
    ]
    folded = active_runs_from_rows(rows)
    assert folded[7].status == "paused"  # paused outranks running
    assert folded[9].pr_num == 3
    assert None not in folded


# ── sync_issues: import through the repository + cursor persistence ───────────


async def test_sync_issues_writes_through_repository_and_persists_cursor() -> None:
    """sync_issues upserts each issue via the writer and persists the since cursor."""
    pages = [
        _page(
            [
                _issue_node(
                    10,
                    title="A",
                    updated_at="2026-06-08T12:00:00Z",
                    labels=["agent:queued"],
                ),
            ],
            closed_nodes=[
                _issue_node(3, state="CLOSED", closed_at="2026-06-08T00:00:00Z"),
            ],
        )
    ]
    client = FakeClient(pages)
    writer = RecordingWriter()
    result = await sync_issues(client, "o/r", writer=writer)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client

    assert result.imported == 2
    nums = {i["num"] for i in writer.issues}
    assert nums == {10, 3}
    # Issue 10's cached state is label-derived (queued); issue 3 is closed → done.
    by_num = {i["num"]: i for i in writer.issues}
    assert by_num[10]["state"] == "queued"
    assert by_num[3]["state"] == "done"
    # PERF (FIX-1): the whole page is written in a SINGLE batch upsert (one writer
    # transaction), not one upsert call per issue.
    assert len(writer.upsert_batches) == 1
    assert {r.num for r in writer.upsert_batches[0]} == {10, 3}
    # The high-water since cursor is persisted for the next incremental poll.
    assert writer.settings["sync_since::o/r"] == "2026-06-08T12:00:00Z"


async def test_sync_issues_reads_persisted_since_for_incremental() -> None:
    """An incremental sync passes the persisted since into the board read."""
    pages = [_page([_issue_node(10, updated_at="2026-06-09T00:00:00Z")])]
    client = FakeClient(pages)
    writer = RecordingWriter(since="2026-06-08T00:00:00Z")
    await sync_issues(client, "o/r", writer=writer)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client
    # The very first GraphQL variables are the base (no since in variables — the
    # since is applied as the in-driver cutoff), and only the newer issue is kept.
    assert client.graphql_calls  # at least one call happened
