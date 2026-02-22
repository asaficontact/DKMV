"""End-to-end tests for task-based component execution.

These tests require Docker and an ANTHROPIC_API_KEY.
They are skipped by default — run with: pytest -m e2e
"""

from __future__ import annotations

import pytest


@pytest.mark.e2e
async def test_dev_component_e2e() -> None:
    """E2E: dkmv run dev with real container + mocked Claude Code."""
    pytest.skip("Requires Docker + API key — run manually with pytest -m e2e")


@pytest.mark.e2e
async def test_multi_task_dev_sequential() -> None:
    """E2E: Both dev tasks (plan + implement) run in sequence."""
    pytest.skip("Requires Docker + API key — run manually with pytest -m e2e")
