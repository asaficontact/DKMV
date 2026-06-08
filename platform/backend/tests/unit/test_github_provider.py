"""Slice 1.1 — GitHub client provider wiring (INV-4 secret hygiene).

The provider builds a :class:`~app.github.pat_client.PatGitHubClient` over the
encrypted :class:`~app.secrets.store.SecretStore`, seeding the dev-ingress
``GITHUB_TOKEN`` into the store as **ciphertext** so the token is never read from
env at call time and never sits in DB cleartext (INV-4). These tests exercise
that path directly.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.github.client import GitHubClient
from app.github.pat_client import GITHUB_PAT_SECRET_KEY, PatGitHubClient
from app.github.provider import (
    get_github_client,
    get_secret_store,
    set_github_client,
)
from app.secrets.store import SECRET_KEY_ENV, SecretStore

from tests.conftest import make_settings


def _app() -> SimpleNamespace:
    """A minimal app stand-in carrying a ``state`` namespace (Starlette-like)."""
    return SimpleNamespace(state=SimpleNamespace())


async def test_explicit_client_is_returned() -> None:
    """An installed client is returned verbatim (used by connect/tests)."""
    app = _app()
    settings = make_settings()

    class _Fake(GitHubClient):
        async def list_repos(self):  # type: ignore[override]  # DKMVP-ESCAPE: test fake
            return []

        async def check_write_permission(self, repo: str):  # type: ignore[override]  # DKMVP-ESCAPE: test fake
            raise NotImplementedError

        async def graphql(self, query, variables):  # type: ignore[override]  # DKMVP-ESCAPE: test fake
            raise NotImplementedError

        async def replace_labels(self, repo, num, labels):  # type: ignore[override]  # DKMVP-ESCAPE: test fake
            raise NotImplementedError

    fake = _Fake()
    set_github_client(app, fake)  # type: ignore[arg-type]  # DKMVP-ESCAPE: SimpleNamespace app stub
    resolved = await get_github_client(app, settings)  # type: ignore[arg-type]  # DKMVP-ESCAPE: app stub
    assert resolved is fake


async def test_builds_pat_client_and_seeds_dev_token(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """With a configured key + dev GITHUB_TOKEN, the token is seeded as ciphertext."""
    key = SecretStore.generate_key()
    monkeypatch.setenv(SECRET_KEY_ENV, key)
    app = _app()
    settings = make_settings(GITHUB_TOKEN="github_pat_devSeedToken")  # noqa: S106

    client = await get_github_client(app, settings)  # type: ignore[arg-type]  # DKMVP-ESCAPE: app stub
    assert isinstance(client, PatGitHubClient)

    # The token landed in the store as the decryptable secret (never DB cleartext).
    store = get_secret_store(app, settings)  # type: ignore[arg-type]  # DKMVP-ESCAPE: app stub
    assert store is not None
    assert await store.get(GITHUB_PAT_SECRET_KEY) == "github_pat_devSeedToken"


async def test_no_key_falls_back_to_ephemeral_store(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """With no encryption key, an ephemeral in-process store is used (no env read).

    ``get_secret_store`` returns ``None`` for a *fresh* app with no configured
    key; once ``get_github_client`` builds the ephemeral fallback, the token is
    still encrypted at rest in-process (never read from env at call time).
    """
    monkeypatch.delenv(SECRET_KEY_ENV, raising=False)
    app = _app()
    settings = make_settings(GITHUB_TOKEN="github_pat_devSeedToken")  # noqa: S106

    # Fresh app, no key configured → no store.
    assert get_secret_store(app, settings) is None  # type: ignore[arg-type]  # DKMVP-ESCAPE: app stub

    client = await get_github_client(app, settings)  # type: ignore[arg-type]  # DKMVP-ESCAPE: app stub
    assert isinstance(client, PatGitHubClient)
    # The ephemeral store now backs the client and holds the dev token as the
    # decryptable secret — never as a plain-env read at call time.
    store = app.state.secret_store
    assert await store.get(GITHUB_PAT_SECRET_KEY) == "github_pat_devSeedToken"
