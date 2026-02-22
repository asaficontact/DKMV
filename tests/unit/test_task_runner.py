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
        run_id = run_manager.start_run("dev", MagicMock(model_dump=MagicMock(return_value={})))

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
        run_id = run_manager.start_run("dev", MagicMock(model_dump=MagicMock(return_value={})))

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
        run_id = run_manager.start_run("dev", MagicMock(model_dump=MagicMock(return_value={})))

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
        run_id = run_manager.start_run("dev", MagicMock(model_dump=MagicMock(return_value={})))

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
        run_id = run_manager.start_run("dev", MagicMock(model_dump=MagicMock(return_value={})))

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
        run_id = run_manager.start_run("dev", MagicMock(model_dump=MagicMock(return_value={})))

        sandbox.read_file = AsyncMock(side_effect=FileNotFoundError("not found"))
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
        run_id = run_manager.start_run("dev", MagicMock(model_dump=MagicMock(return_value={})))

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

    async def test_commit_false_skips_git(
        self, runner: TaskRunner, sandbox: AsyncMock, session: MagicMock
    ) -> None:
        task = _make_task(commit=False)
        await runner._git_teardown(task, session)
        sandbox.execute.assert_not_awaited()

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
        run_id = run_manager.start_run("dev", MagicMock(model_dump=MagicMock(return_value={})))

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
        run_id = run_manager.start_run("dev", MagicMock(model_dump=MagicMock(return_value={})))

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
        sandbox.read_file = AsyncMock(side_effect=FileNotFoundError("missing"))
        runner = TaskRunner(sandbox, run_manager, stream_parser, Console(quiet=True))

        task = _make_task(outputs=[TaskOutput(path="/workspace/missing.md", required=True)])
        run_id = run_manager.start_run("dev", MagicMock(model_dump=MagicMock(return_value={})))

        result = await runner.run(task, session, run_id, config, CLIOverrides())

        assert result.status == "failed"
        assert result.total_cost_usd == 0.05  # From mock stream
        assert result.num_turns == 3
        assert result.duration_seconds > 0
