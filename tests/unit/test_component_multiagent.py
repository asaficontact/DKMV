"""Tests for mixed-agent component scenarios (T074)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dkmv.adapters import get_adapter
from dkmv.tasks.manifest import ComponentManifest, ManifestTaskRef


class TestAgentsNeededScanning:
    """Test agents_needed computation from manifest data."""

    def test_agents_needed_from_manifest_agent(self) -> None:
        manifest = ComponentManifest(
            name="test",
            agent="codex",
            tasks=[ManifestTaskRef(file="task1.yaml")],
        )
        agents_needed: set[str] = set()
        if manifest.agent:
            agents_needed.add(manifest.agent)
        for ref in manifest.tasks:
            if ref.agent:
                agents_needed.add(ref.agent)
        assert agents_needed == {"codex"}

    def test_agents_needed_mixed_manifest(self) -> None:
        manifest = ComponentManifest(
            name="test",
            agent="claude",
            tasks=[
                ManifestTaskRef(file="plan.yaml", agent="claude"),
                ManifestTaskRef(file="implement.yaml", agent="codex"),
            ],
        )
        agents_needed: set[str] = set()
        if manifest.agent:
            agents_needed.add(manifest.agent)
        for ref in manifest.tasks:
            if ref.agent:
                agents_needed.add(ref.agent)
        assert agents_needed == {"claude", "codex"}

    def test_agents_needed_single_agent_component(self) -> None:
        manifest = ComponentManifest(
            name="test",
            agent="claude",
            tasks=[
                ManifestTaskRef(file="task1.yaml"),
                ManifestTaskRef(file="task2.yaml"),
            ],
        )
        agents_needed: set[str] = set()
        if manifest.agent:
            agents_needed.add(manifest.agent)
        for ref in manifest.tasks:
            if ref.agent:
                agents_needed.add(ref.agent)
        assert agents_needed == {"claude"}

    def test_agents_needed_no_manifest_agent(self) -> None:
        """No manifest agent — only task-ref agents are collected."""
        manifest = ComponentManifest(
            name="test",
            tasks=[
                ManifestTaskRef(file="task1.yaml", agent="claude"),
                ManifestTaskRef(file="task2.yaml", agent="codex"),
            ],
        )
        agents_needed: set[str] = set()
        if manifest.agent:
            agents_needed.add(manifest.agent)
        for ref in manifest.tasks:
            if ref.agent:
                agents_needed.add(ref.agent)
        assert agents_needed == {"claude", "codex"}


class TestBuildSandboxConfigMultiAgent:
    """Test _build_sandbox_config() with multiple agents."""

    def _make_runner(self) -> object:
        from dkmv.tasks.component import ComponentRunner

        return ComponentRunner(
            sandbox=MagicMock(),
            run_manager=MagicMock(),
            task_loader=MagicMock(),
            task_runner=MagicMock(),
            console=MagicMock(),
        )

    def test_single_claude_agent_includes_anthropic_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dkmv.config import DKMVConfig

        runner = self._make_runner()
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        config = DKMVConfig()
        config.anthropic_api_key = "sk-ant-test"
        config.auth_method = "api_key"

        sandbox_config, _ = runner._build_sandbox_config(config, 30, {"claude"})  # type: ignore[attr-defined]
        assert "ANTHROPIC_API_KEY" in sandbox_config.env_vars
        assert sandbox_config.env_vars["ANTHROPIC_API_KEY"] == "sk-ant-test"

    def test_codex_agent_includes_codex_key(self) -> None:
        from dkmv.config import DKMVConfig

        runner = self._make_runner()
        config = DKMVConfig()
        config.codex_api_key = "sk-codex-test"
        config.auth_method = "api_key"

        sandbox_config, _ = runner._build_sandbox_config(config, 30, {"codex"})  # type: ignore[attr-defined]
        assert "CODEX_API_KEY" in sandbox_config.env_vars
        assert sandbox_config.env_vars["CODEX_API_KEY"] == "sk-codex-test"

    def test_mixed_agents_include_both_keys(self) -> None:
        from dkmv.config import DKMVConfig

        runner = self._make_runner()
        config = DKMVConfig()
        config.anthropic_api_key = "sk-ant-test"
        config.codex_api_key = "sk-codex-test"
        config.auth_method = "api_key"

        sandbox_config, _ = runner._build_sandbox_config(config, 30, {"claude", "codex"})  # type: ignore[attr-defined]
        assert "ANTHROPIC_API_KEY" in sandbox_config.env_vars
        assert "CODEX_API_KEY" in sandbox_config.env_vars

    def test_default_agents_needed_is_claude(self) -> None:
        from dkmv.config import DKMVConfig

        runner = self._make_runner()
        config = DKMVConfig()
        config.anthropic_api_key = "sk-ant-test"
        config.auth_method = "api_key"

        sandbox_config, _ = runner._build_sandbox_config(config, 30)  # type: ignore[attr-defined]
        assert "ANTHROPIC_API_KEY" in sandbox_config.env_vars

    def test_github_token_always_included(self) -> None:
        from dkmv.config import DKMVConfig

        runner = self._make_runner()
        config = DKMVConfig()
        config.anthropic_api_key = "sk-ant-test"
        config.github_token = "ghp-test"
        config.auth_method = "api_key"

        sandbox_config, _ = runner._build_sandbox_config(config, 30, {"claude"})  # type: ignore[attr-defined]
        assert "GITHUB_TOKEN" in sandbox_config.env_vars
        assert sandbox_config.env_vars["GITHUB_TOKEN"] == "ghp-test"


class TestMultiAgentGitignore:
    """Test gitignore entries for multiple agents."""

    def test_claude_adapter_gitignore_entries(self) -> None:
        adapter = get_adapter("claude")
        assert ".claude/" in adapter.gitignore_entries

    def test_codex_adapter_gitignore_entries(self) -> None:
        adapter = get_adapter("codex")
        assert ".codex/" in adapter.gitignore_entries

    def test_mixed_agents_gitignore_entries(self) -> None:
        """Mixed-agent components get both .claude/ and .codex/ entries."""
        agents_needed = {"claude", "codex"}
        seen: set[str] = set()
        entries: list[str] = []
        for agent_name in agents_needed:
            for entry in get_adapter(agent_name).gitignore_entries:
                if entry not in seen:
                    seen.add(entry)
                    entries.append(entry)
        assert ".claude/" in entries
        assert ".codex/" in entries

    def test_single_agent_has_no_duplicate_entries(self) -> None:
        """Single-agent component only includes that agent's entries."""
        agents_needed = {"claude"}
        seen: set[str] = set()
        entries: list[str] = []
        for agent_name in agents_needed:
            for entry in get_adapter(agent_name).gitignore_entries:
                if entry not in seen:
                    seen.add(entry)
                    entries.append(entry)
        assert ".claude/" in entries
        assert ".codex/" not in entries
