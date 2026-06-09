"""Slice 2.3 — SSE endpoint: cookie auth, anti-buffering headers, replay (AC-9/10/11).

End-to-end over the real app + a migrated SQLite DB. Seeds a **finished** run's
durable backlog (no live hub) so the stream flushes the backlog and closes — the
deterministic path for asserting:

* **AC-9 / INV-2:** the SSE handler 401s without the cookie, 200s with the
  HttpOnly ``SameSite=Strict`` cookie, and rejects an ``Origin``/``Host`` mismatch;
  the token NEVER rides the URL.
* **AC-10:** the response sets ``Cache-Control: no-cache`` + ``X-Accel-Buffering: no``.
* **AC-11:** a ``Last-Event-ID`` reconnect replays only ``id > last`` with **no
  gaps and no duplicates**; a paused-run reconnect rehydrates the decision card
  from ``GET /runs/{id}`` (the ``decision`` block), not the live push.
"""

from __future__ import annotations

import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.db import Repository
from app.db.repository import EventRecord
from app.security.access_control import SSE_TOKEN_COOKIE
from fastapi.testclient import TestClient

from tests.conftest import TEST_TOKEN, auth_headers, build_client, make_settings

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _migrate(db_path: Path) -> str:
    url = f"sqlite:///{db_path}"
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


def _client(db_path: Path) -> tuple[TestClient, str]:
    url = _migrate(db_path)
    return build_client(settings=make_settings(DATABASE_URL=url)), url


async def _seed_finished_run(url: str, *, agent: str = "claude") -> str:
    """Seed a run with three persisted events (the durable backlog); return its id."""
    repo = Repository(url)
    await repo.start()
    try:
        run_id, _ = await repo.claim_run(
            idempotency_key=f"sse-{agent}",
            repo="o/r",
            issue_num=3,
            workflow_id="plan",
            agent=agent,
            branch="dkmv/issue-3",
            feature_name="issue-3",
        )
        await repo.append_events(
            [
                EventRecord(
                    run_id=run_id,
                    sequence=1,
                    event_type="task_started",
                    payload={"type": "task_started"},
                    task_index=0,
                ),
                EventRecord(
                    run_id=run_id,
                    sequence=2,
                    event_type="assistant",
                    payload={"type": "assistant"},
                    task_index=0,
                ),
                EventRecord(
                    run_id=run_id,
                    sequence=3,
                    event_type="task_completed",
                    payload={"type": "task_completed"},
                    task_index=0,
                    cost_usd=2.0,
                ),
            ]
        )
        return run_id
    finally:
        await repo.close()


def _sse_cookie() -> dict[str, str]:
    return {SSE_TOKEN_COOKIE: TEST_TOKEN}


def _parse_sse(body: str) -> list[dict[str, str]]:
    """Parse an SSE response body into a list of {id, event, data} message dicts."""
    messages: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in body.splitlines():
        if line == "":
            if current:
                messages.append(current)
                current = {}
            continue
        if line.startswith(":"):
            continue  # heartbeat / comment
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        current[field] = value
    if current:
        messages.append(current)
    return messages


def test_sse_requires_cookie_401_without(tmp_path: Path) -> None:
    """No SSE cookie (and no bearer) → 401 (INV-2 / AC-9)."""
    client, url = _client(tmp_path / "a.db")
    import asyncio

    run_id = asyncio.new_event_loop().run_until_complete(_seed_finished_run(url))
    # No Authorization header, no cookie → the middleware/handler reject with 401.
    resp = client.get(f"/api/v1/runs/{run_id}/events")
    assert resp.status_code == 401


def test_sse_200_with_cookie_and_anti_buffering_headers(tmp_path: Path) -> None:
    """The cookie authenticates; the stream sets the anti-buffering headers (AC-9/10)."""
    client, url = _client(tmp_path / "b.db")
    import asyncio

    run_id = asyncio.new_event_loop().run_until_complete(_seed_finished_run(url))
    with client.stream("GET", f"/api/v1/runs/{run_id}/events", cookies=_sse_cookie()) as resp:
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-cache"
        assert resp.headers["x-accel-buffering"] == "no"
        body = "".join(resp.iter_text())
    messages = _parse_sse(body)
    # The backlog replayed in id order, each id = events.id.
    events = [m for m in messages if "data" in m]
    assert [m["event"] for m in events] == ["task_started", "assistant", "task_completed"]
    ids = [int(m["id"]) for m in events]
    assert ids == sorted(ids)  # monotonic


