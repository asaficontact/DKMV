"""SSE cookie auth — HttpOnly ``SameSite=Strict`` token, never in a URL (INV-2 / §8.3).

Browser ``EventSource`` **cannot set an ``Authorization`` header**, and a token in
the query string would leak into reverse-proxy logs and the platform's
**append-only ``events`` table** — a permanent, replayable secret leak (§8.6). So
the SSE auth token rides an **HttpOnly, ``SameSite=Strict`` cookie**: auto-sent by
``EventSource``, unreadable by JS, and never present in any URL.

This module is the SSE-specific auth layer **on top of** the app-wide
:class:`~app.security.AccessControlMiddleware` (INV-1) — not instead of it. The
middleware already enforces the loopback ``Host`` + ``Origin`` gate and now also
accepts the SSE cookie as a token carrier (:data:`~app.security.access_control.SSE_TOKEN_COOKIE`),
so an ``EventSource`` connection clears the middleware. This layer re-validates the
**cookie token + ``Origin``/``Host``** explicitly at the SSE handler so the
endpoint's auth contract is self-evident and independently tested (AC-9): it 401s
without the cookie, 200s with it, and rejects an ``Origin``/``Host``-mismatched
request.

It also exposes :func:`set_sse_cookie` — the helper the connect/session path uses
to install the HttpOnly ``SameSite=Strict`` cookie (it is here so the cookie's
security attributes are declared in one place).

Nothing here reaches into ``dkmv/``.
"""

from __future__ import annotations

import secrets as _secrets

from fastapi import Request, Response

from app.config import Settings
from app.security.access_control import (
    SSE_TOKEN_COOKIE,
    _is_loopback,
)

#: Cookie max-age (seconds). Matches a long-lived local session; the token is the
#: loopback control-plane token, rotated by re-issuing the cookie.
_COOKIE_MAX_AGE = 7 * 24 * 3600


class SseAuthError(Exception):
    """Raised when an SSE connection fails the cookie / Origin / Host check.

    Carries the HTTP ``status_code`` (401 for a missing/invalid cookie token, 403
    for an ``Origin``/``Host`` mismatch) so the endpoint maps it to the §8.9
    envelope. Never embeds the token value.
    """

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def authenticate_sse(request: Request) -> None:
    """Validate an SSE connection's cookie token + ``Origin``/``Host`` (INV-2).

    The binding checks, in order:

    1. **Host/Origin** (anti-DNS-rebinding, layered on the middleware's gate):
       ``Host`` must be a loopback authority and any ``Origin`` must match → else
       :class:`SseAuthError` 403. The token NEVER rides a URL/query.
    2. **Cookie token** present + constant-time-equal to the configured local
       token → else :class:`SseAuthError` 401. The token is read ONLY from the
       HttpOnly ``SameSite=Strict`` cookie (browser ``EventSource`` cannot set a
       header) — never from the query string.

    Raises :class:`SseAuthError` on failure; returns ``None`` on success.
    """
    settings = _settings(request)

    # 1. Host/Origin (403). Defense-in-depth on top of the middleware so the SSE
    # endpoint's own contract rejects a rebinding/cross-origin probe.
    host = request.headers.get("host", "")
    if not host or not _is_loopback(host):
        raise SseAuthError(403, "forbidden", "Host header is not a permitted loopback authority")
    origin = request.headers.get("origin")
    if origin is not None and not _is_loopback(origin):
        raise SseAuthError(403, "forbidden", "Origin header is not a permitted loopback authority")

    # 2. Cookie token (401). Read ONLY from the HttpOnly SameSite=Strict cookie —
    # NEVER from a query param (a URL token would leak into the events table).
    expected = settings.DKMV_PLATFORM_TOKEN.get_secret_value()
    presented = request.cookies.get(SSE_TOKEN_COOKIE)
    if not expected or not presented or not _secrets.compare_digest(presented, expected):
        raise SseAuthError(401, "unauthorized", "Missing or invalid SSE auth cookie")


def set_sse_cookie(response: Response, token: str, *, secure: bool = False) -> None:
    """Install the HttpOnly ``SameSite=Strict`` SSE auth cookie on ``response``.

    The cookie carries the local control-plane token so a subsequent
    ``EventSource`` connection authenticates without a header (INV-2). Attributes:
    ``httponly=True`` (unreadable by JS — no XSS exfiltration), ``samesite="strict"``
    (never sent cross-site — CSRF defense), ``path="/api/v1"`` (scoped to the API).
    ``secure`` defaults off for loopback ``http://127.0.0.1`` dev; a TLS-terminated
    deployment sets it on.
    """
    response.set_cookie(
        key=SSE_TOKEN_COOKIE,
        value=token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/api/v1",
    )
