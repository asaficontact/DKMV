from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from dkmv.components import get_component, list_components, register_component
from dkmv.components.base import BaseComponent
from dkmv.config import DKMVConfig
from dkmv.core.models import BaseComponentConfig, BaseResult, ComponentName
from dkmv.core.runner import RunManager
from dkmv.core.sandbox import CommandResult, SandboxManager, SandboxSession
from dkmv.core.stream import StreamParser


# --- Mock Component for testing ---


class MockConfig(BaseComponentConfig):
    extra_field: str = "test"


class MockResult(BaseResult):
    custom_data: str = ""


class MockComponent(BaseComponent[MockConfig, MockResult]):
    @property
    def name(self) -> ComponentName:
        return "dev"

    def build_prompt(self, config: MockConfig) -> str:
        return f"Implement {config.feature_name}"

    def parse_result(self, raw_result: dict[str, Any], config: MockConfig) -> MockResult:
        return MockResult(
            run_id="",
            component="dev",
            custom_data=raw_result.get("custom", ""),
        )


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

    # stream_claude yields a result event
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
) -> MockComponent:
    return MockComponent(
        global_config=global_config,
        sandbox=mock_sandbox,
        run_manager=run_manager,
        stream_parser=stream_parser,
    )


@pytest.fixture
def config() -> MockConfig:
    return MockConfig(
        repo="https://github.com/test/repo.git",
        branch="feature/auth",
        feature_name="user-auth",
        timeout_minutes=5,
    )


# --- Full Lifecycle Tests ---


class TestRunLifecycle:
    async def test_happy_path_full_lifecycle(
        self, component: MockComponent, config: MockConfig
    ) -> None:
        result = await component.run(config)

        assert isinstance(result, MockResult)
        assert result.status == "completed"
        assert result.total_cost_usd == 0.05
        assert result.num_turns == 3
        assert result.session_id == "sess-test"
        assert result.repo == config.repo
        assert result.branch == config.branch
        assert result.feature_name == config.feature_name

    async def test_run_creates_run_directory(
        self, component: MockComponent, config: MockConfig
    ) -> None:
        result = await component.run(config)
        run_dir = component.run_manager._run_dir(result.run_id)
        assert run_dir.exists()
        assert (run_dir / "config.json").exists()

    async def test_error_saves_failed_result(
        self, component: MockComponent, config: MockConfig, mock_sandbox: AsyncMock
    ) -> None:
        mock_sandbox.start = AsyncMock(side_effect=RuntimeError("Container failed"))

        result = await component.run(config)

        assert result.status == "failed"
        assert "Container failed" in result.error_message
        # Result should still be saved
        result_file = component.run_manager._run_dir(result.run_id) / "result.json"
        assert result_file.exists()

    async def test_timeout_saves_timed_out_result(
        self, component: MockComponent, config: MockConfig, mock_sandbox: AsyncMock
    ) -> None:
        mock_sandbox.start = AsyncMock(side_effect=TimeoutError())

        result = await component.run(config)

        assert result.status == "timed_out"
        assert result.error_message == "Component timed out"

    async def test_container_cleanup_on_error(
        self, component: MockComponent, config: MockConfig, mock_sandbox: AsyncMock
    ) -> None:
        async def failing_stream(**kwargs: Any) -> Any:
            raise RuntimeError("Stream failed")
            yield  # type: ignore[misc]  # noqa: F841

        mock_sandbox.stream_claude = failing_stream

        result = await component.run(config)

        assert result.status == "failed"
        mock_sandbox.stop.assert_awaited_once()

    async def test_prompt_saved_to_run_directory(
        self, component: MockComponent, config: MockConfig
    ) -> None:
        result = await component.run(config)
        prompt_file = component.run_manager._run_dir(result.run_id) / "prompt.md"
        assert prompt_file.exists()
        assert "user-auth" in prompt_file.read_text()

    async def test_stream_events_appended(
        self, component: MockComponent, config: MockConfig
    ) -> None:
        result = await component.run(config)
        stream_file = component.run_manager._run_dir(result.run_id) / "stream.jsonl"
        assert stream_file.exists()
        lines = stream_file.read_text().strip().splitlines()
        assert len(lines) == 2  # assistant + result events


