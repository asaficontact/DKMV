"""E2E test for the Dev component pipeline.

Requires Docker and ANTHROPIC_API_KEY to be available.
Marked with @pytest.mark.e2e — skipped in regular test runs.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dkmv.components.dev import DevComponent, DevConfig
from dkmv.config import DKMVConfig
from dkmv.core.runner import RunManager
from dkmv.core.sandbox import SandboxManager
from dkmv.core.stream import StreamParser

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
async def test_dev_pipeline_trivial_prd(tmp_path: Path) -> None:
    """Run Dev component with a trivial PRD to verify the full pipeline."""
    # Create a trivial PRD
    prd_path = tmp_path / "prd.md"
    prd_path.write_text(
        "## Requirements\n"
        "Add a function `greet(name: str) -> str` that returns "
        "'Hello, {name}!' to `src/greet.py`.\n\n"
        "## Evaluation Criteria\n"
        "- Function exists and returns correct greeting\n"
    )

    config_obj = DKMVConfig()
    dev_config = DevConfig(
        repo="https://github.com/octocat/Hello-World.git",
        prd_path=prd_path,
        feature_name="greet",
        model="claude-haiku-4-5-20251001",
        max_turns=10,
        timeout_minutes=10,
    )

    sandbox = SandboxManager()
    run_mgr = RunManager(output_dir=tmp_path / "outputs")
    parser = StreamParser(verbose=True)
    component = DevComponent(
        global_config=config_obj,
        sandbox=sandbox,
        run_manager=run_mgr,
        stream_parser=parser,
    )

    result = await component.run(dev_config)

    assert result.run_id
    assert result.component == "dev"
    assert result.status in ("completed", "failed")
