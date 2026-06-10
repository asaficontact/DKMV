"""G6 — ``GET/PUT /api/v1/settings`` run-defaults endpoint (FR-SET-1, §5.9).

Covers:
  - ``GET`` returns a fully-populated default view (config/engine defaults) on a
    fresh DB, with **no secret** in the payload.
  - ``PUT`` persists a partial update and the merged values **round-trip** through
    a follow-up ``GET``.
  - ``PUT`` **rejects** an out-of-bounds value with the §8.9 ``validation_error``
    envelope (and does not persist it).
  - INV-1: both routes are behind access control — a request with **no token** is
    401, and a request from a **foreign Host** is 403.

The persisted defaults live in the existing ``settings`` KV table; each test gets a
fresh migrated SQLite DB so there are no cross-test overrides.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import _migrate, auth_headers, build_client, make_settings


def _client(tmp_path: Path) -> TestClient:
    url = _migrate(tmp_path / "settings.db")
    return build_client(settings=make_settings(DATABASE_URL=url))


# ── GET defaults (FR-SET-1) ──────────────────────────────────────────────────


def test_get_returns_fully_populated_defaults(tmp_path: Path) -> None:
    resp = _client(tmp_path).get("/api/v1/settings", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    # Every field is present and truthful from the config/engine defaults.
    assert body["default_agent"] == "claude"
    assert body["default_model"] == "claude-sonnet-4-6"
    assert body["default_memory"] == "8g"
    assert body["default_timeout_minutes"] == 40
    assert body["daily_spend_alert_usd"] == 25.0
    assert body["default_max_budget_usd"] is None
    assert body["default_max_turns"] is None


def test_get_never_leaks_a_secret(tmp_path: Path) -> None:
    """The GET view carries only run-shaping defaults — never a token/key."""
    body = _client(tmp_path).get("/api/v1/settings", headers=auth_headers()).json()
    keys = set(body)
    for forbidden_key in ("github_token", "anthropic_api_key", "codex_api_key", "token"):
        assert forbidden_key not in keys
    # No value looks like a credential blob either.
    for value in body.values():
        assert "sk-" not in str(value)
        assert "ghp_" not in str(value)


# ── PUT persist + round-trip (FR-SET-1) ──────────────────────────────────────


def test_put_persists_and_round_trips(tmp_path: Path) -> None:
    client = _client(tmp_path)
    put = client.put(
        "/api/v1/settings",
        headers=auth_headers(),
        json={
            "default_agent": "codex",
            "default_memory": "16g",
            "default_timeout_minutes": 25,
            "daily_spend_alert_usd": 40.0,
        },
    )
    assert put.status_code == 200
    updated = put.json()
    assert updated["default_agent"] == "codex"
    assert updated["default_memory"] == "16g"
    assert updated["default_timeout_minutes"] == 25
    assert updated["daily_spend_alert_usd"] == 40.0
    # Untouched fields keep their default (partial update).
    assert updated["default_model"] == "claude-sonnet-4-6"

    # The persisted values survive a fresh GET (round-trip through the KV table).
    got = client.get("/api/v1/settings", headers=auth_headers()).json()
    assert got["default_agent"] == "codex"
    assert got["default_memory"] == "16g"
    assert got["default_timeout_minutes"] == 25
    assert got["daily_spend_alert_usd"] == 40.0


def test_put_clears_optional_via_explicit_null(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.put(
        "/api/v1/settings",
        headers=auth_headers(),
        json={"default_max_budget_usd": 12.5},
    )
    assert (
        client.get("/api/v1/settings", headers=auth_headers()).json()["default_max_budget_usd"]
        == 12.5
    )
    # An explicit null clears it back to None.
    client.put(
        "/api/v1/settings",
        headers=auth_headers(),
        json={"default_max_budget_usd": None},
    )
    assert (
        client.get("/api/v1/settings", headers=auth_headers()).json()["default_max_budget_usd"]
        is None
    )


# ── PUT validation (§8.9 / §8.10) ────────────────────────────────────────────


def test_put_rejects_out_of_bounds_timeout(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.put(
        "/api/v1/settings",
        headers=auth_headers(),
        json={"default_timeout_minutes": 0},
    )
    assert resp.status_code in (400, 422)
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    # The bad value did not persist (the GET still shows the default).
    assert (
        client.get("/api/v1/settings", headers=auth_headers()).json()["default_timeout_minutes"]
        == 40
    )


def test_put_rejects_bad_memory_shape(tmp_path: Path) -> None:
    resp = _client(tmp_path).put(
        "/api/v1/settings",
        headers=auth_headers(),
        json={"default_memory": "lots"},
    )
    assert resp.status_code in (400, 422)
    assert resp.json()["error"]["code"] == "validation_error"


def test_put_rejects_unknown_field(tmp_path: Path) -> None:
    """``extra='forbid'`` rejects a smuggled key (e.g. a secret) — 400/422."""
    resp = _client(tmp_path).put(
        "/api/v1/settings",
        headers=auth_headers(),
        json={"github_token": "ghp_secret"},
    )
    assert resp.status_code in (400, 422)


# ── INV-1 access control on the new routes ───────────────────────────────────


def test_get_requires_local_token(tmp_path: Path) -> None:
    resp = _client(tmp_path).get("/api/v1/settings")  # no Authorization header
    assert resp.status_code == 401


def test_put_requires_local_token(tmp_path: Path) -> None:
    resp = _client(tmp_path).put("/api/v1/settings", json={"default_memory": "8g"})
    assert resp.status_code == 401


def test_get_rejects_foreign_host(tmp_path: Path) -> None:
    """A non-loopback Host is rejected (403, anti-DNS-rebinding — INV-1)."""
    url = _migrate(tmp_path / "settings.db")
    client = build_client(settings=make_settings(DATABASE_URL=url), host="evil.example.com")
    resp = client.get("/api/v1/settings", headers=auth_headers())
    assert resp.status_code == 403