class TestWorkspaceSetup:
    async def test_clones_repo(
        self, component: MockComponent, config: MockConfig, mock_sandbox: AsyncMock
    ) -> None:
        await component.run(config)

        calls = [str(c) for c in mock_sandbox.execute.call_args_list]
        clone_calls = [c for c in calls if "git clone" in c]
        assert len(clone_calls) > 0

    async def test_branch_checkout(
        self, component: MockComponent, config: MockConfig, mock_sandbox: AsyncMock
    ) -> None:
        await component.run(config)

        calls = [str(c) for c in mock_sandbox.execute.call_args_list]
        branch_calls = [c for c in calls if "feature/auth" in c and "checkout" in c]
        assert len(branch_calls) > 0

    async def test_branch_not_checked_out_when_none(
        self, component: MockComponent, mock_sandbox: AsyncMock
    ) -> None:
        config = MockConfig(repo="https://github.com/test/repo.git", branch=None)
        await component.run(config)

        calls = [str(c) for c in mock_sandbox.execute.call_args_list]
        checkout_calls = [c for c in calls if "checkout" in c]
        assert len(checkout_calls) == 0


class TestClaudeMd:
    async def test_claude_md_written(
        self, component: MockComponent, config: MockConfig, mock_sandbox: AsyncMock
    ) -> None:
        await component.run(config)

        mock_sandbox.write_file.assert_awaited()
        write_calls = mock_sandbox.write_file.call_args_list
        claude_md_calls = [c for c in write_calls if "CLAUDE.md" in str(c)]
        assert len(claude_md_calls) > 0

        # Check content
        content = claude_md_calls[0].args[2] if len(claude_md_calls[0].args) > 2 else ""
        if not content:
            content = claude_md_calls[0].kwargs.get("content", "")
        assert "dev" in content
        assert "dkmv-dev" in content

    async def test_claude_md_with_prd(
        self, component: MockComponent, mock_sandbox: AsyncMock
    ) -> None:
        class PrdConfig(MockConfig):
            prd_path: str = ""

        config = PrdConfig(
            repo="https://github.com/test/repo.git",
            prd_path="/path/to/prd.md",
        )
        await component.run(config)

        write_calls = mock_sandbox.write_file.call_args_list
        claude_md_calls = [c for c in write_calls if "CLAUDE.md" in str(c)]
        content = claude_md_calls[0].args[2] if len(claude_md_calls[0].args) > 2 else ""
        if not content:
            content = claude_md_calls[0].kwargs.get("content", "")
        assert "prd.md" in content


class TestGitTeardown:
    async def test_commits_and_pushes(
        self, component: MockComponent, config: MockConfig, mock_sandbox: AsyncMock
    ) -> None:
        # Make porcelain return something so commit happens
        async def execute_side_effect(*args: Any, **kwargs: Any) -> CommandResult:
            cmd = args[1] if len(args) > 1 else kwargs.get("command", "")
            if "porcelain" in str(cmd):
                return CommandResult(output="M file.py", exit_code=0)
            return CommandResult(output="", exit_code=0)

        mock_sandbox.execute = AsyncMock(side_effect=execute_side_effect)
        mock_sandbox.setup_git_auth = AsyncMock(return_value=CommandResult(output="", exit_code=0))

        await component.run(config)

        calls = [str(c) for c in mock_sandbox.execute.call_args_list]
        commit_calls = [c for c in calls if "git commit" in c]
        push_calls = [c for c in calls if "git push" in c]
        assert len(commit_calls) > 0
        assert len(push_calls) > 0

    async def test_nothing_to_commit(
        self, component: MockComponent, config: MockConfig, mock_sandbox: AsyncMock
    ) -> None:
        # porcelain returns empty — default mock already does this
        result = await component.run(config)
        assert result.status == "completed"

        calls = [str(c) for c in mock_sandbox.execute.call_args_list]
        commit_calls = [c for c in calls if "git commit" in c]
        assert len(commit_calls) == 0


