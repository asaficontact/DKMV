"""Slice 4.1 — read-only Workflows viewer API (F12 / PRD §5.8 FR-07-1v, §6.2).

Covers:

* **AC-1** — ``GET /workflows`` lists the five built-ins (``plan/dev/qa/docs/ship``)
  via the engine's ``list_components``; ``GET /workflows/{id}`` returns the pipeline
  summary (stages / per-stage budget / pause points / est. total) **plus** the
  ``component.yaml`` + task YAML text; an unknown id → ``404 workflow_not_found``.
* **AC-4** — the ``qa`` component reports **3 stages / 1 pause (after Evaluate) /
  $2.00 total** (the $2.00 component-level ``max_budget_usd`` is authoritative; the
  per-stage split is not asserted).
* **AC-2 (ADR-P010, read-only)** — no ``POST``/``PUT`` ``/workflows`` route exists
  (404/405); the service writes/registers/validates-to-save nothing.
* **AC-3 / INV-13** — introspection flows in-process through ``RunService`` (the
  engine's own ``list_components``/``inspect_component``/``preview_execution_plan``),
  never the CLI.
* **INV-1 (SECURITY_CHECKS)** — the new GET routes inherit app access control: a
  foreign ``Host`` → 403; a missing token → 401.

The injected runtime is a duck-typed stand-in whose introspection methods delegate
to the **real** engine introspection functions (pure, read-only, no Docker), so the
tests exercise the real pipeline-summary derivation without a sandbox.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.runtime import RunService
from app.workflows import WorkflowService
from app.workflows.service import WorkflowNotFoundError
from dkmv.runtime import (
    inspect_component,
    list_components,
    preview_execution_plan,
)

from tests.conftest import TEST_TOKEN, auth_headers, build_client, make_settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dkmv.runtime import ComponentInfo, ExecutionPlan

BUILTINS = {"plan", "dev", "qa", "docs", "ship"}


class IntrospectRuntime:
    """Engine stand-in whose introspection delegates to the real engine functions.

    The real ``list_components``/``inspect_component``/``preview_execution_plan`` are
    pure, read-only, and Docker-free, so the API tests exercise the true
    pipeline-summary derivation without constructing a sandbox-bound runtime.
    """

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

    def get_capabilities(self) -> Any:  # pragma: no cover - not under test here
        raise AssertionError("capabilities not under test")


def _client() -> Any:
    return build_client(runtime=IntrospectRuntime(), raise_server_exceptions=True)


def _service() -> WorkflowService:
    settings = make_settings()
    return WorkflowService(RunService(settings, runtime=IntrospectRuntime()))  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed introspection runtime


# ── AC-1: list lists the five built-ins ──────────────────────────────────────


def test_list_returns_five_builtins() -> None:
    resp = _client().get("/api/v1/workflows", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    ids = {entry["id"] for entry in body}
    assert BUILTINS <= ids


def test_list_entries_carry_summary_fields() -> None:
    body = _client().get("/api/v1/workflows", headers=auth_headers()).json()
    entry = next(e for e in body if e["id"] == "qa")
    assert set(entry) >= {
        "id",
        "name",
        "stages",
        "stage_count",
        "pause_count",
        "pause_points",
        "est_total_usd",
    }
    assert isinstance(entry["stages"], list) and entry["stages"]
    for stage in entry["stages"]:
        assert {"index", "name", "pause_after"} <= set(stage)


# ── AC-1: detail returns summary + YAML text + 404 on unknown ─────────────────


def test_detail_returns_summary_and_yaml() -> None:
    resp = _client().get("/api/v1/workflows/qa", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["id"] == "qa"
    assert body["component_yaml"] is not None
    assert body["component_yaml"]["filename"] in {"component.yaml", "component.yml"}
    assert "max_budget_usd" in body["component_yaml"]["content"]
    assert isinstance(body["task_yaml"], list) and body["task_yaml"]
    for doc in body["task_yaml"]:
        assert doc["filename"].endswith((".yaml", ".yml"))
        assert isinstance(doc["content"], str) and doc["content"]


def test_detail_unknown_id_returns_404_envelope() -> None:
    resp = _client().get("/api/v1/workflows/does-not-exist", headers=auth_headers())
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "workflow_not_found"


# ── AC-4: qa summary — 3 stages / 1 pause (after Evaluate) / $2.00 total ──────


def test_qa_summary_three_stages_one_pause_two_dollars() -> None:
    body = _client().get("/api/v1/workflows/qa", headers=auth_headers()).json()
    summary = body["summary"]
    assert summary["stage_count"] == 3
    assert summary["pause_count"] == 1
    # The single pause point is after the first (Evaluate) stage.
    assert len(summary["pause_points"]) == 1
    first_stage = summary["stages"][0]
    assert first_stage["pause_after"] is True
    assert summary["pause_points"][0] == first_stage["name"]
    # $2.00 component-level max_budget_usd is the authoritative total (§7.2).
    assert summary["est_total_usd"] == 2.0


def test_qa_summary_via_service_layer() -> None:
    detail = _service().get_workflow("qa")
    assert detail.summary.stage_count == 3
    assert detail.summary.pause_count == 1
    assert detail.summary.est_total_usd == 2.0
    assert detail.summary.stages[0].pause_after is True


def test_service_unknown_id_raises() -> None:
    import pytest

    with pytest.raises(WorkflowNotFoundError):
        _service().get_workflow("nope-not-real")


# ── AC-2 / ADR-P010: no write endpoint exists (read-only) ─────────────────────


def test_no_post_workflows_route() -> None:
    resp = _client().post(
        "/api/v1/workflows",
        json={"name": "x"},
        headers={**auth_headers(), "Origin": "http://127.0.0.1"},
    )
    assert resp.status_code in {404, 405}


def test_no_put_workflows_route() -> None:
    resp = _client().put(
        "/api/v1/workflows/qa",
        json={"name": "x"},
        headers={**auth_headers(), "Origin": "http://127.0.0.1"},
    )
    assert resp.status_code in {404, 405}


# ── AC-3 / INV-13: introspection is in-process via RunService ─────────────────


def test_service_uses_run_service_runtime() -> None:
    settings = make_settings()
    runtime = IntrospectRuntime()
    run_service = RunService(settings, runtime=runtime)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed introspection runtime
    service = WorkflowService(run_service)
    # The service reaches the engine only through the injected RunService's runtime.
    assert run_service.runtime is runtime
    summaries = service.list_workflows()
    assert {s.id for s in summaries} >= BUILTINS


# ── INV-1 (SECURITY_CHECKS): the GET routes are behind app access control ─────


def test_workflows_foreign_host_forbidden() -> None:
    client = build_client(runtime=IntrospectRuntime(), host="evil.example.com")
    resp = client.get("/api/v1/workflows", headers=auth_headers())
    assert resp.status_code == 403


def test_workflows_missing_token_unauthorized() -> None:
    resp = _client().get("/api/v1/workflows")
    assert resp.status_code == 401


def test_workflows_detail_missing_token_unauthorized() -> None:
    resp = _client().get("/api/v1/workflows/qa")
    assert resp.status_code == 401


def test_workflows_token_value_not_in_summary() -> None:
    # Defensive: the summary never echoes the platform token.
    body = _client().get("/api/v1/workflows", headers=auth_headers()).text
    assert TEST_TOKEN not in body


# ── Registered on-disk custom component appears (custom-resolution path) ──────


def test_registered_custom_component_appears(tmp_path: Path) -> None:
    """A component authored on disk + ``ComponentRegistry.register`` is listed.

    Exercises the ``project_root`` registry-resolution path the engine's
    ``list_components`` uses for custom components (the data path AC-8/T110 builds
    on). Read-only: the service only *reads* what ``register`` wrote.
    """
    from dkmv.registry import ComponentRegistry

    project_root = tmp_path / "proj"
    (project_root / ".dkmv").mkdir(parents=True)
    comp_dir = project_root / "components" / "custom"
    comp_dir.mkdir(parents=True)
    (comp_dir / "component.yaml").write_text(
        "name: custom\ndescription: a custom workflow\n"
        "max_budget_usd: 1.50\n"
        "tasks:\n  - file: 01-step.yaml\n    pause_after: true\n"
    )
    (comp_dir / "01-step.yaml").write_text(
        "name: step\ndescription: the only step\nprompt: do the thing\n"
    )
    ComponentRegistry.register(project_root, "custom", str(comp_dir))

    settings = make_settings()
    service = WorkflowService(
        RunService(settings, runtime=IntrospectRuntime()),  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed introspection runtime
        project_root=project_root,
    )
    summaries = service.list_workflows()
    ids = {s.id for s in summaries}
    assert "custom" in ids
    assert BUILTINS <= ids

    detail = service.get_workflow("custom")
    assert detail.summary.id == "custom"
    assert detail.summary.est_total_usd == 1.5
    assert detail.summary.pause_count == 1
    assert detail.component_yaml is not None
