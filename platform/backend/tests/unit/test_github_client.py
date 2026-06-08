"""Slice 1.1 — GitHubClient interface + PAT client + GET /repos + write preflight.

Covers AC-1 (a single ``GitHubClient`` interface with a PAT impl; PAT read from
the encrypted ``SecretStore``, never env/DB-cleartext; App/webhooks OUT) and
AC-2 (effective-write-permission preflight: a read-only token on the selected
repo is a blocker, not a success — it fails fast at connect).

GitHub is mocked with an :class:`httpx.MockTransport`; the SecretStore is the
real encrypt-at-rest store running in-memory (no DB, no network).
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from app.github.client import (
    GitHubAuthError,
    GitHubClient,
    Repo,
    WritePermission,
)
from app.github.pat_client import GITHUB_PAT_SECRET_KEY, PatGitHubClient
from app.secrets.store import SecretStore

from tests.conftest import auth_headers, build_client

# ── fixtures / helpers ───────────────────────────────────────────────────────

_REAL_TOKEN = "github_pat_11ABCDEFG0_thisIsNotARealToken"  # noqa: S105 - fixture


async def _seed(store: SecretStore, token: str = _REAL_TOKEN) -> None:
    await store.put(GITHUB_PAT_SECRET_KEY, token)


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
    store: SecretStore,
) -> PatGitHubClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://api.github.com")
    return PatGitHubClient(store, http_client=http)


_REPO_JSON = {
    "name": "DKMV",
    "owner": {"login": "asaficontact"},
    "language": "Python",
    "private": True,
    "updated_at": "2026-06-08T10:00:00Z",
    "open_issues_count": 12,
    "stargazers_count": 3,
    "description": "GitHub Issues → autonomous coding-agent runs",
}


# ── AC-1: interface + PAT impl + secret hygiene ──────────────────────────────


def test_pat_client_is_a_githubclient() -> None:
    """The PAT impl is an instance of the single GitHubClient interface (ADR-P004)."""
    store = SecretStore(key=SecretStore.generate_key())
    client = PatGitHubClient(store)
    assert isinstance(client, GitHubClient)


async def test_list_repos_returns_repo_shape() -> None:
    """GET /repos maps the GitHub payload to the §6.1 Repo shape (AC-1)."""
    store = SecretStore(key=SecretStore.generate_key())
    await _seed(store)

    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=[_REPO_JSON])

    client = _client(handler, store)
    repos = await client.list_repos()

    assert len(repos) == 1
    repo = repos[0]
    assert isinstance(repo, Repo)
    assert repo.org == "asaficontact"
    assert repo.name == "DKMV"
    assert repo.lang == "Python"
    assert repo.lang_color.startswith("var(--")  # token ref, never a raw hex (INV-14)
    assert repo.private is True
    assert repo.issues == 12
    assert repo.stars == 3
    assert repo.desc is not None
    # The PAT was read from the store and sent as a Bearer header.
    assert captured["auth"] == f"Bearer {_REAL_TOKEN}"


async def test_pat_read_from_secret_store_not_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The PAT comes from the SecretStore — env is never consulted (INV-4)."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_envTokenShouldNeverBeUsed")  # noqa: S105
    store = SecretStore(key=SecretStore.generate_key())
    await _seed(store, token=_REAL_TOKEN)

    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=[])

    client = _client(handler, store)
    await client.list_repos()
    # The store token is used; the env token is NOT.
    assert seen["auth"] == f"Bearer {_REAL_TOKEN}"
    assert "ghp_envTokenShouldNeverBeUsed" not in seen["auth"]


async def test_missing_pat_raises_auth_error() -> None:
    """With no PAT in the store, the client raises a clean auth error (no env read)."""
    store = SecretStore(key=SecretStore.generate_key())

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - not reached
        return httpx.Response(200, json=[])

    client = _client(handler, store)
    with pytest.raises(GitHubAuthError):
        await client.list_repos()


async def test_list_repos_paginates() -> None:
    """list_repos pages until a short page is returned."""
    store = SecretStore(key=SecretStore.generate_key())
    await _seed(store)

    pages: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        pages.append(page)
        if page == "1":
            return httpx.Response(200, json=[dict(_REPO_JSON, name=f"r{i}") for i in range(100)])
        return httpx.Response(200, json=[dict(_REPO_JSON, name="last")])

    client = _client(handler, store)
    repos = await client.list_repos()
    assert len(repos) == 101
    assert pages == ["1", "2"]


async def test_rejected_credential_raises_auth_error() -> None:
    """A 401 from GitHub surfaces as GitHubAuthError (bad/expired token)."""
    store = SecretStore(key=SecretStore.generate_key())
    await _seed(store)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    client = _client(handler, store)
    with pytest.raises(GitHubAuthError):
        await client.list_repos()


# ── AC-2: effective-write-permission preflight ───────────────────────────────


async def test_write_permission_true_for_pushable_repo() -> None:
    """A token that can push → can_write True, no missing scopes (AC-2)."""
    store = SecretStore(key=SecretStore.generate_key())
    await _seed(store)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=dict(_REPO_JSON, permissions={"push": True, "pull": True}),
        )

    client = _client(handler, store)
    perm = await client.check_write_permission("asaficontact/DKMV")
    assert isinstance(perm, WritePermission)
    assert perm.can_write is True
    assert perm.missing == ()
    assert perm.role == "write"


async def test_write_permission_false_for_readonly_token() -> None:
    """A read-only token → can_write False with the required scopes missing (AC-2).

    This is the fast-fail signal: the preflight blocks at connect, not late at
    PR-creation time.
    """
    store = SecretStore(key=SecretStore.generate_key())
    await _seed(store)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=dict(_REPO_JSON, permissions={"push": False, "pull": True}),
        )

    client = _client(handler, store)
    perm = await client.check_write_permission("asaficontact/DKMV")
    assert perm.can_write is False
    assert perm.role == "read"
    assert "issues:write" in perm.missing
    assert "contents:write" in perm.missing
    assert "pull_requests:write" in perm.missing


async def test_check_write_permission_malformed_repo() -> None:
    """A non 'owner/name' value is rejected before any network call."""
    store = SecretStore(key=SecretStore.generate_key())
    await _seed(store)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - not reached
        return httpx.Response(200, json={})

    client = _client(handler, store)
    from app.github.client import GitHubError

    with pytest.raises(GitHubError):
        await client.check_write_permission("not-a-slug")


# ── HTTP-layer: GET /repos behind the access-control middleware ───────────────


class _FakeGitHubClient(GitHubClient):
    """In-memory fake installed on app.state for the HTTP-layer tests.

    ``raise_on`` lets a test force an error from either method ("list" /
    "write") to exercise the route's error mapping.
    """

    def __init__(
        self,
        repos: list[Repo],
        write: WritePermission,
        *,
        raise_on: tuple[str, Exception] | None = None,
    ) -> None:
        self._repos = repos
        self._write = write
        self._raise_on = raise_on

    async def list_repos(self) -> list[Repo]:
        if self._raise_on and self._raise_on[0] == "list":
            raise self._raise_on[1]
        return self._repos

    async def check_write_permission(self, repo: str) -> WritePermission:
        if self._raise_on and self._raise_on[0] == "write":
            raise self._raise_on[1]
        return self._write


def _repo() -> Repo:
    return Repo(
        org="asaficontact",
        name="DKMV",
        lang="Python",
        lang_color="var(--lang-python)",
        private=True,
        updated="updated 2026-06-08T10:00:00Z",
        issues=12,
        stars=3,
        desc="GitHub Issues → autonomous coding-agent runs",
    )


def test_get_repos_requires_token() -> None:
    """GET /repos inherits the INV-1 middleware — no token → 401 (AC-14/INV-1)."""
    client = build_client()
    resp = client.get("/api/v1/repos")
    assert resp.status_code == 401


def test_get_repos_foreign_host_403() -> None:
    """A foreign Host is rejected before reaching the route (INV-1)."""
    client = build_client(host="evil.example.com")
    resp = client.get("/api/v1/repos", headers=auth_headers())
    assert resp.status_code == 403


def test_get_repos_returns_items() -> None:
    """GET /repos serializes the Repo shape with langColor as a token ref."""
    client = build_client()
    from app.github.provider import set_github_client

    fake = _FakeGitHubClient(
        [_repo()],
        WritePermission(repo="asaficontact/DKMV", can_write=True, role="write", can_push=True),
    )
    set_github_client(client.app, fake)

    resp = client.get("/api/v1/repos", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    item = body["items"][0]
    assert item["org"] == "asaficontact"
    assert item["name"] == "DKMV"
    assert item["langColor"].startswith("var(--")
    assert item["issues"] == 12
    assert item["stars"] == 3


def test_get_repos_no_token_literal_in_response() -> None:
    """The repos response never echoes a GitHub token literal (INV-4)."""
    client = build_client()
    from app.github.provider import set_github_client

    fake = _FakeGitHubClient(
        [_repo()],
        WritePermission(repo="asaficontact/DKMV", can_write=True, role="write", can_push=True),
    )
    set_github_client(client.app, fake)
    resp = client.get("/api/v1/repos", headers=auth_headers())
    text = json.dumps(resp.json())
    assert "github_pat_" not in text
    assert "ghp_" not in text


# ── HTTP-layer: /preflight write-permission probe on the selected repo ────────


def test_preflight_with_readonly_token_is_blocked() -> None:
    """AC-2: /preflight?repo=… with a read-only token → ready False + a blocker."""
    from app.github.provider import set_github_client

    from tests.conftest import FakeRuntime, make_settings

    # A capabilities report where the standing checks all pass, so the ONLY
    # blocker is the read-only write probe (isolates AC-2).
    report = _all_green_report()
    settings = make_settings()
    client = build_client(settings=settings, runtime=FakeRuntime(report))

    fake = _FakeGitHubClient(
        [_repo()],
        WritePermission(
            repo="asaficontact/DKMV",
            can_write=False,
            role="read",
            can_push=False,
            missing=("issues:write", "contents:write", "pull_requests:write"),
        ),
    )
    set_github_client(client.app, fake)

    resp = client.get(
        "/api/v1/preflight", params={"repo": "asaficontact/DKMV"}, headers=auth_headers()
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is False
    write_rows = [c for c in body["checks"] if c["id"] == "github_write"]
    assert len(write_rows) == 1
    assert write_rows[0]["ok"] is False
    assert any("Write access" in b for b in body["blockers"])


def test_preflight_with_writable_token_passes() -> None:
    """A writable token adds a passing write row and does not add a blocker."""
    from app.github.provider import set_github_client

    from tests.conftest import FakeRuntime, make_settings

    report = _all_green_report()
    client = build_client(settings=make_settings(), runtime=FakeRuntime(report))
    fake = _FakeGitHubClient(
        [_repo()],
        WritePermission(repo="asaficontact/DKMV", can_write=True, role="write", can_push=True),
    )
    set_github_client(client.app, fake)

    resp = client.get(
        "/api/v1/preflight", params={"repo": "asaficontact/DKMV"}, headers=auth_headers()
    )
    body = resp.json()
    write_rows = [c for c in body["checks"] if c["id"] == "github_write"]
    assert write_rows[0]["ok"] is True
    assert not any("Write access" in b for b in body["blockers"])


def test_preflight_without_repo_omits_write_row() -> None:
    """No ?repo= → the standing checklist only; no write probe row."""
    from tests.conftest import FakeRuntime, make_settings

    client = build_client(settings=make_settings(), runtime=FakeRuntime(_all_green_report()))
    resp = client.get("/api/v1/preflight", headers=auth_headers())
    body = resp.json()
    assert all(c["id"] != "github_write" for c in body["checks"])


def test_get_repos_auth_error_maps_to_401() -> None:
    """A rejected credential surfaces as a 401 §8.9 envelope."""
    from app.github.provider import set_github_client

    client = build_client()
    fake = _FakeGitHubClient(
        [],
        WritePermission(repo="x/y", can_write=True, role="write"),
        raise_on=("list", GitHubAuthError("bad token")),
    )
    set_github_client(client.app, fake)
    resp = client.get("/api/v1/repos", headers=auth_headers())
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "github_unauthorized"


def test_get_repos_upstream_error_maps_to_502() -> None:
    """An upstream GitHub failure surfaces as a 502 §8.9 envelope."""
    from app.github.client import GitHubError
    from app.github.provider import set_github_client

    client = build_client()
    fake = _FakeGitHubClient(
        [],
        WritePermission(repo="x/y", can_write=True, role="write"),
        raise_on=("list", GitHubError("boom", status=500)),
    )
    set_github_client(client.app, fake)
    resp = client.get("/api/v1/repos", headers=auth_headers())
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "github_upstream_error"


def test_preflight_credential_rejected_is_blocked() -> None:
    """A rejected credential at the write probe → a failing write row + blocker."""
    from app.github.provider import set_github_client

    from tests.conftest import FakeRuntime, make_settings

    client = build_client(settings=make_settings(), runtime=FakeRuntime(_all_green_report()))
    fake = _FakeGitHubClient(
        [],
        WritePermission(repo="x/y", can_write=True, role="write"),
        raise_on=("write", GitHubAuthError("bad token")),
    )
    set_github_client(client.app, fake)
    resp = client.get(
        "/api/v1/preflight", params={"repo": "asaficontact/DKMV"}, headers=auth_headers()
    )
    body = resp.json()
    assert body["ready"] is False
    write_rows = [c for c in body["checks"] if c["id"] == "github_write"]
    assert write_rows[0]["ok"] is False


def test_preflight_upstream_error_is_blocked() -> None:
    """An upstream failure at the write probe → a failing write row + blocker."""
    from app.github.client import GitHubError
    from app.github.provider import set_github_client

    from tests.conftest import FakeRuntime, make_settings

    client = build_client(settings=make_settings(), runtime=FakeRuntime(_all_green_report()))
    fake = _FakeGitHubClient(
        [],
        WritePermission(repo="x/y", can_write=True, role="write"),
        raise_on=("write", GitHubError("not found", status=404)),
    )
    set_github_client(client.app, fake)
    resp = client.get(
        "/api/v1/preflight", params={"repo": "asaficontact/DKMV"}, headers=auth_headers()
    )
    body = resp.json()
    assert body["ready"] is False
    write_rows = [c for c in body["checks"] if c["id"] == "github_write"]
    assert write_rows[0]["ok"] is False


async def test_pat_client_404_repo_raises() -> None:
    """check_write_permission on a missing repo raises GitHubError(404)."""
    from app.github.client import GitHubError

    store = SecretStore(key=SecretStore.generate_key())
    await _seed(store)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    client = _client(handler, store)
    with pytest.raises(GitHubError) as excinfo:
        await client.check_write_permission("asaficontact/missing")
    assert excinfo.value.status == 404


def _all_green_report() -> object:
    """A CapabilityReport-like object whose standing checks all pass."""

    class _Report:
        docker_available = True
        docker_version = "27.0"
        image_exists = True
        image_name = "dkmv-sandbox:latest"
        has_anthropic_key = True
        has_codex_key = False
        has_github_token = True

    return _Report()
