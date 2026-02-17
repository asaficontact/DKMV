from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from dkmv.components import get_component
from dkmv.components.docs import DocsComponent, DocsConfig, DocsResult
from dkmv.config import DKMVConfig
from dkmv.core.runner import RunManager
from dkmv.core.sandbox import CommandResult, SandboxManager, SandboxSession
from dkmv.core.stream import StreamParser


# --- Fixtures ---


@pytest.fixture
def global_config() -> DKMVConfig:
    return DKMVConfig.model_construct(
        anthropic_api_key="sk-ant-test",
        github_token="ghp_test",
        default_model="claude-sonnet-4-20250514",
        default_max_turns=10,
        image_name="dkmv-sandbox:latest",
        output_dir=Path("./outputs"),
        timeout_minutes=5,
        memory_limit="4g",
    )


@pytest.fixture
def mock_sandbox() -> AsyncMock:
    sandbox = AsyncMock(spec=SandboxManager)
    mock_session = MagicMock(spec=SandboxSession)
    mock_session.deployment = MagicMock()
    mock_session.container_name = "test-container"
    sandbox.start = AsyncMock(return_value=mock_session)
    sandbox.execute = AsyncMock(return_value=CommandResult(output="", exit_code=0))
    sandbox.write_file = AsyncMock()
    sandbox.read_file = AsyncMock(return_value="")
    sandbox.stop = AsyncMock()
    sandbox.setup_git_auth = AsyncMock(return_value=CommandResult(output="", exit_code=0))
    sandbox.get_container_name = MagicMock(return_value="test-container")

    async def mock_stream(**kwargs: Any) -> Any:
        yield {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Documenting..."}]},
        }
        yield {
            "type": "result",
            "total_cost_usd": 0.02,
            "duration_ms": 2000,
            "num_turns": 2,
            "session_id": "sess-docs",
            "is_error": False,
        }

    sandbox.stream_claude = mock_stream
    return sandbox


@pytest.fixture
def run_manager(tmp_path: Path) -> RunManager:
    return RunManager(output_dir=tmp_path)


@pytest.fixture
def stream_parser() -> StreamParser:
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=120)
    return StreamParser(console=console)


@pytest.fixture
def component(
    global_config: DKMVConfig,
    mock_sandbox: AsyncMock,
    run_manager: RunManager,
    stream_parser: StreamParser,
) -> DocsComponent:
    return DocsComponent(
        global_config=global_config,
        sandbox=mock_sandbox,
        run_manager=run_manager,
        stream_parser=stream_parser,
    )


@pytest.fixture
def config() -> DocsConfig:
    return DocsConfig(
        repo="https://github.com/test/repo.git",
        branch="feature/test-docs",
        timeout_minutes=5,
    )


# --- Model Tests ---


class TestDocsModels:
    def test_docs_config_no_prd_required(self) -> None:
        config = DocsConfig(
            repo="https://github.com/test/repo.git",
            branch="feat",
        )
        assert not hasattr(config, "prd_path")

    def test_docs_config_create_pr_defaults(self) -> None:
        config = DocsConfig(repo="https://github.com/test/repo.git", branch="feat")
        assert config.create_pr is False
        assert config.pr_base == "main"

    def test_docs_result_defaults(self) -> None:
        result = DocsResult(run_id="test", component="docs")
        assert result.docs_generated == []
        assert result.pr_url is None

    def test_docs_result_json_roundtrip(self) -> None:
        result = DocsResult(
            run_id="test",
            component="docs",
            docs_generated=["README.md", "API.md"],
            pr_url="https://github.com/test/repo/pull/1",
        )
        data = result.model_dump_json()
        restored = DocsResult.model_validate_json(data)
        assert restored.docs_generated == ["README.md", "API.md"]
        assert restored.pr_url == "https://github.com/test/repo/pull/1"


# --- Prompt ---


class TestDocsPrompt:
    def test_prompt_loads(self, component: DocsComponent, config: DocsConfig) -> None:
        prompt = component.build_prompt(config)
        assert "technical writer" in prompt
        assert "documentation" in prompt.lower()


# --- Parse Result ---


class TestParseResult:
    def test_parse_result_from_raw(self, component: DocsComponent, config: DocsConfig) -> None:
        raw = {
            "docs_generated": ["README.md"],
            "pr_url": "https://github.com/test/repo/pull/1",
        }
        result = component.parse_result(raw, config)
        assert result.docs_generated == ["README.md"]
        assert result.pr_url == "https://github.com/test/repo/pull/1"

    def test_parse_result_empty(self, component: DocsComponent, config: DocsConfig) -> None:
        result = component.parse_result({}, config)
        assert result.docs_generated == []
        assert result.pr_url is None


