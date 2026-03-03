from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from dkmv.config import DKMVConfig
from dkmv.core.runner import RunManager
from dkmv.core.sandbox import SandboxManager, SandboxSession
from dkmv.core.stream import StreamParser
from dkmv.tasks.models import CLIOverrides, TaskDefinition, TaskInput, TaskOutput, TaskResult
from dkmv.tasks.runner import TaskRunner


@pytest.fixture
def config(make_config: Any) -> DKMVConfig:
    return make_config()


@pytest.fixture
def run_manager(tmp_path: Path) -> RunManager:
    rm = RunManager(output_dir=tmp_path)
    # Pre-create a run directory for tests
    return rm


@pytest.fixture
def stream_parser() -> StreamParser:
    return StreamParser(console=Console(quiet=True))


def _make_sandbox(**overrides: Any) -> AsyncMock:
    sandbox = AsyncMock(spec=SandboxManager)
    sandbox.execute = AsyncMock(return_value=MagicMock(output="", exit_code=0))
    sandbox.write_file = AsyncMock()
    sandbox.read_file = AsyncMock(return_value="file content")
    sandbox.file_exists = AsyncMock(return_value=True)

    async def mock_stream(**kwargs: Any) -> Any:
        yield {
            "type": "result",
            "total_cost_usd": 0.05,
            "num_turns": 3,
            "session_id": "sess-test",
        }

    sandbox.stream_claude = mock_stream
    return sandbox


@pytest.fixture
def sandbox() -> AsyncMock:
    return _make_sandbox()


@pytest.fixture
def session() -> MagicMock:
    return MagicMock(spec=SandboxSession)


@pytest.fixture
def runner(sandbox: AsyncMock, run_manager: RunManager, stream_parser: StreamParser) -> TaskRunner:
    return TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))


def _make_task(**overrides: Any) -> TaskDefinition:
    defaults: dict[str, Any] = {
        "name": "test-task",
        "instructions": "Do the thing",
        "prompt": "Go ahead",
    }
    defaults.update(overrides)
    return TaskDefinition(**defaults)


class TestInputInjection:
    async def test_file_input_copies_to_container(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock, tmp_path: Path
    ) -> None:
        src = tmp_path / "input.txt"
        src.write_text("hello world")

        task = _make_task(
            inputs=[TaskInput(name="src", type="file", src=str(src), dest="/workspace/input.txt")]
        )
        env_vars = await runner._inject_inputs(task, session)

        sandbox.write_file.assert_awaited_once()
        call_args = sandbox.write_file.call_args
        assert call_args[0][1] == "/workspace/input.txt"
        assert call_args[0][2] == "hello world"
        assert env_vars == {}

    async def test_file_input_directory_recursive(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock, tmp_path: Path
    ) -> None:
        src_dir = tmp_path / "docs"
        src_dir.mkdir()
        (src_dir / "a.txt").write_text("file a")
        sub = src_dir / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("file b")

        task = _make_task(
            inputs=[TaskInput(name="docs", type="file", src=str(src_dir), dest="/workspace/docs")]
        )
        await runner._inject_inputs(task, session)

        assert sandbox.write_file.await_count == 2
        paths = [call[0][1] for call in sandbox.write_file.call_args_list]
        assert "/workspace/docs/a.txt" in paths
        assert "/workspace/docs/sub/b.txt" in paths

    async def test_text_input_writes_content(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock
    ) -> None:
        task = _make_task(
            inputs=[
                TaskInput(
                    name="config", type="text", content="key=value", dest="/workspace/config.txt"
                )
            ]
        )
        await runner._inject_inputs(task, session)

        sandbox.write_file.assert_awaited_once()
        call_args = sandbox.write_file.call_args
        assert call_args[0][1] == "/workspace/config.txt"
        assert call_args[0][2] == "key=value"

    async def test_env_input_collects_vars(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock
    ) -> None:
        task = _make_task(
            inputs=[
                TaskInput(name="api-key", type="env", key="API_KEY", value="secret123"),
                TaskInput(name="mode", type="env", key="MODE", value="prod"),
            ]
        )
        env_vars = await runner._inject_inputs(task, session)

        assert env_vars == {"API_KEY": "secret123", "MODE": "prod"}
        sandbox.write_file.assert_not_awaited()

    async def test_optional_missing_skips_silently(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock
    ) -> None:
        task = _make_task(
            inputs=[
                TaskInput(
                    name="opt",
                    type="file",
                    src="/nonexistent/path.txt",
                    dest="/workspace/opt.txt",
                    optional=True,
                )
            ]
        )
        env_vars = await runner._inject_inputs(task, session)

        assert env_vars == {}
        sandbox.write_file.assert_not_awaited()

    async def test_required_missing_raises(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock
    ) -> None:
        task = _make_task(
            inputs=[
                TaskInput(
                    name="required",
                    type="file",
                    src="/nonexistent/path.txt",
                    dest="/workspace/req.txt",
                )
            ]
        )
        with pytest.raises(FileNotFoundError, match="source not found"):
            await runner._inject_inputs(task, session)


