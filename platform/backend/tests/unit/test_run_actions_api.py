"""Slice 2.4 — run control endpoints (AC-15 / §8.5).

* ``POST /runs/{id}/stop`` for a **paused** run uses ``RunHandle.stop(force=True)``
  (the engine checks ``cancel_event`` only between tasks — a cooperative stop
  never fires at ``await on_pause``); a **running** run stops cooperatively
  (``force=False``).
* ``POST /runs/{id}/exec`` is a **one-shot** ``execute_in_container`` (NOT a PTY):
  one command in, captured stdout out.
* Both inherit access control (no token → 401) and 404 an unknown run.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from app.db import Repository
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


class FakeHandle:
    """A RunHandle stand-in that records the ``stop`` call's ``force`` flag."""

    def __init__(self) -> None:
        self.stopped_with: bool | None = None

    async def stop(self, *, force: bool = False) -> None:
        self.stopped_with = force


class FakeRuntime:
    """Engine stand-in exposing the control surface ``run_actions`` reaches.

    ``get_handle`` returns a pre-registered :class:`FakeHandle` by engine id;
    ``execute_in_container`` records the one-shot command and returns canned
    stdout (or raises to exercise the error paths).
    """

    def __init__(self) -> None:
        self.handles: dict[str, FakeHandle] = {}
        self.exec_calls: list[tuple[str, str]] = []
        self.exec_result: str = "ok\n"
        self.exec_error: Exception | None = None

    def get_handle(self, run_id: str) -> FakeHandle | None:
        return self.handles.get(run_id)

    def execute_in_container(self, run_id: str, command: str) -> str:
        self.exec_calls.append((run_id, command))
        if self.exec_error is not None:
            raise self.exec_error
        return self.exec_result


async def _seed_run(url: str, *, status: str, engine_id: str | None) -> str:
    repository = Repository(url)
    await repository.start()
    try:
        run_id, _won = await repository.claim_run(
            idempotency_key=f"k-{status}-{engine_id}",
            repo="o/r",
            issue_num=7,
            workflow_id="qa",
            agent="claude",
            model="claude-sonnet-4-6",
        )
        fields: dict[str, Any] = {"status": status}
        if engine_id is not None:
            fields["engine_run_id"] = engine_id
        await repository.update_run_fields(run_id, **fields)
        return run_id
    finally:
        await repository.close()


def _client_with_runtime(db_path: Path, runtime: FakeRuntime) -> tuple[TestClient, str]:
    url = _migrate(db_path)
    return build_client(settings=make_settings(DATABASE_URL=url), runtime=runtime), url


