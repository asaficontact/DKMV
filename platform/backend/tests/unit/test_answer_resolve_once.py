"""Slice 2.5 — resolve-exactly-once + the answer endpoint (AC-17 / INV-9 / §8.5).

The binding guarantee (INV-9): ``POST /runs/{id}/answer`` resolves a pause
**exactly once** via the rowcount-guarded transition
``UPDATE pause_decisions SET status='answered' … WHERE id=? AND status='pending'``,
firing the in-memory keyed event **only on rowcount==1**. A double-submit, a second
browser tab, and a racing timeout sweep can therefore never all win — exactly one
flips the row + resumes the engine; the rest get ``409 pause_already_resolved``.

Two layers:

* **Unit (the guard).** Two concurrent :func:`resolve_pending_pause` for the same
  decision → exactly one wins; a human + a timeout racing the same row → one
  resolution. The DB row ends ``answered`` with the winner's ``resolved_by``.
* **API.** ``POST /runs/{id}/answer`` over the real app: first call ``200
  {resolved:true}``, second ``409 pause_already_resolved``; the posted body's
  chosen **value** is stored (the engine-authoritative value, not a label).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from app.db import Repository
from app.hitl import DecisionRegistry
from app.hitl.answer import resolve_pending_pause

from tests.conftest import auth_headers, build_client, make_settings

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _run[T](coro: Awaitable[T]) -> T:
    """Run a coroutine on a throwaway loop (sync helper for the unit-guard tests)."""
    return asyncio.new_event_loop().run_until_complete(coro)


def _migrate(db_path: Path) -> str:
    url = f"sqlite:///{db_path}"
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


async def _seed_pending(repo: Repository) -> str:
    """Claim a run + write a pending pause; return the decision_id."""
    run_id, _ = await repo.claim_run(
        idempotency_key="9::qa::main",
        repo="o/r",
        issue_num=9,
        workflow_id="qa",
        agent="claude",
    )
    return await repo.create_pause_decision(
        run_id=run_id,
        request_json='{"task_name":"Analyze","questions":[],"context":{}}',
        task_name="Analyze",
        timeout_at="2099-01-01T00:00:00+00:00",
    )


# ── Unit: the rowcount guard resolves exactly once ───────────────────────────


@pytest.mark.asyncio
async def test_two_concurrent_resolves_one_wins(repo: Repository) -> None:
    decision_id = await _seed_pending(repo)
    decisions = DecisionRegistry()

    async def _attempt(by: str) -> bool:
        return await resolve_pending_pause(
            repository=repo,
            decisions=decisions,
            decision_id=decision_id,
            answers={"q": "v"},
            skip_remaining=False,
            resolved_by=by,
        )

    results = await asyncio.gather(_attempt("human"), _attempt("human"))
    assert sorted(results) == [False, True]  # exactly one won

    row = await repo.get_pause_decision(decision_id)
    assert row is not None
    assert row["status"] == "answered"


@pytest.mark.asyncio
async def test_human_and_timeout_race_one_resolution(repo: Repository) -> None:
    """A human answer + a racing timeout sweep resolve the SAME row exactly once."""
    decision_id = await _seed_pending(repo)
    decisions = DecisionRegistry()

    human, timeout = await asyncio.gather(
        resolve_pending_pause(
            repository=repo,
            decisions=decisions,
            decision_id=decision_id,
            answers={"q": "v"},
            skip_remaining=False,
            resolved_by="human",
        ),
        resolve_pending_pause(
            repository=repo,
            decisions=decisions,
            decision_id=decision_id,
            answers={},
            skip_remaining=True,
            resolved_by="timeout",
        ),
    )
    assert [human, timeout].count(True) == 1  # exactly one resolution overall
    row = await repo.get_pause_decision(decision_id)
    assert row is not None
    assert row["status"] == "answered"
    assert row["resolved_by"] in {"human", "timeout"}


# ── API: POST /runs/{id}/answer → 200 then 409 ───────────────────────────────


async def _seed_pending_at(url: str) -> str:
    """Seed a run + pending pause over a throwaway Repository on the same DB file.

    The lifespan-entered app and this seeder open separate connections to the same
    WAL SQLite file, so the run + pending decision are visible to the answer
    endpoint's lifespan-owned repository (mirrors ``test_run_reads`` seeding).
    """
    repository = Repository(url)
    await repository.start()
    try:
        run_id, _ = await repository.claim_run(
            idempotency_key="11::qa::main",
            repo="o/r",
            issue_num=11,
            workflow_id="qa",
            agent="claude",
        )
        await repository.create_pause_decision(
            run_id=run_id,
            request_json='{"task_name":"Analyze","questions":[],"context":{}}',
            task_name="Analyze",
            timeout_at="2099-01-01T00:00:00+00:00",
        )
        return run_id
    finally:
        await repository.close()


async def _read_decision_at(url: str, run_id: str) -> dict[str, Any] | None:
    repository = Repository(url)
    await repository.start()
    try:
        async with repository._read_conn() as conn:  # noqa: SLF001 - test read of stored answer
            rows = list(
                await conn.execute_fetchall(
                    "SELECT * FROM pause_decisions WHERE run_id = ?", (run_id,)
                )
            )
        return dict(rows[0]) if rows else None
    finally:
        await repository.close()


def test_answer_endpoint_200_then_409(tmp_path: Path) -> None:
    url = _migrate(tmp_path / "t.db")
    run_id = _run(_seed_pending_at(url))
    client = build_client(settings=make_settings(DATABASE_URL=url))

    body = {"answers": {"phases": "merge34"}, "skip_remaining": False}
    first = client.post(f"/api/v1/runs/{run_id}/answer", json=body, headers=auth_headers())
    assert first.status_code == 200
    assert first.json() == {"resolved": True}

    second = client.post(f"/api/v1/runs/{run_id}/answer", json=body, headers=auth_headers())
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "pause_already_resolved"

    # The stored answer carries the chosen VALUE (engine-authoritative), not a label.
    row = _run(_read_decision_at(url, run_id))
    assert row is not None
    assert row["status"] == "answered"
    assert row["resolved_by"] == "human"
    assert "merge34" in (row["answer_json"] or "")


def test_answer_audit_records_precise_decision_id(tmp_path: Path) -> None:
    """FIX-3 / AC-12: the §8.6 decision-resolution audit records the PRECISE
    ``pause_decisions.id`` (not the run id), threaded onto ``AnswerResult``."""
    from app.security import AuditEventKind, AuditLog, MemoryAuditSink

    url = _migrate(tmp_path / "t.db")
    run_id = _run(_seed_pending_at(url))
    # The decision row's real id (what the audit must record).
    decision_row = _run(_read_decision_at(url, run_id))
    assert decision_row is not None
    decision_id = str(decision_row["id"])
    assert decision_id != run_id  # a UUID-distinct id, not the run id

    client = build_client(settings=make_settings(DATABASE_URL=url))
    # Swap the lifespan's file sink for an in-memory one the route resolves via
    # ``get_audit`` per-request (one canonical reader seam — FIX-1).
    sink = MemoryAuditSink()
    client.app.state.audit = AuditLog(sink)  # type: ignore[attr-defined]  # DKMVP-ESCAPE: test re-publishes the audit singleton

    body = {"answers": {"phases": "merge34"}, "skip_remaining": False}
    resp = client.post(f"/api/v1/runs/{run_id}/answer", json=body, headers=auth_headers())
    assert resp.status_code == 200
    assert resp.json() == {"resolved": True}

    rec = next(r for r in sink.records if r.kind is AuditEventKind.DECISION_RESOLUTION)
    assert rec.run_id == run_id
    assert rec.details["decision_id"] == decision_id
    assert rec.details["resolved_by"] == "human"


def test_answer_unknown_run_404(tmp_path: Path) -> None:
    url = _migrate(tmp_path / "t.db")
    client = build_client(settings=make_settings(DATABASE_URL=url))
    resp = client.post(
        "/api/v1/runs/does-not-exist/answer",
        json={"answers": {}, "skip_remaining": False},
        headers=auth_headers(),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "run_not_found"
