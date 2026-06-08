"""Repo-scoped, ≤1 hr GitHub run token (INV-4 / AC-0.5-3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.secrets.github_token import (
    GitHubTokenMinter,
    MintedToken,
    TokenExpiredError,
    TokenScopeError,
)
from app.secrets.store import GITHUB_TOKEN_TTL, SecretStore


def _minter(ttl: timedelta = GITHUB_TOKEN_TTL) -> GitHubTokenMinter:
    store = SecretStore(key=SecretStore.generate_key())
    return GitHubTokenMinter(store, base_token="ghp-operator-pat", ttl=ttl)


async def test_minted_token_is_repo_scoped_and_short_lived() -> None:
    minter = _minter()
    token = await minter.mint("octo/repo-a", run_id="run-1")
    assert token.repo == "octo/repo-a"
    # ≤ 1 hr TTL (INV-4).
    assert token.expires_at - datetime.now(UTC) <= GITHUB_TOKEN_TTL + timedelta(seconds=2)
    assert not token.is_expired()


async def test_token_cannot_push_to_second_repo() -> None:
    minter = _minter()
    token = await minter.mint("octo/repo-a", run_id="run-1")
    # Authorized for its own repo.
    token.authorize_push("octo/repo-a")
    # A prompt-injected agent trying repo B is refused (the core INV-4 guarantee).
    with pytest.raises(TokenScopeError):
        token.authorize_push("octo/repo-b")


async def test_expired_token_is_refused() -> None:
    minter = _minter(ttl=timedelta(seconds=1))
    token = await minter.mint("octo/repo-a", run_id="run-1")
    future = datetime.now(UTC) + timedelta(hours=2)
    assert token.is_expired(now=future)
    with pytest.raises(TokenExpiredError):
        token.authorize_push("octo/repo-a", now=future)


async def test_ttl_is_clamped_to_one_hour() -> None:
    # A misconfigured wider TTL must be clamped to the ≤1 hr ceiling.
    minter = _minter(ttl=timedelta(hours=24))
    token = await minter.mint("octo/repo-a", run_id="run-1")
    assert token.expires_at - datetime.now(UTC) <= GITHUB_TOKEN_TTL + timedelta(seconds=2)


def test_repo_normalization_matches_git_suffix() -> None:
    token = MintedToken(
        repo="octo/repo-a",
        value="x",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert token.is_scoped_to("Octo/Repo-A")
    assert token.is_scoped_to("octo/repo-a.git")
    assert not token.is_scoped_to("octo/repo-b")


async def test_empty_repo_rejected() -> None:
    minter = _minter()
    with pytest.raises(ValueError):
        await minter.mint("   ", run_id="run-1")
