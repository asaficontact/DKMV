"""Slice 3.1 — ``GET /retry-queue`` shape (AC-4 / FR-06-3, §8.9).

The retry **scheduler** that populates the queue is slice 3.4; 3.1 ships the
endpoint + the wire shape. Asserts:

* ``GET /retry-queue`` returns the cursor envelope ``{ items, next_cursor }``.
* Before 3.4 populates it, ``items`` is empty (no stub rows, no error).
* The endpoint inherits access control (no token → 401).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import auth_headers, build_client, make_settings

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _client() -> TestClient:
    return build_client(settings=make_settings())


def test_retry_queue_empty_envelope() -> None:
    client = _client()
    resp = client.get("/api/v1/retry-queue", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"items": [], "next_cursor": None}


def test_retry_queue_requires_token() -> None:
    client = _client()
    assert client.get("/api/v1/retry-queue").status_code == 401


def test_retry_entry_shape_is_documented() -> None:
    """The endpoint source documents the ``RetryEntry`` shape 3.4 will fill (FR-06-3)."""
    src = (_BACKEND_ROOT / "app" / "api" / "retry_queue.py").read_text()
    for field in ("id", "issue", "attempt", "dueIn", "lastError"):
        assert field in src, f"RetryEntry field {field} not referenced in retry_queue.py"
