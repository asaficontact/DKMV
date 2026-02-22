from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from dkmv.core.runner import RunManager
from dkmv.core.sandbox import SandboxManager
from dkmv.tasks.component import ComponentRunner
from dkmv.tasks.loader import TaskLoader
from dkmv.tasks.models import CLIOverrides, TaskDefinition, TaskResult
from dkmv.tasks.runner import TaskRunner


def _make_task(name: str = "plan") -> TaskDefinition:
    return TaskDefinition(name=name, instructions="do stuff", prompt="go")


def _make_task_result(
    name: str = "plan", status: str = "completed", cost: float = 0.5, turns: int = 3
) -> TaskResult:
    return TaskResult(
        task_name=name,
        status=status,  # type: ignore[arg-type]
        total_cost_usd=cost,
        num_turns=turns,
    )


@pytest.fixture
def sandbox() -> AsyncMock:
    s = AsyncMock(spec=SandboxManager)
    s.execute = AsyncMock(return_value=MagicMock(output="", exit_code=0))
    s.start = AsyncMock(return_value=MagicMock())
    s.stop = AsyncMock()
    s.setup_git_auth = AsyncMock(return_value=MagicMock(exit_code=0, output=""))
    s.get_container_name = MagicMock(return_value="dkmv-test-container")
    return s


@pytest.fixture
def run_manager(tmp_path: Path) -> RunManager:
    return RunManager(output_dir=tmp_path)


@pytest.fixture
def task_runner() -> AsyncMock:
    return AsyncMock(spec=TaskRunner)


@pytest.fixture
def task_loader() -> MagicMock:
    return MagicMock(spec=TaskLoader)


def _mock_config() -> MagicMock:
    cfg = MagicMock()
    cfg.anthropic_api_key = "sk-ant-test"
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
def config() -> MagicMock:
    return _mock_config()


@pytest.fixture
def component_runner(
    sandbox: AsyncMock,
    run_manager: RunManager,
    task_loader: MagicMock,
    task_runner: AsyncMock,
) -> ComponentRunner:
    return ComponentRunner(sandbox, run_manager, task_loader, task_runner, Console())


def _create_component_dir(tmp_path: Path, num_tasks: int = 2) -> Path:
    comp_dir = tmp_path / "my-component"
    comp_dir.mkdir()
    for i in range(num_tasks):
        (comp_dir / f"0{i + 1}-task{i + 1}.yaml").write_text(
            f"name: task{i + 1}\ninstructions: do stuff\nprompt: go\n"
        )
    return comp_dir


class TestContainerLifecycle:
    async def test_container_started_and_stopped(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=1)
        task_loader.load.return_value = _make_task("task1")
        task_runner.run.return_value = _make_task_result("task1")

        await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
        )

        sandbox.start.assert_awaited_once()
        sandbox.stop.assert_awaited_once_with(sandbox.start.return_value, keep_alive=False)

    async def test_container_kept_alive_when_requested(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=1)
        task_loader.load.return_value = _make_task("task1")
        task_runner.run.return_value = _make_task_result("task1")

        await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
            keep_alive=True,
        )

        sandbox.stop.assert_awaited_once_with(sandbox.start.return_value, keep_alive=True)

    async def test_container_stopped_on_error(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=1)
        task_loader.load.return_value = _make_task("task1")
        task_runner.run.side_effect = RuntimeError("boom")

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
        )

        assert result.status == "failed"
        sandbox.stop.assert_awaited_once()


class TestWorkspaceSetup:
    async def test_git_clone_and_branch_setup(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=1)
        task_loader.load.return_value = _make_task("task1")
        task_runner.run.return_value = _make_task_result("task1")

        await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            "feat-branch",
            "feat",
            {},
            config,
            CLIOverrides(),
        )

        sandbox.setup_git_auth.assert_awaited_once()
        calls = [str(c) for c in sandbox.execute.call_args_list]
        assert any("git clone" in c for c in calls)
        assert any("git checkout" in c and "feat-branch" in c for c in calls)

    async def test_dkmv_dir_and_gitignore_created(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=1)
        task_loader.load.return_value = _make_task("task1")
        task_runner.run.return_value = _make_task_result("task1")

        await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
        )

        calls = [str(c) for c in sandbox.execute.call_args_list]
        assert any("mkdir -p .dkmv" in c for c in calls)
        assert any(".gitignore" in c for c in calls)


