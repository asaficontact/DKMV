"""Slice 2.5 — the real ``on_pause`` bridge is wired into the launch path (AC-18).

Slice 2.1 passed a no-op ``_passthrough_on_pause`` placeholder to
``EmbeddedRuntime.start``; slice 2.5 replaces it with the durable HITL bridge built
per-run from the claimed UUID. This asserts that a ``POST /runs`` actually hands the
engine a **real** bridge: invoking the ``on_pause`` the engine received writes a
``pause_decisions`` row (the passthrough would not) — proving the wiring, not the
placeholder, is what reaches ``start``.

Over the real app + a migrated DB + the fake engine/GitHub (no Docker — INV-13).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.db import Repository
from dkmv.tasks.pause import PauseQuestion, PauseRequest

from tests.conftest import auth_headers
from tests.unit.test_runs_launch import _body, _client


def _pause_request() -> PauseRequest:
    return PauseRequest(
        task_name="Analyze",
        questions=[
            PauseQuestion(
                id="phases",
                question="Proceed?",
                options=[{"value": "all", "label": "All phases"}],
                default="all",
            )
        ],
        context={"summary": "ctx"},
    )


def test_launch_passes_real_pause_bridge(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    client, runtime, _gh = _client(db)
    resp = client.post("/api/v1/runs", json=_body(agent="claude"), headers=auth_headers())
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]

    # The engine received a callable on_pause (not None / not the no-op placeholder).
    assert len(runtime.start_calls) == 1
    on_pause = runtime.start_calls[0]["on_pause"]
    assert callable(on_pause)
    assert getattr(on_pause, "__name__", "") != "_passthrough_on_pause"

    # Invoke the bridge as the engine would (park it; resolve via the answer route)
    # and assert it wrote a durable pending pause_decisions row keyed to THIS run —
    # the behavior the passthrough placeholder lacked.
    async def _drive() -> dict[str, object] | None:
        task = asyncio.ensure_future(on_pause(_pause_request()))
        repository: Repository = client.app.state.repository  # type: ignore[attr-defined]
        pending: dict[str, object] | None = None
        for _ in range(50):
            pending = await repository.read_pending_pause(run_id)
            if pending is not None:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 - cancelled park
            pass
        return pending

    assert client.portal is not None
    pending = client.portal.call(_drive)
    assert pending is not None
    assert pending["task_name"] == "Analyze"
    assert pending["status"] == "pending"
