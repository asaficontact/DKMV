"""Slice 1.3 — the PAT client's ``replace_labels`` primitive (§8.1, INV-11, AC-7).

The single GitHub mutation behind ``set_agent_state``: ``PUT .../issues/{n}/labels``
replace-all. Mocks GitHub with an :class:`httpx.MockTransport` and asserts:

* the request is a **PUT** to the **labels** path with the full label set as body
  (replace-all — never a single-label PATCH endpoint);
* a **403 + ``Retry-After``** (the content-creation **secondary** limit) is raised
  as :class:`SecondaryRateLimitError` carrying the interval, so the write-queue
  honors it rather than a caller blindly retrying (AC-7);
* the latest ``X-RateLimit-*`` headers fold into the injected accounting (FR-06-2);
* an ordinary 403 (no secondary signal) is an auth error, not a secondary one.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from app.github.client import GitHubAuthError
from app.github.pat_client import GITHUB_PAT_SECRET_KEY, PatGitHubClient
from app.github.write_queue import RateLimitState, SecondaryRateLimitError
from app.secrets.store import SecretStore

_TOKEN = "github_pat_11ABCDEFG0_notReal"  # noqa: S105 - fixture


async def _store() -> SecretStore:
    store = SecretStore(key=SecretStore.generate_key())
    await store.put(GITHUB_PAT_SECRET_KEY, _TOKEN)
    return store


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
    store: SecretStore,
    *,
    rate_state: RateLimitState | None = None,
) -> PatGitHubClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://api.github.com")
    return PatGitHubClient(store, http_client=http, rate_limit_state=rate_state)


async def test_replace_labels_is_a_put_to_labels_path() -> None:
    """The primitive is PUT .../issues/{n}/labels with the full label set (INV-11)."""
    store = await _store()
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=[{"name": "bug"}, {"name": "agent:queued"}])

    client = _client(handler, store)
    result = await client.replace_labels("o/r", 7, ["bug", "agent:queued"])

    assert seen["method"] == "PUT"  # replace-all, NOT PATCH
    assert "/repos/o/r/issues/7/labels" in str(seen["url"])
    assert seen["body"] == {"labels": ["bug", "agent:queued"]}
    assert result == ["bug", "agent:queued"]


async def test_replace_labels_secondary_limit_raises_with_retry_after() -> None:
    """A 403 + Retry-After is raised as SecondaryRateLimitError(retry_after) (AC-7)."""
    store = await _store()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"Retry-After": "12", "X-RateLimit-Remaining": "4900"},
            json={"message": "You have exceeded a secondary rate limit"},
        )

    client = _client(handler, store)
    with pytest.raises(SecondaryRateLimitError) as exc_info:
        await client.replace_labels("o/r", 7, ["agent:queued"])
    assert exc_info.value.retry_after == 12.0


async def test_replace_labels_records_rate_limit_headers() -> None:
    """X-RateLimit-* headers fold into the injected accounting (FR-06-2)."""
    store = await _store()
    state = RateLimitState()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"X-RateLimit-Remaining": "4999", "X-RateLimit-Limit": "5000"},
            json=[{"name": "agent:queued"}],
        )

    client = _client(handler, store, rate_state=state)
    await client.replace_labels("o/r", 7, ["agent:queued"])
    assert state.primary_remaining == 4999
    assert state.primary_limit == 5000


async def test_replace_labels_plain_403_is_auth_error() -> None:
    """A 403 with no secondary signal is an identity/permission error, not secondary."""
    store = await _store()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"message": "Resource not accessible by personal access token"}
        )

    client = _client(handler, store)
    with pytest.raises(GitHubAuthError):
        await client.replace_labels("o/r", 7, ["agent:queued"])