class TestTaskSequencing:
    async def test_tasks_execute_in_order(
        self,
        component_runner: ComponentRunner,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=2)
        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        task_runner.run.side_effect = [
            _make_task_result("task1"),
            _make_task_result("task2"),
        ]

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
        )

        assert task_runner.run.call_count == 2
        assert result.task_results[0].task_name == "task1"
        assert result.task_results[1].task_name == "task2"

    async def test_fail_fast_on_failure(
        self,
        component_runner: ComponentRunner,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=2)
        task_loader.load.return_value = _make_task("task1")
        task_runner.run.return_value = _make_task_result("task1", status="failed")

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
        )

        assert result.status == "failed"
        assert task_runner.run.call_count == 1
        assert len(result.task_results) == 2
        assert result.task_results[1].status == "skipped"

    async def test_fail_fast_on_timeout(
        self,
        component_runner: ComponentRunner,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=2)
        task_loader.load.return_value = _make_task("task1")
        task_runner.run.return_value = _make_task_result("task1", status="timed_out")

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
        )

        assert result.status == "timed_out"
        assert result.task_results[1].status == "skipped"


class TestVariablePropagation:
    async def test_builtin_vars_available(
        self,
        component_runner: ComponentRunner,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=1)
        task_loader.load.return_value = _make_task("task1")
        task_runner.run.return_value = _make_task_result("task1")

        await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            "main",
            "my-feature",
            {},
            config,
            CLIOverrides(),
        )

        call_args = task_loader.load.call_args
        variables = call_args[0][1]
        assert variables["repo"] == "https://github.com/t/r"
        assert variables["branch"] == "main"
        assert variables["feature_name"] == "my-feature"
        assert variables["component"] == comp_dir.name
        assert variables["model"] == config.default_model
        assert "run_id" in variables

    async def test_cli_vars_available(
        self,
        component_runner: ComponentRunner,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=1)
        task_loader.load.return_value = _make_task("task1")
        task_runner.run.return_value = _make_task_result("task1")

        await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {"prd_path": "/tmp/prd.md", "extra": "val"},
            config,
            CLIOverrides(),
        )

        call_args = task_loader.load.call_args
        variables = call_args[0][1]
        assert variables["prd_path"] == "/tmp/prd.md"
        assert variables["extra"] == "val"

    async def test_previous_task_results_in_variables(
        self,
        component_runner: ComponentRunner,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=2)
        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        task_runner.run.side_effect = [
            _make_task_result("task1", cost=1.23, turns=5),
            _make_task_result("task2"),
        ]

        await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
        )

        # The second call to load should have task1's results in variables
        second_call = task_loader.load.call_args_list[1]
        variables = second_call[0][1]
        assert "tasks" in variables
        assert variables["tasks"]["task1"]["status"] == "completed"
        assert variables["tasks"]["task1"]["cost"] == "1.23"
        assert variables["tasks"]["task1"]["turns"] == "5"


class TestAggregation:
    async def test_cost_aggregated_across_tasks(
        self,
        component_runner: ComponentRunner,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=2)
        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        task_runner.run.side_effect = [
            _make_task_result("task1", cost=1.0),
            _make_task_result("task2", cost=2.5),
        ]

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
        )

        assert result.total_cost_usd == 3.5

    async def test_run_result_saved(
        self,
        component_runner: ComponentRunner,
        run_manager: RunManager,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=1)
        task_loader.load.return_value = _make_task("task1")
        task_runner.run.return_value = _make_task_result("task1")

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
        )

        # Verify result.json exists
        run_dir = run_manager._runs_dir / result.run_id
        assert (run_dir / "result.json").exists()
        assert (run_dir / "tasks_result.json").exists()


class TestResultStatuses:
    async def test_all_tasks_succeed_completed(
        self,
        component_runner: ComponentRunner,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=2)
        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        task_runner.run.side_effect = [
            _make_task_result("task1"),
            _make_task_result("task2"),
        ]

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
        )

        assert result.status == "completed"

    async def test_empty_component_returns_completed(
        self,
        component_runner: ComponentRunner,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = tmp_path / "empty-component"
        comp_dir.mkdir()

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
        )

        assert result.status == "completed"
        assert result.task_results == []
