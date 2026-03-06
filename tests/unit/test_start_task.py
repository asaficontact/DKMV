"""Tests for --start-task feature: skip earlier tasks, reconstruct from repo."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console
from typer.testing import CliRunner

from dkmv.cli import app
from dkmv.core.runner import RunManager
from dkmv.core.sandbox import SandboxManager
from dkmv.tasks.component import ComponentRunner, WORKSPACE_DIR
from dkmv.tasks.loader import TaskLoader
from dkmv.tasks.models import CLIOverrides, TaskDefinition, TaskOutput, TaskResult
from dkmv.tasks.runner import TaskRunner

runner = CliRunner()

AGENT_DIR = f"{WORKSPACE_DIR}/.agent/"


# ── Fixtures ──────────────────────────────────────────────────────────


def _make_task(name: str = "t", outputs: list[TaskOutput] | None = None) -> TaskDefinition:
    return TaskDefinition(
        name=name,
        instructions="do stuff",
        prompt="go",
        outputs=outputs or [],
    )


def _make_task_result(name: str = "t", status: str = "completed") -> TaskResult:
    return TaskResult(task_name=name, status=status, total_cost_usd=0.1, num_turns=1)


@pytest.fixture
def sandbox() -> AsyncMock:
    s = AsyncMock(spec=SandboxManager)
    s.execute = AsyncMock(return_value=MagicMock(output="", exit_code=0))
    s.start = AsyncMock(return_value=MagicMock())
    s.stop = AsyncMock()
    s.setup_git_auth = AsyncMock(return_value=MagicMock(exit_code=0, output=""))
    s.get_container_name = MagicMock(return_value="dkmv-test-container")
    s.write_file = AsyncMock()
    s.read_file = AsyncMock(return_value="")
    s.file_exists = AsyncMock(return_value=False)
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


@pytest.fixture
def component_runner(
    sandbox: AsyncMock,
    run_manager: RunManager,
    task_loader: MagicMock,
    task_runner_mock: AsyncMock,
) -> ComponentRunner:
    return ComponentRunner(sandbox, run_manager, task_loader, task_runner_mock, Console())


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
    cfg.default_agent = "claude"
    return cfg


# ── _resolve_start_task tests ────────────────────────────────────────


class TestResolveStartTask:
    def _make_refs(self, names: list[str]) -> list[tuple[Path, None, None, None]]:
        return [(Path(f"{n}.yaml"), None, None, None) for n in names]

    def test_numeric_index_valid(self) -> None:
        refs = self._make_refs(["01-analyze", "02-features", "03-phases"])
        assert ComponentRunner._resolve_start_task("2", refs) == 1

    def test_numeric_index_first(self) -> None:
        refs = self._make_refs(["01-analyze", "02-features"])
        assert ComponentRunner._resolve_start_task("1", refs) == 0

    def test_numeric_index_last(self) -> None:
        refs = self._make_refs(["01-analyze", "02-features", "03-phases"])
        assert ComponentRunner._resolve_start_task("3", refs) == 2

    def test_numeric_index_zero_raises(self) -> None:
        refs = self._make_refs(["01-analyze"])
        with pytest.raises(ValueError, match="out of range"):
            ComponentRunner._resolve_start_task("0", refs)

    def test_numeric_index_too_large_raises(self) -> None:
        refs = self._make_refs(["01-analyze", "02-features"])
        with pytest.raises(ValueError, match="out of range"):
            ComponentRunner._resolve_start_task("5", refs)

    def test_exact_stem_match(self) -> None:
        refs = self._make_refs(["01-analyze", "02-features", "03-phases"])
        assert ComponentRunner._resolve_start_task("02-features", refs) == 1

    def test_suffix_match(self) -> None:
        refs = self._make_refs(["01-analyze", "02-features", "03-phases"])
        assert ComponentRunner._resolve_start_task("phases", refs) == 2

    def test_suffix_match_first(self) -> None:
        refs = self._make_refs(["01-analyze", "02-features"])
        assert ComponentRunner._resolve_start_task("analyze", refs) == 0

    def test_name_not_found_raises(self) -> None:
        refs = self._make_refs(["01-analyze", "02-features"])
        with pytest.raises(ValueError, match="not found"):
            ComponentRunner._resolve_start_task("phases", refs)

    def test_error_lists_available(self) -> None:
        refs = self._make_refs(["01-analyze", "02-features"])
        with pytest.raises(ValueError, match="01-analyze.*02-features"):
            ComponentRunner._resolve_start_task("missing", refs)


# ── _reconstruct_task_from_repo tests ────────────────────────────────


class TestReconstructTaskFromRepo:
    async def test_reads_existing_output(
        self, component_runner: ComponentRunner, sandbox: AsyncMock
    ) -> None:
        output = TaskOutput(path="result.json", required=True, required_fields=[])
        task = _make_task("analyze", outputs=[output])
        session = MagicMock()

        sandbox.file_exists.return_value = True
        sandbox.read_file.return_value = '{"output_dir": "docs/impl"}'

        result = await component_runner._reconstruct_task_from_repo(task, session)

        assert result.task_name == "analyze"
        assert result.status == "pre-existing"
        # Path is normalized by TaskOutput validator
        assert task.outputs[0].path in result.outputs

    async def test_required_output_missing_raises(
        self, component_runner: ComponentRunner, sandbox: AsyncMock
    ) -> None:
        output = TaskOutput(path="result.json", required=True, required_fields=[])
        task = _make_task("analyze", outputs=[output])
        session = MagicMock()

        sandbox.file_exists.return_value = False

        with pytest.raises(FileNotFoundError, match="Cannot skip task 'analyze'"):
            await component_runner._reconstruct_task_from_repo(task, session)

    async def test_optional_output_missing_skipped(
        self, component_runner: ComponentRunner, sandbox: AsyncMock
    ) -> None:
        output = TaskOutput(path="optional.txt", required=False, required_fields=[])
        task = _make_task("t", outputs=[output])
        session = MagicMock()

        sandbox.file_exists.return_value = False

        result = await component_runner._reconstruct_task_from_repo(task, session)

        assert result.status == "pre-existing"
        assert result.outputs == {}

    async def test_multiple_outputs_partial(
        self, component_runner: ComponentRunner, sandbox: AsyncMock
    ) -> None:
        outputs = [
            TaskOutput(path="required.json", required=True, required_fields=[]),
            TaskOutput(path="optional.txt", required=False, required_fields=[]),
        ]
        task = _make_task("t", outputs=outputs)
        session = MagicMock()

        # First output exists, second doesn't
        sandbox.file_exists.side_effect = [True, False]
        sandbox.read_file.return_value = '{"key": "value"}'

        result = await component_runner._reconstruct_task_from_repo(task, session)

        assert result.status == "pre-existing"
        assert len(result.outputs) == 1

    async def test_no_outputs_succeeds(
        self, component_runner: ComponentRunner, sandbox: AsyncMock
    ) -> None:
        task = _make_task("t", outputs=[])
        session = MagicMock()

        result = await component_runner._reconstruct_task_from_repo(task, session)

        assert result.status == "pre-existing"
        assert result.outputs == {}


# ── ComponentRunner.run with start_task ──────────────────────────────


def _create_component_dir(tmp_path: Path, task_count: int = 3) -> Path:
    comp_dir = tmp_path / "my-comp"
    comp_dir.mkdir()
    for i in range(1, task_count + 1):
        name = ["analyze", "features", "phases"][i - 1] if i <= 3 else f"task{i}"
        (comp_dir / f"0{i}-{name}.yaml").write_text(
            f"name: {name}\ninstructions: do stuff\nprompt: go\n"
        )
    return comp_dir


class TestStartTaskIntegration:
    async def test_start_task_skips_earlier_tasks(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner_mock: AsyncMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path)
        config = _mock_config()

        # Task loader returns different tasks for each call
        task_loader.load.side_effect = [
            _make_task("analyze"),  # skipped - reconstructed
            _make_task("features"),  # skipped - reconstructed
            _make_task("phases"),  # actually run
        ]
        task_runner_mock.run.return_value = _make_task_result("phases")

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
            start_task="3",
        )

        # Task runner should only be called once (for task 3)
        assert task_runner_mock.run.call_count == 1
        called_task = task_runner_mock.run.call_args[0][0]
        assert called_task.name == "phases"

        # All 3 tasks in results
        assert len(result.task_results) == 3
        assert result.task_results[0].status == "pre-existing"
        assert result.task_results[1].status == "pre-existing"
        assert result.task_results[2].status == "completed"

    async def test_start_task_by_name(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner_mock: AsyncMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path)
        config = _mock_config()

        task_loader.load.side_effect = [
            _make_task("analyze"),
            _make_task("features"),
            _make_task("phases"),
        ]
        task_runner_mock.run.return_value = _make_task_result("phases")

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
            start_task="phases",
        )

        assert task_runner_mock.run.call_count == 1
        assert result.task_results[0].status == "pre-existing"
        assert result.task_results[1].status == "pre-existing"

    async def test_start_task_none_runs_all(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner_mock: AsyncMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, task_count=2)
        config = _mock_config()

        task_loader.load.side_effect = [
            _make_task("analyze"),
            _make_task("features"),
        ]
        task_runner_mock.run.return_value = _make_task_result("t")

        await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
        )

        # Both tasks should be run (not skipped)
        assert task_runner_mock.run.call_count == 2

    async def test_start_task_1_runs_all(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner_mock: AsyncMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, task_count=2)
        config = _mock_config()

        task_loader.load.side_effect = [
            _make_task("analyze"),
            _make_task("features"),
        ]
        task_runner_mock.run.return_value = _make_task_result("t")

        await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
            start_task="1",
        )

        assert task_runner_mock.run.call_count == 2

    async def test_start_task_invalid_raises(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner_mock: AsyncMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path)
        config = _mock_config()

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
            start_task="99",
        )

        # Should fail with error
        assert result.status == "failed"
        assert "out of range" in result.error_message

    async def test_start_task_missing_output_fails(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner_mock: AsyncMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path)
        config = _mock_config()

        # First task has required output that's missing from repo
        output = TaskOutput(path="analysis.json", required=True, required_fields=[])
        task_loader.load.return_value = _make_task("analyze", outputs=[output])
        sandbox.file_exists.return_value = False

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
            start_task="2",
        )

        assert result.status == "failed"
        assert "Cannot skip task" in result.error_message

    async def test_skipped_task_outputs_available_to_later_tasks(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner_mock: AsyncMock,
        tmp_path: Path,
    ) -> None:
        """Verify that reconstructed outputs feed into _build_variables for later tasks."""
        comp_dir = _create_component_dir(tmp_path, task_count=2)
        config = _mock_config()

        # First task has a required output
        output = TaskOutput(path="analysis.json", required=True, required_fields=[])
        task1 = _make_task("analyze", outputs=[output])
        task2 = _make_task("features")
        task_loader.load.side_effect = [task1, task2]

        # Output exists in repo
        sandbox.file_exists.return_value = True
        sandbox.read_file.return_value = '{"output_dir": "docs/impl"}'
        task_runner_mock.run.return_value = _make_task_result("features")

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
            start_task="2",
        )

        assert result.status == "completed"
        # The reconstructed task should have outputs populated
        assert result.task_results[0].status == "pre-existing"
        assert len(result.task_results[0].outputs) == 1

        # Verify _build_variables was called with the reconstructed outputs
        # by checking that the second task_loader.load received variables
        # with tasks.analyze populated
        second_call_vars = task_loader.load.call_args_list[1][0][1]
        assert "tasks" in second_call_vars
        assert "analyze" in second_call_vars["tasks"]
        assert "output_dir" in second_call_vars["tasks"]["analyze"]["outputs"]["analysis"]


# ── CLI --start-task option tests ────────────────────────────────────


class TestCLIStartTaskOption:
    def test_plan_help_shows_start_task(self) -> None:
        result = runner.invoke(app, ["plan", "--help"])
        assert result.exit_code == 0
        assert "--start-task" in result.output

    def test_dev_help_shows_start_task(self) -> None:
        result = runner.invoke(app, ["dev", "--help"])
        assert result.exit_code == 0
        assert "--start-task" in result.output

    def test_qa_help_shows_start_task(self) -> None:
        result = runner.invoke(app, ["qa", "--help"])
        assert result.exit_code == 0
        assert "--start-task" in result.output

    def test_docs_help_shows_start_task(self) -> None:
        result = runner.invoke(app, ["docs", "--help"])
        assert result.exit_code == 0
        assert "--start-task" in result.output

    def test_run_help_shows_start_task(self) -> None:
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--start-task" in result.output

    def test_dev_start_phase_and_start_task_mutually_exclusive(self) -> None:
        result = runner.invoke(
            app,
            [
                "dev",
                "--impl-docs",
                "/tmp/nonexistent",
                "--start-phase",
                "2",
                "--start-task",
                "3",
            ],
        )
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output