class TestFeedbackSynthesis:
    def test_sorts_by_severity(self) -> None:
        verdict = {
            "issues": [
                {"severity": "low", "description": "Minor style issue"},
                {"severity": "critical", "description": "Security vulnerability"},
                {"severity": "medium", "description": "Missing tests"},
            ]
        }
        feedback = BaseComponent.synthesize_feedback(verdict)
        # Filter to only bullet lines
        bullets = [line for line in feedback.splitlines() if line.startswith("- ")]
        assert "CRITICAL" in bullets[0]
        assert "MEDIUM" in bullets[1]
        assert "LOW" in bullets[2]

    def test_empty_verdict(self) -> None:
        feedback = BaseComponent.synthesize_feedback({"issues": []})
        assert "Feedback from Judge" in feedback


class TestValidation:
    async def test_empty_repo_raises(self, component: MockComponent) -> None:
        config = MockConfig(repo="")
        with pytest.raises(ValueError, match="repo is required"):
            await component.run(config)

    async def test_zero_timeout_raises(self, component: MockComponent) -> None:
        config = MockConfig(repo="https://github.com/test/repo.git", timeout_minutes=0)
        with pytest.raises(ValueError, match="timeout_minutes must be positive"):
            await component.run(config)


class TestComponentRegistry:
    def test_register_and_get(self) -> None:
        @register_component("test_comp")
        class TestComp(MockComponent):
            pass

        assert get_component("test_comp") is TestComp
        # Cleanup
        from dkmv.components import _REGISTRY

        del _REGISTRY["test_comp"]

    def test_get_unknown_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="Unknown component"):
            get_component("nonexistent_xyz")

    def test_list_components(self) -> None:
        from dkmv.components import _REGISTRY

        _REGISTRY["aaa"] = MockComponent  # type: ignore[assignment]
        _REGISTRY["zzz"] = MockComponent  # type: ignore[assignment]
        names = list_components()
        assert names == sorted(names)
        del _REGISTRY["aaa"]
        del _REGISTRY["zzz"]


class TestLoadPromptTemplate:
    def test_existing_template_loads(self, component: MockComponent) -> None:
        # MockComponent.name == "dev" which now has a real template
        content = component._load_prompt_template()
        assert "senior software engineer" in content

    def test_missing_template_raises(
        self,
        global_config: DKMVConfig,
        mock_sandbox: AsyncMock,
        run_manager: RunManager,
        stream_parser: StreamParser,
    ) -> None:
        import importlib.resources

        class NoTemplateComponent(BaseComponent[MockConfig, MockResult]):
            @property
            def name(self) -> ComponentName:
                return "dev"

            def build_prompt(self, config: MockConfig) -> str:
                return ""

            def parse_result(self, raw_result: dict[str, Any], config: MockConfig) -> MockResult:
                return MockResult(run_id="", component="dev")

            def _load_prompt_template(self) -> str:
                # Override to look in nonexistent package
                try:
                    files = importlib.resources.files("dkmv.components.nonexistent")
                    prompt_file = files / "prompt.md"
                    return prompt_file.read_text(encoding="utf-8")  # type: ignore[union-attr]
                except (ModuleNotFoundError, FileNotFoundError, TypeError) as e:
                    msg = "Prompt template not found for component 'nonexistent'"
                    raise FileNotFoundError(msg) from e

        comp = NoTemplateComponent(
            global_config=global_config,
            sandbox=mock_sandbox,
            run_manager=run_manager,
            stream_parser=stream_parser,
        )
        with pytest.raises(FileNotFoundError, match="Prompt template not found"):
            comp._load_prompt_template()