class TestInstructionsWriting:
    async def test_instructions_written_to_claude_md(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock
    ) -> None:
        task = _make_task(instructions="Follow these rules carefully")
        await runner._write_instructions(task, session)

        sandbox.execute.assert_awaited_once()
        mkdir_cmd = sandbox.execute.call_args[0][1]
        assert "mkdir -p" in mkdir_cmd
        assert ".claude" in mkdir_cmd

        sandbox.write_file.assert_awaited_once()
        call_args = sandbox.write_file.call_args
        assert ".claude/CLAUDE.md" in call_args[0][1]
        assert "Follow these rules carefully" in call_args[0][2]

    async def test_write_instructions_returns_rendered_content(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock
    ) -> None:
        task = _make_task(instructions="Custom rules here")
        content = await runner._write_instructions(task, session, component_agent_md="## Agent MD")

        assert "DKMV Agent" in content
        assert "## Agent MD" in content
        assert "Custom rules here" in content

    async def test_commit_true_injects_git_rules(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock
    ) -> None:
        task = _make_task(commit=True)
        content = await runner._write_instructions(task, session)

        assert "## Git Commit Rules" in content
        assert "conventional commit messages" in content
        assert "Do NOT leave uncommitted changes" in content

    async def test_commit_false_omits_git_rules(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock
    ) -> None:
        task = _make_task(commit=False)
        content = await runner._write_instructions(task, session)

        assert "Git Commit Rules" not in content


class TestParameterCascade:
    async def test_task_model_wins(
        self,
        sandbox: AsyncMock,
        run_manager: RunManager,
        stream_parser: StreamParser,
        session: MagicMock,
        config: DKMVConfig,
    ) -> None:
        captured: dict[str, Any] = {}

        async def capturing_stream(**kwargs: Any) -> Any:
            captured.update(kwargs)
            yield {
                "type": "result",
                "total_cost_usd": 0.01,
                "num_turns": 1,
                "session_id": "s",
            }

        sandbox.stream_claude = capturing_stream
        runner = TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))

        task = _make_task(model="claude-opus-4-6")
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        await runner.run(task, session, run_id, config, CLIOverrides(model="claude-haiku-4-5"))

        assert captured["model"] == "claude-opus-4-6"

    async def test_cli_model_used_when_task_none(
        self,
        sandbox: AsyncMock,
        run_manager: RunManager,
        stream_parser: StreamParser,
        session: MagicMock,
        config: DKMVConfig,
    ) -> None:
        captured: dict[str, Any] = {}

        async def capturing_stream(**kwargs: Any) -> Any:
            captured.update(kwargs)
            yield {
                "type": "result",
                "total_cost_usd": 0.01,
                "num_turns": 1,
                "session_id": "s",
            }

        sandbox.stream_claude = capturing_stream
        runner = TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))

        task = _make_task()  # model=None
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        await runner.run(task, session, run_id, config, CLIOverrides(model="claude-haiku-4-5"))

        assert captured["model"] == "claude-haiku-4-5"

    async def test_global_model_used_as_fallback(
        self,
        sandbox: AsyncMock,
        run_manager: RunManager,
        stream_parser: StreamParser,
        session: MagicMock,
        config: DKMVConfig,
    ) -> None:
        captured: dict[str, Any] = {}

        async def capturing_stream(**kwargs: Any) -> Any:
            captured.update(kwargs)
            yield {
                "type": "result",
                "total_cost_usd": 0.01,
                "num_turns": 1,
                "session_id": "s",
            }

        sandbox.stream_claude = capturing_stream
        runner = TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))

        task = _make_task()  # model=None
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        await runner.run(task, session, run_id, config, CLIOverrides())

        assert captured["model"] == config.default_model

    async def test_budget_zero_preserved(
        self,
        sandbox: AsyncMock,
        run_manager: RunManager,
        stream_parser: StreamParser,
        session: MagicMock,
        config: DKMVConfig,
    ) -> None:
        captured: dict[str, Any] = {}

        async def capturing_stream(**kwargs: Any) -> Any:
            captured.update(kwargs)
            yield {
                "type": "result",
                "total_cost_usd": 0.0,
                "num_turns": 1,
                "session_id": "s",
            }

        sandbox.stream_claude = capturing_stream
        runner = TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))

        task = _make_task(max_budget_usd=0.0)
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        await runner.run(task, session, run_id, config, CLIOverrides())

        assert captured["max_budget_usd"] == 0.0


