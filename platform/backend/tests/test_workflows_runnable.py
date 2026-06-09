"""Slice 4.2 / T110 — a registered on-disk component appears **and** is runnable.

The AC-8 integration test (PRD §5.8 FR-07-1v, AT-Workflows). It exercises the
**read-only viewer + the Phase-2 launch path together** end-to-end over the real
app + a migrated SQLite DB:

1. **Author a component on disk** (a ``component.yaml`` + one task ``*.yaml``) and
   **register it** via the engine's ``ComponentRegistry.register`` — exactly the
   "custom component authored on disk" path FR-07-1v promises is supported.
2. Drive the project root through the **real production seam** — set
   ``DKMV_PROJECT_ROOT`` on the settings so the app **lifespan** publishes it on
   ``app.state.project_root`` (exactly as production does), NOT a bare ``app.state``
   injection — and assert the custom component **appears** in ``GET /workflows``
   alongside the five built-ins.
3. Assert ``POST /runs`` against that component **by its registry NAME** (the id the
   viewer surfaces — ``"custom"``, not an absolute path) **dispatches** through the
   normal Phase-2 launch path: the engine ``start(...)`` is invoked with the NAME
   workflow id **and** the INV-5 claim-lock ``runs`` row is created (status
   ``pending``). This proves the end-to-end production path: a registry-name workflow
   resolves only because ``project_root`` is threaded from the lifespan seam into the
   launch path's ``validate_component`` / agent resolution (FIX-3).

The injected runtime both (a) delegates introspection to the **real** engine
functions (pure, read-only, Docker-free) so the viewer lists the registered
component, and (b) records ``start`` and returns a fake handle so the launch never
touches Docker (INV-13). The viewer never writes/registers — only the test's
explicit ``ComponentRegistry.register`` does; the service only *reads* it back.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from alembic import command
from alembic.config import Config
from app.db import Repository
from app.github.client import GitHubClient, Repo, WritePermission
from app.github.provider import set_github_client
from dkmv.registry import ComponentRegistry
from dkmv.runtime import inspect_component, list_components, preview_execution_plan

from tests.conftest import auth_headers, build_client, make_settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dkmv.runtime import ComponentInfo, ExecutionPlan
    from fastapi.testclient import TestClient

_BACKEND_ROOT = Path(__file__).resolve().parents[1]

BUILTINS = {"plan", "dev", "qa", "docs", "ship"}


def _migrate(db_path: Path) -> str:
    url = f"sqlite:///{db_path}"
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


class _FakeHandle:
    """Engine ``RunHandle`` stand-in (mirrors test_runs_launch._FakeHandle).

    ``run_id`` is ``None`` (the engine id back-fills via the event stream); the
    minimal surface the slice-2.3 stream wiring consumes is satisfied so the pump
    idles and the supervisor closes immediately — exactly the no-op a launch-only
    test wants. ``wait`` blocks so the run stays un-finalized (``pending``) at the
    moment ``POST /runs`` returns.
    """

    run_id = None

    def __init__(self) -> None:
        self.observers: list[Any] = []
        self.status = "running"
        self.result = None

    def add_observer(self, observer: Any) -> None:
        self.observers.append(observer)

    async def wait(self, timeout: float | None = None) -> None:
        await asyncio.Event().wait()


class IntrospectStartRuntime:
    """Engine stand-in: real read-only introspection + a recorded ``start``.

    Introspection (``list_components``/``inspect_component``/
    ``preview_execution_plan``) delegates to the **real** engine functions — pure,
    read-only, Docker-free — so the viewer lists the registered custom component.
    ``start`` is recorded and returns a :class:`_FakeHandle` so the launch path
    dispatches without ever constructing a container (INV-13).
    """

    def __init__(self) -> None:
        self.start_calls: list[dict[str, Any]] = []

    def list_components(
        self, project_root: Path | None = None, variables: dict[str, str] | None = None
    ) -> list[ComponentInfo]:
        return list_components(project_root, variables)

    def inspect_component(
        self,
        name_or_path: str,
        project_root: Path | None = None,
        variables: dict[str, str] | None = None,
    ) -> ComponentInfo:
        return inspect_component(name_or_path, project_root, variables)

    def preview_execution_plan(
        self,
        name_or_path: str,
        variables: dict[str, str] | None = None,
        project_root: Path | None = None,
        start_task: str | None = None,
    ) -> ExecutionPlan:
        return preview_execution_plan(name_or_path, variables, project_root, start_task)

    async def start(self, **kwargs: Any) -> _FakeHandle:
        self.start_calls.append(kwargs)
        return _FakeHandle()

    def get_capabilities(self) -> Any:  # pragma: no cover - not under test here
        raise AssertionError("capabilities not under test")


class FakeClient(GitHubClient):
    """A :class:`GitHubClient` whose label replace-all is recorded (no network)."""

    def __init__(self) -> None:
        self.replace_calls: list[tuple[str, int, list[str]]] = []

    async def list_repos(self) -> list[Repo]:  # pragma: no cover - not exercised
        return []

    async def check_write_permission(self, repo: str) -> WritePermission:  # pragma: no cover
        return WritePermission(repo=repo, can_write=True, role="write")

    async def graphql(  # pragma: no cover - not exercised here
        self, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        return {"data": {}}

    async def replace_labels(self, repo: str, num: int, labels: Any) -> list[str]:
        self.replace_calls.append((repo, num, list(labels)))
        return list(labels)


def _author_and_register(project_root: Path) -> Path:
    """Author a minimal custom component on disk + register it; return its dir.

    A one-task component with a component-level ``max_budget_usd`` so the viewer's
    pipeline summary is non-trivial (1 stage / $1.50). The registry write is the
    *test's* explicit ``register`` — the viewer never writes it (read-only).
    """
    (project_root / ".dkmv").mkdir(parents=True, exist_ok=True)
    comp_dir = project_root / "components" / "custom"
    comp_dir.mkdir(parents=True, exist_ok=True)
    (comp_dir / "component.yaml").write_text(
        "name: custom\n"
        "description: a custom workflow authored on disk\n"
        "max_budget_usd: 1.50\n"
        "tasks:\n"
        "  - file: 01-step.yaml\n"
    )
    (comp_dir / "01-step.yaml").write_text(
        "name: step\ndescription: the only step\nprompt: do the thing\n"
    )
    ComponentRegistry.register(project_root, "custom", str(comp_dir))
    return comp_dir


def _client(
    db_path: Path, project_root: Path | None = None
) -> tuple[TestClient, IntrospectStartRuntime]:
    """A TestClient over a fresh migrated DB + the introspect/start runtime + fake GH.

    ``project_root`` is passed as ``DKMV_PROJECT_ROOT`` on the settings so the app
    **lifespan** publishes it on ``app.state.project_root`` through the REAL seam
    (``_resolve_project_root``) — proving the production wiring, not a bare
    ``app.state`` injection.
    """
    url = _migrate(db_path)
    runtime = IntrospectStartRuntime()
    overrides: dict[str, Any] = {"DATABASE_URL": url}
    if project_root is not None:
        overrides["DKMV_PROJECT_ROOT"] = str(project_root)
    client = build_client(settings=make_settings(**overrides), runtime=runtime)
    set_github_client(client.app, FakeClient())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck GitHub client
    return client, runtime


# ── AC-8 / T110: appears in the viewer ────────────────────────────────────────


def test_registered_component_appears_in_workflows(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    _author_and_register(project_root)

    # The project root is published by the LIFESPAN from DKMV_PROJECT_ROOT (the real
    # production seam) — not a bare app.state injection — so the registry resolves.
    client, _runtime = _client(tmp_path / "t.db", project_root=project_root)
    assert client.app.state.project_root == project_root.resolve()

    resp = client.get("/api/v1/workflows", headers=auth_headers())
    assert resp.status_code == 200
    ids = {entry["id"] for entry in resp.json()}
    assert "custom" in ids
    assert BUILTINS <= ids


def test_registered_component_detail_summary(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    _author_and_register(project_root)

    client, _runtime = _client(tmp_path / "t.db", project_root=project_root)

    resp = client.get("/api/v1/workflows/custom", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["id"] == "custom"
    # The component-level max_budget_usd is the authoritative est. total.
    assert body["summary"]["est_total_usd"] == 1.5
    assert body["component_yaml"] is not None


# ── AC-8 / T110: runnable through the Phase-2 launch path ─────────────────────


def test_registered_component_is_runnable(tmp_path: Path) -> None:
    """``POST /runs`` against the registered component BY REGISTRY NAME dispatches.

    Drives the launch BY THE REGISTRY NAME (``"custom"`` — the id ``GET /workflows``
    surfaces), not an absolute path. That id resolves ONLY because the lifespan
    published ``DKMV_PROJECT_ROOT`` on ``app.state.project_root`` and the launch path
    threads it into ``validate_component`` (FIX-3). This is the genuine end-to-end
    production path a user follows: see a registered workflow in the viewer, run it.
    """
    project_root = tmp_path / "proj"
    _author_and_register(project_root)

    client, runtime = _client(tmp_path / "t.db", project_root=project_root)

    # Confirm the viewer surfaces the NAME we then dispatch by (the real id contract).
    listed = client.get("/api/v1/workflows", headers=auth_headers())
    assert "custom" in {entry["id"] for entry in listed.json()}

    resp = client.post(
        "/api/v1/runs",
        json={
            "issue_num": 42,
            "repo": "o/r",
            "workflow_id": "custom",
            "agent": "claude",
            "branch": "dkmv/issue-42-custom",
            "feature_name": "issue-42-custom",
        },
        headers=auth_headers(),
    )
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["run_id"]
    assert run_id

    # Engine ``start(...)`` was invoked exactly once for the registered component,
    # addressed BY ITS REGISTRY NAME (proving NAME resolution, not a path).
    assert len(runtime.start_calls) == 1
    assert runtime.start_calls[0]["component"] == "custom"

    # The INV-5 claim-lock ``runs`` row exists (a real, dispatched run).
    async def _row_count() -> int:
        repository: Repository = client.app.state.repository
        async with repository.read_connection() as conn:
            rows = await conn.execute_fetchall(
                "SELECT id, status FROM runs WHERE id = ?", (run_id,)
            )
        return len(list(rows))

    assert asyncio.new_event_loop().run_until_complete(_row_count()) == 1
