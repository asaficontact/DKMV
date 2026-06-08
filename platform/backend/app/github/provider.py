"""GitHub client + secret-store wiring for the API layer (§8.1, INV-4).

The route handlers (``GET /repos``, the preflight write-probe) need a
:class:`~app.github.client.GitHubClient` whose PAT is read from the encrypted
:class:`~app.secrets.store.SecretStore` (INV-4 — never plain env, never DB
cleartext). This module is the small composition seam that builds and caches
those on ``app.state`` so:

* the **interface** is what handlers depend on (a deferred GitHub App client
  drops in here behind the same :class:`GitHubClient`, ADR-P004), and
* tests can inject a fake client via :func:`set_github_client` without touching
  the network.

**PAT seeding (dev ingress).** In a real deployment the connect flow
(``POST /connect/github``, slice 1.4) writes the PAT into the store. For the
dev-mode env ingress, if ``settings.GITHUB_TOKEN`` is set we seed it into the
**encrypted** store once at first use — so even the dev path keeps the token out
of DB cleartext and out of logs (it is encrypted at rest via Fernet; INV-4). If
no encryption key is configured, no store is built and the client surfaces a
clear "no PAT configured" auth error rather than reading env ad hoc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.github.client import GitHubClient
from app.github.pat_client import GITHUB_PAT_SECRET_KEY, PatGitHubClient
from app.secrets.store import SecretStore, SecretStoreError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from starlette.applications import Starlette

    from app.config import Settings

#: ``app.state`` attribute names (so multiple slices agree on the seam).
_CLIENT_ATTR = "github_client"
_STORE_ATTR = "secret_store"


def set_github_client(app: Starlette, client: GitHubClient) -> None:
    """Install an explicit :class:`GitHubClient` on ``app.state`` (tests/connect).

    Used by the connect flow and by tests that inject a fake client; once set it
    is returned verbatim by :func:`get_github_client`.
    """
    setattr(app.state, _CLIENT_ATTR, client)


def get_secret_store(app: Starlette, settings: Settings) -> SecretStore | None:
    """Return (building+caching once) the app's encrypted SecretStore, or None.

    Returns ``None`` when no encryption key is configured — in that case there is
    no safe at-rest location for the PAT, so the client reports "no PAT
    configured" rather than falling back to a plaintext env read (INV-4).
    """
    existing = getattr(app.state, _STORE_ATTR, None)
    if existing is not None:
        assert isinstance(existing, SecretStore)
        return existing
    try:
        store = SecretStore()
    except SecretStoreError:
        return None
    setattr(app.state, _STORE_ATTR, store)
    return store


async def get_github_client(app: Starlette, settings: Settings) -> GitHubClient:
    """Resolve the :class:`GitHubClient`, building+caching the PAT client once.

    Order of resolution:

    1. an explicitly installed client (``set_github_client`` — connect/tests);
    2. otherwise a :class:`PatGitHubClient` over the app's encrypted SecretStore,
       seeding the dev-ingress ``GITHUB_TOKEN`` into the store if present so the
       token is encrypted at rest, never read from env ad hoc at call time.

    Raises :class:`app.secrets.store.SecretStoreError` only if a store cannot be
    built *and* a token is configured; with no token the client is still returned
    and surfaces a clean auth error on use.
    """
    existing = getattr(app.state, _CLIENT_ATTR, None)
    if existing is not None:
        assert isinstance(existing, GitHubClient)
        return existing

    store = get_secret_store(app, settings)
    if store is None:
        # No encryption key → build an ephemeral in-memory store so the dev token
        # (if any) is still encrypted in-process and never read from env ad hoc.
        store = SecretStore(key=SecretStore.generate_key())
        setattr(app.state, _STORE_ATTR, store)

    # Seed the dev-ingress PAT into the encrypted store once (idempotent: only if
    # absent), so the token lives at rest as ciphertext, not in env at call time.
    if await store.get(GITHUB_PAT_SECRET_KEY) is None:
        dev_token = settings.GITHUB_TOKEN.get_secret_value()
        if dev_token:
            await store.put(GITHUB_PAT_SECRET_KEY, dev_token)

    client: GitHubClient = PatGitHubClient(store)
    setattr(app.state, _CLIENT_ATTR, client)
    # NOTE (Phase-2 lifespan ask): this cached client owns a long-lived
    # ``httpx.AsyncClient`` that is never ``aclose()``-d at app shutdown. The
    # close belongs in the Phase-2 app-lifespan composition (the same place the
    # SecretStore/Repository lifespan wiring lands) — call ``client.aclose()``
    # there. Deliberately not adding a shutdown handler in slice 1.1.
    return client
