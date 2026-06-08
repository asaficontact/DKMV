"""Issue import + board-state derivation (PRD §8.1, §5.3.1).

Two responsibilities, both sitting on top of the 1.2 GraphQL board read
(:func:`app.github.graphql.read_board`):

1. **Import** — :func:`sync_issues` reads the board for a repo and writes each
   issue into the platform ``issues`` cache **through the repository layer**
   (:meth:`app.db.repository.Repository.upsert_issue`), never raw SQL. The new
   ``since`` high-water cursor is persisted (via the repository ``settings`` KV)
   so the next poll is incremental. This backs ``POST /projects/{repo}/sync``.

2. **Derive board state** — :func:`derive_state` implements the §5.3.1 label→column
   table plus the **authority rule** (§8.1): for an issue with an **active run**
   the DB ``runs`` row is authoritative; otherwise the ``agent:*`` label governs,
   with precedence ``in-progress > paused > review > queued`` if several are seen.
   :func:`build_board_list` joins the cache with active runs to produce the
   ``GET /repos/{repo}/issues`` list shape.

Nothing here mutates GitHub. Label creation (connect-time) is
:func:`app.github.labels.ensure_agent_labels`; the ``set_agent_state`` write
primitive is slice 1.3.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from app.db.repository import IssueRow
from app.github.graphql import BoardIssue, BoardPage, read_board

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.github.client import GitHubClient
    from app.github.hash_cache import HashCache

# ── board-state vocabulary (§5.3.1) ──────────────────────────────────────────

#: The six board columns, left→right, in §5.3.1 / ``data.jsx COLUMNS`` order. The
#: derived ``state`` value for an issue is exactly one of these.
BOARD_STATES: tuple[str, ...] = (
    "backlog",
    "queued",
    "in_progress",
    "needs_you",
    "in_review",
    "done",
)

#: ``agent:*`` label → board state (§5.3.1). Backlog is the absence of any label.
_LABEL_TO_STATE: dict[str, str] = {
    "agent:queued": "queued",
    "agent:in-progress": "in_progress",
    "agent:paused": "needs_you",
    "agent:review": "in_review",
}

#: Multi-label precedence when several ``agent:*`` labels are observed on one
#: issue (§8.1): ``in-progress > paused > review > queued``. Lower index wins.
_LABEL_PRECEDENCE: tuple[str, ...] = (
    "agent:in-progress",
    "agent:paused",
    "agent:review",
    "agent:queued",
)

#: Run statuses that count as an **active run** (non-terminal) for the authority
#: rule (§8.1). The engine ``RunStatus`` (§6.4) is ``pending | running | paused |
#: stopping | cancelled | completed | failed | timed_out``; the first four are
#: live, the rest are terminal (the DB row no longer overrides the label).
ACTIVE_RUN_STATUSES: frozenset[str] = frozenset({"pending", "running", "paused", "stopping"})

#: Active-run ``status`` → board state (the authority-rule mapping, §8.1). A
#: ``paused`` run lands the issue in **Needs You**; the rest are **In Progress**.
_RUN_STATUS_TO_STATE: dict[str, str] = {
    "paused": "needs_you",
    "running": "in_progress",
    "pending": "in_progress",
    "stopping": "in_progress",
}


#: ``settings`` key template for the persisted incremental ``since`` cursor per
#: repo, so the next poll re-reads only changed issues (AC-3).
def _since_key(repo: str) -> str:
    return f"sync_since::{repo.strip().lower()}"


# ── repository / read seam ───────────────────────────────────────────────────


class IssueWriter(Protocol):
    """The subset of the repository the import path writes through (never SQL).

    Kept to exactly what :func:`sync_issues` needs so the import demonstrably
    goes **through the repository layer** (the platform's single DB seam, INV-6)
    rather than issuing its own writes. :class:`app.db.repository.Repository`
    satisfies this structurally.

    The import upserts a whole board page via :meth:`upsert_issues` (plural) so
    the page lands in **one** writer transaction (one ``BEGIN IMMEDIATE``) rather
    than N — the user-facing ``POST /sync`` no longer runs N round-trips through
    the single writer (PERF).
    """

    async def upsert_issues(self, rows: Sequence[IssueRow]) -> None: ...

    async def set_setting(self, key: str, value: str) -> None: ...

    async def get_setting(self, key: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class ActiveRun:
    """The minimal active-run projection the authority rule consults (§8.1)."""

    issue_num: int
    status: str
    pr_num: int | None = None


# ── derivation: label → column + authority rule (§5.3.1, §8.1) ────────────────


def _label_state(labels: Sequence[str]) -> str:
    """Derive the column from the ``agent:*`` labels alone (no run) — §5.3.1.

    Backlog when no ``agent:*`` label is present. When multiple are seen,
    :data:`_LABEL_PRECEDENCE` decides (``in-progress > paused > review > queued``,
    §8.1) so a stray double-label never renders an issue in two columns.
    """
    present = {lbl for lbl in labels if lbl in _LABEL_TO_STATE}
    if not present:
        return "backlog"
    for label in _LABEL_PRECEDENCE:
        if label in present:
            return _LABEL_TO_STATE[label]
    return "backlog"  # pragma: no cover - present is a subset of the precedence set


def derive_state(
    *,
    labels: Sequence[str],
    is_closed: bool = False,
    merged_pr_num: int | None = None,
    active_run: ActiveRun | None = None,
) -> str:
    """Derive an issue's board column per §5.3.1 + the authority rule (§8.1).

    Resolution order:

    1. **Done** — a closed issue (or one with a linked merged PR) is Done
       regardless of any stale ``agent:*`` label (§5.3.1 row 6).
    2. **Authority rule** — if there is an **active run** (status in
       :data:`ACTIVE_RUN_STATUSES`), the DB ``runs`` row wins: a ``paused`` run →
       Needs You, otherwise In Progress. The label is advisory while a run is live
       (§8.1), so a stale ``agent:queued`` on a now-running issue does **not** pull
       it back to Queued.
    3. **Label** — otherwise the ``agent:*`` label governs via :func:`_label_state`
       (with precedence), and absence of a label is Backlog.

    A *terminal* run (completed/failed/…) is **not** active, so it does not
    override the label — the failed-run demotion that moves the label is 1.3's
    reconciliation; here a terminal run simply yields to the label/closed signal.
    """
    if is_closed or merged_pr_num is not None:
        return "done"
    if active_run is not None and active_run.status in ACTIVE_RUN_STATUSES:
        return _RUN_STATUS_TO_STATE.get(active_run.status, "in_progress")
    return _label_state(labels)


def derive_issue_state(issue: BoardIssue, active_run: ActiveRun | None = None) -> str:
    """Convenience: derive the board state for a parsed :class:`BoardIssue`."""
    return derive_state(
        labels=issue.labels,
        is_closed=issue.is_closed,
        merged_pr_num=issue.merged_pr_num,
        active_run=active_run,
    )


# ── import: GraphQL board read → issues cache (through the repository) ─────────


@dataclass(frozen=True, slots=True)
class SyncResult:
    """Outcome of one :func:`sync_issues` import."""

    repo: str
    imported: int
    since_cursor: str | None
    from_cache: bool


async def sync_issues(
    client: GitHubClient,
    repo: str,
    *,
    writer: IssueWriter,
    cache: HashCache[BoardPage] | None = None,
    incremental: bool = True,
) -> SyncResult:
    """Import the repo's issues into the cache through the repository (§8.1, T037).

    Reads the board (paginated GraphQL, Done-bounded) — incrementally from the
    persisted ``since`` cursor when ``incremental`` (the default) — and upserts
    the **whole page in one transaction** via :meth:`Repository.upsert_issues`
    (never raw SQL): a single writer ``BEGIN IMMEDIATE`` for the page rather than
    one per issue, so importing N issues on the user-facing ``POST /sync`` is one
    writer round-trip, not N (PERF). The new high-water ``since`` is persisted via
    the repository ``settings`` KV so the next poll re-reads only changed issues
    (AC-3).

    The derived board ``state`` written to the cache is the **label-only**
    derivation (closed→done included); the live authority-rule overlay (active-run
    DB row wins) is applied at *read* time in :func:`build_board_list`, because run
    state changes faster than a sync and the cache must not pin a stale "running".
    """
    since = await writer.get_setting(_since_key(repo)) if incremental else None
    page = await read_board(client, repo, since=since, cache=cache)

    rows = [
        IssueRow(
            repo=repo,
            num=issue.num,
            title=issue.title,
            state=derive_state(
                labels=issue.labels,
                is_closed=issue.is_closed,
                merged_pr_num=issue.merged_pr_num,
            ),
            labels=list(issue.labels),
            pr_num=issue.merged_pr_num,
        )
        for issue in page.issues
    ]
    # One batched upsert for the whole page → a single writer transaction (PERF).
    await writer.upsert_issues(rows)

    if page.since_cursor:
        await writer.set_setting(_since_key(repo), page.since_cursor)

    return SyncResult(
        repo=repo,
        imported=len(page.issues),
        since_cursor=page.since_cursor,
        from_cache=page.from_cache,
    )


# ── read: issues cache + active runs → board list (§5.3.1 + authority) ─────────


class IssueReader(Protocol):
    """The subset of the repository the board read path reads through (NFR-PORT-1).

    Mirrors :class:`IssueWriter` for the read side so ``GET /repos/{repo}/issues``
    honors the same single DB seam as the writes. :class:`app.db.repository.Repository`
    satisfies this structurally.
    """

    async def read_issues(self, repo: str) -> list[dict[str, Any]]: ...

    async def read_active_runs(
        self, repo: str, statuses: Sequence[str]
    ) -> list[dict[str, Any]]: ...


def active_runs_from_rows(rows: Sequence[Mapping[str, Any]]) -> dict[int, ActiveRun]:
    """Fold ``(issue_num, status, pr_num)`` rows into ``issue_num → ActiveRun``.

    When several active runs share an issue (should not happen), the most-advanced
    by :data:`_RUN_STATUS_TO_STATE` precedence is kept (paused outranks running for
    Needs-You surfacing).
    """
    by_issue: dict[int, ActiveRun] = {}
    for row in rows:
        if row["issue_num"] is None:
            continue
        num = int(row["issue_num"])
        run = ActiveRun(
            issue_num=num,
            status=str(row["status"]),
            pr_num=(int(row["pr_num"]) if row["pr_num"] is not None else None),
        )
        existing = by_issue.get(num)
        if existing is None or _run_rank(run.status) < _run_rank(existing.status):
            by_issue[num] = run
    return by_issue


async def read_board_via_repository(
    reader: IssueReader, repo: str
) -> tuple[list[dict[str, Any]], dict[int, ActiveRun]]:
    """Read cached issues + active runs through the repository seam (NFR-PORT-1).

    The board list's two inputs — the cached ``issues`` rows (with the persisted
    ``state``/Done signal) and the repo's active runs for the authority rule — both
    flow through :class:`app.db.repository.Repository` read methods, so the read
    path honors the same single DB boundary as the writes. Returns
    ``(cached_issues, active_runs)`` ready for :func:`build_board_list`.
    """
    cached = await reader.read_issues(repo)
    run_rows = await reader.read_active_runs(repo, sorted(ACTIVE_RUN_STATUSES))
    return cached, active_runs_from_rows(run_rows)


def _run_rank(status: str) -> int:
    """Rank an active status for the "most advanced run" tiebreak (paused first)."""
    order = ("paused", "running", "stopping", "pending")
    return order.index(status) if status in order else len(order)


def build_board_list(
    cached_issues: Sequence[Mapping[str, Any]],
    active_runs: Mapping[int, ActiveRun],
) -> list[dict[str, Any]]:
    """Join cached issues with active runs into the board list shape (§5.3.1).

    For each cached issue, the board ``state`` is re-derived with the authority
    rule applied (active-run DB row > label, §8.1) so the list is **live** even
    though the cache row stored only the label-derived state at sync time. The
    **closed/Done signal is honored**: :func:`sync_issues` persisted the §5.3.1
    derivation into the ``state`` column, so a cached ``state == "done"`` means the
    issue is closed (or has a merged PR) and must re-derive to **Done**, not get
    flattened to Backlog by a hardcoded ``is_closed=False`` (AC-5 / §5.3.1 row 6).
    The returned dicts carry the fields the board card reads (``data.jsx ISSUES``):
    number, title, labels, derived state, workflow/agent chips, and pr.
    """
    out: list[dict[str, Any]] = []
    for row in cached_issues:
        num = int(row["num"])
        labels = _decode_labels(row.get("labels_json"))
        run = active_runs.get(num)
        pr_num = row.get("pr_num")
        # The persisted ``state`` carries the closed/merged Done signal from sync
        # time (§5.3.1). Feed it back into the live derivation so a closed issue
        # stays Done even when it has no merged-PR linkage and no agent:* label.
        cached_done = str(row.get("state") or "") == "done"
        state = derive_state(
            labels=labels,
            is_closed=cached_done,
            merged_pr_num=(int(pr_num) if pr_num is not None else None),
            active_run=run,
        )
        out.append(
            {
                "num": num,
                "title": row.get("title", ""),
                "labels": labels,
                "state": state,
                "workflow_id": row.get("workflow_id"),
                "agent": row.get("agent"),
                "pr_num": (int(pr_num) if pr_num is not None else None),
                "run_status": run.status if run else None,
            }
        )
    return out


def _decode_labels(labels_json: Any) -> list[str]:
    """Decode the cache's ``labels_json`` column to a list of label names."""
    if not labels_json:
        return []
    try:
        value = json.loads(labels_json)
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [str(v) for v in value]
