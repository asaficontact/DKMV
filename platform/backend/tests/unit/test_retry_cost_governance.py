"""Slice 5.2 FIX — a retried run carries its original cost-governance caps.

A security/correctness review found that the retry redispatch path
(``app.orchestrator.retry_deps._redispatch``) reconstructed the §8.4
:class:`~app.runs.launch.LaunchRequest` WITHOUT re-populating ``max_budget_usd`` /
``max_turns`` from the stored ``runs`` row — so a RETRIED Claude run was relaunched
with NO per-run budget/turn hard cap (only the default timeout), silently escaping
the cap its first dispatch enforced (a cost-governance hole).

These tests pin the fix on the **real lifespan-composed** ``_redispatch`` closure
(``build_retry_scheduler`` against the production ``app.state``): they intercept the
single ``launch_run`` boundary (ADR-P001 — there is exactly one launch path) and
assert the reconstructed :class:`LaunchRequest`:

1. for a **Claude** run, carries the SAME ``max_budget_usd`` + ``max_turns`` the
   first dispatch persisted (a retry is equivalent to first dispatch — INV-8 hard
   caps preserved);
2. for a **Codex** run, the capability layer (``resolve_enforced_caps``, the real
   gate ``launch_run`` runs) still force-drops budget/turns to ``None`` — no smuggle
   on retry (INV-8 timeout-only profile).

The lifespan is entered directly (it is an ``@asynccontextmanager``) so the
single-writer Repository, the GitHub seam, and the scheduler are composed exactly as
in production on ONE event loop (a ``TestClient`` runs them on a separate loop and
deadlocks the cross-loop ``await``s).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pytest
from app.config import Settings
from app.db import Repository
from app.main import _lifespan, create_app
from app.orchestrator.enforcement import resolve_enforced_caps
from app.orchestrator.retry_deps import build_retry_scheduler
from app.runs.launch import LaunchRequest, LaunchResult
from fastapi import FastAPI

from tests.conftest import TEST_TOKEN, _migrate

pytestmark = pytest.mark.asyncio

_REPO = "octo/widgets"


class _StubRuntime:
    """A duck-typed engine stub: preflight ready, no live handles (no Docker)."""

    class _Report:
        ready = True

    class _Runtime:
        def get_handle(self, _engine_run_id: str) -> None:
            return None

    runtime = _Runtime()

    def get_capabilities(self) -> Any:
        return self._Report()


def _settings(url: str) -> Settings:
    return Settings(  # type: ignore[call-arg]  # DKMVP-ESCAPE: pydantic-settings injected kwargs
        _env_file=None,
        DKMV_PLATFORM_TOKEN=TEST_TOKEN,
        DATABASE_URL=url,
        TICK_INTERVAL_S=10_000,
    )


def _fresh_url() -> str:
    fd, path = tempfile.mkstemp(prefix="dkmvp-retry-cost-", suffix=".db")
    os.close(fd)
    return _migrate(Path(path))


async def _seed_project(url: str) -> None:
    repository = Repository(url)
    await repository.start()
    await repository.upsert_project(project_id="p1", repo=_REPO)
    await repository.close()


def _build_app(url: str) -> FastAPI:
    settings = _settings(url)
    from app.runtime import RunService

    run_service = RunService(settings, runtime=_StubRuntime())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed runtime stub
    return create_app(settings, run_service=run_service)


class _CapturingLaunch:
    """Capture the reconstructed :class:`LaunchRequest` at the launch boundary.

    Stands in for ``app.runs.launch.launch_run`` (the single dispatch path the
    retry closure routes through). It records the request the closure built so the
    test can assert which caps a retry carries — without starting an engine run.
    """

    def __init__(self) -> None:
        self.requests: list[LaunchRequest] = []

    async def __call__(self, req: LaunchRequest, **_: Any) -> LaunchResult:
        self.requests.append(req)
        return LaunchResult(run_id="redispatched", resolved_agent=req.agent, resolved_model=None)


async def _redispatch_and_capture(
    app: FastAPI,
    *,
    row: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> LaunchRequest:
    """Build the LIVE ``_redispatch`` closure + drive it, capturing the LaunchRequest."""
    import app.runs.launch as launch_mod

    capture = _CapturingLaunch()
    # ``_redispatch`` imports ``launch_run`` from ``app.runs.launch`` at call time,
    # so patching the module attribute intercepts the real closure's single boundary.
    monkeypatch.setattr(launch_mod, "launch_run", capture)

    scheduler = build_retry_scheduler(app)
    result = await scheduler.redispatch(row, None)
    assert result == "redispatched"
    assert len(capture.requests) == 1
    return capture.requests[0]


# ── (1) a retried Claude run carries its original budget + turn caps ──────────


async def test_retried_claude_run_preserves_budget_and_turn_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A RETRIED Claude run re-dispatches WITH its original max_budget_usd + max_turns."""
    url = _fresh_url()
    await _seed_project(url)
    app = _build_app(url)

    async with _lifespan(app):
        repository: Repository = app.state.repository
        # First dispatch persisted these hard caps at claim_run (the §8.9 config
        # block source). Claude supports budget + turns, so they are real caps.
        run_id, won = await repository.claim_run(
            idempotency_key="81::qa::main",
            repo=_REPO,
            issue_num=81,
            workflow_id="qa",
            agent="claude",
            model="claude-sonnet-4-6",
            branch="dkmv/issue-feature",
            feature_name="issue-81",
            max_turns=42,
            timeout_minutes=90,
            max_budget_usd=7.5,
            memory_limit="8g",
        )
        assert won
        await repository.update_run_fields(run_id, status="failed")
        row = await repository.get_run(run_id)
        assert row is not None
        # The stored row actually persists the caps (claim_run writes them).
        assert row["max_budget_usd"] == 7.5
        assert row["max_turns"] == 42

        req = await _redispatch_and_capture(app, row=row, monkeypatch=monkeypatch)

        # The retry's reconstructed launch carries the SAME hard caps — equivalent
        # to first dispatch (the cost-governance hole this fix closes).
        assert req.agent == "claude"
        assert req.max_budget_usd == 7.5
        assert req.max_turns == 42
        assert req.timeout_minutes == 90

        # And the capability layer ``launch_run`` runs keeps them as ENFORCED caps
        # for Claude (a hard ceiling that fires) — not dropped.
        caps = resolve_enforced_caps(
            agent=req.agent,
            max_budget_usd=req.max_budget_usd,
            max_turns=req.max_turns,
            timeout_minutes=req.timeout_minutes,
        )
        assert caps.max_budget_usd == 7.5
        assert caps.max_turns == 42
        assert caps.budget_cap_active is True
        assert caps.turn_cap_active is True


