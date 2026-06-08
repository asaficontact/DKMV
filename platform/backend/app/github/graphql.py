"""Paginated GraphQL board read for one project (PRD §8.1, §5.3.1).

The orchestrator's poll (§8.2) and the Connect "Open project" sync (§8.1) both
need the *current* board state for a repo: every open issue plus the recently
closed ones, each with its labels (the `agent:*` state plane), assignee, and any
linked pull-request `merged` flag (for the In Review→Done transition, built in
1.3). The PRD pins this to a **single GraphQL board read per project**, paginated
``first:100`` + cursors, persisting a ``since``/cursor for incremental polls and
**bounding the Done column** to a window (closed in the last N days, capped at a
small page).

This module owns:

* :data:`BOARD_QUERY` — the GraphQL document (open issues by ``UPDATED_AT`` desc,
  plus a bounded recently-closed page for Done) with cursor variables.
* :class:`BoardIssue` / :class:`BoardPage` — the parsed, transport-agnostic shapes
  the sync layer (1.2) and the state-machine derivation (1.3) consume.
* :func:`read_board` — the pagination driver: it calls the injected
  :class:`~app.github.client.GitHubClient`'s GraphQL primitive page-by-page,
  consulting the :class:`~app.github.hash_cache.HashCache` (GraphQL has no ETag —
  we self-hash, §8.1) so an identical read inside the TTL window does not re-spend
  GraphQL points.

**Incremental polls.** A persisted ``since`` (the highest issue ``updatedAt`` seen
last sync) is passed back in as the ``$since`` filter so an incremental read only
re-fetches issues touched since then; the new high-water ``updatedAt`` is returned
as :attr:`BoardPage.since_cursor` for the caller to persist. The first sync (no
``since``) reads the full open set.

**Read-only.** Nothing here mutates GitHub. The label-write primitive
(``set_agent_state``, ``PUT .../labels``) is slice 1.3; this module never issues a
mutation and never constructs the fictional label-patch endpoint INV-11 forbids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.github.hash_cache import HashCache

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.github.client import GitHubClient

#: Page size for every paginated edge (issues, labels, the linked-PR lookup).
#: ``first:100`` is GitHub's max page and the value the PRD pins (§8.1).
PAGE_SIZE = 100

#: Default Done-window bound: closed issues are only read if closed within this
#: many days (§8.1 "closed in the last N days"). The board's Done column is a
#: recent slice, not the repo's full closed history, so a long-lived repo never
#: drags thousands of closed issues into every poll.
DONE_WINDOW_DAYS = 14

#: Hard cap on recently-closed issues pulled for Done in one sync (§8.1 "or last
#: 50"). Bounds the Done page independently of the date window.
DONE_WINDOW_MAX = 50

#: The single GraphQL board document. Two issue connections in one request (one
#: query round-trip per page, §8.1):
#:
#: * ``open`` — open issues ordered by ``UPDATED_AT`` desc so the ``$since``
#:   high-water cutoff lets an incremental poll stop early.
#: * ``closed`` — the bounded Done window, ordered ``UPDATED_AT`` desc and sliced
#:   to :data:`DONE_WINDOW_MAX` by the caller after the date filter.
#:
#: Each issue carries its labels (the ``agent:*`` state plane), assignee, and the
#: ``timelineItems`` cross-referenced PR ``merged`` flag (issue↔PR linkage for the
#: In Review→Done transition built in 1.3).
BOARD_QUERY = """
query Board($owner: String!, $name: String!, $openAfter: String, $closedAfter: String) {
  repository(owner: $owner, name: $name) {
    open: issues(
      first: 100
      after: $openAfter
      states: [OPEN]
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      pageInfo { hasNextPage endCursor }
      nodes { ...IssueFields }
    }
    closed: issues(
      first: 100
      after: $closedAfter
      states: [CLOSED]
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      pageInfo { hasNextPage endCursor }
      nodes { ...IssueFields }
    }
  }
}

fragment IssueFields on Issue {
  number
  title
  state
  updatedAt
  closedAt
  assignees(first: 1) { nodes { login avatarUrl } }
  labels(first: 100) { nodes { name color } }
  timelineItems(first: 10, itemTypes: [CROSS_REFERENCED_EVENT]) {
    nodes {
      ... on CrossReferencedEvent {
        source { ... on PullRequest { number merged } }
      }
    }
  }
}
"""


def _utc_now() -> datetime:
    """Current UTC time (overridable indirection for testability)."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class BoardIssue:
    """One issue parsed from the board read — transport-agnostic.

    Carries exactly what board-state derivation (§5.3.1) and the issue cache
    (1.2) need: the number/title, the open/closed state, the full label set (the
    ``agent:*`` plane plus the GitHub labels the card renders), an optional linked
    merged-PR number (issue↔PR linkage for In Review→Done), the assignee, and the
    ``updatedAt`` used to advance the incremental ``since`` cursor.
    """

    num: int
    title: str
    #: GitHub issue state, lowercased: ``"open"`` or ``"closed"``.
    state: str
    labels: tuple[str, ...]
    updated_at: str
    closed_at: str | None = None
    #: Number of a cross-referenced PR that is **merged** (drives In Review→Done
    #: in 1.3), or ``None`` if no merged PR references this issue.
    merged_pr_num: int | None = None
    assignee: str | None = None
    assignee_avatar: str | None = None

    @property
    def is_closed(self) -> bool:
        """True iff the issue is closed (Done-column candidate)."""
        return self.state == "closed"

    @property
    def agent_labels(self) -> tuple[str, ...]:
        """Just the ``agent:*`` labels on this issue (the state plane)."""
        return tuple(name for name in self.labels if name.startswith("agent:"))


