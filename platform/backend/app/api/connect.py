"""``POST /api/v1/connect/github`` — store the fine-grained GitHub PAT (FR-01-3).

Screen 01's **Connect** step posts the operator's fine-grained Personal Access
Token (the four-permission, single-repo token from §8.1). This module is the
single place that token is accepted and persisted, and it upholds two invariants:

* **INV-1 (access control).** The route is a state-changing ``POST`` behind the
  app-wide :class:`~app.security.AccessControlMiddleware` — loopback ``Host`` +
  local token + ``Origin``/CSRF — exactly like every other Phase-1 endpoint. It
  declares **no** auth opt-out, so a foreign ``Host`` is rejected (403) and a
  missing local token is rejected (401) before any handler runs (AC-14).
* **INV-4 (secret hygiene).** The PAT is written **only** to the encrypted
  :class:`~app.secrets.SecretStore` (Fernet at-rest), never echoed in a
  response, never logged, and never returned. The request model is a
  :class:`pydantic.SecretStr` so the value cannot accidentally serialize, and
  the response carries only a redacted *hint* (``github_pat_••••1234`` /
  ``ghp_••••1234``) — never the token.

**Scope boundary (slice 1.4).** The `GitHubClient`, ``GET /repos`` and the
effective-write-permission preflight live in slice 1.1 (``app/github/*`` /
``app/api/repos.py``) and are *not* implemented here. This endpoint validates the
PAT's **shape** (fine-grained ``github_pat_`` or classic ``ghp_``) and stores it;
the live token→GitHub validation + repo-scope/write-permission probe is 1.1's
``GET /preflight`` concern (AC-2). A malformed token is rejected at 400 with the
§8.9 envelope so the UI can surface a clear error before the picker.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, SecretStr

from app.api.errors import validation_error
from app.secrets import SecretStore

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.config import Settings

# No prefix here: the ``/api/v1`` version prefix is owned by the single parent
# router in :mod:`app.api`, which this router attaches to.
router = APIRouter(tags=["connect"])

#: SecretStore key the GitHub PAT is persisted under. The PAT is the user's
#: own onboarding token (not the per-run minted token); it lives under a stable
#: key so 1.1's GitHubClient can read it back from the same encrypted store.
GITHUB_PAT_KEY = "github_pat"

#: Recognized fine-grained / classic PAT prefixes. v1 onboarding (§8.1) asks for
#: a *fine-grained* PAT (``github_pat_``); the classic ``ghp_`` prefix is also
#: accepted so an existing classic token is not rejected outright (the live
#: scope/write-permission gate is 1.1's preflight, not this shape check).
_PAT_PREFIXES: tuple[str, ...] = ("github_pat_", "ghp_")

#: The four permissions the onboarding screen asks the operator to grant on the
#: single selected repo (§8.1). Surfaced here so the contract is asserted in one
#: place (the UI lists the same four — AC-10).
REQUIRED_PAT_PERMISSIONS: tuple[str, ...] = (
    "issues:write",
    "pull_requests:write",
    "contents:write",
    "metadata:read",
)


class ConnectGitHubRequest(BaseModel):
    """Body for ``POST /connect/github``: the fine-grained PAT.

    ``token`` is a :class:`~pydantic.SecretStr` so the value never prints in a
    repr / log / validation error (INV-4). ``min_length`` rejects an empty
    submission at the §8.10 validation layer.
    """

    token: SecretStr = Field(
        ...,
        description="Fine-grained GitHub PAT (github_pat_…) scoped to the one repo.",
    )


class ConnectGitHubResponse(BaseModel):
    """Response for a successful connect — carries **no** token value (INV-4).

    Only a non-reversible redacted *hint* of the stored token is returned so the
    UI can show "connected as github_pat_••••1234" without ever handling the
    secret. ``permissions`` echoes the four required scopes for the picker's
    "What we'll do" / preflight copy.
    """

    connected: bool
    token_hint: str
    permissions: list[str]


def _redacted_hint(token: str) -> str:
    """Return a non-reversible hint: the PAT prefix + ``••••`` + last 4 chars.

    Never the token. For a token shorter than its prefix + 4 we emit only the
    prefix + ``••••`` so we never echo a meaningful fraction of a short secret.
    """
    prefix = next((p for p in _PAT_PREFIXES if token.startswith(p)), "")
    tail = token[-4:] if len(token) >= len(prefix) + 4 else ""
    return f"{prefix}••••{tail}"


def _validate_pat_shape(token: str) -> None:
    """Reject an empty / non-PAT-shaped token at 400 (§8.9 envelope).

    Shape-only: the live token→GitHub validation + repo-scope/write-permission
    probe is slice 1.1's ``GET /preflight`` (AC-2). We only ensure the operator
    pasted a plausible fine-grained/classic PAT, not a stray string, so the UI
    can correct an obvious paste error before the picker.
    """
    stripped = token.strip()
    if not stripped:
        raise validation_error("GitHub token must not be empty")
    if not stripped.startswith(_PAT_PREFIXES):
        raise validation_error(
            "Token does not look like a fine-grained GitHub PAT (expected a github_pat_… prefix)",
            details={"expected_prefixes": list(_PAT_PREFIXES)},
        )


def _get_secret_store(request: Request) -> SecretStore:
    """Return the single lifespan-owned :class:`SecretStore` from ``app.state``.

    The app-lifespan (slice 2.0) composes exactly ONE :class:`SecretStore` on
    ``app.state.secret_store`` at startup (real host key, persisted through the
    shared :class:`Repository` — INV-4), so this handler **reuses** it rather than
    building an ephemeral per-request store. As a *test fallback only* (a
    :class:`~fastapi.testclient.TestClient` that did not enter the lifespan), it
    builds an in-memory store from the env/dev key once and caches it on
    ``app.state`` — the store always encrypts at rest (INV-4); only the
    persistence backend (DB vs. in-memory) varies.
    """
    existing: SecretStore | None = getattr(request.app.state, "secret_store", None)
    if existing is not None:
        return existing
    # Test-only fallback: no lifespan ran, so build a store on the dev key once.
    settings: Settings = request.app.state.settings
    repository = getattr(request.app.state, "repository", None)
    store = SecretStore(repository, key=_resolve_secret_key(settings))
    request.app.state.secret_store = store
    return store


def _resolve_secret_key(settings: Settings) -> str:
    """Resolve the Fernet host key for the test-fallback store (env key, else dev key).

    In prod the lifespan-owned store is used and this is never reached; only the
    no-lifespan test fallback resolves a key here. ``DKMV_SECRET_KEY`` (prod: OS
    keychain / sealed secret, §8.6) wins; otherwise a generated dev key is cached
    on ``settings`` so encryption is never silently disabled (INV-4).
    """
    import os

    env_key = os.environ.get("DKMV_SECRET_KEY")
    if env_key:
        return env_key
    # Cache a generated dev key on settings so the same process reuses it (a new
    # key per call would make stored ciphertext undecryptable on read-back).
    cached: str | None = getattr(settings, "_dkmv_dev_secret_key", None)
    if cached is None:
        cached = SecretStore.generate_key()
        object.__setattr__(settings, "_dkmv_dev_secret_key", cached)
    return cached


@router.post("/connect/github", response_model=ConnectGitHubResponse)
async def connect_github(body: ConnectGitHubRequest, request: Request) -> ConnectGitHubResponse:
    """Accept + persist the fine-grained GitHub PAT (FR-01-3, AC-10/AC-14).

    The PAT (a ``SecretStr``) is shape-validated then encrypted into the
    :class:`SecretStore` under :data:`GITHUB_PAT_KEY`. The response contains only
    a redacted hint and the four required permissions — never the token (INV-4).
    On success the UI advances ``connecting → picker``.
    """
    token = body.token.get_secret_value()
    _validate_pat_shape(token)

    store = _get_secret_store(request)
    await store.put(GITHUB_PAT_KEY, token)

    return ConnectGitHubResponse(
        connected=True,
        token_hint=_redacted_hint(token),
        permissions=list(REQUIRED_PAT_PERMISSIONS),
    )
