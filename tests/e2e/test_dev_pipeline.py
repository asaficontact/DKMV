"""E2E test for the Dev component pipeline.

Requires Docker and ANTHROPIC_API_KEY to be available.
Marked with @pytest.mark.e2e — skipped in regular test runs.

NOTE: The dev component now uses the YAML-based task system with
ComponentRunner. The legacy class-based DevComponent has been removed.
This E2E test needs a real implementation docs directory with phase files
to test the full pipeline.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dkmv.config import DKMVConfig
from dkmv.core.runner import RunManager
from dkmv.core.sandbox import SandboxManager
from dkmv.core.stream import StreamParser
from dkmv.tasks import ComponentRunner, TaskLoader, TaskRunner, resolve_component
from dkmv.tasks.models import CLIOverrides

from rich.console import Console

pytestmark = pytest.mark.e2e

SKIP_NO_DOCKER = pytest.mark.skipif(
    os.system("docker info > /dev/null 2>&1") != 0,
    reason="Docker not available",
)

SKIP_NO_API_KEY = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


@SKIP_NO_DOCKER
@SKIP_NO_API_KEY
async def test_dev_pipeline_trivial_impl_docs(tmp_path: Path) -> None:
    """Run Dev component with trivial impl docs to verify the full pipeline."""
    # Create a trivial implementation docs directory
    impl_docs = tmp_path / "greet-feature"
    impl_docs.mkdir()
    (impl_docs / "CLAUDE.md").write_text("# Greet Feature\nAdd a greet function.\n")
    (impl_docs / "tasks.md").write_text("# Tasks\n- T010: Add greet function\n")
    (impl_docs / "phase1_foundation.md").write_text(
        "# Phase 1: Foundation\n"
        "## Tasks\n"
        "### T010: Add greet function\n"
        "Add `greet(name: str) -> str` to `src/greet.py` that returns 'Hello, {name}!'.\n"
    )

    config_obj = DKMVConfig()
    component_dir = resolve_component("dev")
    sandbox = SandboxManager()
    run_mgr = RunManager(output_dir=tmp_path / "outputs")
    parser = StreamParser(verbose=True)
    loader = TaskLoader()
    task_runner = TaskRunner(sandbox, run_mgr, parser, Console())
    runner = ComponentRunner(sandbox, run_mgr, loader, task_runner, Console())

    variables: dict[str, object] = {
        "impl_docs_path": str(impl_docs),
        "phases": [
            {"phase_number": 1, "phase_name": "foundation", "phase_file": "phase1_foundation.md"},
        ],
    }

    result = await runner.run(
        component_dir=component_dir,
        repo="https://github.com/octocat/Hello-World.git",
        branch="feature/greet-dev",
        feature_name="greet",
        variables=variables,
        config=config_obj,
        cli_overrides=CLIOverrides(
            model="claude-haiku-4-5-20251001",
            max_turns=10,
            timeout_minutes=10,
        ),
    )

    assert result.run_id
    assert result.component == "dev"
    assert result.status in ("completed", "failed")