class TestOutputCollection:
    async def test_required_output_present_success(
        self,
        runner: TaskRunner,
        sandbox: AsyncMock,
        session: MagicMock,
        run_manager: RunManager,
    ) -> None:
        task = _make_task(
            outputs=[TaskOutput(path="/workspace/report.md", required=True, save=True)]
        )
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        sandbox.file_exists = AsyncMock(return_value=True)
        sandbox.read_file = AsyncMock(return_value="report content")
        result: TaskResult = await runner.run(
            task,
            session,
            run_id,
            MagicMock(
                default_model="m",
                default_max_turns=10,
                timeout_minutes=5,
                max_budget_usd=None,
            ),
            CLIOverrides(),
        )

        assert result.status == "completed"
        assert "/workspace/report.md" in result.outputs

    async def test_required_output_missing_fails(
        self,
        runner: TaskRunner,
        sandbox: AsyncMock,
        session: MagicMock,
        run_manager: RunManager,
    ) -> None:
        task = _make_task(outputs=[TaskOutput(path="/workspace/missing.md", required=True)])
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        sandbox.file_exists = AsyncMock(return_value=False)
        result: TaskResult = await runner.run(
            task,
            session,
            run_id,
            MagicMock(
                default_model="m",
                default_max_turns=10,
                timeout_minutes=5,
                max_budget_usd=None,
            ),
            CLIOverrides(),
        )

        assert result.status == "failed"
        assert "Required output missing" in result.error_message

    async def test_save_flag_respected(
        self,
        sandbox: AsyncMock,
        run_manager: RunManager,
        stream_parser: StreamParser,
        session: MagicMock,
    ) -> None:
        runner = TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))
        task = _make_task(
            outputs=[
                TaskOutput(path="/workspace/saved.md", save=True),
                TaskOutput(path="/workspace/unsaved.md", save=False),
            ]
        )
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        sandbox.file_exists = AsyncMock(return_value=True)
        sandbox.read_file = AsyncMock(return_value="content")
        await runner.run(
            task,
            session,
            run_id,
            MagicMock(
                default_model="m",
                default_max_turns=10,
                timeout_minutes=5,
                max_budget_usd=None,
            ),
            CLIOverrides(),
        )

        run_dir = run_manager._runs_dir / run_id
        assert (run_dir / "saved.md").exists()
        assert not (run_dir / "unsaved.md").exists()

    async def test_claude_md_saved_as_artifact(
        self,
        sandbox: AsyncMock,
        run_manager: RunManager,
        stream_parser: StreamParser,
        session: MagicMock,
    ) -> None:
        runner = TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))
        task = _make_task(instructions="My task rules")
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        await runner.run(
            task,
            session,
            run_id,
            MagicMock(
                default_model="m",
                default_max_turns=10,
                timeout_minutes=5,
                max_budget_usd=None,
            ),
            CLIOverrides(),
            component_agent_md="## Component Context",
        )

        run_dir = run_manager._runs_dir / run_id
        claude_md_file = run_dir / "claude_md_test-task.md"
        assert claude_md_file.exists()
        content = claude_md_file.read_text()
        assert "DKMV Agent" in content
        assert "## Component Context" in content
        assert "My task rules" in content


