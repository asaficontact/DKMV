"""Secret hygiene surface (INV-4 / §8.6): encrypted store, redaction, token mint.

Public surface:

* :class:`SecretStore` — encrypt-at-rest secret storage + **file-mount**
  injection (secrets injected as a read-only file, never an env var, §8.6).
* :class:`GitHubTokenMinter` / :class:`MintedToken` — repo-scoped, ≤1 hr GitHub
  run tokens (a prompt-injected agent cannot push to a second repo).
* :class:`Redactor` / :func:`redact_text` / :func:`redact_value` — the
  redact-before-persist scrubber wired in front of the append-only ``events``
  table and the structured-log pipeline (a leak there is permanent).
"""

from __future__ import annotations

from app.secrets.github_token import (
    GitHubTokenMinter,
    MintedToken,
    TokenExpiredError,
    TokenScopeError,
)
from app.secrets.redaction import (
    REDACTION_PLACEHOLDER,
    RedactingLogFilter,
    Redactor,
    install_log_redaction,
    redact_text,
    redact_value,
)
from app.secrets.store import (
    GITHUB_TOKEN_TTL,
    SECRET_KEY_ENV,
    MountedSecret,
    SecretStore,
    SecretStoreError,
)

__all__ = [
    "GITHUB_TOKEN_TTL",
    "REDACTION_PLACEHOLDER",
    "SECRET_KEY_ENV",
    "GitHubTokenMinter",
    "MintedToken",
    "MountedSecret",
    "RedactingLogFilter",
    "Redactor",
    "SecretStore",
    "SecretStoreError",
    "TokenExpiredError",
    "TokenScopeError",
    "install_log_redaction",
    "redact_text",
    "redact_value",
]
