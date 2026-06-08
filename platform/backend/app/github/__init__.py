"""GitHub control plane (PRD §8.1, ADR-P004). Lands in Phase 1.

Slice 1.1 ships the auth + read seam:

* :class:`GitHubClient` — the backend interface (the deferred GitHub App slots
  behind it, ADR-P004);
* :class:`PatGitHubClient` — the v1 fine-grained-PAT implementation (token read
  from the encrypted :class:`~app.secrets.store.SecretStore`, INV-4);
* :class:`Repo` / :class:`WritePermission` — the §6.1 picker shape + the
  effective-write-permission preflight result.

Later slices add the GraphQL board read (1.2) and the ``set_agent_state`` label
state machine + write-queue (1.3). **No inbound GitHub receiver exists here** —
v1 is PAT-first + poll-only (ADR-P004).
"""

from __future__ import annotations

from app.github.client import (
    GitHubAuthError,
    GitHubClient,
    GitHubError,
    Repo,
    WritePermission,
)
from app.github.pat_client import (
    GITHUB_API_BASE,
    GITHUB_PAT_SECRET_KEY,
    REQUIRED_WRITE_SCOPES,
    PatGitHubClient,
)
from app.github.provider import get_github_client, get_secret_store, set_github_client
from app.github.state_machine import (
    SetAgentStateResult,
    TransitionPlan,
    closed_transition,
    compute_desired_labels,
    failed_run_demotion,
    merged_pr_transition,
    reopened_transition,
    set_agent_state,
)
from app.github.write_queue import (
    RateLimitState,
    SecondaryRateLimitError,
    WriteQueue,
)

__all__ = [
    "GITHUB_API_BASE",
    "GITHUB_PAT_SECRET_KEY",
    "REQUIRED_WRITE_SCOPES",
    "GitHubAuthError",
    "GitHubClient",
    "GitHubError",
    "PatGitHubClient",
    "RateLimitState",
    "Repo",
    "SecondaryRateLimitError",
    "SetAgentStateResult",
    "TransitionPlan",
    "WritePermission",
    "WriteQueue",
    "closed_transition",
    "compute_desired_labels",
    "failed_run_demotion",
    "get_github_client",
    "get_secret_store",
    "merged_pr_transition",
    "reopened_transition",
    "set_agent_state",
    "set_github_client",
]