class TestRequiredFieldsValidation:
    def test_validate_all_fields_present_returns_none(self) -> None:
        output = TaskOutput(path="/workspace/out.json", required_fields=["output_dir", "features"])
        content = '{"output_dir": "/out", "features": ["a", "b"]}'
        assert TaskRunner._validate_required_fields(output, content) is None

    def test_validate_missing_field_returns_error(self) -> None:
        output = TaskOutput(path="/workspace/out.json", required_fields=["output_dir", "features"])
        content = '{"output_dir": "/out"}'
        error = TaskRunner._validate_required_fields(output, content)
        assert error is not None
        assert "missing required fields" in error
        assert "features" in error

    def test_validate_non_json_returns_error(self) -> None:
        output = TaskOutput(path="/workspace/out.json", required_fields=["output_dir"])
        error = TaskRunner._validate_required_fields(output, "plain text")
        assert error is not None
        assert "not valid JSON" in error

    def test_validate_non_dict_json_returns_error(self) -> None:
        output = TaskOutput(path="/workspace/out.json", required_fields=["output_dir"])
        error = TaskRunner._validate_required_fields(output, "[1, 2, 3]")
        assert error is not None
        assert "not a JSON object" in error

    def test_validate_empty_required_fields_returns_none(self) -> None:
        output = TaskOutput(path="/workspace/out.json", required_fields=[])
        assert TaskRunner._validate_required_fields(output, "anything") is None

    async def test_collect_outputs_fails_on_missing_fields(
        self,
        sandbox: AsyncMock,
        run_manager: RunManager,
        stream_parser: StreamParser,
        session: MagicMock,
        config: DKMVConfig,
    ) -> None:
        sandbox.file_exists = AsyncMock(return_value=True)
        sandbox.read_file = AsyncMock(return_value='{"output_dir": "/out"}')
        runner = TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))

        task = _make_task(
            outputs=[
                TaskOutput(
                    path="/workspace/out.json",
                    required=True,
                    required_fields=["output_dir", "features"],
                )
            ]
        )
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        result = await runner.run(task, session, run_id, config, CLIOverrides())

        assert result.status == "failed"
        assert "missing required fields" in result.error_message
        assert "features" in result.error_message

    async def test_collect_outputs_passes_with_all_fields(
        self,
        sandbox: AsyncMock,
        run_manager: RunManager,
        stream_parser: StreamParser,
        session: MagicMock,
        config: DKMVConfig,
    ) -> None:
        sandbox.file_exists = AsyncMock(return_value=True)
        sandbox.read_file = AsyncMock(return_value='{"output_dir": "/out", "features": ["a"]}')
        runner = TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))

        task = _make_task(
            outputs=[
                TaskOutput(
                    path="/workspace/out.json",
                    required=True,
                    required_fields=["output_dir", "features"],
                )
            ]
        )
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        result = await runner.run(task, session, run_id, config, CLIOverrides())

        assert result.status == "completed"
        assert "/workspace/out.json" in result.outputs


