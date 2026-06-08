"""App access-control middleware (INV-1 / PRD NFR-SEC-2, §8.8).

The DKMV platform is a **control plane** that reaches the host Docker socket
(root-equivalent) and launches money-spending agent runs, so it MUST NOT be
openly reachable. Loopback alone is *not* sufficient — NFR-SEC-2 requires
**loopback bind + local token + Host/Origin validation + CSRF on state-changing
POSTs**, and this middleware enforces all four layers in front of the API:

1. **Loopback bind.** The server binds ``127.0.0.1`` (``DKMV_PLATFORM_BIND``);
   the host the server *answers on* is fixed at startup. This middleware adds
   the defense-in-depth check that the request's ``Host`` header is in the
   allowed loopback set — this is the anti-DNS-rebinding guard (a malicious
   page that resolves an attacker domain to ``127.0.0.1`` still sends a foreign
   ``Host``/``Origin`` and is rejected).
2. **Local token.** Every API request must present the
   ``DKMV_PLATFORM_TOKEN`` (``Authorization: Bearer <token>`` or the
   ``X-DKMV-Token`` header), compared in constant time. Missing/invalid → 401.
3. **Host/Origin validation.** ``Host`` must be a loopback authority; if an
   ``Origin``/``Referer`` is present it must also be loopback. Foreign → 403.
4. **CSRF on state-changing methods.** ``POST``/``PUT``/``PATCH``/``DELETE``
   require a non-form content type *and* either a matching ``Origin`` (already
   checked) or an explicit double-submit CSRF token header. The bearer-token
   requirement already blocks classic CSRF (a cross-site form can't read or set
   the ``Authorization`` header), but we additionally reject browser
   form-encoded submissions outright as defense-in-depth.

Token-exempt path (and *only* the token check is ever waived): the
unauthenticated liveness probe at the **exact** path ``/api/v1/healthz``, so a
``docker compose`` health check can confirm the process is up before the token
is configured. The match is **exact** — there is no subtree prefix matching, so
``/api/v1/healthz/../secret`` or ``/api/v1/healthz/anything`` is *not* exempt and
still requires the token (a prefix match here would expose the whole API subtree
to unauthenticated callers — INV-1).

Crucially, the Host/Origin/CSRF gate (the anti-DNS-rebinding defense) is applied
to **every** request, including the liveness probe. Token exemption never waives
the Host/Origin check — only the token check — so a foreign ``Host`` is rejected
(403) even on an otherwise token-exempt route.

The framework's interactive docs (``/openapi.json``, ``/docs``, ``/redoc``)
expose the full API surface and are therefore **not** token-exempt by default:
they are gated like every other route. An operator who explicitly opts in via
``DKMV_EXPOSE_DOCS_UNAUTHENTICATED`` (default OFF) can waive *only* the token
check for those paths in local development; the Host/Origin gate still applies.

The error bodies are the §8.9 envelope (via :mod:`app.api.errors`). No secret
value is ever logged or returned.
"""

from __future__ import annotations

import secrets as _secrets
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.errors import forbidden, unauthorized
from app.config import Settings

# Hosts the control plane is allowed to answer on. Bind is loopback-only
# (DKMV_PLATFORM_BIND default 127.0.0.1:8787), so only loopback authorities are
# legitimate. ``localhost`` resolves to loopback and is allowed; everything else
# (including a rebound attacker domain) is rejected.
_LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})

# State-changing methods that require CSRF defense.
_UNSAFE_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Browser-driven form content types a cross-site form *can* send without a
# preflight; we reject these on state-changing methods (the API is JSON-only).
_FORM_CONTENT_TYPES: tuple[str, ...] = (
    "application/x-www-form-urlencoded",
    "multipart/form-data",
    "text/plain",
)

# The **exact** liveness path whose token check is waived (no subtree match).
_LIVENESS_PATH: str = "/api/v1/healthz"

# Framework docs paths. Token-exempt only when the operator explicitly opts in
# via ``DKMV_EXPOSE_DOCS_UNAUTHENTICATED`` (default OFF); the Host/Origin gate
# still applies even then. Matched exactly — never as a subtree prefix.
_DOCS_PATHS: frozenset[str] = frozenset({"/openapi.json", "/docs", "/redoc"})