class TestBuildSandboxConfig:
    def test_merges_env_vars(self, component: MockComponent, config: MockConfig) -> None:
        sandbox_config = component._build_sandbox_config(config)
        assert sandbox_config.env_vars["ANTHROPIC_API_KEY"] == "sk-ant-test"
        assert sandbox_config.env_vars["GITHUB_TOKEN"] == "ghp_test"

    def test_uses_global_config_values(self, component: MockComponent, config: MockConfig) -> None:
        sandbox_config = component._build_sandbox_config(config)
        assert sandbox_config.image == "dkmv-sandbox:latest"
        assert sandbox_config.memory_limit == "4g"


class TestCommandInjection:
    async def test_repo_with_shell_metacharacters(
        self, component: MockComponent, mock_sandbox: AsyncMock
    ) -> None:
        config = MockConfig(
            repo="https://example.com/repo;rm -rf /",
            timeout_minutes=5,
        )
        await component.run(config)
        calls = [str(c) for c in mock_sandbox.execute.call_args_list]
        clone_calls = [c for c in calls if "git clone" in c]
        assert len(clone_calls) > 0
        # The repo URL should be shell-quoted, not raw
        assert ";rm -rf /" not in clone_calls[0] or "'" in clone_calls[0]

    async def test_branch_with_shell_metacharacters(
        self, component: MockComponent, mock_sandbox: AsyncMock
    ) -> None:
        config = MockConfig(
            repo="https://github.com/test/repo.git",
            branch="feature/$(whoami)",
            timeout_minutes=5,
        )
        await component.run(config)
        calls = [str(c) for c in mock_sandbox.execute.call_args_list]
        checkout_calls = [c for c in calls if "checkout" in c]
        assert len(checkout_calls) > 0
        # $(whoami) should be inside quotes, not executed
        for call in checkout_calls:
            assert "'feature/$(whoami)'" in call

    async def test_feature_name_in_commit_message_quoted(
        self, component: MockComponent, mock_sandbox: AsyncMock
    ) -> None:
        async def execute_side_effect(*args: Any, **kwargs: Any) -> CommandResult:
            cmd = args[1] if len(args) > 1 else kwargs.get("command", "")
            if "porcelain" in str(cmd):
                return CommandResult(output="M file.py", exit_code=0)
            return CommandResult(output="", exit_code=0)

        mock_sandbox.execute = AsyncMock(side_effect=execute_side_effect)
        mock_sandbox.setup_git_auth = AsyncMock(return_value=CommandResult(output="", exit_code=0))

        config = MockConfig(
            repo="https://github.com/test/repo.git",
            feature_name='test"; rm -rf /',
            timeout_minutes=5,
        )
        await component.run(config)
        calls = [str(c) for c in mock_sandbox.execute.call_args_list]
        commit_calls = [c for c in calls if "git commit" in c]
        assert len(commit_calls) > 0
        # The commit message should be shell-quoted
        for call in commit_calls:
            assert "'" in call  # shlex.quote wraps in single quotes


class TestAsyncSetupWorkspace:
    async def test_async_setup_workspace_called(
        self,
        global_config: DKMVConfig,
        mock_sandbox: AsyncMock,
        run_manager: RunManager,
        stream_parser: StreamParser,
    ) -> None:
        setup_called = False

        class AsyncSetupComponent(MockComponent):
            async def setup_workspace(self, session: Any, config: Any) -> None:
                nonlocal setup_called
                setup_called = True

        comp = AsyncSetupComponent(
            global_config=global_config,
            sandbox=mock_sandbox,
            run_manager=run_manager,
            stream_parser=stream_parser,
        )
        config = MockConfig(repo="https://github.com/test/repo.git", timeout_minutes=5)
        await comp.run(config)
        assert setup_called