class TestGitTeardown:
    async def test_force_add_declared_outputs(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock
    ) -> None:
        task = _make_task(
            outputs=[
                TaskOutput(path="/workspace/report.md"),
                TaskOutput(path="/workspace/plan.md"),
            ],
            commit=True,
            push=False,
        )
        # Simulate something to commit
        sandbox.execute = AsyncMock(return_value=MagicMock(output="M file.txt", exit_code=0))

        await runner._git_teardown(task, session)

        cmds = [call[0][1] for call in sandbox.execute.call_args_list]
        force_adds = [c for c in cmds if "git add -f" in c]
        assert len(force_adds) == 2
        assert any("/workspace/report.md" in c for c in force_adds)
        assert any("/workspace/plan.md" in c for c in force_adds)

    async def test_commit_false_push_false_skips_git(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock
    ) -> None:
        task = _make_task(commit=False, push=False)
        await runner._git_teardown(task, session)
        sandbox.execute.assert_not_awaited()

    async def test_commit_false_push_true_only_pushes(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock
    ) -> None:
        task = _make_task(commit=False, push=True)
        sandbox.execute = AsyncMock(return_value=MagicMock(output="", exit_code=0))
        await runner._git_teardown(task, session)

        cmds = [call[0][1] for call in sandbox.execute.call_args_list]
        assert any("git push" in c for c in cmds)
        assert not any("git commit" in c for c in cmds)
        assert not any("git add" in c for c in cmds)

    async def test_nothing_to_commit_no_error(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock
    ) -> None:
        task = _make_task(commit=True)
        # Empty porcelain output = nothing to commit
        sandbox.execute = AsyncMock(return_value=MagicMock(output="", exit_code=0))

        await runner._git_teardown(task, session)

        cmds = [call[0][1] for call in sandbox.execute.call_args_list]
        commit_cmds = [c for c in cmds if "git commit" in c]
        assert len(commit_cmds) == 0

    async def test_safety_net_commit_message(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock
    ) -> None:
        task = _make_task(commit=True, push=False)
        # Simulate uncommitted changes
        sandbox.execute = AsyncMock(return_value=MagicMock(output="M file.txt", exit_code=0))

        await runner._git_teardown(task, session)

        cmds = [call[0][1] for call in sandbox.execute.call_args_list]
        commit_cmds = [c for c in cmds if "git commit" in c]
        assert len(commit_cmds) == 1
        assert "chore: uncommitted changes from test-task [dkmv]" in commit_cmds[0]

    async def test_safety_net_excludes_workspace_dirs(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock
    ) -> None:
        task = _make_task(commit=True, push=False)
        sandbox.execute = AsyncMock(return_value=MagicMock(output="", exit_code=0))

        await runner._git_teardown(task, session)

        cmds = [call[0][1] for call in sandbox.execute.call_args_list]
        add_all_cmds = [c for c in cmds if "git add -A" in c]
        assert len(add_all_cmds) == 1
        assert "':!.agent/'" in add_all_cmds[0]
        assert "':!.claude/'" in add_all_cmds[0]


class TestGitPushFailurePropagation:
    async def test_push_failure_raises_runtime_error(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock
    ) -> None:
        task = _make_task(commit=False, push=True)
        sandbox.execute = AsyncMock(
            return_value=MagicMock(output="fatal: remote rejected", exit_code=1)
        )

        with pytest.raises(RuntimeError, match="git push failed"):
            await runner._git_teardown(task, session)

    async def test_push_failure_causes_task_failure(
        self,
        sandbox: AsyncMock,
        run_manager: RunManager,
        stream_parser: StreamParser,
        session: MagicMock,
        config: DKMVConfig,
    ) -> None:
        """When git push fails, the full task run should report status='failed'."""

        async def success_stream(**kwargs: Any) -> Any:
            yield {
                "type": "result",
                "total_cost_usd": 0.05,
                "num_turns": 3,
                "session_id": "sess-test",
            }

        sandbox.stream_claude = success_stream

        # All commands succeed except git push
        async def selective_execute(session: Any, command: str, **kw: Any) -> MagicMock:
            if "git push" in command:
                return MagicMock(output="fatal: remote rejected", exit_code=1)
            return MagicMock(output="", exit_code=0)

        sandbox.execute = AsyncMock(side_effect=selective_execute)
        runner = TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))

        task = _make_task(commit=True, push=True)
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        result = await runner.run(task, session, run_id, config, CLIOverrides())

        assert result.status == "failed"
        assert "git push failed" in result.error_message

    async def test_push_success_does_not_raise(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock
    ) -> None:
        task = _make_task(commit=False, push=True)
        sandbox.execute = AsyncMock(return_value=MagicMock(output="", exit_code=0))

        # Should not raise
        await runner._git_teardown(task, session)

    async def test_commit_failure_does_not_raise(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock
    ) -> None:
        """Commit failures are soft warnings, not errors."""
        task = _make_task(commit=True, push=False)
        # Simulate uncommitted changes but git commit fails
        sandbox.execute = AsyncMock(return_value=MagicMock(output="M file.txt", exit_code=1))

        # Should not raise — commit failures are warnings only
        await runner._git_teardown(task, session)