@dataclass(frozen=True, slots=True)
class BoardPage:
    """The fully-paginated result of one board read for a repo.

    :attr:`issues` is the union of open issues and the bounded recently-closed
    Done window. :attr:`since_cursor` is the new high-water ``updatedAt`` the
    caller persists for the next incremental poll. :attr:`from_cache` records
    whether this page was served from the :class:`HashCache` (a points-saving
    hit) rather than fetched from GitHub.
    """

    repo: str
    issues: tuple[BoardIssue, ...]
    since_cursor: str | None = None
    from_cache: bool = False
    #: Per-section cursors for diagnostics/tests (the last ``endCursor`` seen).
    open_end_cursor: str | None = field(default=None)
    closed_end_cursor: str | None = field(default=None)


def _split_owner_name(repo: str) -> tuple[str, str]:
    """Split an ``owner/name`` slug into its two GraphQL variables."""
    cleaned = repo.strip().strip("/")
    parts = [p for p in cleaned.split("/") if p]
    if len(parts) != 2:
        raise ValueError(f"repo must be 'owner/name', got {repo!r}")
    return parts[0], parts[1]


def _parse_issue(node: dict[str, Any]) -> BoardIssue:
    """Map one GraphQL issue node to a :class:`BoardIssue`."""
    labels_conn = node.get("labels") or {}
    label_nodes = labels_conn.get("nodes") or []
    labels = tuple(str(n.get("name", "")) for n in label_nodes if n and n.get("name"))

    assignee_conn = node.get("assignees") or {}
    assignee_nodes = assignee_conn.get("nodes") or []
    assignee = None
    assignee_avatar = None
    if assignee_nodes:
        first = assignee_nodes[0] or {}
        login = first.get("login")
        assignee = str(login) if login else None
        avatar = first.get("avatarUrl")
        assignee_avatar = str(avatar) if avatar else None

    merged_pr_num = _first_merged_pr(node)

    state = str(node.get("state", "")).lower()
    closed_at = node.get("closedAt")
    return BoardIssue(
        num=int(node.get("number", 0)),
        title=str(node.get("title", "")),
        state=state,
        labels=labels,
        updated_at=str(node.get("updatedAt", "")),
        closed_at=str(closed_at) if closed_at else None,
        merged_pr_num=merged_pr_num,
        assignee=assignee,
        assignee_avatar=assignee_avatar,
    )


def _first_merged_pr(node: dict[str, Any]) -> int | None:
    """Return the number of the first cross-referenced **merged** PR, if any.

    Issue↔PR linkage for the In Review→Done transition (§8.1): a merged PR that
    references the issue means the work shipped. The label demotion that consumes
    this lives in 1.3; here we only surface the merged-PR number.
    """
    timeline = node.get("timelineItems") or {}
    for item in timeline.get("nodes") or []:
        if not item:
            continue
        source = item.get("source") or {}
        if source.get("merged") is True and source.get("number") is not None:
            return int(source["number"])
    return None