def test_sse_rejects_foreign_origin(tmp_path: Path) -> None:
    """An Origin-mismatched SSE request is rejected (anti-DNS-rebinding, AC-9)."""
    client, url = _client(tmp_path / "c.db")
    import asyncio

    run_id = asyncio.new_event_loop().run_until_complete(_seed_finished_run(url))
    resp = client.get(
        f"/api/v1/runs/{run_id}/events",
        cookies=_sse_cookie(),
        headers={"Origin": "http://evil.example.com"},
    )
    assert resp.status_code == 403


def test_sse_unknown_run_404(tmp_path: Path) -> None:
    """An unknown platform UUID → 404 run_not_found (addresses the platform id)."""
    client, _ = _client(tmp_path / "d.db")
    resp = client.get("/api/v1/runs/does-not-exist/events", cookies=_sse_cookie())
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "run_not_found"


def test_sse_last_event_id_replays_no_gaps_no_dups(tmp_path: Path) -> None:
    """Reconnect with Last-Event-ID replays only id > last, no gaps/dups (AC-11)."""
    client, url = _client(tmp_path / "e.db")
    import asyncio

    run_id = asyncio.new_event_loop().run_until_complete(_seed_finished_run(url))
    # First connect: full backlog (3 events).
    with client.stream("GET", f"/api/v1/runs/{run_id}/events", cookies=_sse_cookie()) as resp:
        first = _parse_sse("".join(resp.iter_text()))
    first_events = [m for m in first if "data" in m]
    assert len(first_events) == 3
    cursor = int(first_events[1]["id"])  # reconnect after the 2nd event

    # Reconnect with Last-Event-ID = cursor → only the 3rd event, no gaps/dups.
    with client.stream(
        "GET",
        f"/api/v1/runs/{run_id}/events",
        cookies=_sse_cookie(),
        headers={"Last-Event-ID": str(cursor)},
    ) as resp:
        second = _parse_sse("".join(resp.iter_text()))
    second_events = [m for m in second if "data" in m]
    second_ids = [int(m["id"]) for m in second_events]
    assert all(i > cursor for i in second_ids)  # no replay of already-seen ids
    assert len(second_ids) == len(set(second_ids))  # no duplicates
    assert second_ids == [int(first_events[2]["id"])]  # exactly the tail, no gap


def test_token_never_in_sse_url(tmp_path: Path) -> None:
    """The SSE URL carries no token — auth is the cookie only (INV-2)."""
    client, url = _client(tmp_path / "f.db")
    import asyncio

    run_id = asyncio.new_event_loop().run_until_complete(_seed_finished_run(url))
    # A token in the query string must NOT be how auth works: without the cookie,
    # even a ?token=... URL is rejected (the token rides the cookie, never the URL).
    resp = client.get(f"/api/v1/runs/{run_id}/events?token={TEST_TOKEN}")
    assert resp.status_code == 401


def test_paused_run_rehydrates_decision_from_get_run(tmp_path: Path) -> None:
    """A paused run exposes its decision on GET /runs/{id} for PauseCard rehydration (AC-11)."""
    client, url = _client(tmp_path / "g.db")
    import asyncio

    async def _seed_paused() -> str:
        repo = Repository(url)
        await repo.start()
        try:
            run_id, _ = await repo.claim_run(
                idempotency_key="paused-k",
                repo="o/r",
                issue_num=9,
                workflow_id="plan",
                agent="claude",
                branch="dkmv/issue-9",
                feature_name="issue-9",
            )
            await repo.update_run_fields(run_id, status="paused")
            # A pending pause_decisions row (the rehydration source) — written via
            # the writer through a small inline job (slice 2.5 owns the bridge that
            # normally writes this; here we seed it directly).
            await _insert_pause(repo, run_id)
            return run_id
        finally:
            await repo.close()

    run_id = asyncio.new_event_loop().run_until_complete(_seed_paused())
    resp = client.get(f"/api/v1/runs/{run_id}", headers=auth_headers())
    assert resp.status_code == 200
    decision = resp.json()["decision"]
    assert decision is not None
    assert decision["status"] == "pending"
    assert decision["task_name"] == "analyze"
    assert decision["request"]["question"] == "Proceed?"


async def _insert_pause(repo: Repository, run_id: str) -> None:
    """Insert a pending pause_decisions row through the single writer."""
    import aiosqlite

    request_json = json.dumps({"question": "Proceed?", "options": []})

    async def _job(conn: aiosqlite.Connection) -> None:
        await conn.execute(
            "INSERT INTO pause_decisions (id, run_id, task_name, request_json, status, "
            "timeout_at, created_at) VALUES (?, ?, ?, ?, 'pending', ?, ?)",
            (
                "dec-1",
                run_id,
                "analyze",
                request_json,
                "2099-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )

    await repo._writer.submit(_job)  # noqa: SLF001 - test seeds the row the bridge writes in 2.5