class TestErrorHandling:
    async def test_timeout_returns_timed_out(
        self,
        sandbox: AsyncMock,
        run_manager: RunManager,
        stream_parser: StreamParser,
        session: MagicMock,
        config: DKMVConfig,
    ) -> None:
        async def timeout_stream(**kwargs: Any) -> Any:
            raise TimeoutError("timed out")
            yield  # noqa: RET503 — make this an async generator

        sandbox.stream_claude = timeout_stream
        runner = TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))

        task = _make_task()
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        result = await runner.run(task, session, run_id, config, CLIOverrides())

        assert result.status == "timed_out"
        assert "timed out" in result.error_message

    async def test_missing_input_returns_failed(
        self,
        runner: TaskRunner,
        sandbox: AsyncMock,
        session: MagicMock,
        run_manager: RunManager,
        config: DKMVConfig,
    ) -> None:
        task = _make_task(
            inputs=[
                TaskInput(
                    name="missing",
                    type="file",
                    src="/nonexistent/file.txt",
                    dest="/workspace/file.txt",
                )
            ]
        )
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        result = await runner.run(task, session, run_id, config, CLIOverrides())

        assert result.status == "failed"
        assert "source not found" in result.error_message

    async def test_partial_results_preserved(
        self,
        sandbox: AsyncMock,
        run_manager: RunManager,
        stream_parser: StreamParser,
        session: MagicMock,
        config: DKMVConfig,
    ) -> None:
        """Cost/turns set after streaming should be preserved even if output collection fails."""
        sandbox.file_exists = AsyncMock(return_value=False)
        runner = TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))

        task = _make_task(outputs=[TaskOutput(path="/workspace/missing.md", required=True)])
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        result = await runner.run(task, session, run_id, config, CLIOverrides())

        assert result.status == "failed"
        # Cost includes both initial stream (0.05) and retry stream (0.05)
        assert result.total_cost_usd == 0.10
        assert result.num_turns == 6
        assert result.duration_seconds > 0