def _within_done_window(issue: BoardIssue, *, now: datetime, days: int) -> bool:
    """True iff a closed issue is recent enough to belong in the Done window.

    Bounds Done to issues closed within ``days`` (§8.1). Issues without a parseable
    ``closedAt`` are conservatively included (they were just returned as CLOSED).
    """
    if not issue.closed_at:
        return True
    try:
        closed = datetime.fromisoformat(issue.closed_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if closed.tzinfo is None:
        closed = closed.replace(tzinfo=UTC)
    return closed >= now - timedelta(days=days)


async def read_board(
    client: GitHubClient,
    repo: str,
    *,
    since: str | None = None,
    cache: HashCache[BoardPage] | None = None,
    done_window_days: int = DONE_WINDOW_DAYS,
    done_window_max: int = DONE_WINDOW_MAX,
) -> BoardPage:
    """Read the full board for ``repo`` (open issues + a bounded Done window).

    Drives GraphQL pagination over the injected ``client``'s GraphQL primitive,
    ``first:100`` per page with ``endCursor``/``hasNextPage`` follow-up, and:

    * **Incremental** — when ``since`` (a prior high-water ``updatedAt``) is given,
      open-issue pagination **stops** as soon as it crosses an issue not updated
      since then (the open set is ``UPDATED_AT`` desc), so an incremental poll
      re-reads only changed issues rather than the whole repo (AC-3).
    * **Done-bounded** — closed issues are filtered to those closed within
      ``done_window_days`` and capped at ``done_window_max`` (AC-3).
    * **Cached** — the ``(query, variables)`` hash is looked up in ``cache``
      first (GraphQL has no ETag; we self-hash, §8.1); a fresh hit returns the
      prior :class:`BoardPage` with ``from_cache=True`` and spends no GraphQL
      points.

    The returned :attr:`BoardPage.since_cursor` is the new high-water
    ``updatedAt`` the caller persists for the next incremental poll.
    """
    owner, name = _split_owner_name(repo)
    base_vars: dict[str, Any] = {"owner": owner, "name": name}

    # Cache key is over the query + the *entry* variables (the since cutoff is part
    # of the logical read); a fresh hit short-circuits the whole pagination.
    cache_vars = {**base_vars, "since": since}
    if cache is not None:
        cached = cache.get(BOARD_QUERY, cache_vars)
        if cached is not None:
            # Re-tag as a cache hit without mutating the stored (frozen) value.
            return BoardPage(
                repo=cached.repo,
                issues=cached.issues,
                since_cursor=cached.since_cursor,
                from_cache=True,
                open_end_cursor=cached.open_end_cursor,
                closed_end_cursor=cached.closed_end_cursor,
            )

    now = _utc_now()
    open_issues: list[BoardIssue] = []
    closed_issues: list[BoardIssue] = []
    open_cursor: str | None = None
    closed_cursor: str | None = None
    open_done = False
    closed_done = False
    last_open_cursor: str | None = None
    last_closed_cursor: str | None = None

    # Paginate both sections until each is exhausted (or short-circuited). The two
    # connections live in one document, so one request advances both cursors; we
    # pass ``null`` for a section already finished so GitHub re-reads only the open
    # connection on later pages.
    while not (open_done and closed_done):
        variables: dict[str, Any] = {
            **base_vars,
            "openAfter": open_cursor,
            "closedAfter": closed_cursor,
        }
        payload = await client.graphql(BOARD_QUERY, variables)
        repository = (payload.get("data") or {}).get("repository") or {}

        if not open_done:
            open_conn = repository.get("open") or {}
            page_info = open_conn.get("pageInfo") or {}
            for node in open_conn.get("nodes") or []:
                if not node:
                    continue
                issue = _parse_issue(node)
                # Incremental cutoff: the open set is UPDATED_AT desc, so once we
                # reach an issue not newer than the persisted high-water we have
                # seen everything that changed — stop paginating open (AC-3).
                if since is not None and issue.updated_at and issue.updated_at <= since:
                    open_done = True
                    break
                open_issues.append(issue)
            last_open_cursor = page_info.get("endCursor") or last_open_cursor
            if open_done or not page_info.get("hasNextPage"):
                open_done = True
            else:
                open_cursor = page_info.get("endCursor")

        if not closed_done:
            closed_conn = repository.get("closed") or {}
            page_info = closed_conn.get("pageInfo") or {}
            for node in closed_conn.get("nodes") or []:
                if not node:
                    continue
                issue = _parse_issue(node)
                if not _within_done_window(issue, now=now, days=done_window_days):
                    # CLOSED is UPDATED_AT desc; once we pass the window the rest
                    # are older still — stop, and respect the count cap too.
                    closed_done = True
                    break
                closed_issues.append(issue)
                if len(closed_issues) >= done_window_max:
                    closed_done = True
                    break
            last_closed_cursor = page_info.get("endCursor") or last_closed_cursor
            if closed_done or not page_info.get("hasNextPage"):
                closed_done = True
            else:
                closed_cursor = page_info.get("endCursor")

    issues = (*open_issues, *closed_issues[:done_window_max])
    new_since = _high_water(issues, prior=since)

    page = BoardPage(
        repo=repo,
        issues=issues,
        since_cursor=new_since,
        from_cache=False,
        open_end_cursor=last_open_cursor,
        closed_end_cursor=last_closed_cursor,
    )
    if cache is not None:
        cache.put(BOARD_QUERY, cache_vars, page)
    return page


def _high_water(issues: tuple[BoardIssue, ...], *, prior: str | None) -> str | None:
    """Return the newest ``updatedAt`` across ``issues`` (or the prior cursor).

    ISO-8601 UTC timestamps sort lexically, so ``max`` over the strings yields the
    most-recently-updated issue's timestamp — the cursor to persist for the next
    incremental poll. Falls back to ``prior`` when the page is empty (an
    incremental poll that found nothing changed keeps its old high-water).
    """
    timestamps = [i.updated_at for i in issues if i.updated_at]
    if not timestamps:
        return prior
    newest = max(timestamps)
    if prior is not None and prior > newest:
        return prior
    return newest
