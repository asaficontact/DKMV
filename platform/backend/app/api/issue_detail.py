"""``GET /issues/{num}`` — the issue **detail** for the issue-detail screen (§8.1).

The detail view (PRD §5.4, §8.1 endpoints) is **distinct** from Phase 1's board-list
shape (``GET /repos/{repo}/issues`` — a compact per-card projection). The detail
carries what the issue-detail screen renders: the markdown **body**, the full
**labels** set, the author, and the **comments** thread — plus a small block on the
issue's **active run** (if any) so the existing-run alert card (slice 2.2) can
render paused/running without a second round-trip.

It is one GraphQL round-trip (issue body + labels + author + comments) via the
shared :class:`~app.github.client.GitHubClient` (reads are point-cheaper on
GraphQL — R-2), then a single repository read for the active run. Like every
Phase-1/2 endpoint it sits behind the app-wide
:class:`~app.security.AccessControlMiddleware` (INV-1 — loopback ``Host`` + local
token + ``Origin``/CSRF); it declares **no** auth opt-out. Nothing here reaches
into ``dkmv/``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.deps import get_repository
from app.api.errors import ApiError, issue_not_found
from app.github.client import GitHubAuthError, GitHubError
from app.github.provider import get_github_client

# No prefix here: the ``/api/v1`` version prefix is owned by the single parent
# router in :mod:`app.api`, which this router attaches to.
router = APIRouter(tags=["github"])

#: Active-run statuses (non-terminal) the existing-run alert surfaces (§5.4).
_ACTIVE_RUN_STATUSES: tuple[str, ...] = ("pending", "running", "paused", "stopping")

#: GraphQL issue-detail document: the body markdown, labels, author, and the
#: comments thread (the issue-detail screen, §5.4). One round-trip; ``first:50``
#: comments bounds the page (older comments paginate later if needed).
ISSUE_DETAIL_QUERY = """
query IssueDetail($owner: String!, $name: String!, $num: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $num) {
      number
      title
      body
      state
      url
      createdAt
      author { login avatarUrl }
      labels(first: 100) { nodes { name color } }
      comments(first: 50) {
        nodes {
          id
          body
          createdAt
          author { login avatarUrl }
        }
      }
    }
  }
}
"""


def _split_owner_name(repo: str) -> tuple[str, str]:
    """Split an ``owner/name`` slug into the two GraphQL variables."""
    cleaned = repo.strip().strip("/")
    parts = [p for p in cleaned.split("/") if p]
    if len(parts) != 2:
        raise ApiError(400, "validation_error", f"repo must be 'owner/name', got {repo!r}")
    return parts[0], parts[1]


def _author(node: dict[str, Any] | None) -> dict[str, Any] | None:
    """Project a GraphQL author node to ``{login, avatar}`` (or ``None``)."""
    if not node:
        return None
    login = node.get("login")
    if not login:
        return None
    return {"login": str(login), "avatar": node.get("avatarUrl")}


def _labels(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Project the issue's labels to ``[{name, color}]`` (the GhLabel pills)."""
    conn = node.get("labels") or {}
    out: list[dict[str, Any]] = []
    for label in conn.get("nodes") or []:
        if label and label.get("name"):
            out.append({"name": str(label["name"]), "color": label.get("color")})
    return out


def _comments(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Project the comments thread to the issue-detail screen shape (§5.4)."""
    conn = node.get("comments") or {}
    out: list[dict[str, Any]] = []
    for comment in conn.get("nodes") or []:
        if not comment:
            continue
        out.append(
            {
                "id": comment.get("id"),
                "body": comment.get("body") or "",
                "created_at": comment.get("createdAt"),
                "author": _author(comment.get("author")),
            }
        )
    return out


async def _active_run(repository: Any, repo: str, num: int) -> dict[str, Any] | None:
    """Return the issue's active (non-terminal) run block, or ``None`` (§5.4).

    Drives the existing-run alert (slice 2.2): the run id + status so the card
    renders the paused (amber, "Review decision") vs running (blue, "Watch live")
    variant. Read through the repository seam (the active-run DB row is
    authoritative — §8.1).
    """
    active = await repository.read_active_runs(repo, _ACTIVE_RUN_STATUSES)
    for row in active:
        if row.get("issue_num") == num:
            return {
                "status": row.get("status"),
                "pr_num": row.get("pr_num"),
            }
    return None


def _map_github_error(exc: Exception) -> ApiError:
    """Map a GitHub failure to the §8.9 error envelope (matches issues.py)."""
    if isinstance(exc, GitHubAuthError):
        return ApiError(
            status_code=401,
            code="github_unauthorized",
            message="GitHub rejected the credential. Reconnect with a valid token.",
        )
    return ApiError(
        status_code=502,
        code="github_upstream_error",
        message="GitHub could not be reached.",
    )


@router.get("/issues/{owner}/{name}/{num}")
async def get_issue_detail(owner: str, name: str, num: int, request: Request) -> dict[str, Any]:
    """Return one issue's **detail** (markdown body, labels, author, comments) (§5.4).

    The issue-detail screen read (T059): one GraphQL round-trip for the body +
    labels + author + comments, plus a repository read for the issue's active run
    (so the existing-run alert renders without a second request). Distinct from the
    board-list shape. A ``404 issue_not_found`` when GitHub has no such issue.
    """
    repo = f"{owner}/{name}"
    settings = request.app.state.settings
    client = await get_github_client(request.app, settings)

    try:
        payload = await client.graphql(
            ISSUE_DETAIL_QUERY, {"owner": owner, "name": name, "num": num}
        )
    except (GitHubAuthError, GitHubError) as exc:
        raise _map_github_error(exc) from exc

    issue_node = ((payload.get("data") or {}).get("repository") or {}).get("issue")
    if not issue_node:
        raise issue_not_found(repo, num)

    async with get_repository(request) as repository:
        active = await _active_run(repository, repo, num)

    return {
        "num": int(issue_node.get("number", num)),
        "title": str(issue_node.get("title", "")),
        "body": issue_node.get("body") or "",
        "state": str(issue_node.get("state", "")).lower(),
        "url": issue_node.get("url"),
        "created_at": issue_node.get("createdAt"),
        "author": _author(issue_node.get("author")),
        "labels": _labels(issue_node),
        "comments": _comments(issue_node),
        "active_run": active,
    }