def _authority_host(value: str) -> str:
    """Return the bare host of an authority/URL, lowercased, port stripped.

    Accepts a ``Host`` header (``host:port``), or an ``Origin``/``Referer`` URL
    (``scheme://host:port/...``). IPv6 brackets are stripped.
    """
    value = value.strip()
    if "://" in value:
        value = urlsplit(value).netloc
    # Strip userinfo if present.
    if "@" in value:
        value = value.rsplit("@", 1)[1]
    # IPv6 literal: ``[::1]:8787`` → ``::1``.
    if value.startswith("["):
        return value[1 : value.find("]")].lower()
    # host:port → host (rpartition tolerates hostless ``:port``).
    host = value.rsplit(":", 1)[0] if ":" in value else value
    return host.lower()


def _is_loopback(authority: str) -> bool:
    """True iff the authority's host is a loopback host."""
    return _authority_host(authority) in _LOOPBACK_HOSTS


def _is_token_exempt(path: str, *, expose_docs: bool) -> bool:
    """True iff *only the token check* is waived for this **exact** path.

    Matching is exact — never a subtree prefix — so the liveness exemption can
    never be widened into ``/api/v1/healthz/<anything>`` and expose the API to
    unauthenticated callers (INV-1). The Host/Origin/CSRF gate is applied
    separately and is *never* waived here.
    """
    if path == _LIVENESS_PATH:
        return True
    return expose_docs and path in _DOCS_PATHS


def _extract_token(request: Request) -> str | None:
    """Pull the presented token from ``Authorization`` or ``X-DKMV-Token``."""
    auth = request.headers.get("authorization")
    if auth:
        scheme, _, value = auth.partition(" ")
        if scheme.lower() == "bearer" and value:
            return value.strip()
    header_token = request.headers.get("x-dkmv-token")
    if header_token:
        return header_token.strip()
    return None


class AccessControlMiddleware:
    """ASGI middleware enforcing the NFR-SEC-2 access-control stack (INV-1)."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self._app = app
        self._settings = settings
        self._token = settings.DKMV_PLATFORM_TOKEN.get_secret_value()
        # Dev-only opt-in (default OFF): waive *only* the token check for the
        # framework docs paths. The Host/Origin gate still applies.
        self._expose_docs = settings.DKMV_EXPOSE_DOCS_UNAUTHENTICATED

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        error = self._check(request)
        if error is not None:
            await error(scope, receive, send)
            return
        await self._app(scope, receive, send)

    def _check(self, request: Request) -> JSONResponse | None:
        """Run the access-control checks; return an error response or ``None``.

        The Host/Origin/CSRF gate (403, anti-DNS-rebinding) runs **first and on
        every request** — including token-exempt routes — so a rebinding probe is
        rejected before anything else and exemption can never waive it. Only the
        **token** check (401) is skipped for the exact token-exempt paths.
        """
        path = request.url.path

        # 1+3. Host/Origin validation (anti-DNS-rebinding) → 403. Applies to
        # EVERY request, including exempt routes (exemption never waives this).
        host = request.headers.get("host", "")
        if not host or not _is_loopback(host):
            return forbidden("Host header is not a permitted loopback authority").to_response()

        origin = request.headers.get("origin")
        if origin is not None and not _is_loopback(origin):
            return forbidden("Origin header is not a permitted loopback authority").to_response()

        referer = request.headers.get("referer")
        if referer is not None and not _is_loopback(referer):
            return forbidden("Referer header is not a permitted loopback authority").to_response()

        # 4. CSRF on state-changing methods → 403. The API is JSON-only; a
        # cross-site HTML form can only send the form content types below, so we
        # reject them on unsafe methods (the bearer-token requirement is the
        # primary CSRF defense — a cross-site form cannot set Authorization).
        if request.method.upper() in _UNSAFE_METHODS:
            content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type in _FORM_CONTENT_TYPES:
                return forbidden(
                    "Form-encoded state-changing requests are rejected (CSRF)"
                ).to_response()

        # 2. Local token (constant-time) → 401. Waived *only* for the exact
        # token-exempt paths (the liveness probe always; docs only when the
        # dev-only opt-in is on). The Host/Origin gate above already ran.
        if _is_token_exempt(path, expose_docs=self._expose_docs):
            return None

        presented = _extract_token(request)
        if (
            not self._token
            or presented is None
            or not _secrets.compare_digest(presented, self._token)
        ):
            return unauthorized().to_response()

        return None