class TestRetryWithResume:
    async def test_retry_invoked_on_output_failure(
        self,
        run_manager: RunManager,
        stream_parser: StreamParser,
        session: MagicMock,
        config: DKMVConfig,
    ) -> None:
        """When output collection fails, stream_claude is called again with resume_session_id."""
        call_count = 0

        async def counting_stream(**kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            yield {
                "type": "result",
                "total_cost_usd": 0.05,
                "num_turns": 3,
                "session_id": "sess-123",
            }

        sandbox = _make_sandbox()
        sandbox.stream_claude = counting_stream
        # Always fail to find the file
        sandbox.file_exists = AsyncMock(return_value=False)
        runner = TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))

        task = _make_task(outputs=[TaskOutput(path="/workspace/missing.md", required=True)])
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        result = await runner.run(task, session, run_id, config, CLIOverrides())

        assert result.status == "failed"
        # Initial call + retry = 2 calls
        assert call_count == 2

    async def test_retry_succeeds_produces_output(
        self,
        run_manager: RunManager,
        stream_parser: StreamParser,
        session: MagicMock,
        config: DKMVConfig,
    ) -> None:
        """After retry, output is collected successfully."""
        call_count = 0

        async def counting_stream(**kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            yield {
                "type": "result",
                "total_cost_usd": 0.05,
                "num_turns": 3,
                "session_id": "sess-123",
            }

        sandbox = _make_sandbox()
        sandbox.stream_claude = counting_stream
        # First call: missing, second call (after retry): found
        sandbox.file_exists = AsyncMock(side_effect=[False, True])
        sandbox.read_file = AsyncMock(return_value="report content")
        runner = TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))

        task = _make_task(outputs=[TaskOutput(path="/workspace/report.md", required=True)])
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        result = await runner.run(task, session, run_id, config, CLIOverrides())

        assert result.status == "completed"
        assert "/workspace/report.md" in result.outputs

    async def test_retry_still_fails_returns_error(
        self,
        run_manager: RunManager,
        stream_parser: StreamParser,
        session: MagicMock,
        config: DKMVConfig,
    ) -> None:
        """Retry also fails — task fails with error."""
        sandbox = _make_sandbox()
        sandbox.file_exists = AsyncMock(return_value=False)
        runner = TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))

        task = _make_task(outputs=[TaskOutput(path="/workspace/missing.md", required=True)])
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        result = await runner.run(task, session, run_id, config, CLIOverrides())

        assert result.status == "failed"
        assert "Required output missing" in result.error_message

    async def test_no_retry_without_session_id(
        self,
        run_manager: RunManager,
        stream_parser: StreamParser,
        session: MagicMock,
        config: DKMVConfig,
    ) -> None:
        """If session_id is empty, no retry is attempted."""
        call_count = 0

        async def no_session_stream(**kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            yield {
                "type": "result",
                "total_cost_usd": 0.05,
                "num_turns": 3,
                "session_id": "",  # Empty session_id
            }

        sandbox = _make_sandbox()
        sandbox.stream_claude = no_session_stream
        sandbox.file_exists = AsyncMock(return_value=False)
        runner = TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))

        task = _make_task(outputs=[TaskOutput(path="/workspace/missing.md", required=True)])
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        result = await runner.run(task, session, run_id, config, CLIOverrides())

        assert result.status == "failed"
        assert call_count == 1  # No retry

    async def test_retry_cost_accumulated(
        self,
        run_manager: RunManager,
        stream_parser: StreamParser,
        session: MagicMock,
        config: DKMVConfig,
    ) -> None:
        """Cost from retry is added to total."""
        costs = [0.10, 0.05]

        async def varying_cost_stream(**kwargs: Any) -> Any:
            cost = costs.pop(0)
            yield {
                "type": "result",
                "total_cost_usd": cost,
                "num_turns": 3,
                "session_id": "sess-123",
            }

        sandbox = _make_sandbox()
        sandbox.stream_claude = varying_cost_stream
        # First: missing, second (after retry): found
        sandbox.file_exists = AsyncMock(side_effect=[False, True])
        sandbox.read_file = AsyncMock(return_value="content")
        runner = TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))

        task = _make_task(outputs=[TaskOutput(path="/workspace/out.md", required=True)])
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        result = await runner.run(task, session, run_id, config, CLIOverrides())

        assert result.status == "completed"
        assert result.total_cost_usd == pytest.approx(0.15)
        assert result.num_turns == 6

    async def test_retry_max_turns_capped(
        self,
        run_manager: RunManager,
        stream_parser: StreamParser,
        session: MagicMock,
        config: DKMVConfig,
    ) -> None:
        """Retry uses at most 10 turns."""
        captured_kwargs: dict[str, Any] = {}

        async def capturing_stream(**kwargs: Any) -> Any:
            captured_kwargs.update(kwargs)
            yield {
                "type": "result",
                "total_cost_usd": 0.05,
                "num_turns": 3,
                "session_id": "sess-123",
            }

        sandbox = _make_sandbox()
        sandbox.stream_claude = capturing_stream
        # First: missing, retry also missing
        sandbox.file_exists = AsyncMock(return_value=False)
        runner = TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))

        task = _make_task(
            max_turns=50,
            outputs=[TaskOutput(path="/workspace/out.md", required=True)],
        )
        run_id = run_manager.start_run(
            "dev", MagicMock(feature_name="test", model_dump=MagicMock(return_value={}))
        )

        await runner.run(task, session, run_id, config, CLIOverrides())

        # The retry call should cap max_turns at 10
        assert captured_kwargs["max_turns"] == 10
        assert captured_kwargs.get("resume_session_id") == "sess-123"