class TestMissingResultEvent:
    async def test_no_result_event_marks_failed(
        self, component: MockComponent, mock_sandbox: AsyncMock
    ) -> None:
        async def no_result_stream(**kwargs: Any) -> Any:
            yield {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "hi"}]},
            }

        mock_sandbox.stream_claude = no_result_stream
        config = MockConfig(repo="https://github.com/test/repo.git", timeout_minutes=5)
        result = await component.run(config)
        assert result.status == "failed"
        assert "No result event" in result.error_message


class TestArtifactsToCommit:
    async def test_artifacts_force_added(
        self, component: MockComponent, mock_sandbox: AsyncMock
    ) -> None:
        async def execute_side_effect(*args: Any, **kwargs: Any) -> CommandResult:
            cmd = args[1] if len(args) > 1 else kwargs.get("command", "")
            if "porcelain" in str(cmd):
                return CommandResult(output="M file.py", exit_code=0)
            return CommandResult(output="", exit_code=0)

        mock_sandbox.execute = AsyncMock(side_effect=execute_side_effect)

        session = MagicMock()
        config = MockConfig(repo="https://github.com/test/repo.git", timeout_minutes=5)
        await component._teardown_git(
            session, config, artifacts_to_commit=[".dkmv/report; rm -rf /"]
        )
        calls = [str(c) for c in mock_sandbox.execute.call_args_list]
        force_add_calls = [c for c in calls if "git add -f" in c]
        assert len(force_add_calls) > 0
        # Artifact path with shell metacharacters should be quoted
        assert "'.dkmv/report; rm -rf /'" in force_add_calls[0]


class TestKeepAliveForwarding:
    async def test_keep_alive_forwarded_to_sandbox_stop(
        self, component: MockComponent, mock_sandbox: AsyncMock
    ) -> None:
        config = MockConfig(
            repo="https://github.com/test/repo.git",
            keep_alive=True,
            timeout_minutes=5,
        )
        await component.run(config)
        mock_sandbox.stop.assert_awaited_once()
        _, kwargs = mock_sandbox.stop.call_args
        assert kwargs.get("keep_alive") is True


class TestNoBranchSkipsPush:
    async def test_no_branch_skips_push(
        self, component: MockComponent, mock_sandbox: AsyncMock
    ) -> None:
        """B-2: When branch is None, _teardown_git should skip push entirely."""

        async def execute_side_effect(*args: Any, **kwargs: Any) -> CommandResult:
            cmd = args[1] if len(args) > 1 else kwargs.get("command", "")
            if "porcelain" in str(cmd):
                return CommandResult(output="M file.py", exit_code=0)
            return CommandResult(output="", exit_code=0)

        mock_sandbox.execute = AsyncMock(side_effect=execute_side_effect)
        mock_sandbox.setup_git_auth = AsyncMock(return_value=CommandResult(output="", exit_code=0))

        config = MockConfig(
            repo="https://github.com/test/repo.git",
            branch=None,
            timeout_minutes=5,
        )
        await component.run(config)

        calls = [str(c) for c in mock_sandbox.execute.call_args_list]
        push_calls = [c for c in calls if "git push" in c]
        assert len(push_calls) == 0, "Should NOT push when branch is None"


