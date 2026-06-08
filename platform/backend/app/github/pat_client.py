"""Fine-grained-PAT GitHub backend (PRD §8.1, ADR-P004 — the v1 identity).

:class:`PatGitHubClient` implements the :class:`~app.github.client.GitHubClient`
interface with a **fine-grained Personal Access Token** scoped to one repo with
``issues:write`` / ``pull_requests:write`` / ``contents:write`` /
``metadata:read``. It is the only required auth in v1; the deferred GitHub App
slots behind the same interface (ADR-P004), so nothing here is App-specific.

**Secret hygiene (INV-4).** The PAT is **read from the encrypted**
:class:`~app.secrets.store.SecretStore`, never from plain env and never written
to the DB in cleartext. The token value is held only for the duration of a call,
sent as a ``Bearer`` header, and **never logged** — debug strings and exceptions
carry no token literal. The store key is :data:`GITHUB_PAT_SECRET_KEY`.

**Effective-write-permission preflight (§8.1, FR-01-6).** ``check_write_permission``
reads the repo's fine-grained ``permissions`` block (what the *token* can do on
*this* repo) and reports ``can_write=False`` for a read-only token so the Connect
flow fails fast at connect, not late at PR time.

**Poll-only in v1 (ADR-P004).** No inbound GitHub receiver and no
signature/delivery machinery — v1 is poll-only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from app.github.client import (
    GitHubAuthError,
    GitHubClient,
    GitHubError,
    Repo,
    WritePermission,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.secrets.store import SecretStore

#: SecretStore key under which the operator's fine-grained PAT is persisted
#: (ciphertext only; INV-4). The connect flow writes it here; this client reads
#: it. Never an env var, never DB cleartext.
GITHUB_PAT_SECRET_KEY = "github_pat"

#: GitHub REST base. Pinned so the egress allowlist (``api.github.com``) covers it.
GITHUB_API_BASE = "https://api.github.com"

#: The minimum write capabilities a DKMV run requires on the selected repo, as the
#: human labels the Connect preflight renders. The fine-grained-PAT permission
#: keys that satisfy each are checked in :func:`_evaluate_write_permission`.
REQUIRED_WRITE_SCOPES: tuple[str, ...] = (
    "issues:write",
    "contents:write",
    "pull_requests:write",
)

# GitHub API media type + version pin (keeps the response schema stable).
_ACCEPT = "application/vnd.github+json"
_API_VERSION = "2022-11-28"

# Language → token color mapping for the picker dot. The concrete hex lives in
# the FRONTEND tokens file (INV-14); here we emit a *token name* so the backend
# never hardcodes a color and the UI resolves it from ``--lang-*`` vars. The
# prototype's ``langColor`` field carries this token reference.
_LANG_COLOR_TOKENS: dict[str, str] = {
    "Python": "var(--lang-python)",
    "TypeScript": "var(--lang-typescript)",
    "JavaScript": "var(--lang-javascript)",
    "Rust": "var(--lang-rust)",
    "Go": "var(--lang-go)",
    "Shell": "var(--lang-shell)",
    "Ruby": "var(--lang-ruby)",
    "Java": "var(--lang-java)",
    "C": "var(--lang-c)",
    "C++": "var(--lang-cpp)",
}
_LANG_COLOR_DEFAULT = "var(--lang-default)"


class PatGitHubClient(GitHubClient):
    """Fine-grained-PAT implementation of :class:`GitHubClient` (§8.1, ADR-P004).

    Args:
        secret_store: The encrypted store the PAT is read from (INV-4). The token
            is fetched per call and never cached in a logged/printed field.
        http_client: An optional injected :class:`httpx.AsyncClient` (tests pass a
            transport-mocked one); otherwise one is lazily created against
            :data:`GITHUB_API_BASE`.
        secret_key: The store key under which the PAT lives
            (default :data:`GITHUB_PAT_SECRET_KEY`).
    """

    def __init__(
        self,
        secret_store: SecretStore,
        *,
        http_client: httpx.AsyncClient | None = None,
        secret_key: str = GITHUB_PAT_SECRET_KEY,
    ) -> None:
        self._store = secret_store
        self._secret_key = secret_key
        self._client = http_client
        self._owns_client = http_client is None

    # ── transport ────────────────────────────────────────────────────────────

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=GITHUB_API_BASE, timeout=15.0)
        return self._client

    async def _token(self) -> str:
        """Fetch the PAT plaintext from the encrypted store (INV-4).

        The value is returned to the immediate caller only and never logged; the
        error message deliberately carries no token literal.
        """
        token = await self._store.get(self._secret_key)
        if not token:
            raise GitHubAuthError("no GitHub PAT configured (run the connect flow first)")
        return token

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Issue an authenticated GitHub request, mapping failures to GitHubError.

        The ``Authorization`` header carries the PAT for this one call; it is
        never persisted or logged. A 401/403 at the identity layer becomes
        :class:`GitHubAuthError`; other non-2xx become :class:`GitHubError` with
        the status (and **no** token in the message).
        """
        token = await self._token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": _ACCEPT,
            "X-GitHub-Api-Version": _API_VERSION,
        }
        headers.update(kwargs.pop("headers", {}))
        try:
            response = await self._http().request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:  # transport failure — no token in the message
            raise GitHubError(f"GitHub request failed: {type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            # Identity-layer rejection (bad/expired/over-narrow token). A repo-level
            # *permission* shortfall is reported structurally elsewhere, not here.
            raise GitHubAuthError("GitHub rejected the credential", status=response.status_code)
        if response.status_code >= 400:
            raise GitHubError(
                f"GitHub returned {response.status_code} for {method} {path}",
                status=response.status_code,
            )
        return response

    # ── GitHubClient surface ─────────────────────────────────────────────────

    async def list_repos(self) -> list[Repo]:
        """List the PAT's accessible repos in the §6.1 ``Repo`` shape (FR-01-4).

        Pages through ``GET /user/repos`` (the repos the fine-grained PAT can
        see), sorted by most-recently-updated, and maps each to the picker row.
        """
        repos: list[Repo] = []
        page = 1
        while True:
            response = await self._request(
                "GET",
                "/user/repos",
                params={
                    "per_page": 100,
                    "page": page,
                    "sort": "updated",
                    "direction": "desc",
                },
            )
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                break
            repos.extend(_to_repo(item) for item in batch)
            if len(batch) < 100:
                break
            page += 1
        return repos

    async def check_write_permission(self, repo: str) -> WritePermission:
        """Probe **effective** write permission on ``repo`` (§8.1, FR-01-6).

        Reads ``GET /repos/{owner}/{name}`` and evaluates the fine-grained
        ``permissions`` block. A read-only token yields ``can_write=False`` with
        the missing scopes populated, so the Connect preflight blocks at connect
        rather than failing late at PR time. A missing repo raises
        :class:`GitHubError` with ``status=404``.
        """
        owner_name = _split_repo(repo)
        response = await self._request("GET", f"/repos/{owner_name}")
        payload = response.json()
        return _evaluate_write_permission(repo, payload)

    async def aclose(self) -> None:
        """Close the owned HTTP client (no-op when one was injected)."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


# ── mapping helpers ──────────────────────────────────────────────────────────


def _split_repo(repo: str) -> str:
    """Normalize an ``owner/name`` slug; raise on a malformed value."""
    cleaned = repo.strip().strip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[: -len(".git")]
    parts = [p for p in cleaned.split("/") if p]
    if len(parts) != 2:
        raise GitHubError(f"repo must be 'owner/name', got {repo!r}")
    return f"{parts[0]}/{parts[1]}"


def _lang_color_token(lang: str | None) -> str:
    """Resolve a language to a *token reference* (never a raw hex; INV-14)."""
    if not lang:
        return _LANG_COLOR_DEFAULT
    return _LANG_COLOR_TOKENS.get(lang, _LANG_COLOR_DEFAULT)


def _to_repo(item: dict[str, Any]) -> Repo:
    """Map a GitHub repo object to the §6.1 ``Repo`` UI shape."""
    owner = item.get("owner") or {}
    org = str(owner.get("login", "")) if isinstance(owner, dict) else ""
    name = str(item.get("name", ""))
    lang = item.get("language")
    return Repo(
        org=org,
        name=name,
        lang=str(lang) if lang else "",
        lang_color=_lang_color_token(lang if isinstance(lang, str) else None),
        private=bool(item.get("private", False)),
        updated=_humanize_updated(item.get("updated_at") or item.get("pushed_at")),
        issues=int(item.get("open_issues_count", 0) or 0),
        stars=int(item.get("stargazers_count", 0) or 0),
        desc=(str(item["description"]) if item.get("description") else None),
    )


def _humanize_updated(updated_at: str | None) -> str:
    """Render the raw ISO ``updated_at`` as the picker's ``updated …`` sub-label.

    The prototype shows a relative string ("updated 2h ago"); the backend keeps
    this deterministic by passing through the ISO timestamp prefixed with
    ``updated`` (the UI does the relative formatting). Empty when unknown.
    """
    if not updated_at:
        return "updated unknown"
    return f"updated {updated_at}"


def _evaluate_write_permission(repo: str, payload: dict[str, Any]) -> WritePermission:
    """Derive the effective-write-permission result from a repo payload (§8.1).

    GitHub returns a ``permissions`` block on the repo object reflecting what the
    *authenticated token* can do here: ``push``/``maintain``/``admin`` (write
    ability) vs. ``pull``/``triage`` (read-ish). A fine-grained PAT without
    contents/issues/PR write reports ``push: false``, which is the fast-fail
    signal: ``can_write`` is ``False`` and the required scopes are reported as
    missing so the preflight box renders a precise blocker (FR-01-6).
    """
    perms = payload.get("permissions") or {}
    can_push = bool(perms.get("push", False))
    can_admin = bool(perms.get("admin", False))
    can_maintain = bool(perms.get("maintain", False))
    can_write = can_push or can_admin or can_maintain

    role = _role_label(perms)
    missing: tuple[str, ...] = () if can_write else REQUIRED_WRITE_SCOPES
    return WritePermission(
        repo=repo,
        can_write=can_write,
        role=role,
        can_push=can_push,
        missing=missing,
    )


def _role_label(perms: dict[str, Any]) -> str:
    """Map GitHub's fine-grained ability flags to a coarse role label."""
    if perms.get("admin"):
        return "admin"
    if perms.get("maintain"):
        return "maintain"
    if perms.get("push"):
        return "write"
    if perms.get("triage"):
        return "triage"
    if perms.get("pull"):
        return "read"
    return "none"
