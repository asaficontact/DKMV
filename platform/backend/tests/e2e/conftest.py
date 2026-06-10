"""Shared helpers for the §13 e2e suite (slice 5.4).

Builds a real authed :class:`TestClient` over a fresh migrated DB plus a
**same-DB** :class:`Repository` the test can seed through, so the HTTP-level ATs
(Connect / Board / Launch / History / CodexCost) exercise the real API reading the
rows the test wrote. Reuses the root conftest's ``build_client`` / ``make_settings``
/ ``auth_headers`` so the e2e client is the same loopback-pinned, lifespan-entered
app the unit suite uses (INV-1).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest_asyncio
from app.db import Repository
from app.github.provider import set_github_client
from dkmv.runtime import (
    inspect_component,
    list_components,
    preview_execution_plan,
)
from fastapi.testclient import TestClient

from tests.conftest import _migrate, build_client, make_settings
from tests.unit.test_runs_launch import FakeClient, FakeRuntime

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path as _PathT

    from dkmv.runtime import ComponentInfo, ExecutionPlan


class IntrospectFakeRuntime(FakeRuntime):
    """The launch fake (records ``start``) PLUS real, Docker-free engine introspection.

    The Workflows viewer AT reads through ``RunService`` → the engine's read-only
    ``list_components`` / ``inspect_component`` / ``preview_execution_plan``; those
    are pure and need no sandbox (INV-13), so the e2e harness delegates them to the
    real engine functions while keeping ``start`` faked (no Docker).
    """

    def list_components(
        self, project_root: _PathT | None = None, variables: dict[str, str] | None = None
    ) -> list[ComponentInfo]:
        return list_components(project_root, variables)

    def inspect_component(
        self,
        name_or_path: str,
        project_root: _PathT | None = None,
        variables: dict[str, str] | None = None,
    ) -> ComponentInfo:
        return inspect_component(name_or_path, project_root, variables)

    def preview_execution_plan(
        self,
        name_or_path: str,
        project_root: _PathT | None = None,
        variables: dict[str, str] | None = None,
    ) -> ExecutionPlan:
        return preview_execution_plan(name_or_path, project_root, variables)


@dataclass(slots=True)
class E2EHarness:
    """A live app client + the engine/GitHub fakes + a same-DB seed repository."""

    client: TestClient
    runtime: IntrospectFakeRuntime
    github: FakeClient
    repository: Repository
    database_url: str


@pytest_asyncio.fixture
async def harness(tmp_path: Path) -> AsyncIterator[E2EHarness]:
    """A real app (fake engine + fake GitHub) + a same-DB Repository to seed through.

    The client enters the app lifespan over its own migrated DB; the returned
    :class:`Repository` is opened on the SAME ``DATABASE_URL`` so a test can seed
    ``runs`` / ``events`` rows the HTTP endpoints then read back (the board/history
    ATs). No Docker, no engine (INV-13).
    """
    url = _migrate(tmp_path / "e2e.db")
    runtime = IntrospectFakeRuntime()
    client = build_client(settings=make_settings(DATABASE_URL=url), runtime=runtime)
    github = FakeClient()
    set_github_client(client.app, github)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed client
    repository = Repository(url)
    await repository.start()
    try:
        yield E2EHarness(
            client=client,
            runtime=runtime,
            github=github,
            repository=repository,
            database_url=url,
        )
    finally:
        await repository.close()


def run_body(**overrides: Any) -> dict[str, Any]:
    """A valid ``POST /runs`` body for the launch ATs; overrides patch fields."""
    base: dict[str, Any] = {
        "issue_num": 7,
        "repo": "o/r",
        "workflow_id": "qa",
        "agent": "claude",
        "branch": "dkmv/issue-7-fix",
        "feature_name": "issue-7-fix",
    }
    base.update(overrides)
    return base
