from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from dkmv.components import get_component
from dkmv.components.dev import DevComponent, DevConfig, DevResult
from dkmv.components.dev.component import _strip_eval_criteria
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
            "message": {"content": [{"type": "text", "text": "Working..."}]},
        }
        yield {
            "type": "result",
            "total_cost_usd": 0.05,
            "duration_ms": 5000,
            "num_turns": 3,
            "session_id": "sess-test",
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
) -> DevComponent:
    return DevComponent(
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
def config(prd_file: Path) -> DevConfig:
    return DevConfig(
        repo="https://github.com/test/repo.git",
        branch="feature/test-dev",
        feature_name="test-feature",
        prd_path=prd_file,
        timeout_minutes=5,
    )


# --- Model Tests ---


class TestDevModels:
    def test_dev_config_requires_prd_path(self) -> None:
        with pytest.raises(Exception):
            DevConfig(repo="https://github.com/test/repo.git")  # type: ignore[call-arg]

    def test_dev_config_with_all_fields(self, prd_file: Path, tmp_path: Path) -> None:
        feedback = tmp_path / "feedback.json"
        feedback.write_text("{}")
        docs = tmp_path / "design_docs"
        docs.mkdir()

        config = DevConfig(
            repo="https://github.com/test/repo.git",
            prd_path=prd_file,
            feedback_path=feedback,
            design_docs_path=docs,
        )
        assert config.prd_path == prd_file
        assert config.feedback_path == feedback
        assert config.design_docs_path == docs

    def test_dev_config_optional_fields_default_none(self, prd_file: Path) -> None:
        config = DevConfig(repo="https://github.com/test/repo.git", prd_path=prd_file)
        assert config.feedback_path is None
        assert config.design_docs_path is None

    def test_dev_result_defaults(self) -> None:
        result = DevResult(run_id="test", component="dev")
        assert result.files_changed == []
        assert result.tests_passed is None
        assert result.tests_failed is None

    def test_dev_result_json_roundtrip(self) -> None:
        result = DevResult(
            run_id="test",
            component="dev",
            files_changed=["a.py", "b.py"],
            tests_passed=5,
            tests_failed=1,
        )
        data = result.model_dump_json()
        restored = DevResult.model_validate_json(data)
        assert restored.files_changed == ["a.py", "b.py"]
        assert restored.tests_passed == 5


# --- Eval Criteria Stripping ---


class TestEvalCriteriaStripping:
    def test_strips_eval_section(self) -> None:
        prd = "## Requirements\nBuild X\n\n## Evaluation Criteria\nTest Y\n"
        result = _strip_eval_criteria(prd)
        assert "Requirements" in result
        assert "Evaluation Criteria" not in result

    def test_preserves_prd_without_eval(self) -> None:
        prd = "## Requirements\nBuild X\n"
        result = _strip_eval_criteria(prd)
        assert result.strip() == prd.strip()

    def test_strips_eval_at_end_of_file(self) -> None:
        prd = "## Reqs\nBuild\n\n## Evaluation Criteria\nCriteria here\n"
        result = _strip_eval_criteria(prd)
        assert "Criteria here" not in result
        assert "Reqs" in result

    def test_strips_eval_between_sections(self) -> None:
        prd = "## Intro\nHello\n\n## Evaluation Criteria\nStuff\n\n## Other Section\nMore content\n"
        result = _strip_eval_criteria(prd)
        assert "Evaluation Criteria" not in result
        assert "Intro" in result
        assert "Other Section" in result


# --- Branch Derivation ---


class TestBranchDerivation:
    async def test_auto_branch_from_feature_name(
        self, component: DevComponent, mock_sandbox: AsyncMock, prd_file: Path
    ) -> None:
        config = DevConfig(
            repo="https://github.com/test/repo.git",
            feature_name="login",
            prd_path=prd_file,
            timeout_minutes=5,
        )
        result = await component.run(config)
        assert result.branch == "feature/login-dev"

    async def test_auto_branch_from_prd_filename(
        self, component: DevComponent, mock_sandbox: AsyncMock, prd_file: Path
    ) -> None:
        config = DevConfig(
            repo="https://github.com/test/repo.git",
            prd_path=prd_file,
            timeout_minutes=5,
        )
        # prd_file.stem = "prd"
        result = await component.run(config)
        assert result.branch == f"feature/{prd_file.stem}-dev"

    async def test_explicit_branch_not_overridden(
        self, component: DevComponent, mock_sandbox: AsyncMock, prd_file: Path
    ) -> None:
        config = DevConfig(
            repo="https://github.com/test/repo.git",
            branch="custom/branch",
            prd_path=prd_file,
            timeout_minutes=5,
        )
        result = await component.run(config)
        assert result.branch == "custom/branch"

    async def test_auto_branch_checkout_happens(
        self, component: DevComponent, mock_sandbox: AsyncMock, prd_file: Path
    ) -> None:
        """Verify auto-derived branch is actually used in git checkout."""
        config = DevConfig(
            repo="https://github.com/test/repo.git",
            feature_name="login",
            prd_path=prd_file,
            timeout_minutes=5,
        )
        await component.run(config)

        calls = [str(c) for c in mock_sandbox.execute.call_args_list]
        checkout_calls = [c for c in calls if "checkout" in c]
        assert len(checkout_calls) > 0
        assert "feature/login-dev" in checkout_calls[0]


# --- Workspace Setup ---


class TestDevWorkspaceSetup:
    async def test_prd_written_to_container(
        self, component: DevComponent, config: DevConfig, mock_sandbox: AsyncMock
    ) -> None:
        await component.run(config)

        write_calls = mock_sandbox.write_file.call_args_list
        prd_calls = [c for c in write_calls if "prd.md" in str(c) and "CLAUDE" not in str(c)]
        assert len(prd_calls) > 0

    async def test_prd_stripped_of_eval_criteria(
        self, component: DevComponent, config: DevConfig, mock_sandbox: AsyncMock
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
        assert "Evaluation Criteria" not in content


class TestDesignDocs:
    async def test_design_docs_copied_to_container(
        self,
        component: DevComponent,
        mock_sandbox: AsyncMock,
        prd_file: Path,
        tmp_path: Path,
    ) -> None:
        docs_dir = tmp_path / "design_docs"
        docs_dir.mkdir()
        (docs_dir / "arch.md").write_text("Architecture doc")

        config = DevConfig(
            repo="https://github.com/test/repo.git",
            branch="feature/test",
            prd_path=prd_file,
            design_docs_path=docs_dir,
            timeout_minutes=5,
        )
        await component.run(config)

        write_calls = mock_sandbox.write_file.call_args_list
        doc_calls = [c for c in write_calls if "design_docs" in str(c)]
        assert len(doc_calls) > 0

    def test_prompt_includes_design_docs_section(
        self, component: DevComponent, prd_file: Path, tmp_path: Path
    ) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        config = DevConfig(
            repo="https://github.com/test/repo.git",
            prd_path=prd_file,
            design_docs_path=docs_dir,
            timeout_minutes=5,
        )
        prompt = component.build_prompt(config)
        assert "Design Documents" in prompt

    def test_prompt_no_design_docs_section_when_none(
        self, component: DevComponent, prd_file: Path
    ) -> None:
        config = DevConfig(
            repo="https://github.com/test/repo.git",
            prd_path=prd_file,
            timeout_minutes=5,
        )
        prompt = component.build_prompt(config)
        assert "Design Documents" not in prompt


class TestFeedbackInjection:
    async def test_feedback_copied_to_container(
        self,
        component: DevComponent,
        mock_sandbox: AsyncMock,
        prd_file: Path,
        tmp_path: Path,
    ) -> None:
        feedback_file = tmp_path / "feedback.json"
        feedback_file.write_text('{"items": []}')

        config = DevConfig(
            repo="https://github.com/test/repo.git",
            branch="feature/test",
            prd_path=prd_file,
            feedback_path=feedback_file,
            timeout_minutes=5,
        )
        await component.run(config)

        write_calls = mock_sandbox.write_file.call_args_list
        feedback_calls = [c for c in write_calls if "feedback.json" in str(c)]
        assert len(feedback_calls) > 0

    def test_prompt_includes_feedback_section(
        self, component: DevComponent, prd_file: Path, tmp_path: Path
    ) -> None:
        feedback_file = tmp_path / "feedback.json"
        feedback_file.write_text("{}")
        config = DevConfig(
            repo="https://github.com/test/repo.git",
            prd_path=prd_file,
            feedback_path=feedback_file,
            timeout_minutes=5,
        )
        prompt = component.build_prompt(config)
        assert "Previous Feedback" in prompt

    def test_prompt_no_feedback_section_when_none(
        self, component: DevComponent, prd_file: Path
    ) -> None:
        config = DevConfig(
            repo="https://github.com/test/repo.git",
            prd_path=prd_file,
            timeout_minutes=5,
        )
        prompt = component.build_prompt(config)
        assert "Previous Feedback" not in prompt


# --- Parse Result ---


class TestParseResult:
    def test_parse_result_from_raw(self, component: DevComponent, config: DevConfig) -> None:
        raw = {"files_changed": ["a.py"], "tests_passed": 5, "tests_failed": 0}
        result = component.parse_result(raw, config)
        assert result.files_changed == ["a.py"]
        assert result.tests_passed == 5
        assert result.tests_failed == 0

    def test_parse_result_empty(self, component: DevComponent, config: DevConfig) -> None:
        result = component.parse_result({}, config)
        assert result.files_changed == []
        assert result.tests_passed is None


# --- Registration ---


class TestRegistration:
    def test_dev_registered(self) -> None:
        cls = get_component("dev")
        assert cls is DevComponent


# --- Plan Capture ---


class TestPlanCapture:
    async def test_plan_captured_to_run_dir(
        self, component: DevComponent, config: DevConfig, mock_sandbox: AsyncMock
    ) -> None:
        mock_sandbox.read_file = AsyncMock(return_value="# My Plan\nDo stuff")
        result = await component.run(config)

        run_dir = component.run_manager._run_dir(result.run_id)
        plan_file = run_dir / "plan.md"
        assert plan_file.exists()
        assert "My Plan" in plan_file.read_text()

    async def test_missing_plan_does_not_fail(
        self, component: DevComponent, config: DevConfig, mock_sandbox: AsyncMock
    ) -> None:
        mock_sandbox.read_file = AsyncMock(side_effect=Exception("File not found"))
        result = await component.run(config)
        assert result.status == "completed"


# --- Full Lifecycle ---


class TestDevLifecycle:
    async def test_happy_path(self, component: DevComponent, config: DevConfig) -> None:
        result = await component.run(config)
        assert result.status == "completed"
        assert isinstance(result, DevResult)
        assert result.component == "dev"

    async def test_error_saves_failed(
        self, component: DevComponent, config: DevConfig, mock_sandbox: AsyncMock
    ) -> None:
        mock_sandbox.start = AsyncMock(side_effect=RuntimeError("Container boom"))
        result = await component.run(config)
        assert result.status == "failed"
        assert "Container boom" in result.error_message
