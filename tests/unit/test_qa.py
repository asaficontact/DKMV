from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from dkmv.components import get_component
from dkmv.components.qa import QAComponent, QAConfig, QAResult
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
        default_model="claude-sonnet-4-6",
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
            "message": {"content": [{"type": "text", "text": "QA running..."}]},
        }
        yield {
            "type": "result",
            "total_cost_usd": 0.03,
            "duration_ms": 3000,
            "num_turns": 2,
            "session_id": "sess-qa",
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
) -> QAComponent:
    return QAComponent(
        global_config=global_config,
        sandbox=mock_sandbox,
        run_manager=run_manager,
        stream_parser=stream_parser,
    )


@pytest.fixture
def prd_file(tmp_path: Path) -> Path:
    prd = tmp_path / "prd.md"
    prd.write_text(
        "## Requirements\nBuild feature X\n\n## Evaluation Criteria\nTest coverage > 80%\n"
    )
    return prd


@pytest.fixture
def config(prd_file: Path) -> QAConfig:
    return QAConfig(
        repo="https://github.com/test/repo.git",
        branch="feature/test",
        prd_path=prd_file,
        timeout_minutes=5,
    )


# --- Model Tests ---


class TestQAModels:
    def test_qa_config_requires_prd_path(self) -> None:
        with pytest.raises(Exception):
            QAConfig(repo="https://github.com/test/repo.git", branch="feat")  # type: ignore[call-arg]

    def test_qa_result_defaults(self) -> None:
        result = QAResult(run_id="test", component="qa")
        assert result.tests_total == 0
        assert result.tests_passed == 0
        assert result.tests_failed == 0
        assert result.warnings == []

    def test_qa_result_json_roundtrip(self) -> None:
        result = QAResult(
            run_id="test",
            component="qa",
            tests_total=10,
            tests_passed=8,
            tests_failed=2,
            warnings=["Missing edge case test"],
        )
        data = result.model_dump_json()
        restored = QAResult.model_validate_json(data)
        assert restored.tests_total == 10
        assert restored.warnings == ["Missing edge case test"]


# --- Workspace Setup ---


class TestQAWorkspaceSetup:
    async def test_full_prd_written_to_container(
        self, component: QAComponent, config: QAConfig, mock_sandbox: AsyncMock
    ) -> None:
        await component.run(config)

        write_calls = mock_sandbox.write_file.call_args_list
        prd_calls = [c for c in write_calls if ".dkmv/prd.md" in str(c)]
        assert len(prd_calls) > 0
        # QA gets FULL PRD (including eval criteria)
        content = prd_calls[0].args[2] if len(prd_calls[0].args) > 2 else ""
        if not content:
            for arg in prd_calls[0].args:
                if isinstance(arg, str) and "Requirements" in arg:
                    content = arg
                    break
        assert "Evaluation Criteria" in content


# --- Git Teardown with Artifacts ---


class TestQAGitTeardown:
    async def test_qa_report_force_committed(
        self, component: QAComponent, mock_sandbox: AsyncMock, config: QAConfig
    ) -> None:
        async def execute_side_effect(*args: Any, **kwargs: Any) -> CommandResult:
            cmd = args[1] if len(args) > 1 else kwargs.get("command", "")
            if "porcelain" in str(cmd):
                return CommandResult(output="M file.py", exit_code=0)
            return CommandResult(output="", exit_code=0)

        mock_sandbox.execute = AsyncMock(side_effect=execute_side_effect)
        mock_sandbox.setup_git_auth = AsyncMock(return_value=CommandResult(output="", exit_code=0))

        await component.run(config)

        calls = [str(c) for c in mock_sandbox.execute.call_args_list]
        force_add_calls = [c for c in calls if "git add -f" in c and "qa_report" in c]
        assert len(force_add_calls) > 0


# --- Prompt ---


class TestQAPrompt:
    def test_prompt_loads(self, component: QAComponent, config: QAConfig) -> None:
        prompt = component.build_prompt(config)
        assert "QA engineer" in prompt
        assert "qa_report.json" in prompt


# --- Parse Result ---


class TestParseResult:
    def test_parse_result_from_raw(self, component: QAComponent, config: QAConfig) -> None:
        raw = {"tests_total": 10, "tests_passed": 8, "tests_failed": 2, "warnings": ["warn"]}
        result = component.parse_result(raw, config)
        assert result.tests_total == 10
        assert result.warnings == ["warn"]

    def test_parse_result_empty(self, component: QAComponent, config: QAConfig) -> None:
        result = component.parse_result({}, config)
        assert result.tests_total == 0


# --- Registration ---


class TestRegistration:
    def test_qa_registered(self) -> None:
        cls = get_component("qa")
        assert cls is QAComponent


# --- Artifact Collection ---


class TestArtifactCollection:
    async def test_qa_report_read_from_container(
        self, component: QAComponent, config: QAConfig, mock_sandbox: AsyncMock
    ) -> None:
        import json

        report_data = {"tests_total": 10, "tests_passed": 8, "tests_failed": 2, "warnings": ["w"]}
        mock_sandbox.read_file = AsyncMock(return_value=json.dumps(report_data))

        result = await component.run(config)
        assert result.status == "completed"
        assert result.tests_total == 10
        assert result.tests_passed == 8
        assert result.tests_failed == 2
        assert result.warnings == ["w"]

    async def test_missing_report_does_not_fail(
        self, component: QAComponent, config: QAConfig, mock_sandbox: AsyncMock
    ) -> None:
        mock_sandbox.read_file = AsyncMock(side_effect=Exception("not found"))
        result = await component.run(config)
        assert result.status == "completed"


# --- Lifecycle ---


class TestQALifecycle:
    async def test_happy_path(self, component: QAComponent, config: QAConfig) -> None:
        result = await component.run(config)
        assert result.status == "completed"
        assert isinstance(result, QAResult)
        assert result.component == "qa"