def test_stop_paused_run_uses_force(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    handle = FakeHandle()
    runtime.handles["eng-paused"] = handle
    client, url = _client_with_runtime(tmp_path / "t.db", runtime)
    run_id = _run(_seed_run(url, status="paused", engine_id="eng-paused"))

    resp = client.post(f"/api/v1/runs/{run_id}/stop", headers=auth_headers())
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "stopping"
    assert body["forced"] is True
    # The paused path forces the cancel (R-7).
    assert handle.stopped_with is True


def test_stop_running_run_is_cooperative(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    handle = FakeHandle()
    runtime.handles["eng-run"] = handle
    client, url = _client_with_runtime(tmp_path / "t.db", runtime)
    run_id = _run(_seed_run(url, status="running", engine_id="eng-run"))

    resp = client.post(f"/api/v1/runs/{run_id}/stop", headers=auth_headers())
    assert resp.status_code == 202
    assert resp.json()["forced"] is False
    assert handle.stopped_with is False  # cooperative for a running run


def test_stop_terminal_run_409(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    client, url = _client_with_runtime(tmp_path / "t.db", runtime)
    run_id = _run(_seed_run(url, status="completed", engine_id="eng-done"))

    resp = client.post(f"/api/v1/runs/{run_id}/stop", headers=auth_headers())
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "run_not_stoppable"


def test_stop_unknown_run_404(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    client, _url = _client_with_runtime(tmp_path / "t.db", runtime)
    resp = client.post("/api/v1/runs/does-not-exist/stop", headers=auth_headers())
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "run_not_found"


def test_stop_requires_auth(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    client, url = _client_with_runtime(tmp_path / "t.db", runtime)
    run_id = _run(_seed_run(url, status="running", engine_id="eng-run"))
    resp = client.post(f"/api/v1/runs/{run_id}/stop")  # no token
    assert resp.status_code == 401


def test_exec_one_shot_runs_command(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    runtime.exec_result = "hello from container\n"
    client, url = _client_with_runtime(tmp_path / "t.db", runtime)
    run_id = _run(_seed_run(url, status="running", engine_id="eng-exec"))

    resp = client.post(
        f"/api/v1/runs/{run_id}/exec",
        headers=auth_headers(),
        json={"command": "echo hi"},
    )
    assert resp.status_code == 200
    assert resp.json()["output"] == "hello from container\n"
    # Exactly ONE exec call (one-shot, not a streaming session) against the engine id.
    assert runtime.exec_calls == [("eng-exec", "echo hi")]


def test_exec_no_container_409(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    runtime.exec_error = RuntimeError("Container for run X is not running (state=removed)")
    client, url = _client_with_runtime(tmp_path / "t.db", runtime)
    run_id = _run(_seed_run(url, status="running", engine_id="eng-gone"))

    resp = client.post(
        f"/api/v1/runs/{run_id}/exec",
        headers=auth_headers(),
        json={"command": "ls"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "container_unavailable"


def test_exec_command_failure_400(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    runtime.exec_error = RuntimeError("Command failed (exit 1): bad command")
    client, url = _client_with_runtime(tmp_path / "t.db", runtime)
    run_id = _run(_seed_run(url, status="running", engine_id="eng-fail"))

    resp = client.post(
        f"/api/v1/runs/{run_id}/exec",
        headers=auth_headers(),
        json={"command": "false"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "exec_failed"


def test_exec_no_engine_id_409(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    client, url = _client_with_runtime(tmp_path / "t.db", runtime)
    # A run that has not yet surfaced its engine id has no addressable container.
    run_id = _run(_seed_run(url, status="running", engine_id=None))
    resp = client.post(
        f"/api/v1/runs/{run_id}/exec",
        headers=auth_headers(),
        json={"command": "ls"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "container_unavailable"


# A known secret SHAPE the platform never held (e.g. a value the agent minted or a
# token sitting in the container env). Assembled from fragments so the INV-4
# secret-in-events grep does not flag this test file. The exec endpoint returns
# container stdout VERBATIM, so without redaction this would surface in the UI.
_FAKE_ANTHROPIC = "sk" + "-ant" + "-api03-" + "A" * 40
_FAKE_GH_PAT = "gh" + "p_" + "B" * 36


def test_exec_output_is_redacted(tmp_path: Path) -> None:
    """INV-4 defense-in-depth: a one-shot exec scrubs token shapes from its stdout.

    An operator command like ``env`` could otherwise echo a live model/GitHub token
    straight into the live UI. The platform redactor scrubs the verbatim stdout
    before it leaves the endpoint.
    """
    runtime = FakeRuntime()
    runtime.exec_result = (
        f"ANTHROPIC_API_KEY={_FAKE_ANTHROPIC}\nGITHUB_TOKEN={_FAKE_GH_PAT}\nPATH=/usr/bin\n"
    )
    client, url = _client_with_runtime(tmp_path / "t.db", runtime)
    run_id = _run(_seed_run(url, status="running", engine_id="eng-secret"))

    resp = client.post(
        f"/api/v1/runs/{run_id}/exec",
        headers=auth_headers(),
        json={"command": "env"},
    )
    assert resp.status_code == 200
    output = resp.json()["output"]
    # The secret VALUES are scrubbed; the placeholder is present; benign lines stay.
    assert _FAKE_ANTHROPIC not in output
    assert _FAKE_GH_PAT not in output
    assert "[REDACTED]" in output
    assert "PATH=/usr/bin" in output


def test_exec_error_reason_is_redacted(tmp_path: Path) -> None:
    """INV-4: the failed-command stderr in ``details.reason`` is scrubbed too."""
    runtime = FakeRuntime()
    runtime.exec_error = RuntimeError(f"Command failed (exit 1): echo {_FAKE_ANTHROPIC}")
    client, url = _client_with_runtime(tmp_path / "t.db", runtime)
    run_id = _run(_seed_run(url, status="running", engine_id="eng-fail-secret"))

    resp = client.post(
        f"/api/v1/runs/{run_id}/exec",
        headers=auth_headers(),
        json={"command": "echo secret"},
    )
    assert resp.status_code == 400
    reason = resp.json()["error"]["details"]["reason"]
    assert _FAKE_ANTHROPIC not in reason
    assert "[REDACTED]" in reason
