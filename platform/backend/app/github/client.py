"""The ``GitHubClient`` interface + shared GitHub data shapes (PRD §8.1, ADR-P004).

v1 ships a single GitHub backend — a **fine-grained PAT** client
(:class:`~app.github.pat_client.PatGitHubClient`) — but the PRD's load-bearing
commitment (§8.1, ADR-P004) is that the deferred **GitHub App** identity is an
*additive backend behind the SAME interface*, not a rewrite. This module defines
that seam: an abstract :class:`GitHubClient` that the PAT client implements now
and the App client will implement later, with no change to call sites.

The interface is intentionally minimal for slice 1.1 — the surface the Connect
flow needs:

* :meth:`GitHubClient.list_repos` — the repos the credential can see, rendered in
  the §6.1 :class:`Repo` shape for the picker (``GET /repos``).
* :meth:`GitHubClient.check_write_permission` — the **effective-write-permission**
  preflight on the *selected* repo (§8.1, FR-01-6): probe that the token can
  actually write (issues / contents / pull-requests) so a read-only token fails
  fast at connect, not late at PR-creation time.

Later slices (1.2 issue sync, 1.3 the label state machine + write-queue) extend
this same interface with the GraphQL board read and the ``set_agent_state``
mutation primitive — those are out of scope for 1.1 and are *not* declared here
yet, so the interface stays honest about what is implemented.

Auth is never an env read here and never a DB cleartext write: the PAT lives in
the encrypted :class:`~app.secrets.store.SecretStore` (INV-4); the client is
handed the plaintext only for the lifetime of a call and never logs it.

**Poll-only in v1 (ADR-P004 / SECURITY_CHECKS).** This module — and the whole
``app.github`` package in Phase 1 — introduces no inbound GitHub receiver and no
signature/delivery machinery; v1 is PAT-first + poll-only (the App identity and
its push transport are deferred to the scaling phase, §8.1).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


class GitHubError(RuntimeError):
    """A GitHub API call failed (network, auth, or a non-2xx response).

    ``status`` is the HTTP status when the failure came from a response (``None``
    for transport-level errors). The message never carries the token value.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class GitHubAuthError(GitHubError):
    """The credential was rejected (401/403 at the identity layer).

    Distinct from a *permission* shortfall on a specific repo — that is reported
    structurally via :class:`WritePermission`, not raised — so the Connect flow
    can tell "bad/expired token" apart from "read-only token on this repo".
    """


@dataclass(frozen=True, slots=True)
class Repo:
    """A repo in the §6.1 ``Repo`` UI contract (``data.jsx REPOS``).

    Fields mirror the picker's row exactly so ``GET /repos`` is a straight
    serialization: ``{org, name, lang, langColor, private, updated, issues,
    stars?, desc?}`` (PRD §6.1, FR-01-4). ``stars`` and ``desc`` are optional in
    the UI contract; ``stars`` defaults to ``0`` and ``desc`` to ``None``.
    """

    org: str
    name: str
    lang: str
    lang_color: str
    private: bool
    updated: str
    issues: int
    stars: int = 0
    desc: str | None = None

    @property
    def full_name(self) -> str:
        """The canonical ``owner/name`` slug."""
        return f"{self.org}/{self.name}"


@dataclass(frozen=True, slots=True)
class WritePermission:
    """The effective-write-permission probe result for one selected repo (§8.1).

    The preflight is about **effective** write ability, not mere token presence:
    ``can_write`` is ``True`` iff the credential can actually push the writes a
    run needs (issues, contents, pull-requests). When ``False``, ``missing``
    lists the human-readable scopes that fell short so the Connect preflight box
    (FR-01-6) can render a precise blocker rather than a generic failure.
    """

    repo: str
    can_write: bool
    #: GitHub's coarse ``permission`` string for the repo (``admin``/``write``/
    #: ``read``/``none``/…) — surfaced for the preflight row's sub-label.
    role: str
    #: The write capabilities a run requires that this credential lacks, as the
    #: human labels the preflight renders (e.g. ``"issues:write"``).
    missing: tuple[str, ...] = field(default_factory=tuple)


class GitHubClient(abc.ABC):
    """The GitHub backend seam (§8.1, ADR-P004).

    v1 has exactly one implementation, :class:`~app.github.pat_client.PatGitHubClient`
    (fine-grained PAT). The deferred GitHub App identity slots in as a second
    implementation of *this* interface — per-install short-lived tokens behind
    the same method surface — so call sites (``GET /repos``, the preflight, and
    later the board read + ``set_agent_state``) never branch on the auth backend.
    """

    @abc.abstractmethod
    async def list_repos(self) -> list[Repo]:
        """Return the repos the credential can access, in the §6.1 ``Repo`` shape.

        Drives the Connect picker (``GET /repos``, FR-01-4). Raises
        :class:`GitHubAuthError` if the credential itself is rejected.
        """

    @abc.abstractmethod
    async def check_write_permission(self, repo: str) -> WritePermission:
        """Probe **effective** write permission on ``repo`` (§8.1, FR-01-6).

        Returns a :class:`WritePermission` whose ``can_write`` is ``False`` (with
        the missing scopes populated) for a read-only token, so the Connect flow
        blocks at connect rather than failing late at PR-creation time. A rejected
        credential raises :class:`GitHubAuthError`; a missing repo raises
        :class:`GitHubError` with ``status=404``.
        """

    async def aclose(self) -> None:
        """Release any underlying transport resources. No-op by default."""
        return None
