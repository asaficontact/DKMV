"""Tests for --context file injection into containers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console
from typer.testing import CliRunner

from dkmv.cli import app
from dkmv.core.runner import RunManager
from dkmv.core.sandbox import SandboxManager
from dkmv.tasks.component import ComponentRunner, WORKSPACE_DIR
from dkmv.tasks.loader import TaskLoader
from dkmv.tasks.models import CLIOverrides, TaskDefinition, TaskResult
from dkmv.tasks.runner import TaskRunner

runner = CliRunner()


# ── Fixtures ──────────────────────────────────────────────────────────


def _make_task(name: str = "t") -> TaskDefinition:
    return TaskDefinition(name=name, instructions="do stuff", prompt="go")


def _make_task_result(name: str = "t") -> TaskResult:
    return TaskResult(task_name=name, status="completed", total_cost_usd=0.1, num_turns=1)


@pytest.fixture
def sandbox() -> AsyncMock:
    s = AsyncMock(spec=SandboxManager)
    s.execute = AsyncMock(return_value=MagicMock(output="", exit_code=0))
    s.start = AsyncMock(return_value=MagicMock())
    s.stop = AsyncMock()
    s.setup_git_auth = AsyncMock(return_value=MagicMock(exit_code=0, output=""))
    s.get_container_name = MagicMock(return_value="dkmv-test-container")
    s.write_file = AsyncMock()
    return s


@pytest.fixture
def run_manager(tmp_path: Path) -> RunManager:
    return RunManager(output_dir=tmp_path)


@pytest.fixture
def task_runner_mock() -> AsyncMock:
    return AsyncMock(spec=TaskRunner)


@pytest.fixture
def task_loader() -> MagicMock:
    return MagicMock(spec=TaskLoader)


def _mock_config() -> MagicMock:
    cfg = MagicMock()
    cfg.anthropic_api_key = "sk-ant-test"
    cfg.claude_oauth_token = ""
    cfg.auth_method = "api_key"
    cfg.github_token = "ghp_test"
    cfg.default_model = "claude-sonnet-4-6"
    cfg.default_max_turns = 100
    cfg.timeout_minutes = 30
    cfg.max_budget_usd = None
    cfg.output_dir = Path("./outputs")
    cfg.image_name = "dkmv-sandbox:latest"
    cfg.memory_limit = "8g"
    return cfg


@pytest.fixture
def component_runner(
    sandbox: AsyncMock,
    run_manager: RunManager,
    task_loader: MagicMock,
    task_runner_mock: AsyncMock,
) -> ComponentRunner:
    return ComponentRunner(sandbox, run_manager, task_loader, task_runner_mock, Console())


def _create_component_dir(tmp_path: Path) -> Path:
    comp_dir = tmp_path / "my-comp"
    comp_dir.mkdir()
    (comp_dir / "01-task.yaml").write_text("name: t\ninstructions: do stuff\nprompt: go\n")
    return comp_dir


# ── ComponentRunner._inject_context_files tests ──────────────────────


class TestInjectContextFiles:
    async def test_single_file_injected(
        self, component_runner: ComponentRunner, sandbox: AsyncMock, tmp_path: Path
    ) -> None:
        ctx_file = tmp_path / "notes.md"
        ctx_file.write_text("some notes")

        session = MagicMock()
        result = await component_runner._inject_context_files(session, [ctx_file])

        assert result == [".agent/context/notes.md"]
        sandbox.execute.assert_called_once()
        sandbox.write_file.assert_called_once_with(
            session, f"{WORKSPACE_DIR}/.agent/context/notes.md", "some notes"
        )

    async def test_directory_injected_recursively(
        self, component_runner: ComponentRunner, sandbox: AsyncMock, tmp_path: Path
    ) -> None:
        ctx_dir = tmp_path / "docs"
        ctx_dir.mkdir()
        (ctx_dir / "api.md").write_text("api docs")
        sub = ctx_dir / "sub"
        sub.mkdir()
        (sub / "detail.md").write_text("details")

        session = MagicMock()
        result = await component_runner._inject_context_files(session, [ctx_dir])

        assert ".agent/context/docs/api.md" in result
        assert ".agent/context/docs/sub/detail.md" in result
        assert len(result) == 2

    async def test_empty_list_returns_empty(
        self, component_runner: ComponentRunner, sandbox: AsyncMock
    ) -> None:
        session = MagicMock()
        result = await component_runner._inject_context_files(session, [])

        assert result == []
        sandbox.execute.assert_not_called()
        sandbox.write_file.assert_not_called()

    async def test_nonexistent_path_skipped(
        self, component_runner: ComponentRunner, sandbox: AsyncMock, tmp_path: Path
    ) -> None:
        session = MagicMock()
        result = await component_runner._inject_context_files(
            session, [tmp_path / "nonexistent.txt"]
        )

        assert result == []

    async def test_binary_file_skipped(
        self, component_runner: ComponentRunner, sandbox: AsyncMock, tmp_path: Path
    ) -> None:
        binary = tmp_path / "image.bin"
        binary.write_bytes(b"\x00\x01\x02\xff\xfe")

        session = MagicMock()
        result = await component_runner._inject_context_files(session, [binary])

        assert result == []
        sandbox.write_file.assert_not_called()

    async def test_multiple_context_paths(
        self, component_runner: ComponentRunner, sandbox: AsyncMock, tmp_path: Path
    ) -> None:
        f1 = tmp_path / "a.md"
        f1.write_text("file a")
        f2 = tmp_path / "b.txt"
        f2.write_text("file b")

        session = MagicMock()
        result = await component_runner._inject_context_files(session, [f1, f2])

        assert ".agent/context/a.md" in result
        assert ".agent/context/b.txt" in result
        assert len(result) == 2

    async def test_mixed_file_and_dir(
        self, component_runner: ComponentRunner, sandbox: AsyncMock, tmp_path: Path
    ) -> None:
        f1 = tmp_path / "single.md"
        f1.write_text("single file")
        d1 = tmp_path / "mydir"
        d1.mkdir()
        (d1 / "inner.txt").write_text("inner content")

        session = MagicMock()
        result = await component_runner._inject_context_files(session, [f1, d1])

        assert ".agent/context/single.md" in result
        assert ".agent/context/mydir/inner.txt" in result

    async def test_binary_in_dir_skipped(
        self, component_runner: ComponentRunner, sandbox: AsyncMock, tmp_path: Path
    ) -> None:
        d = tmp_path / "mixed"
        d.mkdir()
        (d / "good.md").write_text("text file")
        (d / "bad.bin").write_bytes(b"\x00\xff")

        session = MagicMock()
        result = await component_runner._inject_context_files(session, [d])

        assert ".agent/context/mixed/good.md" in result
        assert len(result) == 1


# ── ComponentRunner.run passes context_files to task_runner ──────────


class TestContextPassthrough:
    async def test_context_files_passed_to_task_runner(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner_mock: AsyncMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path)
        ctx_file = tmp_path / "extra.md"
        ctx_file.write_text("extra context")

        task_loader.load.return_value = _make_task("t")
        task_runner_mock.run.return_value = _make_task_result("t")
        config = _mock_config()

        await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
            context_paths=[ctx_file],
        )

        call_kwargs = task_runner_mock.run.call_args[1]
        assert call_kwargs["context_files"] == [".agent/context/extra.md"]

    async def test_no_context_passes_empty_list(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner_mock: AsyncMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path)
        task_loader.load.return_value = _make_task("t")
        task_runner_mock.run.return_value = _make_task_result("t")
        config = _mock_config()

        await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
        )

        call_kwargs = task_runner_mock.run.call_args[1]
        assert call_kwargs["context_files"] == []


# ── TaskRunner._write_instructions includes context ─────────────────


class TestContextInInstructions:
    async def test_context_files_in_claude_md(self, tmp_path: Path) -> None:
        sandbox = AsyncMock(spec=SandboxManager)
        sandbox.execute = AsyncMock(return_value=MagicMock(output="", exit_code=0))
        sandbox.write_file = AsyncMock()
        rm = RunManager(output_dir=tmp_path)
        from dkmv.core.stream import StreamParser

        parser = StreamParser(console=Console(quiet=True))
        tr = TaskRunner(sandbox, rm, parser, Console(quiet=True))

        task = _make_task("t")
        session = MagicMock()
        context_files = [".agent/context/notes.md", ".agent/context/api/spec.yaml"]

        result = await tr._write_instructions(task, session, context_files=context_files)

        assert "## Additional Context" in result
        assert "`.agent/context/notes.md`" in result
        assert "`.agent/context/api/spec.yaml`" in result

    async def test_no_context_files_no_section(self, tmp_path: Path) -> None:
        sandbox = AsyncMock(spec=SandboxManager)
        sandbox.execute = AsyncMock(return_value=MagicMock(output="", exit_code=0))
        sandbox.write_file = AsyncMock()
        rm = RunManager(output_dir=tmp_path)
        from dkmv.core.stream import StreamParser

        parser = StreamParser(console=Console(quiet=True))
        tr = TaskRunner(sandbox, rm, parser, Console(quiet=True))

        task = _make_task("t")
        session = MagicMock()

        result = await tr._write_instructions(task, session)

        assert "Additional Context" not in result

    async def test_empty_context_list_no_section(self, tmp_path: Path) -> None:
        sandbox = AsyncMock(spec=SandboxManager)
        sandbox.execute = AsyncMock(return_value=MagicMock(output="", exit_code=0))
        sandbox.write_file = AsyncMock()
        rm = RunManager(output_dir=tmp_path)
        from dkmv.core.stream import StreamParser

        parser = StreamParser(console=Console(quiet=True))
        tr = TaskRunner(sandbox, rm, parser, Console(quiet=True))

        task = _make_task("t")
        session = MagicMock()

        result = await tr._write_instructions(task, session, context_files=[])

        assert "Additional Context" not in result


# ── CLI --context option appears in help ─────────────────────────────


class TestCLIContextOption:
    def test_plan_help_shows_context(self) -> None:
        result = runner.invoke(app, ["plan", "--help"])
        assert result.exit_code == 0
        assert "--context" in result.output

    def test_dev_help_shows_context(self) -> None:
        result = runner.invoke(app, ["dev", "--help"])
        assert result.exit_code == 0
        assert "--context" in result.output

    def test_qa_help_shows_context(self) -> None:
        result = runner.invoke(app, ["qa", "--help"])
        assert result.exit_code == 0
        assert "--context" in result.output

    def test_docs_help_shows_context(self) -> None:
        result = runner.invoke(app, ["docs", "--help"])
        assert result.exit_code == 0
        assert "--context" in result.output

    def test_run_help_shows_context(self) -> None:
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--context" in result.output

    def test_run_invocation_passes_context(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "my-comp"
        comp_dir.mkdir()
        (comp_dir / "01-task.yaml").write_text("name: t\ninstructions: x\nprompt: y\n")

        ctx_file = tmp_path / "ctx.md"
        ctx_file.write_text("context data")

        mock_runner = MagicMock()
        mock_result = MagicMock(run_id="r1", status="completed", error_message="")
        mock_runner.run = AsyncMock(return_value=mock_result)

        mock_cfg = MagicMock()
        mock_cfg.default_model = "claude-sonnet-4-6"
        mock_cfg.default_max_turns = 100
        mock_cfg.timeout_minutes = 30
        mock_cfg.max_budget_usd = None
        mock_cfg.output_dir = Path("./outputs")
        mock_cfg.anthropic_api_key = "sk-ant-test"
        mock_cfg.github_token = "ghp_test"
        mock_cfg.image_name = "dkmv-sandbox:latest"
        mock_cfg.memory_limit = "8g"

        with (
            patch("dkmv.cli.load_config", return_value=mock_cfg),
            patch("dkmv.tasks.ComponentRunner", return_value=mock_runner),
            patch("dkmv.core.runner.RunManager"),
            patch("dkmv.core.sandbox.SandboxManager"),
            patch("dkmv.core.stream.StreamParser"),
            patch("dkmv.tasks.loader.TaskLoader"),
            patch("dkmv.tasks.runner.TaskRunner"),
        ):
            result = runner.invoke(
                app,
                [
                    "run",
                    str(comp_dir),
                    "--repo",
                    "https://github.com/t/r",
                    "--context",
                    str(ctx_file),
                ],
            )

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["context_paths"] == [ctx_file]

    def test_run_multiple_context_paths(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "my-comp"
        comp_dir.mkdir()
        (comp_dir / "01-task.yaml").write_text("name: t\ninstructions: x\nprompt: y\n")

        ctx1 = tmp_path / "a.md"
        ctx1.write_text("a")
        ctx2 = tmp_path / "b.md"
        ctx2.write_text("b")

        mock_runner = MagicMock()
        mock_result = MagicMock(run_id="r1", status="completed", error_message="")
        mock_runner.run = AsyncMock(return_value=mock_result)

        mock_cfg = MagicMock()
        mock_cfg.default_model = "claude-sonnet-4-6"
        mock_cfg.default_max_turns = 100
        mock_cfg.timeout_minutes = 30
        mock_cfg.max_budget_usd = None
        mock_cfg.output_dir = Path("./outputs")
        mock_cfg.anthropic_api_key = "sk-ant-test"
        mock_cfg.github_token = "ghp_test"
        mock_cfg.image_name = "dkmv-sandbox:latest"
        mock_cfg.memory_limit = "8g"

        with (
            patch("dkmv.cli.load_config", return_value=mock_cfg),
            patch("dkmv.tasks.ComponentRunner", return_value=mock_runner),
            patch("dkmv.core.runner.RunManager"),
            patch("dkmv.core.sandbox.SandboxManager"),
            patch("dkmv.core.stream.StreamParser"),
            patch("dkmv.tasks.loader.TaskLoader"),
            patch("dkmv.tasks.runner.TaskRunner"),
        ):
            result = runner.invoke(
                app,
                [
                    "run",
                    str(comp_dir),
                    "--repo",
                    "https://github.com/t/r",
                    "--context",
                    str(ctx1),
                    "--context",
                    str(ctx2),
                ],
            )

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert len(call_kwargs["context_paths"]) == 2

    def test_run_no_context_passes_none(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "my-comp"
        comp_dir.mkdir()
        (comp_dir / "01-task.yaml").write_text("name: t\ninstructions: x\nprompt: y\n")

        mock_runner = MagicMock()
        mock_result = MagicMock(run_id="r1", status="completed", error_message="")
        mock_runner.run = AsyncMock(return_value=mock_result)

        mock_cfg = MagicMock()
        mock_cfg.default_model = "claude-sonnet-4-6"
        mock_cfg.default_max_turns = 100
        mock_cfg.timeout_minutes = 30
        mock_cfg.max_budget_usd = None
        mock_cfg.output_dir = Path("./outputs")
        mock_cfg.anthropic_api_key = "sk-ant-test"
        mock_cfg.github_token = "ghp_test"
        mock_cfg.image_name = "dkmv-sandbox:latest"
        mock_cfg.memory_limit = "8g"

        with (
            patch("dkmv.cli.load_config", return_value=mock_cfg),
            patch("dkmv.tasks.ComponentRunner", return_value=mock_runner),
            patch("dkmv.core.runner.RunManager"),
            patch("dkmv.core.sandbox.SandboxManager"),
            patch("dkmv.core.stream.StreamParser"),
            patch("dkmv.tasks.loader.TaskLoader"),
            patch("dkmv.tasks.runner.TaskRunner"),
        ):
            result = runner.invoke(
                app,
                [
                    "run",
                    str(comp_dir),
                    "--repo",
                    "https://github.com/t/r",
                ],
            )

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["context_paths"] is None
