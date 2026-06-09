"""Slice 2.3 — SSE cookie auth unit tests (INV-2 / AC-9).

Drives :func:`app.sse.auth.authenticate_sse` + :func:`app.sse.auth.set_sse_cookie`
directly over a synthetic Starlette request so the cookie/Origin/Host contract is
verified without a live stream:

* missing cookie → 401; valid cookie → pass; ``Origin``/``Host`` mismatch → 403;
* a token in the **query string** is NOT accepted (the token rides the cookie only —
  a URL token would leak into the ``events`` table);
* ``set_sse_cookie`` installs an HttpOnly ``SameSite=Strict`` cookie.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.config import Settings
from app.security.access_control import SSE_TOKEN_COOKIE
from app.sse.auth import SseAuthError, authenticate_sse, set_sse_cookie
from fastapi import Response
from starlette.requests import Request

_TOKEN = "sse-test-token"  # noqa: S105 - test token, not a real secret


def _settings() -> Settings:
    return Settings(_env_file=None, DKMV_PLATFORM_TOKEN=_TOKEN)  # type: ignore[call-arg]  # DKMVP-ESCAPE: pydantic-settings kwargs


def _request(
    *, cookie: str | None, host: str = "127.0.0.1", origin: str | None = None, query: str = ""
) -> Request:
    headers: list[tuple[bytes, bytes]] = [(b"host", host.encode())]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if cookie is not None:
        headers.append((b"cookie", f"{SSE_TOKEN_COOKIE}={cookie}".encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/runs/r1/events",
        "query_string": query.encode(),
        "headers": headers,
        "app": SimpleNamespace(state=SimpleNamespace(settings=_settings())),
    }
    return Request(scope)


def test_missing_cookie_401() -> None:
    with pytest.raises(SseAuthError) as exc:
        authenticate_sse(_request(cookie=None))
    assert exc.value.status_code == 401


def test_valid_cookie_passes() -> None:
    authenticate_sse(_request(cookie=_TOKEN))  # no raise


def test_wrong_cookie_401() -> None:
    with pytest.raises(SseAuthError) as exc:
        authenticate_sse(_request(cookie="nope"))
    assert exc.value.status_code == 401


def test_foreign_host_403() -> None:
    with pytest.raises(SseAuthError) as exc:
        authenticate_sse(_request(cookie=_TOKEN, host="evil.example.com"))
    assert exc.value.status_code == 403


def test_foreign_origin_403() -> None:
    with pytest.raises(SseAuthError) as exc:
        authenticate_sse(_request(cookie=_TOKEN, origin="http://evil.example.com"))
    assert exc.value.status_code == 403


def test_query_string_token_not_accepted() -> None:
    """A ?token=... in the URL is NOT auth — the token rides the cookie only (INV-2)."""
    with pytest.raises(SseAuthError) as exc:
        authenticate_sse(_request(cookie=None, query=f"token={_TOKEN}"))
    assert exc.value.status_code == 401


def test_set_sse_cookie_is_httponly_strict() -> None:
    resp = Response()
    set_sse_cookie(resp, _TOKEN)
    set_cookie = resp.headers["set-cookie"]
    assert f"{SSE_TOKEN_COOKIE}={_TOKEN}" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie.lower() or "samesite=strict" in set_cookie.lower()
