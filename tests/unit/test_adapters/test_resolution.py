"""Tests for 7-level agent resolution cascade."""

from __future__ import annotations

import pytest

from dkmv.tasks.models import TaskDefinition, CLIOverrides
from dkmv.tasks.manifest import ManifestTaskRef, ComponentManifest
from dkmv.tasks.component import ComponentRunner


# ---------------------------------------------------------------------------
# Runtime resolution (levels 4-7): task.agent → cli.agent → config → default
# ---------------------------------------------------------------------------


def test_resolution_task_yaml_wins_over_cli():
    """Level 1 (task YAML) beats level 4 (CLI)."""
    task = TaskDefinition(name="test", agent="codex")
    cli = CLIOverrides(agent="claude")
    resolved = task.agent or cli.agent or "claude"
    assert resolved == "codex"


def test_resolution_cli_wins_over_default():
    """Level 4 (CLI) beats built-in default."""
    task = TaskDefinition(name="test")
    cli = CLIOverrides(agent="codex")
    resolved = task.agent or cli.agent or "claude"
    assert resolved == "codex"


def test_resolution_no_agent_defaults_to_claude():
    """No agent at any level → built-in default 'claude'."""
    task = TaskDefinition(name="test")
    cli = CLIOverrides()
    resolved = task.agent or cli.agent or "claude"
    assert resolved == "claude"


def test_resolution_all_levels_set_task_yaml_wins():
    """When all levels set, task YAML wins."""
    task = TaskDefinition(name="test", agent="codex")
    cli = CLIOverrides(agent="claude")
    config_default = "claude"
    resolved = task.agent or cli.agent or config_default
    assert resolved == "codex"


def test_resolution_config_default_used():
    """config.default_agent used when task and CLI have none."""
    task = TaskDefinition(name="test")
    cli = CLIOverrides()
    config_default_agent = "codex"
    resolved = task.agent or cli.agent or config_default_agent
    assert resolved == "codex"


# ---------------------------------------------------------------------------
# Manifest-level resolution (levels 1-3): task YAML → task_ref → manifest
# ---------------------------------------------------------------------------


def test_manifest_task_ref_agent_propagates_to_task():
    """Level 2: task_ref.agent sets task.agent when task has none."""
    task = TaskDefinition(name="test")
    manifest = ComponentManifest(name="comp")
    task_ref = ManifestTaskRef(file="task.yaml", agent="codex")

    ComponentRunner._apply_manifest_defaults(task, manifest, task_ref)

    assert task.agent == "codex"


def test_manifest_component_agent_propagates_to_task():
    """Level 3: manifest.agent sets task.agent when task and task_ref have none."""
    task = TaskDefinition(name="test")
    manifest = ComponentManifest(name="comp", agent="codex")
    task_ref = ManifestTaskRef(file="task.yaml")

    ComponentRunner._apply_manifest_defaults(task, manifest, task_ref)

    assert task.agent == "codex"


def test_task_yaml_agent_not_overridden_by_task_ref():
    """Level 1: task YAML agent beats task_ref agent."""
    task = TaskDefinition(name="test", agent="claude")
    manifest = ComponentManifest(name="comp")
    task_ref = ManifestTaskRef(file="task.yaml", agent="codex")

    ComponentRunner._apply_manifest_defaults(task, manifest, task_ref)

    assert task.agent == "claude"  # Not overridden


def test_task_ref_agent_beats_manifest_agent():
    """Level 2: task_ref.agent beats manifest.agent."""
    task = TaskDefinition(name="test")
    manifest = ComponentManifest(name="comp", agent="claude")
    task_ref = ManifestTaskRef(file="task.yaml", agent="codex")

    ComponentRunner._apply_manifest_defaults(task, manifest, task_ref)

    assert task.agent == "codex"


def test_no_manifest_agent_task_remains_none():
    """When manifest and task_ref have no agent, task.agent stays None."""
    task = TaskDefinition(name="test")
    manifest = ComponentManifest(name="comp")
    task_ref = ManifestTaskRef(file="task.yaml")

    ComponentRunner._apply_manifest_defaults(task, manifest, task_ref)

    assert task.agent is None


def test_no_task_ref_falls_back_to_manifest():
    """No task_ref → falls back to manifest.agent."""
    task = TaskDefinition(name="test")
    manifest = ComponentManifest(name="comp", agent="codex")

    ComponentRunner._apply_manifest_defaults(task, manifest, None)

    assert task.agent == "codex"


# ---------------------------------------------------------------------------
# Full cascade simulation (all 7 levels)
# ---------------------------------------------------------------------------


def test_full_cascade_task_yaml_level_1_wins():
    """Simulate full 7-level cascade where task YAML wins."""
    # Setup manifest defaults (levels 1-3)
    task = TaskDefinition(name="test", agent="codex")
    manifest = ComponentManifest(name="comp", agent="claude")
    task_ref = ManifestTaskRef(file="task.yaml", agent="claude")
    ComponentRunner._apply_manifest_defaults(task, manifest, task_ref)

    # Runtime resolution (levels 4-7)
    cli = CLIOverrides(agent="claude")
    config_default = "claude"
    resolved = task.agent or cli.agent or config_default

    assert resolved == "codex"  # Task YAML level wins


def test_full_cascade_manifest_level_3_falls_to_cli():
    """Manifest sets agent; runtime CLI also set → manifest wins (it set task.agent first)."""
    task = TaskDefinition(name="test")
    manifest = ComponentManifest(name="comp", agent="codex")
    task_ref = ManifestTaskRef(file="task.yaml")
    ComponentRunner._apply_manifest_defaults(task, manifest, task_ref)

    # task.agent is now "codex" from manifest
    cli = CLIOverrides(agent="claude")
    config_default = "claude"
    resolved = task.agent or cli.agent or config_default

    assert resolved == "codex"  # Manifest (level 3) propagated to task.agent