class TestGitCloneExitCodeCheck:
    async def test_clone_failure_raises(
        self, component: MockComponent, mock_sandbox: AsyncMock
    ) -> None:
        """B-3: git clone failure should raise RuntimeError, not silently continue."""
        mock_sandbox.execute = AsyncMock(
            return_value=CommandResult(output="fatal: repository not found", exit_code=128)
        )
        mock_sandbox.setup_git_auth = AsyncMock(return_value=CommandResult(output="", exit_code=0))

        config = MockConfig(
            repo="https://github.com/test/nonexistent.git",
            timeout_minutes=5,
        )
        result = await component.run(config)
        assert result.status == "failed"
        assert "git clone failed" in result.error_message

    async def test_push_failure_raises(
        self, component: MockComponent, mock_sandbox: AsyncMock
    ) -> None:
        """B-3: git push failure should raise RuntimeError."""
        call_count = 0

        async def execute_side_effect(*args: Any, **kwargs: Any) -> CommandResult:
            nonlocal call_count
            cmd = args[1] if len(args) > 1 else kwargs.get("command", "")
            call_count += 1
            if "porcelain" in str(cmd):
                return CommandResult(output="M file.py", exit_code=0)
            if "git push" in str(cmd):
                return CommandResult(output="Permission denied", exit_code=1)
            return CommandResult(output="", exit_code=0)

        mock_sandbox.execute = AsyncMock(side_effect=execute_side_effect)
        mock_sandbox.setup_git_auth = AsyncMock(return_value=CommandResult(output="", exit_code=0))

        config = MockConfig(
            repo="https://github.com/test/repo.git",
            branch="feature/test",
            timeout_minutes=5,
        )
        result = await component.run(config)
        assert result.status == "failed"
        assert "git push failed" in result.error_message

    async def test_commit_failure_raises(
        self, component: MockComponent, mock_sandbox: AsyncMock
    ) -> None:
        """git commit failure should raise RuntimeError."""

        async def execute_side_effect(*args: Any, **kwargs: Any) -> CommandResult:
            cmd = args[1] if len(args) > 1 else kwargs.get("command", "")
            if "porcelain" in str(cmd):
                return CommandResult(output="M file.py", exit_code=0)
            if "git commit" in str(cmd):
                return CommandResult(output="error: gpg failed", exit_code=1)
            return CommandResult(output="", exit_code=0)

        mock_sandbox.execute = AsyncMock(side_effect=execute_side_effect)
        mock_sandbox.setup_git_auth = AsyncMock(return_value=CommandResult(output="", exit_code=0))

        config = MockConfig(
            repo="https://github.com/test/repo.git",
            branch="feature/test",
            timeout_minutes=5,
        )
        result = await component.run(config)
        assert result.status == "failed"
        assert "git commit failed" in result.error_message


class TestPreWorkspaceSetup:
    async def test_pre_workspace_setup_called_before_checkout(
        self,
        global_config: DKMVConfig,
        mock_sandbox: AsyncMock,
        run_manager: RunManager,
        stream_parser: StreamParser,
    ) -> None:
        """Verify pre_workspace_setup runs before branch checkout."""
        call_order: list[str] = []

        class OrderTrackingComponent(MockComponent):
            async def pre_workspace_setup(self, session: Any, config: Any) -> None:
                call_order.append("pre_workspace_setup")
                config.branch = "feature/derived"

        async def tracking_execute(*args: Any, **kwargs: Any) -> CommandResult:
            cmd = args[1] if len(args) > 1 else kwargs.get("command", "")
            if "checkout" in str(cmd):
                call_order.append("checkout")
            return CommandResult(output="", exit_code=0)

        mock_sandbox.execute = AsyncMock(side_effect=tracking_execute)

        comp = OrderTrackingComponent(
            global_config=global_config,
            sandbox=mock_sandbox,
            run_manager=run_manager,
            stream_parser=stream_parser,
        )
        config = MockConfig(repo="https://github.com/test/repo.git", timeout_minutes=5)
        await comp.run(config)

        assert "pre_workspace_setup" in call_order
        assert "checkout" in call_order
        assert call_order.index("pre_workspace_setup") < call_order.index("checkout")

    async def test_pre_workspace_setup_default_is_noop(
        self, component: MockComponent, config: MockConfig
    ) -> None:
        result = await component.run(config)
        assert result.status == "completed"


