"""Slice 3.1 — ``GET /stats`` aggregates, Codex-excluded spend (AC-3 / INV-8).

End-to-end over the real app + a migrated SQLite DB. Asserts:

* Spend (``total_spend_usd`` + ``spend_series``) is the segment-sum projection
  over ``run_totals`` + active runs, with **Codex $0-cost runs excluded**, while
  ``tokens`` and ``agent_hours`` count Codex normally (FR-06-1a / INV-8 binding).
* ``success_rate = completed/(completed+failed)`` (FR-06-1).
* The ``rate_limits`` block carries github/anthropic/openai slots (FR-06-2).
* Stats are NOT computed via the engine ``list_runs`` / ``get_stats`` scan (§6.5)
  — asserted by a source grep over ``stats.py`` + ``queries_history.py``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.db import Repository
from app.db.repository import EventRecord
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, build_client, make_settings

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _run[T](coro: Awaitable[T]) -> T:
    return asyncio.new_event_loop().run_until_complete(coro)


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


async def _set_started_at(url: str, run_id: str, started_at: str) -> None:
    """Pin a deterministic UTC ``started_at`` for spend-series date bucketing.

    ``claim_run`` stamps ``started_at`` with ``now()``; the spend-series test
    needs fixed dates, so it writes the column directly via aiosqlite (a test-only
    fixture write, outside the production write path).
    """
    import aiosqlite

    db_path = url.replace("sqlite:///", "")
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("UPDATE runs SET started_at = ? WHERE id = ?", (started_at, run_id))
        await conn.commit()


async def _seed(
    url: str,
    *,
    key: str,
    issue_num: int,
    agent: str,
    status: str,
    cost: float | None,
    tokens_in: int,
    tokens_out: int,
    duration_s: float,
    started_at: str | None = None,
) -> str:
    repository = Repository(url)
    await repository.start()
    try:
        run_id, _won = await repository.claim_run(
            idempotency_key=key,
            repo="o/r",
            issue_num=issue_num,
            workflow_id="qa",
            agent=agent,
            model="claude-sonnet-4-6" if agent == "claude" else "gpt-5.4",
            branch=f"dkmv/issue-{issue_num}",
            feature_name=f"issue-{issue_num}",
        )
        await repository.update_run_fields(
            run_id,
            status=status,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_s=duration_s,
        )
        if started_at is not None:
            await _set_started_at(url, run_id, started_at)
        if cost is not None:
            await repository.append_events(
                [
                    EventRecord(
                        run_id=run_id,
                        sequence=1,
                        event_type="task_completed",
                        payload={"type": "task_completed"},
                        task_index=0,
                        cost_usd=cost,
                        agent=agent,
                    )
                ]
            )
        return run_id
    finally:
        await repository.close()


# ── AC-3: Codex excluded from spend, tokens/agent-hours count both ────────────


def test_codex_excluded_from_spend_tokens_counted(tmp_path: Path) -> None:
    client, url = _client(tmp_path / "t.db")
    # Claude completed run: cost 4.0, 100+50 tokens, 3600s.
    _run(
        _seed(
            url,
            key="claude",
            issue_num=1,
            agent="claude",
            status="completed",
            cost=4.0,
            tokens_in=100,
            tokens_out=50,
            duration_s=3600.0,
        )
    )
    # Codex completed run: $0 cost (engine), 200+100 tokens, 1800s.
    _run(
        _seed(
            url,
            key="codex",
            issue_num=2,
            agent="codex",
            status="completed",
            cost=0.0,
            tokens_in=200,
            tokens_out=100,
            duration_s=1800.0,
        )
    )

    body = client.get("/api/v1/stats", headers=auth_headers()).json()
    # Spend is Claude-only (Codex excluded).
    assert body["total_spend_usd"] == 4.0
    # Tokens count BOTH (100+50 + 200+100 = 450).
    assert body["tokens"] == 450
    # Agent-hours count both (3600 + 1800)/3600 = 1.5.
    assert body["agent_hours"] == 1.5
    assert body["total_runs"] == 2


def test_spend_series_excludes_codex(tmp_path: Path) -> None:
    client, url = _client(tmp_path / "t.db")
    _run(
        _seed(
            url,
            key="claude",
            issue_num=1,
            agent="claude",
            status="completed",
            cost=2.5,
            tokens_in=10,
            tokens_out=10,
            duration_s=60.0,
            started_at="2026-06-01T10:00:00+00:00",
        )
    )
    _run(
        _seed(
            url,
            key="codex",
            issue_num=2,
            agent="codex",
            status="completed",
            cost=0.0,
            tokens_in=10,
            tokens_out=10,
            duration_s=60.0,
            started_at="2026-06-02T10:00:00+00:00",
        )
    )
    body = client.get("/api/v1/stats", headers=auth_headers()).json()
    series = body["spend_series"]
    # Only the Claude day appears; the Codex day is excluded ($0, FR-06-1a).
    assert series == [{"date": "2026-06-01", "usd": 2.5}]


# ── AC-3: success rate = completed/(completed+failed) ─────────────────────────


def test_success_rate_math(tmp_path: Path) -> None:
    client, url = _client(tmp_path / "t.db")
    for i in range(3):
        _run(
            _seed(
                url,
                key=f"c{i}",
                issue_num=i,
                agent="claude",
                status="completed",
                cost=1.0,
                tokens_in=1,
                tokens_out=1,
                duration_s=1.0,
            )
        )
    _run(
        _seed(
            url,
            key="f",
            issue_num=99,
            agent="claude",
            status="failed",
            cost=None,
            tokens_in=1,
            tokens_out=1,
            duration_s=1.0,
        )
    )
    # A running run is neither completed nor failed → not in the denominator.
    _run(
        _seed(
            url,
            key="r",
            issue_num=100,
            agent="claude",
            status="running",
            cost=None,
            tokens_in=1,
            tokens_out=1,
            duration_s=1.0,
        )
    )
    body = client.get("/api/v1/stats", headers=auth_headers()).json()
    # 3 completed / (3 completed + 1 failed) = 0.75.
    assert body["success_rate"] == 0.75


def test_success_rate_zero_with_no_outcomes(tmp_path: Path) -> None:
    client, _url = _client(tmp_path / "t.db")
    body = client.get("/api/v1/stats", headers=auth_headers()).json()
    assert body["success_rate"] == 0.0
    assert body["total_runs"] == 0
    assert body["spend_series"] == []


# ── AC-3: rate_limits fields present (FR-06-2) ────────────────────────────────


def test_rate_limits_block_present(tmp_path: Path) -> None:
    client, _url = _client(tmp_path / "t.db")
    body = client.get("/api/v1/stats", headers=auth_headers()).json()
    rl = body["rate_limits"]
    for provider in ("github", "anthropic", "openai"):
        assert provider in rl
        assert "used_pct" in rl[provider]


def test_stats_requires_token(tmp_path: Path) -> None:
    client, _url = _client(tmp_path / "t.db")
    assert client.get("/api/v1/stats").status_code == 401


# ── §6.5: stats does NOT run off the engine list_runs/get_stats scan ──────────


def test_stats_does_not_use_engine_directory_scan() -> None:
    """``stats.py`` carries no engine ``list_runs`` / ``get_stats`` scan (§6.5, §9 grep)."""
    src = (_BACKEND_ROOT / "app" / "api" / "stats.py").read_text()
    # The §9 verification grep ``list_runs|get_stats`` over stats.py MUST be empty.
    assert "list_runs" not in src
    assert "get_stats" not in src
    assert "EmbeddedRuntime" not in src
