"""``GET /api/v1/repos`` — the Connect picker's repo list (PRD §6.1, §8.1).

Lists the repos the configured GitHub credential can access, rendered in the
§6.1 ``Repo`` shape ``{org, name, lang, langColor, private, updated, issues,
stars?, desc?}`` (``data.jsx REPOS``) the Connect picker (FR-01-4) consumes.

The endpoint is read-only (a GET) and inherits the INV-1 access-control
middleware like every other route — there is no unauthenticated path here. It
resolves the :class:`~app.github.client.GitHubClient` from ``app.state`` (the
fine-grained-PAT backend in v1; a GitHub App backend slots behind the same
interface later, ADR-P004), so it never branches on the auth backend and never
reads the token from env.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.errors import ApiError
from app.github.client import GitHubAuthError, GitHubError
from app.github.provider import get_github_client

# No prefix here: the ``/api/v1`` version prefix is owned by the single parent
# router in :mod:`app.api`, which this router attaches to.
router = APIRouter(tags=["github"])


@router.get("/repos")
async def list_repos(request: Request) -> dict[str, Any]:
    """Return the credential's accessible repos in the §6.1 ``Repo`` shape.

    Drives the Connect picker (FR-01-4). A rejected/expired credential surfaces
    as a 401 §8.9 envelope; an upstream GitHub failure surfaces as a 502.
    """
    settings = request.app.state.settings
    client = await get_github_client(request.app, settings)
    try:
        repos = await client.list_repos()
    except GitHubAuthError as exc:
        raise ApiError(
            status_code=401,
            code="github_unauthorized",
            message="GitHub rejected the credential. Reconnect with a valid token.",
        ) from exc
    except GitHubError as exc:
        raise ApiError(
            status_code=502,
            code="github_upstream_error",
            message="GitHub could not be reached.",
        ) from exc

    items = [
        {
            "org": repo.org,
            "name": repo.name,
            "lang": repo.lang,
            "langColor": repo.lang_color,
            "private": repo.private,
            "updated": repo.updated,
            "issues": repo.issues,
            "stars": repo.stars,
            "desc": repo.desc,
        }
        for repo in repos
    ]
    return {"items": items}