# --- PR Creation ---


class TestPRCreation:
    async def test_pr_created_when_flag_set(
        self, component: DocsComponent, mock_sandbox: AsyncMock
    ) -> None:
        mock_sandbox.execute = AsyncMock(
            return_value=CommandResult(output="https://github.com/test/repo/pull/42", exit_code=0)
        )
        mock_sandbox.setup_git_auth = AsyncMock(return_value=CommandResult(output="", exit_code=0))

        config = DocsConfig(
            repo="https://github.com/test/repo.git",
            branch="feature/docs",
            create_pr=True,
            timeout_minutes=5,
        )
        result = await component.run(config)
        assert result.pr_url == "https://github.com/test/repo/pull/42"

    async def test_no_pr_when_flag_not_set(
        self, component: DocsComponent, config: DocsConfig
    ) -> None:
        result = await component.run(config)
        assert result.pr_url is None

    async def test_pr_creation_failure_does_not_crash(
        self, component: DocsComponent, mock_sandbox: AsyncMock
    ) -> None:
        call_count = 0

        async def execute_side_effect(*args: Any, **kwargs: Any) -> CommandResult:
            nonlocal call_count
            call_count += 1
            cmd = args[1] if len(args) > 1 else kwargs.get("command", "")
            if "gh pr create" in str(cmd):
                return CommandResult(output="", exit_code=1)
            return CommandResult(output="", exit_code=0)

        mock_sandbox.execute = AsyncMock(side_effect=execute_side_effect)
        mock_sandbox.setup_git_auth = AsyncMock(return_value=CommandResult(output="", exit_code=0))

        config = DocsConfig(
            repo="https://github.com/test/repo.git",
            branch="feature/docs",
            create_pr=True,
            timeout_minutes=5,
        )
        result = await component.run(config)
        assert result.status == "completed"
        assert result.pr_url is None


class TestShellInjection:
    async def test_branch_with_metacharacters_quoted(
        self, component: DocsComponent, mock_sandbox: AsyncMock
    ) -> None:
        mock_sandbox.execute = AsyncMock(
            return_value=CommandResult(output="https://github.com/test/repo/pull/1", exit_code=0)
        )
        mock_sandbox.setup_git_auth = AsyncMock(return_value=CommandResult(output="", exit_code=0))

        config = DocsConfig(
            repo="https://github.com/test/repo.git",
            branch="feat/$(whoami)",
            create_pr=True,
            timeout_minutes=5,
        )
        await component.run(config)

        calls = [str(c) for c in mock_sandbox.execute.call_args_list]
        pr_calls = [c for c in calls if "gh pr create" in c]
        assert len(pr_calls) > 0
        assert "'feat/$(whoami)'" in pr_calls[0]

    async def test_pr_base_with_metacharacters_quoted(
        self, component: DocsComponent, mock_sandbox: AsyncMock
    ) -> None:
        mock_sandbox.execute = AsyncMock(
            return_value=CommandResult(output="https://github.com/test/repo/pull/1", exit_code=0)
        )
        mock_sandbox.setup_git_auth = AsyncMock(return_value=CommandResult(output="", exit_code=0))

        config = DocsConfig(
            repo="https://github.com/test/repo.git",
            branch="feat/docs",
            pr_base="main;rm -rf /",
            create_pr=True,
            timeout_minutes=5,
        )
        await component.run(config)

        calls = [str(c) for c in mock_sandbox.execute.call_args_list]
        pr_calls = [c for c in calls if "gh pr create" in c]
        assert len(pr_calls) > 0
        assert "'main;rm -rf /'" in pr_calls[0]


# --- Registration ---


class TestRegistration:
    def test_docs_registered(self) -> None:
        cls = get_component("docs")
        assert cls is DocsComponent


# --- Lifecycle ---


class TestDocsLifecycle:
    async def test_happy_path(self, component: DocsComponent, config: DocsConfig) -> None:
        result = await component.run(config)
        assert result.status == "completed"
        assert isinstance(result, DocsResult)
        assert result.component == "docs"

    async def test_error_saves_failed(
        self, component: DocsComponent, config: DocsConfig, mock_sandbox: AsyncMock
    ) -> None:
        mock_sandbox.start = AsyncMock(side_effect=RuntimeError("Container failed"))
        result = await component.run(config)
        assert result.status == "failed"
        assert "Container failed" in result.error_message
