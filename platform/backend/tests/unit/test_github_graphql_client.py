"""Slice 1.2 — the PAT client's GraphQL + label-create transport primitives.

These cover the HTTP surface :func:`app.github.graphql.read_board` and
:func:`app.github.labels.ensure_agent_labels` drive: ``POST /graphql`` (with the
GraphQL-errors→GitHubError promotion) and ``POST /labels`` (with the 422
"already exists" idempotent path — AC-4). GitHub is an :class:`httpx.MockTransport`;
the SecretStore is the real in-memory encrypt-at-rest store.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from app.github.client import GitHubError
from app.github.pat_client import GITHUB_PAT_SECRET_KEY, PatGitHubClient
from app.secrets.store import SecretStore

_TOKEN = "github_pat_11ABCDEFG_not_a_real_token"  # noqa: S105 - fixture


async def _store() -> SecretStore:
    store = SecretStore(key=SecretStore.generate_key())
    await store.put(GITHUB_PAT_SECRET_KEY, _TOKEN)
    return store


def _client(
    handler: Callable[[httpx.Request], httpx.Response], store: SecretStore
) -> PatGitHubClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://api.github.com")
    return PatGitHubClient(store, http_client=http)


async def test_graphql_posts_to_graphql_endpoint() -> None:
    """graphql() POSTs the query+variables to /graphql and returns the JSON body."""
    store = await _store()
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"data": {"repository": {"open": {}}}})

    client = _client(handler, store)
    body = await client.graphql("query {}", {"owner": "o"})
    assert body["data"]["repository"]["open"] == {}
    assert seen["url"] == "https://api.github.com/graphql"
    # The PAT rides the Authorization header for this one call (and is not logged).
    assert seen["auth"] == f"Bearer {_TOKEN}"


async def test_graphql_errors_raise_githuberror() -> None:
    """A GraphQL errors array on a 200 is promoted to GitHubError (no silent empty)."""
    store = await _store()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": None, "errors": [{"message": "NOT_FOUND"}]})

    client = _client(handler, store)
    with pytest.raises(GitHubError, match="NOT_FOUND"):
        await client.graphql("query {}", {})


async def test_create_label_returns_true_on_201() -> None:
    """A newly created label returns True."""
    store = await _store()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/o/r/labels"
        return httpx.Response(201, json={"name": "agent:queued"})

    client = _client(handler, store)
    created = await client.create_label("o/r", name="agent:queued", color="94a3b8")
    assert created is True


async def test_create_label_422_is_idempotent_false() -> None:
    """GitHub's 422 'already_exists' is the idempotent path → returns False (AC-4)."""
    store = await _store()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "Validation Failed"})

    client = _client(handler, store)
    created = await client.create_label("o/r", name="agent:queued", color="94a3b8")
    assert created is False
