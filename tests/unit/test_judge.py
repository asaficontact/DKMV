from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from dkmv.components import get_component
from dkmv.components.judge import (
    JudgeComponent,
    JudgeConfig,
    JudgeIssue,
    JudgeResult,
    PrdRequirement,
)
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

    async def mock_stream(**kwargs: Any) -> Any:
        yield {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Judging..."}]},
        }
        yield {
            "type": "result",
            "total_cost_usd": 0.04,
            "duration_ms": 4000,
            "num_turns": 2,
            "session_id": "sess-judge",
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
) -> JudgeComponent:
    return JudgeComponent(
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
def config(prd_file: Path) -> JudgeConfig:
    return JudgeConfig(
        repo="https://github.com/test/repo.git",
        branch="feature/test",
        prd_path=prd_file,
        timeout_minutes=5,
    )


# --- Model Tests ---


class TestJudgeModels:
    def test_judge_config_requires_prd_path(self) -> None:
        with pytest.raises(Exception):
            JudgeConfig(repo="https://github.com/test/repo.git", branch="feat")  # type: ignore[call-arg]

    def test_judge_result_defaults(self) -> None:
        result = JudgeResult(run_id="test", component="judge")
        assert result.verdict == "fail"
        assert result.confidence == 0.0
        assert result.reasoning == ""
        assert result.prd_requirements == []
        assert result.issues == []
        assert result.suggestions == []
        assert result.score == 0

    def test_judge_result_pass(self) -> None:
        result = JudgeResult(
            run_id="test",
            component="judge",
            verdict="pass",
            confidence=0.95,
            reasoning="All good",
            score=92,
        )
        assert result.verdict == "pass"
        assert result.confidence == 0.95
        assert result.score == 92

    def test_judge_result_with_issues(self) -> None:
        result = JudgeResult(
            run_id="test",
            component="judge",
            verdict="fail",
            reasoning="Issues found",
            issues=[
                JudgeIssue(severity="critical", description="Missing auth check"),
                JudgeIssue(severity="low", description="Typo in comment"),
            ],
            suggestions=["Add auth middleware"],
        )
        assert len(result.issues) == 2
        assert result.issues[0].severity == "critical"
        assert result.issues[0].description == "Missing auth check"
        assert result.suggestions == ["Add auth middleware"]

    def test_judge_result_with_prd_requirements(self) -> None:
        result = JudgeResult(
            run_id="test",
            component="judge",
            verdict="pass",
            prd_requirements=[
                PrdRequirement(requirement="Auth", status="implemented", notes="Done"),
                PrdRequirement(requirement="Logging", status="partial"),
            ],
        )
        assert len(result.prd_requirements) == 2
        assert result.prd_requirements[0].status == "implemented"
        assert result.prd_requirements[1].status == "partial"

    def test_judge_issue_defaults(self) -> None:
        issue = JudgeIssue(description="test")
        assert issue.severity == "medium"
        assert issue.file == ""
        assert issue.line is None
        assert issue.suggestion == ""

    def test_judge_issue_with_line(self) -> None:
        issue = JudgeIssue(severity="high", description="bug", file="foo.py", line=42)
        assert issue.line == 42

    def test_prd_requirement_defaults(self) -> None:
        req = PrdRequirement(requirement="Auth")
        assert req.status == "missing"
        assert req.notes == ""

    def test_judge_result_json_roundtrip(self) -> None:
        result = JudgeResult(
            run_id="test",
            component="judge",
            verdict="pass",
            confidence=0.85,
            reasoning="Looks great",
            prd_requirements=[PrdRequirement(requirement="Auth", status="implemented")],
            issues=[JudgeIssue(severity="low", description="minor", line=10)],
            score=88,
        )
        data = result.model_dump_json()
        restored = JudgeResult.model_validate_json(data)
        assert restored.verdict == "pass"
        assert restored.confidence == 0.85
        assert len(restored.issues) == 1
        assert restored.issues[0].line == 10
        assert len(restored.prd_requirements) == 1
        assert restored.score == 88


# --- Workspace Setup ---


class TestJudgeWorkspaceSetup:
    async def test_full_prd_written_to_container(
        self, component: JudgeComponent, config: JudgeConfig, mock_sandbox: AsyncMock
    ) -> None:
        await component.run(config)

        write_calls = mock_sandbox.write_file.call_args_list
        prd_calls = [c for c in write_calls if ".dkmv/prd.md" in str(c)]
        assert len(prd_calls) > 0
        content = prd_calls[0].args[2] if len(prd_calls[0].args) > 2 else ""
        if not content:
            for arg in prd_calls[0].args:
                if isinstance(arg, str) and "Requirements" in arg:
                    content = arg
                    break
        assert "Evaluation Criteria" in content


# --- Git Teardown with Artifacts ---


class TestJudgeGitTeardown:
    async def test_verdict_force_committed(
        self, component: JudgeComponent, mock_sandbox: AsyncMock, config: JudgeConfig
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
        force_add_calls = [c for c in calls if "git add -f" in c and "verdict" in c]
        assert len(force_add_calls) > 0


# --- Prompt ---


class TestJudgePrompt:
    def test_prompt_loads(self, component: JudgeComponent, config: JudgeConfig) -> None:
        prompt = component.build_prompt(config)
        assert "independent judge" in prompt
        assert "verdict.json" in prompt

    def test_prompt_includes_confidence(
        self, component: JudgeComponent, config: JudgeConfig
    ) -> None:
        prompt = component.build_prompt(config)
        assert "confidence" in prompt

    def test_prompt_includes_prd_requirements(
        self, component: JudgeComponent, config: JudgeConfig
    ) -> None:
        prompt = component.build_prompt(config)
        assert "prd_requirements" in prompt


# --- Parse Result ---


class TestParseResult:
    def test_parse_pass_verdict(self, component: JudgeComponent, config: JudgeConfig) -> None:
        raw = {
            "verdict": "pass",
            "confidence": 0.9,
            "reasoning": "All requirements met",
            "issues": [],
            "score": 95,
        }
        result = component.parse_result(raw, config)
        assert result.verdict == "pass"
        assert result.confidence == 0.9
        assert result.reasoning == "All requirements met"
        assert result.score == 95

    def test_parse_fail_verdict(self, component: JudgeComponent, config: JudgeConfig) -> None:
        raw = {
            "verdict": "fail",
            "confidence": 0.8,
            "reasoning": "Missing tests",
            "prd_requirements": [
                {"requirement": "Auth", "status": "implemented"},
            ],
            "issues": [{"severity": "high", "description": "No tests", "line": 42}],
            "suggestions": ["Add tests"],
            "score": 40,
        }
        result = component.parse_result(raw, config)
        assert result.verdict == "fail"
        assert result.confidence == 0.8
        assert len(result.issues) == 1
        assert result.issues[0].severity == "high"
        assert result.issues[0].line == 42
        assert len(result.prd_requirements) == 1
        assert result.suggestions == ["Add tests"]
        assert result.score == 40

    def test_parse_empty(self, component: JudgeComponent, config: JudgeConfig) -> None:
        result = component.parse_result({}, config)
        assert result.verdict == "fail"  # Default
        assert result.confidence == 0.0
        assert result.score == 0


# --- Registration ---


class TestRegistration:
    def test_judge_registered(self) -> None:
        cls = get_component("judge")
        assert cls is JudgeComponent


# --- Artifact Collection ---


class TestArtifactCollection:
    async def test_verdict_read_from_container(
        self, component: JudgeComponent, config: JudgeConfig, mock_sandbox: AsyncMock
    ) -> None:
        import json

        verdict_data = {
            "verdict": "pass",
            "confidence": 0.92,
            "reasoning": "All good",
            "prd_requirements": [{"requirement": "Auth", "status": "implemented"}],
            "issues": [],
            "suggestions": [],
            "score": 90,
        }
        mock_sandbox.read_file = AsyncMock(return_value=json.dumps(verdict_data))

        result = await component.run(config)
        assert result.status == "completed"
        assert result.verdict == "pass"
        assert result.confidence == 0.92
        assert result.reasoning == "All good"
        assert result.score == 90
        assert len(result.prd_requirements) == 1

    async def test_missing_verdict_does_not_fail(
        self, component: JudgeComponent, config: JudgeConfig, mock_sandbox: AsyncMock
    ) -> None:
        mock_sandbox.read_file = AsyncMock(side_effect=Exception("not found"))
        result = await component.run(config)
        assert result.status == "completed"
        assert result.verdict == "fail"  # Default


# --- Lifecycle ---


class TestJudgeLifecycle:
    async def test_happy_path(self, component: JudgeComponent, config: JudgeConfig) -> None:
        result = await component.run(config)
        assert result.status == "completed"
        assert isinstance(result, JudgeResult)
        assert result.component == "judge"
