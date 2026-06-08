"""INV-1 regressions at the raw ASGI/middleware level.

These drive :class:`AccessControlMiddleware` directly with an *unnormalized*
``scope["path"]`` — which an HTTP client (httpx/``TestClient``) would collapse
before it ever reaches the server, but a real ASGI server does **not**. They
pin the two security defects the polish pass closed:

* **SECURITY-MAJOR** — the token exemption matched whole path *subtrees*
  (``path.startswith(p + "/")``), so an unauthenticated request to
  ``/api/v1/healthz/../secret`` or ``/api/v1/healthz/extra`` reached the inner
  app. The exemption now matches the **exact** liveness path only, so those are
  rejected (401) while the exact liveness path stays exempt.
* **SECURITY-MINOR** — the exemption short-circuited *before* the Host check, so
  a foreign-Host request to a token-exempt/docs route reached the inner app, and
  the docs surface (``/openapi.json``) was served unauthenticated. The Host gate
  now applies to **every** route (foreign Host → 403), and the docs surface is
  token-gated by default (→ 401 without a token).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.security.access_control import AccessControlMiddleware

from tests.conftest import TEST_TOKEN, make_settings


def _drive(
    path: str,
    *,
    method: str = "GET",
    host: str = "127.0.0.1",
    headers: dict[str, str] | None = None,
    expose_docs: bool = False,
) -> tuple[int | None, bool]:
    """Run the middleware over a raw ASGI ``scope`` with an unnormalized path.

    Returns ``(status_code, inner_reached)``.
    """
    import asyncio

    settings = make_settings(DKMV_EXPOSE_DOCS_UNAUTHENTICATED=expose_docs)
    reached = {"inner": False}

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        reached["inner"] = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"INNER"})

    mw = AccessControlMiddleware(inner, settings)

    raw_headers: list[tuple[bytes, bytes]] = [(b"host", host.encode())]
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode(), value.encode()))

    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
        "path": path,  # intentionally NOT url-normalized
        "raw_path": path.encode(),
        "headers": raw_headers,
        "query_string": b"",
    }
    status: dict[str, int | None] = {"code": None}

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            status["code"] = message["status"]

    asyncio.run(mw(scope, receive, send))
    return status["code"], reached["inner"]


def _bearer() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


# ── SECURITY-MAJOR: exact-liveness exemption, no subtree prefix match ─────────


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/healthz/../secret",
        "/api/v1/healthz/extra",
        "/api/v1/healthz/",  # trailing slash is NOT the exact liveness path
        "/api/v1/healthzextra",  # adjacent path, must not be a prefix hit
    ],
)
def test_healthz_subtree_is_not_token_exempt(path: str) -> None:
    status, inner_reached = _drive(path)
    assert status == 401
    assert inner_reached is False


def test_exact_liveness_path_stays_token_exempt() -> None:
    status, inner_reached = _drive("/api/v1/healthz")
    assert status == 200
    assert inner_reached is True


def test_gated_path_without_token_rejected_401() -> None:
    status, inner_reached = _drive("/api/v1/preflight")
    assert status == 401
    assert inner_reached is False


# ── SECURITY-MINOR: Host gate applies to every route incl. exempt/docs ────────


def test_foreign_host_rejected_even_on_exact_liveness() -> None:
    # Token exemption must NOT waive the Host/Origin gate.
    status, inner_reached = _drive("/api/v1/healthz", host="attacker.example.com")
    assert status == 403
    assert inner_reached is False


@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
def test_foreign_host_rejected_on_docs_routes(path: str) -> None:
    status, inner_reached = _drive(path, host="attacker.example.com")
    assert status == 403
    assert inner_reached is False


@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
def test_docs_token_gated_by_default(path: str) -> None:
    # Unauthenticated, loopback: docs surface requires the token by default.
    status, inner_reached = _drive(path)
    assert status == 401
    assert inner_reached is False


@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
def test_docs_reachable_with_token(path: str) -> None:
    status, inner_reached = _drive(path, headers=_bearer())
    assert status == 200
    assert inner_reached is True


# ── Dev-only opt-in: waives ONLY the token check, never the Host gate ─────────


@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
def test_docs_unauthenticated_when_opted_in(path: str) -> None:
    status, inner_reached = _drive(path, expose_docs=True)
    assert status == 200
    assert inner_reached is True


@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
def test_docs_opt_in_still_enforces_host_gate(path: str) -> None:
    # Even with the dev opt-in ON, a foreign Host is rejected (token waiver only).
    status, inner_reached = _drive(path, host="attacker.example.com", expose_docs=True)
    assert status == 403
    assert inner_reached is False