class TestCollectArtifactsHook:
    async def test_collect_artifacts_default_returns_empty(
        self, component: MockComponent, config: MockConfig
    ) -> None:
        result = await component.run(config)
        assert result.status == "completed"
        # custom_data stays default since no artifacts
        assert result.custom_data == ""

    async def test_collect_artifacts_enriches_result(
        self,
        global_config: DKMVConfig,
        mock_sandbox: AsyncMock,
        run_manager: RunManager,
        stream_parser: StreamParser,
    ) -> None:
        class ArtifactComponent(MockComponent):
            async def collect_artifacts(
                self, session: Any, config: Any, result_event: dict[str, Any]
            ) -> dict[str, Any]:
                return {"custom": "artifact-data"}

        comp = ArtifactComponent(
            global_config=global_config,
            sandbox=mock_sandbox,
            run_manager=run_manager,
            stream_parser=stream_parser,
        )
        config = MockConfig(repo="https://github.com/test/repo.git", timeout_minutes=5)
        result = await comp.run(config)
        assert result.status == "completed"
        assert result.custom_data == "artifact-data"


class TestPostTeardownHook:
    async def test_post_teardown_called_after_git_teardown(
        self,
        global_config: DKMVConfig,
        mock_sandbox: AsyncMock,
        run_manager: RunManager,
        stream_parser: StreamParser,
    ) -> None:
        call_order: list[str] = []

        class PostTeardownComponent(MockComponent):
            async def post_teardown(self, session: Any, config: Any, result: Any) -> None:
                call_order.append("post_teardown")

        async def tracking_execute(*args: Any, **kwargs: Any) -> CommandResult:
            cmd = args[1] if len(args) > 1 else kwargs.get("command", "")
            if "git add -A" in str(cmd):
                call_order.append("git_teardown")
            return CommandResult(output="", exit_code=0)

        mock_sandbox.execute = AsyncMock(side_effect=tracking_execute)

        comp = PostTeardownComponent(
            global_config=global_config,
            sandbox=mock_sandbox,
            run_manager=run_manager,
            stream_parser=stream_parser,
        )
        config = MockConfig(repo="https://github.com/test/repo.git", timeout_minutes=5)
        await comp.run(config)

        assert "git_teardown" in call_order
        assert "post_teardown" in call_order
        assert call_order.index("git_teardown") < call_order.index("post_teardown")

    async def test_post_teardown_default_is_noop(
        self, component: MockComponent, config: MockConfig
    ) -> None:
        result = await component.run(config)
        assert result.status == "completed"


class TestMergeArtifactFields:
    def test_merges_component_specific_fields(self, component: MockComponent) -> None:
        target = MockResult(run_id="run1", component="dev", custom_data="")
        source = MockResult(run_id="", component="dev", custom_data="merged-value")
        component._merge_artifact_fields(target, source)
        assert target.custom_data == "merged-value"
        assert target.run_id == "run1"  # Base field not overwritten

    def test_skips_default_values(self, component: MockComponent) -> None:
        target = MockResult(run_id="run1", component="dev", custom_data="original")
        source = MockResult(run_id="", component="dev", custom_data="")  # default
        component._merge_artifact_fields(target, source)
        assert target.custom_data == "original"  # Not overwritten with default


class TestMergeArtifactFieldsDefaultFactory:
    def test_empty_list_does_not_overwrite(self, component: MockComponent) -> None:
        """default_factory=list fields: empty list should not overwrite existing."""
        from pydantic import Field

        class ListResult(BaseResult):
            items: list[str] = Field(default_factory=list)

        target = ListResult(run_id="run1", component="dev", items=["a", "b"])
        source = ListResult(run_id="", component="dev", items=[])
        component._merge_artifact_fields(target, source)
        assert target.items == ["a", "b"]  # Not overwritten with empty list

    def test_non_empty_list_overwrites(self, component: MockComponent) -> None:
        """default_factory=list fields: non-empty list should overwrite."""
        from pydantic import Field

        class ListResult(BaseResult):
            items: list[str] = Field(default_factory=list)

        target = ListResult(run_id="run1", component="dev", items=[])
        source = ListResult(run_id="", component="dev", items=["x", "y"])
        component._merge_artifact_fields(target, source)
        assert target.items == ["x", "y"]
