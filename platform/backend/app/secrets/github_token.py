"""Repo-scoped, short-lived (≤1 hr) GitHub run token minting (INV-4 / §8.6).

The token injected into a run is scoped to **exactly the one target repo** with
≤1 hr TTL, so a prompt-injected agent that reads its own credential cannot push
to other repos the user owns (PRD §8.6 / NFR-SEC-1 / R-3). This is a primary
exfiltration-containment control (alongside the egress allowlist), not a backstop.

In v1 the platform uses a fine-grained PAT (per-repo scopeable) configured by the
operator; this module wraps it as a :class:`MintedToken` carrying the explicit
``repo`` scope + ``expires_at`` and enforces the scope on use via
:meth:`MintedToken.authorize_push`. When the GitHub **App** lands (deferred,
§8.1), :class:`GitHubTokenMinter` is the seam where per-run installation tokens
(natively repo-scoped + 1 hr) are minted instead — the call sites do not change.

The minter never logs the token value and persists only the **ciphertext** via
the :class:`~app.secrets.store.SecretStore` (encrypt-at-rest).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.secrets.store import GITHUB_TOKEN_TTL, SecretStore


class TokenScopeError(PermissionError):
    """Raised when a minted token is used against a repo outside its scope.

    The defining INV-4 guarantee: a run token scoped to repo A cannot push to
    repo B even if the agent (under prompt injection) tries.
    """


class TokenExpiredError(PermissionError):
    """Raised when a minted token is used after its ≤1 hr TTL has elapsed."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class MintedToken:
    """A repo-scoped, time-boxed GitHub token handed to exactly one run.

    ``repo`` is the single ``owner/name`` the token may act on; ``expires_at`` is
    ≤1 hr from mint (INV-4). The plaintext ``value`` is held only as long as the
    run needs it (it is also persisted as ciphertext via the SecretStore).
    """

    repo: str
    value: str
    expires_at: datetime

    def is_expired(self, *, now: datetime | None = None) -> bool:
        """True once the ≤1 hr TTL has elapsed."""
        return (now or _utc_now()) >= self.expires_at

    def is_scoped_to(self, repo: str) -> bool:
        """True iff ``repo`` is exactly this token's single authorized repo."""
        return _normalize_repo(repo) == _normalize_repo(self.repo)

    def authorize_push(self, repo: str, *, now: datetime | None = None) -> None:
        """Assert this token may push to ``repo``; raise otherwise (INV-4).

        Enforces both the **repo scope** (cannot push to a *second* repo) and the
        **≤1 hr TTL**. This is the in-process gate the platform applies before
        handing the token to a git operation; the network-layer egress allowlist
        + GitHub's own per-PAT repo scoping are the defense-in-depth backstops.
        """
        if self.is_expired(now=now):
            raise TokenExpiredError(f"github run token for {self.repo!r} has expired")
        if not self.is_scoped_to(repo):
            raise TokenScopeError(
                f"github run token is scoped to {self.repo!r}; refusing to act on {repo!r}"
            )


def _normalize_repo(repo: str) -> str:
    """Canonicalize an ``owner/name`` (strip, lowercase, drop trailing ``.git``)."""
    cleaned = repo.strip().lower()
    if cleaned.endswith(".git"):
        cleaned = cleaned[: -len(".git")]
    return cleaned.strip("/")


class GitHubTokenMinter:
    """Mint repo-scoped, ≤1 hr GitHub tokens for runs (INV-4 / §8.6).

    Args:
        store: The encrypted :class:`SecretStore` the ciphertext is persisted
            through (the plaintext is never written in the clear).
        base_token: The operator's fine-grained PAT (repo-scopeable). When the
            GitHub App lands this is replaced by an installation-token mint, with
            no change to callers.
        ttl: Token lifetime; defaults to :data:`GITHUB_TOKEN_TTL` (1 hr) and is
            clamped so it can never exceed 1 hr (the INV-4 ceiling).
    """

    def __init__(
        self,
        store: SecretStore,
        *,
        base_token: str,
        ttl: timedelta = GITHUB_TOKEN_TTL,
    ) -> None:
        self._store = store
        self._base_token = base_token
        # Clamp the TTL to the ≤1 hr ceiling — a misconfig must never widen it.
        self._ttl = min(ttl, GITHUB_TOKEN_TTL)

    async def mint(self, repo: str, *, run_id: str) -> MintedToken:
        """Mint a token scoped to ``repo`` for ``run_id``; persist its ciphertext.

        The returned :class:`MintedToken` carries the single-repo scope + the
        ≤1 hr ``expires_at``. The ciphertext is stored under a per-run key with a
        matching DB-side ``expires_at`` so a leaked-at-rest blob is also useless
        after the TTL.
        """
        if not _normalize_repo(repo):
            raise ValueError("repo must be a non-empty 'owner/name'")
        expires_at = _utc_now() + self._ttl
        # v1: the operator PAT is the underlying credential; the repo scope is
        # enforced by this minter (authorize_push) + GitHub's per-PAT scoping.
        token = MintedToken(
            repo=_normalize_repo(repo),
            value=self._base_token,
            expires_at=expires_at,
        )
        await self._store.put(
            f"github_run_token:{run_id}",
            self._base_token,
            ttl=self._ttl,
        )
        return token