# ── (2) a retried Codex run still has budget/turns force-dropped to None ──────


async def test_retried_codex_run_caps_force_dropped_no_smuggle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A RETRIED Codex run carries NO budget/turn cap — the capability layer drops them."""
    url = _fresh_url()
    await _seed_project(url)
    app = _build_app(url)

    async with _lifespan(app):
        repository: Repository = app.state.repository
        # A Codex run: the launch path already persisted None caps (the engine has
        # no budget/turn cap — INV-8). Seed the row the same way.
        run_id, won = await repository.claim_run(
            idempotency_key="82::qa::main",
            repo=_REPO,
            issue_num=82,
            workflow_id="qa",
            agent="codex",
            model="gpt-5.4",
            branch="dkmv/issue-feature",
            feature_name="issue-82",
            max_turns=None,
            timeout_minutes=20,
            max_budget_usd=None,
            memory_limit="8g",
        )
        assert won
        await repository.update_run_fields(run_id, status="failed")
        row = await repository.get_run(run_id)
        assert row is not None
        assert row["agent"] == "codex"

        req = await _redispatch_and_capture(app, row=row, monkeypatch=monkeypatch)

        # The reconstructed launch carries no budget/turn cap from the row.
        assert req.agent == "codex"
        assert req.max_budget_usd is None
        assert req.max_turns is None

        # Even if a budget/turn value were somehow present, the capability layer
        # ``launch_run`` runs force-drops them to None for Codex — no smuggle on
        # retry (INV-8 timeout-only profile).
        caps = resolve_enforced_caps(
            agent="codex",
            max_budget_usd=99.0,
            max_turns=999,
            timeout_minutes=req.timeout_minutes,
        )
        assert caps.max_budget_usd is None
        assert caps.max_turns is None
        assert caps.budget_cap_active is False
        assert caps.turn_cap_active is False
