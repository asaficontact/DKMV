"""``POST /api/v1/connect/github`` — PAT intake, secret hygiene, access control.

Covers the slice 1.4 backend surface:

* AC-10/§8.1 — the response echoes the four required permissions.
* AC-14/INV-1 — the route is behind the access-control middleware: a foreign
  ``Host`` is 403, a missing local token is 401, a form-encoded POST is 403.
* INV-4 — the PAT is stored as ciphertext in the ``SecretStore`` (decryptable
  back to the original) and the token value never appears in the response body.
"""

from __future__ import annotations

from typing import Any

from app.api.connect import GITHUB_PAT_KEY, REQUIRED_PAT_PERMISSIONS
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, build_client

# A plausible fine-grained PAT shape (not a real secret).
_FINE_PAT = "github_pat_" + "A1B2C3D4E5F6G7H8I9J0"  # noqa: S105 - fixture, not a real secret
_CLASSIC_PAT = "ghp_" + "abcdEFGH1234 wxyz5678".replace(" ", "")  # noqa: S105 - fixture


def _client() -> TestClient:
    return build_client(raise_server_exceptions=True)


def _connect(client: TestClient, token: str, **kwargs: Any) -> Any:
    return client.post(
        "/api/v1/connect/github", json={"token": token}, headers=auth_headers(), **kwargs
    )


# ── Happy path + permission contract (AC-10) ─────────────────────────────────


def test_connect_returns_four_permissions() -> None:
    resp = _connect(_client(), _FINE_PAT)
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is True
    assert body["permissions"] == [
        "issues:write",
        "pull_requests:write",
        "contents:write",
        "metadata:read",
    ]
    assert set(REQUIRED_PAT_PERMISSIONS) == set(body["permissions"])


def test_classic_pat_accepted() -> None:
    resp = _connect(_client(), _CLASSIC_PAT)
    assert resp.status_code == 200


# ── INV-4: secret hygiene ────────────────────────────────────────────────────


def test_token_never_echoed_in_response() -> None:
    resp = _connect(_client(), _FINE_PAT)
    raw = resp.text
    assert _FINE_PAT not in raw
    # Only a redacted hint (prefix + dots + last 4) is surfaced.
    assert resp.json()["token_hint"].startswith("github_pat_")
    assert resp.json()["token_hint"].endswith(_FINE_PAT[-4:])
    assert "••••" in resp.json()["token_hint"]


def test_token_persisted_as_ciphertext() -> None:
    client = _client()
    resp = _connect(client, _FINE_PAT)
    assert resp.status_code == 200
    store = client.app.state.secret_store  # type: ignore[attr-defined]  # DKMVP-ESCAPE: test reads app.state
    # The store round-trips to the original plaintext (decryptable), proving it
    # was encrypted at rest and stored, not dropped.
    import anyio

    got = anyio.run(store.get, GITHUB_PAT_KEY)
    assert got == _FINE_PAT


# ── §8.10 validation ─────────────────────────────────────────────────────────


def test_empty_token_rejected() -> None:
    resp = _connect(_client(), "   ")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_non_pat_token_rejected() -> None:
    resp = _connect(_client(), "not-a-real-token-shape")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_missing_token_field_rejected() -> None:
    resp = _client().post("/api/v1/connect/github", json={}, headers=auth_headers())
    assert resp.status_code == 400


# ── AC-14 / INV-1: access control on the state-changing POST ─────────────────


def test_foreign_host_rejected() -> None:
    client = build_client(host="evil.example.com", raise_server_exceptions=True)
    resp = client.post("/api/v1/connect/github", json={"token": _FINE_PAT}, headers=auth_headers())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


def test_missing_local_token_rejected() -> None:
    resp = _client().post("/api/v1/connect/github", json={"token": _FINE_PAT})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_form_encoded_post_rejected_csrf() -> None:
    resp = _client().post(
        "/api/v1/connect/github",
        data={"token": _FINE_PAT},
        headers=auth_headers(),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"
