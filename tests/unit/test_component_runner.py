from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

from dkmv.core.runner import RunManager
from dkmv.core.sandbox import SandboxManager
from dkmv.tasks.component import AGENT_EMAIL, ComponentRunner, _agent_git_name
from dkmv.tasks.loader import TaskLoader
from dkmv.tasks.models import CLIOverrides, TaskDefinition, TaskResult
from dkmv.tasks.pause import PauseResponse
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


def _mock_task_ref(
    file: str,
    model: str | None = None,
    max_turns: int | None = None,
    timeout_minutes: int | None = None,
    max_budget_usd: float | None = None,
    pause_after: bool = False,
    for_each: str | None = None,
) -> MagicMock:
    return MagicMock(
        file=file,
        model=model,
        max_turns=max_turns,
        timeout_minutes=timeout_minutes,
        max_budget_usd=max_budget_usd,
        pause_after=pause_after,
        for_each=for_each,
    )


def _mock_manifest(
    inputs: list | None = None,
    workspace_dirs: list | None = None,
    state_files: list | None = None,
    agent_md: str | None = None,
    agent_md_file: str | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    timeout_minutes: int | None = None,
    max_budget_usd: float | None = None,
    tasks: list | None = None,
) -> MagicMock:
    return MagicMock(
        inputs=inputs or [],
        workspace_dirs=workspace_dirs or [],
        state_files=state_files or [],
        agent_md=agent_md,
        agent_md_file=agent_md_file,
        model=model,
        max_turns=max_turns,
        timeout_minutes=timeout_minutes,
        max_budget_usd=max_budget_usd,
        tasks=tasks or [],
    )


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
    cfg.docker_socket = False
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
        assert any("mkdir -p .agent" in c for c in calls)
        # .claude/ added to gitignore with trailing newline safety; .agent/ is NOT gitignored
        assert any(".claude/" in c and ".gitignore" in c for c in calls)
        assert not any("'.agent/'" in c and ".gitignore" in c for c in calls)
        # Git identity configured in workspace
        assert any("git config user.name" in c and "DKMV/My-Component" in c for c in calls)
        assert any(
            "git config user.email" in c and "dkmv-agent@noreply.dkmv.dev" in c for c in calls
        )


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


class TestOutputVariables:
    async def test_json_outputs_parsed_into_variables(
        self,
        component_runner: ComponentRunner,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=2)
        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        result1 = _make_task_result("task1")
        result1.outputs = {
            ".agent/analysis.json": json.dumps({"output_dir": "/out", "features": ["a"]})
        }
        task_runner.run.side_effect = [result1, _make_task_result("task2")]

        await component_runner.run(
            comp_dir, "https://github.com/t/r", None, "feat", {}, config, CLIOverrides()
        )

        second_call = task_loader.load.call_args_list[1]
        variables = second_call[0][1]
        assert variables["tasks"]["task1"]["outputs"]["analysis"]["output_dir"] == "/out"
        assert variables["tasks"]["task1"]["outputs"]["analysis"]["features"] == ["a"]

    async def test_non_json_outputs_stored_as_strings(
        self,
        component_runner: ComponentRunner,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=2)
        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        result1 = _make_task_result("task1")
        result1.outputs = {".agent/report.txt": "plain text content"}
        task_runner.run.side_effect = [result1, _make_task_result("task2")]

        await component_runner.run(
            comp_dir, "https://github.com/t/r", None, "feat", {}, config, CLIOverrides()
        )

        second_call = task_loader.load.call_args_list[1]
        variables = second_call[0][1]
        assert variables["tasks"]["task1"]["outputs"]["report"] == "plain text content"

    async def test_multiple_outputs_keyed_by_stem(
        self,
        component_runner: ComponentRunner,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=2)
        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        result1 = _make_task_result("task1")
        result1.outputs = {
            ".agent/analysis.json": json.dumps({"key": "val"}),
            ".agent/report.txt": "hello",
        }
        task_runner.run.side_effect = [result1, _make_task_result("task2")]

        await component_runner.run(
            comp_dir, "https://github.com/t/r", None, "feat", {}, config, CLIOverrides()
        )

        second_call = task_loader.load.call_args_list[1]
        variables = second_call[0][1]
        assert "analysis" in variables["tasks"]["task1"]["outputs"]
        assert "report" in variables["tasks"]["task1"]["outputs"]

    async def test_empty_outputs_produces_empty_dict(
        self,
        component_runner: ComponentRunner,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=2)
        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        result1 = _make_task_result("task1")
        result1.outputs = {}
        task_runner.run.side_effect = [result1, _make_task_result("task2")]

        await component_runner.run(
            comp_dir, "https://github.com/t/r", None, "feat", {}, config, CLIOverrides()
        )

        second_call = task_loader.load.call_args_list[1]
        variables = second_call[0][1]
        assert variables["tasks"]["task1"]["outputs"] == {}

    async def test_nested_json_values_accessible(
        self,
        component_runner: ComponentRunner,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_component_dir(tmp_path, num_tasks=2)
        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        result1 = _make_task_result("task1")
        result1.outputs = {
            ".agent/analysis.json": json.dumps({"nested": {"deep": {"key": "value"}}})
        }
        task_runner.run.side_effect = [result1, _make_task_result("task2")]

        await component_runner.run(
            comp_dir, "https://github.com/t/r", None, "feat", {}, config, CLIOverrides()
        )

        second_call = task_loader.load.call_args_list[1]
        variables = second_call[0][1]
        assert (
            variables["tasks"]["task1"]["outputs"]["analysis"]["nested"]["deep"]["key"] == "value"
        )


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


def _create_manifest_component_dir(
    tmp_path: Path,
    num_tasks: int = 2,
    agent_md: str | None = None,
    workspace_dirs: list[str] | None = None,
    state_files: list[dict[str, str]] | None = None,
    defaults: dict[str, object] | None = None,
) -> Path:
    comp_dir = tmp_path / "manifest-component"
    comp_dir.mkdir(exist_ok=True)

    # Create task YAML files
    for i in range(num_tasks):
        (comp_dir / f"0{i + 1}-task{i + 1}.yaml").write_text(f"name: task{i + 1}\nprompt: go\n")

    # Build manifest YAML
    lines = ["name: manifest-component\n"]
    if agent_md:
        lines.append("agent_md: |\n")
        for line in agent_md.split("\n"):
            lines.append(f"  {line}\n")
    if workspace_dirs:
        lines.append("workspace_dirs:\n")
        for d in workspace_dirs:
            lines.append(f"  - {d}\n")
    if state_files:
        lines.append("state_files:\n")
        for sf in state_files:
            lines.append(f"  - dest: {sf['dest']}\n")
            lines.append(f"    content: {sf['content']}\n")
    if defaults:
        for k, v in defaults.items():
            lines.append(f"{k}: {v}\n")
    lines.append("tasks:\n")
    for i in range(num_tasks):
        lines.append(f"  - file: 0{i + 1}-task{i + 1}.yaml\n")

    (comp_dir / "component.yaml").write_text("".join(lines))
    return comp_dir


class TestManifestIntegration:
    async def test_manifest_ordering_used(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When component.yaml exists, task ordering comes from manifest."""
        comp_dir = _create_manifest_component_dir(tmp_path, num_tasks=2)
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[
                _mock_task_ref("02-task2.yaml"),
                _mock_task_ref("01-task1.yaml"),
            ],
        )
        task_loader.load.side_effect = [_make_task("task2"), _make_task("task1")]
        task_runner.run.side_effect = [
            _make_task_result("task2"),
            _make_task_result("task1"),
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
        assert result.task_results[0].task_name == "task2"
        assert result.task_results[1].task_name == "task1"

    async def test_agent_md_passed_to_task_runner(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_manifest_component_dir(tmp_path, num_tasks=1, agent_md="# My Agent")
        task_loader.load_manifest.return_value = _mock_manifest(
            agent_md="# My Agent",
            tasks=[_mock_task_ref("01-task1.yaml")],
        )
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

        call_kwargs = task_runner.run.call_args[1]
        assert call_kwargs["component_agent_md"] == "# My Agent"

    async def test_shared_env_vars_passed_to_task_runner(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_manifest_component_dir(tmp_path, num_tasks=1)
        task_loader.load_manifest.return_value = _mock_manifest(
            inputs=[
                MagicMock(
                    name="token",
                    type="env",
                    key="MY_TOKEN",
                    value="abc123",
                    src=None,
                    dest=None,
                    content=None,
                    optional=False,
                )
            ],
            tasks=[_mock_task_ref("01-task1.yaml")],
        )
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

        call_kwargs = task_runner.run.call_args[1]
        env_vars = call_kwargs["shared_env_vars"]
        assert env_vars["MY_TOKEN"] == "abc123"
        # Git identity vars are also injected
        assert "GIT_AUTHOR_NAME" in env_vars

    async def test_workspace_dirs_created(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_manifest_component_dir(
            tmp_path, num_tasks=1, workspace_dirs=[".agent", ".cache"]
        )
        task_loader.load_manifest.return_value = _mock_manifest(
            workspace_dirs=[".agent", ".cache"],
            tasks=[_mock_task_ref("01-task1.yaml")],
        )
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
        assert any("mkdir -p /home/dkmv/workspace/.agent" in c for c in calls)
        assert any("mkdir -p /home/dkmv/workspace/.cache" in c for c in calls)

    async def test_state_files_written(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_manifest_component_dir(tmp_path, num_tasks=1)
        task_loader.load_manifest.return_value = _mock_manifest(
            state_files=[MagicMock(dest="/workspace/.agent/state.json", content="{}")],
            tasks=[_mock_task_ref("01-task1.yaml")],
        )
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

        sandbox.write_file.assert_any_call(
            sandbox.start.return_value, "/workspace/.agent/state.json", "{}"
        )

    async def test_fallback_without_manifest(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Without component.yaml, fallback to alphabetical scan."""
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
        assert len(result.task_results) == 2
        # load_manifest should not have been called
        task_loader.load_manifest.assert_not_called()

    async def test_defaults_applied_from_manifest(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_manifest_component_dir(
            tmp_path, num_tasks=1, defaults={"model": "claude-sonnet-4-6", "max_turns": 50}
        )
        task_ref_mock = _mock_task_ref("01-task1.yaml")
        task_loader.load_manifest.return_value = _mock_manifest(
            model="claude-sonnet-4-6",
            max_turns=50,
            tasks=[task_ref_mock],
        )
        # Task loaded without model/max_turns — should get defaults applied
        task = TaskDefinition(name="task1", prompt="go")
        task_loader.load.return_value = task
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

        # Verify defaults were applied to the task
        assert task.model == "claude-sonnet-4-6"
        assert task.max_turns == 50


def _create_pause_manifest_component(
    tmp_path: Path,
    pause_after: bool = True,
) -> Path:
    """Create a component dir with manifest that has pause_after on first task."""
    comp_dir = tmp_path / "pause-component"
    comp_dir.mkdir(exist_ok=True)
    (comp_dir / "01-task1.yaml").write_text("name: task1\nprompt: go\n")
    (comp_dir / "02-task2.yaml").write_text("name: task2\nprompt: go\n")

    pause_str = "true" if pause_after else "false"
    manifest = (
        "name: pause-component\n"
        "tasks:\n"
        f"  - file: 01-task1.yaml\n"
        f"    pause_after: {pause_str}\n"
        "  - file: 02-task2.yaml\n"
    )
    (comp_dir / "component.yaml").write_text(manifest)
    return comp_dir


class TestPauseAfter:
    async def test_pause_callback_invoked_when_questions_present(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_pause_manifest_component(tmp_path, pause_after=True)
        analysis_json = json.dumps(
            {
                "features": [],
                "questions": [
                    {"id": "q1", "question": "Which DB?", "options": [], "default": "pg"}
                ],
            }
        )
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[
                _mock_task_ref("01-task1.yaml", pause_after=True),
                _mock_task_ref("02-task2.yaml"),
            ],
        )

        result1 = _make_task_result("task1")
        result1.outputs = {"analysis.json": analysis_json}
        result2 = _make_task_result("task2")

        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        task_runner.run.side_effect = [result1, result2]

        on_pause = AsyncMock(return_value=PauseResponse(answers={"q1": "pg"}))

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
            on_pause=on_pause,
        )

        assert result.status == "completed"
        on_pause.assert_awaited_once()
        pause_req = on_pause.call_args[0][0]
        assert pause_req.task_name == "task1"
        assert len(pause_req.questions) == 1
        # Answers should be merged into analysis.json, not written to user_decisions.json
        merged_data = json.loads(result.task_results[0].outputs["analysis.json"])
        assert merged_data["questions"][0]["user_answer"] == "pg"
        # Container file should be rewritten with merged content
        sandbox.write_file.assert_any_call(
            sandbox.start.return_value,
            "/home/dkmv/workspace/.agent/analysis.json",
            json.dumps(merged_data, indent=2),
        )
        # user_decisions.json should NOT be written (merge succeeded)
        decisions_calls = [
            c for c in sandbox.write_file.call_args_list if "/user_decisions.json" in str(c)
        ]
        assert decisions_calls == []

    async def test_pause_callback_invoked_without_questions(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_pause_manifest_component(tmp_path, pause_after=True)
        # Output with no questions field — callback still invoked
        analysis_json = json.dumps({"features": [], "constraints": []})
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[
                _mock_task_ref("01-task1.yaml", pause_after=True),
                _mock_task_ref("02-task2.yaml"),
            ],
        )

        result1 = _make_task_result("task1")
        result1.outputs = {"analysis.json": analysis_json}
        result2 = _make_task_result("task2")

        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        task_runner.run.side_effect = [result1, result2]

        on_pause = AsyncMock(return_value=PauseResponse(answers={}))

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
            on_pause=on_pause,
        )

        assert result.status == "completed"
        on_pause.assert_awaited_once()
        # No questions array in output → fallback to user_decisions.json
        sandbox.write_file.assert_any_call(
            sandbox.start.return_value,
            "/home/dkmv/workspace/.agent/user_decisions.json",
            json.dumps({}, indent=2),
        )

    async def test_pause_skipped_when_on_pause_is_none(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_pause_manifest_component(tmp_path, pause_after=True)
        analysis_json = json.dumps(
            {"questions": [{"id": "q1", "question": "Which DB?", "options": [], "default": "pg"}]}
        )
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[
                _mock_task_ref("01-task1.yaml", pause_after=True),
                _mock_task_ref("02-task2.yaml"),
            ],
        )

        result1 = _make_task_result("task1")
        result1.outputs = {"analysis.json": analysis_json}
        result2 = _make_task_result("task2")

        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        task_runner.run.side_effect = [result1, result2]

        # on_pause=None (default) — should not pause
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
        assert len(result.task_results) == 2

    async def test_pause_skipped_on_failed_task(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_pause_manifest_component(tmp_path, pause_after=True)
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[
                _mock_task_ref("01-task1.yaml", pause_after=True),
                _mock_task_ref("02-task2.yaml"),
            ],
        )

        task_loader.load.return_value = _make_task("task1")
        task_runner.run.return_value = _make_task_result("task1", status="failed")

        on_pause = AsyncMock(return_value=PauseResponse(answers={}))

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
            on_pause=on_pause,
        )

        assert result.status == "failed"
        on_pause.assert_not_awaited()

    async def test_pause_not_triggered_when_pause_after_false(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_pause_manifest_component(tmp_path, pause_after=False)
        analysis_json = json.dumps(
            {"questions": [{"id": "q1", "question": "Which DB?", "options": [], "default": "pg"}]}
        )
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[
                _mock_task_ref("01-task1.yaml"),
                _mock_task_ref("02-task2.yaml"),
            ],
        )

        result1 = _make_task_result("task1")
        result1.outputs = {"analysis.json": analysis_json}
        result2 = _make_task_result("task2")

        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        task_runner.run.side_effect = [result1, result2]

        on_pause = AsyncMock(return_value=PauseResponse(answers={}))

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
            on_pause=on_pause,
        )

        assert result.status == "completed"
        on_pause.assert_not_awaited()

    async def test_skip_remaining_skips_subsequent_tasks(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_pause_manifest_component(tmp_path, pause_after=True)
        analysis_json = json.dumps({"status": "fail", "issues": []})
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[
                _mock_task_ref("01-task1.yaml", pause_after=True),
                _mock_task_ref("02-task2.yaml"),
            ],
        )

        result1 = _make_task_result("task1")
        result1.outputs = {"eval.json": analysis_json}

        task_loader.load.side_effect = [_make_task("task1")]
        task_runner.run.side_effect = [result1]

        on_pause = AsyncMock(
            return_value=PauseResponse(answers={"action": "ship"}, skip_remaining=True)
        )

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
            on_pause=on_pause,
        )

        assert result.status == "completed"
        assert len(result.task_results) == 2
        assert result.task_results[0].task_name == "task1"
        assert result.task_results[0].status == "completed"
        assert result.task_results[1].task_name == "02-task2"
        assert result.task_results[1].status == "skipped"
        # Only one task should have been run
        task_runner.run.assert_awaited_once()

    async def test_skip_remaining_false_continues_normally(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_pause_manifest_component(tmp_path, pause_after=True)
        analysis_json = json.dumps({"status": "fail", "issues": []})
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[
                _mock_task_ref("01-task1.yaml", pause_after=True),
                _mock_task_ref("02-task2.yaml"),
            ],
        )

        result1 = _make_task_result("task1")
        result1.outputs = {"eval.json": analysis_json}
        result2 = _make_task_result("task2")

        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        task_runner.run.side_effect = [result1, result2]

        on_pause = AsyncMock(
            return_value=PauseResponse(answers={"action": "fix"}, skip_remaining=False)
        )

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
            on_pause=on_pause,
        )

        assert result.status == "completed"
        assert len(result.task_results) == 2
        assert all(r.status == "completed" for r in result.task_results)
        assert task_runner.run.await_count == 2

    async def test_pause_merge_partial_answers(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Only answered questions get user_answer; unanswered ones stay unchanged."""
        comp_dir = _create_pause_manifest_component(tmp_path, pause_after=True)
        analysis_json = json.dumps(
            {
                "features": [],
                "questions": [
                    {"id": "q1", "question": "Which DB?", "options": [], "default": "pg"},
                    {"id": "q2", "question": "Which cache?", "options": [], "default": "redis"},
                ],
            }
        )
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[
                _mock_task_ref("01-task1.yaml", pause_after=True),
                _mock_task_ref("02-task2.yaml"),
            ],
        )

        result1 = _make_task_result("task1")
        result1.outputs = {"analysis.json": analysis_json}
        result2 = _make_task_result("task2")

        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        task_runner.run.side_effect = [result1, result2]

        # User only answered q1, not q2
        on_pause = AsyncMock(return_value=PauseResponse(answers={"q1": "mysql"}))

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
            on_pause=on_pause,
        )

        assert result.status == "completed"
        merged = json.loads(result.task_results[0].outputs["analysis.json"])
        assert merged["questions"][0]["user_answer"] == "mysql"
        assert "user_answer" not in merged["questions"][1]

    async def test_pause_merge_with_multiple_outputs(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Merge targets the output file with questions, not other outputs."""
        comp_dir = _create_pause_manifest_component(tmp_path, pause_after=True)
        analysis_json = json.dumps(
            {
                "features": [],
                "questions": [
                    {"id": "q1", "question": "Which DB?", "options": [], "default": "pg"}
                ],
            }
        )
        other_json = json.dumps({"some": "data"})

        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[
                _mock_task_ref("01-task1.yaml", pause_after=True),
                _mock_task_ref("02-task2.yaml"),
            ],
        )

        result1 = _make_task_result("task1")
        result1.outputs = {"analysis.json": analysis_json, "other.json": other_json}
        result2 = _make_task_result("task2")

        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        task_runner.run.side_effect = [result1, result2]

        on_pause = AsyncMock(return_value=PauseResponse(answers={"q1": "pg"}))

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
            on_pause=on_pause,
        )

        assert result.status == "completed"
        # analysis.json should have user_answer merged
        merged = json.loads(result.task_results[0].outputs["analysis.json"])
        assert merged["questions"][0]["user_answer"] == "pg"
        # other.json should be unchanged
        assert result.task_results[0].outputs["other.json"] == other_json

    async def test_pause_empty_answers_no_merge(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Empty answers dict should fall back to user_decisions.json."""
        comp_dir = _create_pause_manifest_component(tmp_path, pause_after=True)
        analysis_json = json.dumps(
            {
                "features": [],
                "questions": [
                    {"id": "q1", "question": "Which DB?", "options": [], "default": "pg"}
                ],
            }
        )
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[
                _mock_task_ref("01-task1.yaml", pause_after=True),
                _mock_task_ref("02-task2.yaml"),
            ],
        )

        result1 = _make_task_result("task1")
        result1.outputs = {"analysis.json": analysis_json}
        result2 = _make_task_result("task2")

        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        task_runner.run.side_effect = [result1, result2]

        # Empty answers — nothing to merge
        on_pause = AsyncMock(return_value=PauseResponse(answers={}))

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
            on_pause=on_pause,
        )

        assert result.status == "completed"
        # No merge → fallback to user_decisions.json
        sandbox.write_file.assert_any_call(
            sandbox.start.return_value,
            "/home/dkmv/workspace/.agent/user_decisions.json",
            json.dumps({}, indent=2),
        )
        # analysis.json should NOT have user_answer field
        original = json.loads(result.task_results[0].outputs["analysis.json"])
        assert "user_answer" not in original["questions"][0]

    async def test_pause_merge_updates_jinja_variables(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """After merge, _build_variables should expose user_answer in Jinja2 templates."""
        comp_dir = _create_pause_manifest_component(tmp_path, pause_after=True)
        analysis_json = json.dumps(
            {
                "features": ["F1"],
                "questions": [
                    {"id": "q1", "question": "Which DB?", "options": [], "default": "pg"}
                ],
            }
        )
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[
                _mock_task_ref("01-task1.yaml", pause_after=True),
                _mock_task_ref("02-task2.yaml"),
            ],
        )

        result1 = _make_task_result("task1")
        result1.outputs = {"analysis.json": analysis_json}
        result2 = _make_task_result("task2")

        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        task_runner.run.side_effect = [result1, result2]

        on_pause = AsyncMock(return_value=PauseResponse(answers={"q1": "mysql"}))

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {},
            config,
            CLIOverrides(),
            on_pause=on_pause,
        )

        assert result.status == "completed"
        # Verify by calling _build_variables directly on the task results
        variables = component_runner._build_variables(
            {},
            "https://github.com/t/r",
            "main",
            "feat",
            "test",
            "r1",
            CLIOverrides(),
            config,
            result.task_results,
        )
        analysis = variables["tasks"]["task1"]["outputs"]["analysis"]
        assert analysis["questions"][0]["user_answer"] == "mysql"


class TestPromptsLog:
    async def test_prompts_log_created(
        self,
        component_runner: ComponentRunner,
        run_manager: RunManager,
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
            comp_dir, "https://github.com/t/r", None, "feat", {}, config, CLIOverrides()
        )

        run_dir = run_manager._runs_dir / result.run_id
        log_file = run_dir / "prompts_log.md"
        assert log_file.exists()
        content = log_file.read_text()
        assert "## Task 1: task1" in content
        assert "## Task 2: task2" in content

    async def test_prompts_log_includes_claude_md_content(
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
            comp_dir, "https://github.com/t/r", None, "feat", {}, config, CLIOverrides()
        )

        run_dir = run_manager._runs_dir / result.run_id
        # Simulate that task_runner saved a claude_md file (in real flow TaskRunner does this)
        (run_dir / "claude_md_task1.md").write_text("# DKMV Agent\n\nSystem rules here")

        # Re-run _save_prompts_log to pick it up
        component_runner._save_prompts_log(result.run_id, comp_dir.name, result.task_results)

        content = (run_dir / "prompts_log.md").read_text()
        assert "### Instructions" in content
        assert "DKMV Agent" in content

    async def test_prompts_log_includes_prompt_content(
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
            comp_dir, "https://github.com/t/r", None, "feat", {}, config, CLIOverrides()
        )

        run_dir = run_manager._runs_dir / result.run_id
        # Simulate prompt file saved by TaskRunner
        (run_dir / "prompt_task1.md").write_text("You are a senior architect. Do the work.")

        component_runner._save_prompts_log(result.run_id, comp_dir.name, result.task_results)

        content = (run_dir / "prompts_log.md").read_text()
        assert "### Prompt" in content
        assert "You are a senior architect" in content

    async def test_prompts_log_header_includes_component_name(
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
            comp_dir, "https://github.com/t/r", None, "feat", {}, config, CLIOverrides()
        )

        content = (run_manager._runs_dir / result.run_id / "prompts_log.md").read_text()
        assert f"# Component: {comp_dir.name}" in content


def _create_for_each_component(tmp_path: Path, num_normal_tasks: int = 0) -> Path:
    """Create a component with a for_each task YAML and optional normal tasks."""
    comp_dir = tmp_path / "foreach-component"
    comp_dir.mkdir(exist_ok=True)
    (comp_dir / "implement-phase.yaml").write_text(
        "name: phase-{{ item.phase_number }}\nprompt: go\n"
    )
    for i in range(num_normal_tasks):
        (comp_dir / f"0{i + 1}-setup.yaml").write_text(f"name: setup{i + 1}\nprompt: go\n")
    return comp_dir


class TestForEachExpansion:
    async def test_for_each_expands_task_to_n_instances(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_for_each_component(tmp_path)
        phases = [
            {"phase_number": 1, "phase_name": "foundation", "phase_file": "phase1_foundation.md"},
            {"phase_number": 2, "phase_name": "core", "phase_file": "phase2_core.md"},
            {"phase_number": 3, "phase_name": "polish", "phase_file": "phase3_polish.md"},
        ]
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[_mock_task_ref("implement-phase.yaml", for_each="phases")],
        )
        task_loader.load.side_effect = [
            _make_task("phase-1"),
            _make_task("phase-2"),
            _make_task("phase-3"),
        ]
        task_runner.run.side_effect = [
            _make_task_result("phase-1"),
            _make_task_result("phase-2"),
            _make_task_result("phase-3"),
        ]

        (comp_dir / "component.yaml").write_text(
            "name: test\ntasks:\n  - file: implement-phase.yaml\n    for_each: phases\n"
        )

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {"phases": phases},
            config,
            CLIOverrides(),
        )

        assert result.status == "completed"
        assert len(result.task_results) == 3
        assert task_runner.run.call_count == 3

    async def test_for_each_item_available_in_variables(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_for_each_component(tmp_path)
        phases = [
            {"phase_number": 1, "phase_name": "foundation", "phase_file": "phase1_foundation.md"},
        ]
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[_mock_task_ref("implement-phase.yaml", for_each="phases")],
        )
        task_loader.load.return_value = _make_task("phase-1")
        task_runner.run.return_value = _make_task_result("phase-1")
        (comp_dir / "component.yaml").write_text(
            "name: test\ntasks:\n  - file: implement-phase.yaml\n    for_each: phases\n"
        )

        await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {"phases": phases},
            config,
            CLIOverrides(),
        )

        call_args = task_loader.load.call_args
        variables = call_args[0][1]
        assert variables["item"] == {
            "phase_number": 1,
            "phase_name": "foundation",
            "phase_file": "phase1_foundation.md",
        }

    async def test_for_each_item_index_available(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_for_each_component(tmp_path)
        phases = [
            {"phase_number": 1, "phase_name": "a", "phase_file": "p1.md"},
            {"phase_number": 2, "phase_name": "b", "phase_file": "p2.md"},
        ]
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[_mock_task_ref("implement-phase.yaml", for_each="phases")],
        )
        task_loader.load.side_effect = [_make_task("p1"), _make_task("p2")]
        task_runner.run.side_effect = [_make_task_result("p1"), _make_task_result("p2")]
        (comp_dir / "component.yaml").write_text(
            "name: test\ntasks:\n  - file: implement-phase.yaml\n    for_each: phases\n"
        )

        await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {"phases": phases},
            config,
            CLIOverrides(),
        )

        first_call_vars = task_loader.load.call_args_list[0][0][1]
        second_call_vars = task_loader.load.call_args_list[1][0][1]
        assert first_call_vars["item_index"] == 0
        assert second_call_vars["item_index"] == 1

    async def test_for_each_empty_list_skips_task(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_for_each_component(tmp_path)
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[_mock_task_ref("implement-phase.yaml", for_each="phases")],
        )
        (comp_dir / "component.yaml").write_text(
            "name: test\ntasks:\n  - file: implement-phase.yaml\n    for_each: phases\n"
        )

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {"phases": []},
            config,
            CLIOverrides(),
        )

        assert result.status == "completed"
        assert len(result.task_results) == 0
        task_runner.run.assert_not_called()

    async def test_for_each_non_list_raises_error(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_for_each_component(tmp_path)
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[_mock_task_ref("implement-phase.yaml", for_each="phases")],
        )
        (comp_dir / "component.yaml").write_text(
            "name: test\ntasks:\n  - file: implement-phase.yaml\n    for_each: phases\n"
        )

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {"phases": "not-a-list"},
            config,
            CLIOverrides(),
        )

        assert result.status == "failed"
        assert "must reference a list variable" in result.error_message

    async def test_for_each_mixed_with_normal_tasks(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_for_each_component(tmp_path, num_normal_tasks=1)
        phases = [{"phase_number": 1, "phase_name": "a", "phase_file": "p1.md"}]
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[
                _mock_task_ref("01-setup.yaml"),
                _mock_task_ref("implement-phase.yaml", for_each="phases"),
            ],
        )
        task_loader.load.side_effect = [_make_task("setup1"), _make_task("phase-1")]
        task_runner.run.side_effect = [
            _make_task_result("setup1"),
            _make_task_result("phase-1"),
        ]
        (comp_dir / "component.yaml").write_text(
            "name: test\ntasks:\n  - file: 01-setup.yaml\n  - file: implement-phase.yaml\n    for_each: phases\n"
        )

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {"phases": phases},
            config,
            CLIOverrides(),
        )

        assert result.status == "completed"
        assert len(result.task_results) == 2
        assert result.task_results[0].task_name == "setup1"
        assert result.task_results[1].task_name == "phase-1"

    async def test_for_each_task_results_accumulate(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_for_each_component(tmp_path)
        phases = [
            {"phase_number": 1, "phase_name": "a", "phase_file": "p1.md"},
            {"phase_number": 2, "phase_name": "b", "phase_file": "p2.md"},
        ]
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[_mock_task_ref("implement-phase.yaml", for_each="phases")],
        )
        task_loader.load.side_effect = [_make_task("p1"), _make_task("p2")]
        task_runner.run.side_effect = [
            _make_task_result("p1", cost=1.0),
            _make_task_result("p2", cost=2.0),
        ]
        (comp_dir / "component.yaml").write_text(
            "name: test\ntasks:\n  - file: implement-phase.yaml\n    for_each: phases\n"
        )

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {"phases": phases},
            config,
            CLIOverrides(),
        )

        assert len(result.task_results) == 2
        assert result.total_cost_usd == 3.0

    async def test_for_each_failure_skips_remaining(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_for_each_component(tmp_path)
        phases = [
            {"phase_number": 1, "phase_name": "a", "phase_file": "p1.md"},
            {"phase_number": 2, "phase_name": "b", "phase_file": "p2.md"},
            {"phase_number": 3, "phase_name": "c", "phase_file": "p3.md"},
        ]
        task_loader.load_manifest.return_value = _mock_manifest(
            tasks=[_mock_task_ref("implement-phase.yaml", for_each="phases")],
        )
        task_loader.load.side_effect = [_make_task("p1"), _make_task("p2")]
        task_runner.run.side_effect = [
            _make_task_result("p1"),
            _make_task_result("p2", status="failed"),
        ]
        (comp_dir / "component.yaml").write_text(
            "name: test\ntasks:\n  - file: implement-phase.yaml\n    for_each: phases\n"
        )

        result = await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            None,
            "feat",
            {"phases": phases},
            config,
            CLIOverrides(),
        )

        assert result.status == "failed"
        assert len(result.task_results) == 3
        assert result.task_results[0].status == "completed"
        assert result.task_results[1].status == "failed"
        assert result.task_results[2].status == "skipped"


class TestAgentMdFile:
    async def test_agent_md_file_loaded_into_agent_md(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_manifest_component_dir(tmp_path, num_tasks=1)
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Project Rules\nFollow these rules.")

        task_loader.load_manifest.return_value = _mock_manifest(
            agent_md_file=str(claude_md),
            tasks=[_mock_task_ref("01-task1.yaml")],
        )
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

        call_kwargs = task_runner.run.call_args[1]
        assert call_kwargs["component_agent_md"] == "# Project Rules\nFollow these rules."

    async def test_agent_md_file_missing_logs_warning(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        comp_dir = _create_manifest_component_dir(tmp_path, num_tasks=1)
        task_loader.load_manifest.return_value = _mock_manifest(
            agent_md_file="/nonexistent/GUIDE.md",
            tasks=[_mock_task_ref("01-task1.yaml")],
        )
        task_loader.load.return_value = _make_task("task1")
        task_runner.run.return_value = _make_task_result("task1")

        with caplog.at_level(logging.WARNING):
            await component_runner.run(
                comp_dir,
                "https://github.com/t/r",
                None,
                "feat",
                {},
                config,
                CLIOverrides(),
            )

        assert "agent_md_file not found" in caplog.text
        # Should still complete successfully
        call_kwargs = task_runner.run.call_args[1]
        assert call_kwargs["component_agent_md"] is None

    async def test_agent_md_file_overrides_inline_agent_md(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        comp_dir = _create_manifest_component_dir(tmp_path, num_tasks=1)
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# From File")

        task_loader.load_manifest.return_value = _mock_manifest(
            agent_md="# Inline Agent MD",
            agent_md_file=str(claude_md),
            tasks=[_mock_task_ref("01-task1.yaml")],
        )
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

        call_kwargs = task_runner.run.call_args[1]
        assert call_kwargs["component_agent_md"] == "# From File"


class TestAgentGitName:
    @pytest.mark.parametrize(
        "dir_name,expected",
        [
            ("dev", "DKMV/Dev"),
            ("qa", "DKMV/QA"),
            ("plan", "DKMV/Plan"),
            ("docs", "DKMV/Docs"),
            ("my-component", "DKMV/My-Component"),
        ],
    )
    def test_agent_git_name_variations(self, dir_name: str, expected: str) -> None:
        assert _agent_git_name(dir_name) == expected

    def test_agent_email_constant(self) -> None:
        assert AGENT_EMAIL == "dkmv-agent@noreply.dkmv.dev"


class TestGitIdentityEnvVars:
    async def test_git_identity_env_vars_passed_to_tasks(
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

        call_kwargs = task_runner.run.call_args[1]
        env_vars = call_kwargs.get("shared_env_vars", {})
        assert env_vars["GIT_AUTHOR_NAME"] == "DKMV/My-Component"
        assert env_vars["GIT_COMMITTER_NAME"] == "DKMV/My-Component"
        assert env_vars["GIT_AUTHOR_EMAIL"] == AGENT_EMAIL
        assert env_vars["GIT_COMMITTER_EMAIL"] == AGENT_EMAIL

    async def test_git_identity_env_vars_override_manifest_env(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Git identity env vars take precedence over manifest-provided env inputs."""
        comp_dir = _create_manifest_component_dir(tmp_path, num_tasks=1)
        task_loader.load_manifest.return_value = _mock_manifest(
            inputs=[
                MagicMock(
                    name="author",
                    type="env",
                    key="GIT_AUTHOR_NAME",
                    value="SomeOtherName",
                    src=None,
                    dest=None,
                    content=None,
                    optional=False,
                ),
                MagicMock(
                    name="token",
                    type="env",
                    key="MY_TOKEN",
                    value="abc123",
                    src=None,
                    dest=None,
                    content=None,
                    optional=False,
                ),
            ],
            tasks=[_mock_task_ref("01-task1.yaml")],
        )
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

        call_kwargs = task_runner.run.call_args[1]
        env_vars = call_kwargs.get("shared_env_vars", {})
        # Git identity must override the manifest-provided GIT_AUTHOR_NAME
        assert env_vars["GIT_AUTHOR_NAME"] == "DKMV/Manifest-Component"
        # Non-git env vars from manifest are preserved
        assert env_vars["MY_TOKEN"] == "abc123"


class TestParameterCascadeFull:
    """Gap 1: Test the full 4-level parameter cascade through _apply_manifest_defaults.

    The cascade is: task YAML → task_ref override → manifest default → CLI → config.
    _apply_manifest_defaults handles the first 3 levels (task → task_ref → manifest).
    _resolve_param in TaskRunner handles task → CLI → config.
    """

    async def test_task_ref_overrides_manifest_defaults(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """task_ref.max_turns=50 should win over manifest.max_turns=80."""
        comp_dir = _create_manifest_component_dir(
            tmp_path, num_tasks=1, defaults={"max_turns": 80, "model": "claude-sonnet-4-6"}
        )
        task_ref = _mock_task_ref("01-task1.yaml", max_turns=50)
        task_loader.load_manifest.return_value = _mock_manifest(
            model="claude-sonnet-4-6",
            max_turns=80,
            tasks=[task_ref],
        )
        task = TaskDefinition(name="task1", prompt="go")
        task_loader.load.return_value = task
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

        assert task.max_turns == 50
        assert task.model == "claude-sonnet-4-6"

    async def test_task_yaml_value_wins_over_task_ref_and_manifest(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Task YAML sets model; task_ref and manifest also set model. Task YAML wins."""
        comp_dir = _create_manifest_component_dir(
            tmp_path, num_tasks=1, defaults={"model": "claude-sonnet-4-6"}
        )
        task_ref = _mock_task_ref("01-task1.yaml", model="claude-haiku-4-5")
        task_loader.load_manifest.return_value = _mock_manifest(
            model="claude-sonnet-4-6",
            tasks=[task_ref],
        )
        # Task already has model set from YAML
        task = TaskDefinition(name="task1", prompt="go", model="claude-opus-4-6")
        task_loader.load.return_value = task
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

        assert task.model == "claude-opus-4-6"

    async def test_manifest_default_used_when_task_ref_is_none(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When task_ref has no override, manifest default applies."""
        comp_dir = _create_manifest_component_dir(
            tmp_path,
            num_tasks=1,
            defaults={"timeout_minutes": 25, "max_budget_usd": 3.0},
        )
        task_ref = _mock_task_ref("01-task1.yaml")  # no overrides
        task_loader.load_manifest.return_value = _mock_manifest(
            timeout_minutes=25,
            max_budget_usd=3.0,
            tasks=[task_ref],
        )
        task = TaskDefinition(name="task1", prompt="go")
        task_loader.load.return_value = task
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

        assert task.timeout_minutes == 25
        assert task.max_budget_usd == 3.0

    async def test_all_four_params_cascade_independently(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Each param cascades independently: model from task, max_turns from ref,
        timeout from manifest, budget stays None."""
        comp_dir = _create_manifest_component_dir(tmp_path, num_tasks=1)
        task_ref = _mock_task_ref("01-task1.yaml", max_turns=60)
        task_loader.load_manifest.return_value = _mock_manifest(
            model="claude-sonnet-4-6",
            max_turns=80,
            timeout_minutes=25,
            max_budget_usd=5.0,
            tasks=[task_ref],
        )
        # Task has model set, others None
        task = TaskDefinition(name="task1", prompt="go", model="claude-opus-4-6")
        task_loader.load.return_value = task
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

        assert task.model == "claude-opus-4-6"  # from task YAML
        assert task.max_turns == 60  # from task_ref (overrides manifest 80)
        assert task.timeout_minutes == 25  # from manifest
        assert task.max_budget_usd == 5.0  # from manifest

    def test_apply_manifest_defaults_unit(self) -> None:
        """Direct unit test of _apply_manifest_defaults."""
        task = TaskDefinition(name="t", prompt="go")
        manifest = _mock_manifest(
            model="claude-sonnet-4-6", max_turns=80, timeout_minutes=25, max_budget_usd=3.0
        )
        task_ref = _mock_task_ref("t.yaml", max_turns=50, max_budget_usd=1.5)

        ComponentRunner._apply_manifest_defaults(task, manifest, task_ref)

        assert task.model == "claude-sonnet-4-6"  # from manifest (task_ref has None)
        assert task.max_turns == 50  # from task_ref
        assert task.timeout_minutes == 25  # from manifest (task_ref has None)
        assert task.max_budget_usd == 1.5  # from task_ref

    def test_apply_manifest_defaults_task_ref_none(self) -> None:
        """When task_ref is None, only manifest defaults apply."""
        task = TaskDefinition(name="t", prompt="go")
        manifest = _mock_manifest(model="claude-sonnet-4-6", max_turns=80)

        ComponentRunner._apply_manifest_defaults(task, manifest, None)

        assert task.model == "claude-sonnet-4-6"
        assert task.max_turns == 80

    def test_apply_manifest_defaults_preserves_task_values(self) -> None:
        """Task YAML values are not overwritten by task_ref or manifest."""
        task = TaskDefinition(
            name="t",
            prompt="go",
            model="claude-opus-4-6",
            max_turns=10,
            timeout_minutes=5,
            max_budget_usd=0.5,
        )
        manifest = _mock_manifest(
            model="claude-sonnet-4-6", max_turns=80, timeout_minutes=25, max_budget_usd=3.0
        )
        task_ref = _mock_task_ref(
            "t.yaml", model="claude-haiku-4-5", max_turns=50, timeout_minutes=15, max_budget_usd=2.0
        )

        ComponentRunner._apply_manifest_defaults(task, manifest, task_ref)

        assert task.model == "claude-opus-4-6"
        assert task.max_turns == 10
        assert task.timeout_minutes == 5
        assert task.max_budget_usd == 0.5


class TestBuildVariablesEdgeCases:
    """Gap 4: Test _build_variables edge cases including variable collision."""

    async def test_cli_vars_override_builtin_vars(
        self,
        component_runner: ComponentRunner,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """CLI variables (user-provided) override builtin variables like 'model'."""
        comp_dir = _create_component_dir(tmp_path, num_tasks=1)
        task_loader.load.return_value = _make_task("task1")
        task_runner.run.return_value = _make_task_result("task1")

        await component_runner.run(
            comp_dir,
            "https://github.com/t/r",
            "main",
            "feat",
            {"model": "custom-model", "extra_key": "extra_val"},
            config,
            CLIOverrides(),
        )

        call_args = task_loader.load.call_args
        variables = call_args[0][1]
        # cli_vars override builtins
        assert variables["model"] == "custom-model"
        assert variables["extra_key"] == "extra_val"
        # Other builtins remain
        assert variables["repo"] == "https://github.com/t/r"

    async def test_cli_override_model_used_in_builtin_vars(
        self,
        component_runner: ComponentRunner,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When CLI overrides model, the builtin 'model' variable reflects it."""
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
            CLIOverrides(model="claude-haiku-4-5"),
        )

        call_args = task_loader.load.call_args
        variables = call_args[0][1]
        assert variables["model"] == "claude-haiku-4-5"

    async def test_empty_branch_becomes_empty_string(
        self,
        component_runner: ComponentRunner,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When branch is None, the variable is set to empty string."""
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

        call_args = task_loader.load.call_args
        variables = call_args[0][1]
        assert variables["branch"] == ""


class TestBuildSandboxConfigGithubToken:
    """Gap 5: Test _build_sandbox_config GITHUB_TOKEN conditional."""

    async def test_github_token_included_when_set(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        tmp_path: Path,
    ) -> None:
        """GITHUB_TOKEN is included in sandbox env when config has a non-empty token."""
        config = _mock_config()
        config.github_token = "ghp_test123"
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

        start_call = sandbox.start.call_args
        sandbox_config = start_call[0][0]
        assert sandbox_config.env_vars["GITHUB_TOKEN"] == "ghp_test123"
        assert sandbox_config.env_vars["ANTHROPIC_API_KEY"] == "sk-ant-test"

    async def test_github_token_excluded_when_empty(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        tmp_path: Path,
    ) -> None:
        """GITHUB_TOKEN is NOT included in sandbox env when config has empty token."""
        config = _mock_config()
        config.github_token = ""
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

        start_call = sandbox.start.call_args
        sandbox_config = start_call[0][0]
        assert "GITHUB_TOKEN" not in sandbox_config.env_vars
        assert sandbox_config.env_vars["ANTHROPIC_API_KEY"] == "sk-ant-test"

    def test_build_sandbox_config_unit_with_token(self) -> None:
        """Direct unit test of _build_sandbox_config with token."""
        config = _mock_config()
        config.github_token = "ghp_abc"
        runner = ComponentRunner(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(), Console(quiet=True)
        )
        result, _ = runner._build_sandbox_config(config, 30)
        assert result.env_vars["GITHUB_TOKEN"] == "ghp_abc"

    def test_build_sandbox_config_unit_without_token(self) -> None:
        """Direct unit test of _build_sandbox_config without token."""
        config = _mock_config()
        config.github_token = ""
        runner = ComponentRunner(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(), Console(quiet=True)
        )
        result, _ = runner._build_sandbox_config(config, 30)
        assert "GITHUB_TOKEN" not in result.env_vars

    def test_build_sandbox_config_oauth_keychain(self, tmp_path: Path) -> None:
        """auth_method=oauth + Keychain credentials → bind-mount only, NO env var."""
        config = _mock_config()
        config.auth_method = "oauth"
        config.claude_oauth_token = "sk-ant-oat01-test"
        config.anthropic_api_key = "sk-ant-api-key"
        runner = ComponentRunner(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(), Console(quiet=True)
        )
        creds_json = '{"claudeAiOauth":{"accessToken":"at","refreshToken":"rt"}}'
        with patch("dkmv.config._fetch_oauth_credentials", return_value=creds_json):
            result, temp_file = runner._build_sandbox_config(config, 30)
        try:
            assert "CLAUDE_CODE_OAUTH_TOKEN" not in result.env_vars
            assert "ANTHROPIC_API_KEY" not in result.env_vars
            assert "-v" in result.docker_args
            assert temp_file is not None
            assert temp_file.read_text() == creds_json
            mount_arg = result.docker_args[result.docker_args.index("-v") + 1]
            assert mount_arg.endswith(":/home/dkmv/.claude/.credentials.json:ro")
            assert mount_arg.startswith(str(temp_file))
        finally:
            if temp_file:
                temp_file.unlink(missing_ok=True)

    def test_build_sandbox_config_oauth_linux_creds_file(self, tmp_path: Path) -> None:
        """auth_method=oauth + no Keychain + Linux creds file → bind-mount only, NO env var."""
        config = _mock_config()
        config.auth_method = "oauth"
        config.claude_oauth_token = "sk-ant-oat01-test"
        runner = ComponentRunner(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(), Console(quiet=True)
        )
        # Create a fake credentials file at fake home
        fake_claude = tmp_path / ".claude"
        fake_claude.mkdir()
        creds_file = fake_claude / ".credentials.json"
        creds_file.write_text("{}")
        with (
            patch("dkmv.config._fetch_oauth_credentials", return_value=""),
            patch("dkmv.adapters.claude.Path.home", return_value=tmp_path),
        ):
            result, temp_file = runner._build_sandbox_config(config, 30)
        assert temp_file is None
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in result.env_vars
        assert "-v" in result.docker_args
        mount_arg = result.docker_args[result.docker_args.index("-v") + 1]
        assert str(creds_file) in mount_arg
        assert mount_arg.endswith(":ro")

    def test_build_sandbox_config_oauth_env_var_fallback(self) -> None:
        """auth_method=oauth + no Keychain + no creds file → env var only."""
        config = _mock_config()
        config.auth_method = "oauth"
        config.claude_oauth_token = "sk-ant-oat01-test"
        config.anthropic_api_key = "sk-ant-api-key"
        runner = ComponentRunner(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(), Console(quiet=True)
        )
        with (
            patch("dkmv.config._fetch_oauth_credentials", return_value=""),
            patch("dkmv.adapters.claude.Path.home", return_value=Path("/nonexistent")),
        ):
            result, temp_file = runner._build_sandbox_config(config, 30)
        assert temp_file is None
        assert result.env_vars["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-test"
        assert "ANTHROPIC_API_KEY" not in result.env_vars
        assert result.docker_args == ["--shm-size=2g"]

    def test_build_sandbox_config_api_key_when_no_oauth(self) -> None:
        """auth_method=api_key → ANTHROPIC_API_KEY passed, not CLAUDE_CODE_OAUTH_TOKEN."""
        config = _mock_config()
        config.auth_method = "api_key"
        config.claude_oauth_token = ""
        config.anthropic_api_key = "sk-ant-api-key"
        runner = ComponentRunner(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(), Console(quiet=True)
        )
        result, temp_file = runner._build_sandbox_config(config, 30)
        assert temp_file is None
        assert result.env_vars["ANTHROPIC_API_KEY"] == "sk-ant-api-key"
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in result.env_vars


class TestBuildSandboxConfigDockerSocket:
    """Test _build_sandbox_config Docker socket mount logic."""

    def _mock_socket_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        original_exists = os.path.exists

        def patched_exists(path: str) -> bool:
            if path == "/var/run/docker.sock":
                return True
            return original_exists(path)

        monkeypatch.setattr("os.path.exists", patched_exists)
        monkeypatch.setattr(
            "os.stat",
            lambda p: (
                type("stat", (), {"st_gid": 999})() if p == "/var/run/docker.sock" else os.stat(p)
            ),
        )

    def test_docker_socket_via_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._mock_socket_exists(monkeypatch)
        config = _mock_config()
        config.docker_socket = False
        runner = ComponentRunner(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(), Console(quiet=True)
        )
        result, _ = runner._build_sandbox_config(config, 30, docker_socket=True)
        assert "-v" in result.docker_args
        sock_mount = result.docker_args[result.docker_args.index("-v") + 1]
        assert "/var/run/docker.sock" in sock_mount
        assert "--group-add=999" in result.docker_args

    def test_docker_socket_via_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._mock_socket_exists(monkeypatch)
        config = _mock_config()
        config.docker_socket = True
        runner = ComponentRunner(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(), Console(quiet=True)
        )
        result, _ = runner._build_sandbox_config(config, 30)
        assert "-v" in result.docker_args

    def test_no_docker_socket_by_default(self) -> None:
        config = _mock_config()
        config.docker_socket = False
        runner = ComponentRunner(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(), Console(quiet=True)
        )
        result, _ = runner._build_sandbox_config(config, 30)
        assert "-v" not in result.docker_args
        assert "--group-add=999" not in " ".join(result.docker_args)

    def test_docker_socket_coexists_with_shm_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._mock_socket_exists(monkeypatch)
        config = _mock_config()
        config.docker_socket = False
        runner = ComponentRunner(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(), Console(quiet=True)
        )
        result, _ = runner._build_sandbox_config(config, 30, docker_socket=True)
        assert "--shm-size=2g" in result.docker_args
        assert "-v" in result.docker_args

    def test_docker_socket_missing_no_mount(self, monkeypatch: pytest.MonkeyPatch) -> None:
        original_exists = os.path.exists

        def patched_exists(path: str) -> bool:
            if path == "/var/run/docker.sock":
                return False
            return original_exists(path)

        monkeypatch.setattr("os.path.exists", patched_exists)
        config = _mock_config()
        config.docker_socket = False
        runner = ComponentRunner(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(), Console(quiet=True)
        )
        result, _ = runner._build_sandbox_config(config, 30, docker_socket=True)
        assert "-v" not in result.docker_args
        assert "--group-add=999" not in " ".join(result.docker_args)


class TestSetupWorkspaceGitAuth:
    """setup_git_auth is skipped when no GitHub token is configured."""

    async def test_setup_git_auth_skipped_without_token(self, sandbox: AsyncMock) -> None:
        """No GitHub token → setup_git_auth not called, no crash."""
        runner = ComponentRunner(
            sandbox, MagicMock(), MagicMock(), MagicMock(), Console(quiet=True)
        )
        await runner._setup_workspace(
            sandbox.start.return_value,
            "https://github.com/o/r",
            "main",
            "dev",
            has_github_token=False,
        )
        sandbox.setup_git_auth.assert_not_awaited()

    async def test_setup_git_auth_called_with_token(self, sandbox: AsyncMock) -> None:
        """GitHub token present → setup_git_auth called normally."""
        runner = ComponentRunner(
            sandbox, MagicMock(), MagicMock(), MagicMock(), Console(quiet=True)
        )
        await runner._setup_workspace(
            sandbox.start.return_value,
            "https://github.com/o/r",
            "main",
            "dev",
            has_github_token=True,
        )
        sandbox.setup_git_auth.assert_awaited_once()


class TestPromptsLogEdgeCases:
    """Gap 6: Test _save_prompts_log with missing/empty artifact files."""

    async def test_prompts_log_handles_no_artifact_files(
        self,
        component_runner: ComponentRunner,
        run_manager: RunManager,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Prompts log is created even when no claude_md or prompt files exist."""
        comp_dir = _create_component_dir(tmp_path, num_tasks=1)
        task_loader.load.return_value = _make_task("task1")
        task_runner.run.return_value = _make_task_result("task1")

        result = await component_runner.run(
            comp_dir, "https://github.com/t/r", None, "feat", {}, config, CLIOverrides()
        )

        run_dir = run_manager._runs_dir / result.run_id
        log_file = run_dir / "prompts_log.md"
        assert log_file.exists()
        content = log_file.read_text()
        assert "## Task 1: task1" in content
        # No Instructions or Prompt sections since files don't exist
        assert "### Instructions" not in content
        assert "### Prompt" not in content

    async def test_prompts_log_skips_empty_prompt_file(
        self,
        component_runner: ComponentRunner,
        run_manager: RunManager,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Empty prompt file content is skipped in the log."""
        comp_dir = _create_component_dir(tmp_path, num_tasks=1)
        task_loader.load.return_value = _make_task("task1")
        task_runner.run.return_value = _make_task_result("task1")

        result = await component_runner.run(
            comp_dir, "https://github.com/t/r", None, "feat", {}, config, CLIOverrides()
        )

        run_dir = run_manager._runs_dir / result.run_id
        # Create an empty prompt file
        (run_dir / "prompt_task1.md").write_text("")

        component_runner._save_prompts_log(result.run_id, comp_dir.name, result.task_results)

        content = (run_dir / "prompts_log.md").read_text()
        # Empty prompt should not produce a "### Prompt" section
        assert "### Prompt" not in content

    async def test_prompts_log_multiple_tasks_mixed_artifacts(
        self,
        component_runner: ComponentRunner,
        run_manager: RunManager,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """One task has artifacts, another doesn't. Both appear in log correctly."""
        comp_dir = _create_component_dir(tmp_path, num_tasks=2)
        task_loader.load.side_effect = [_make_task("task1"), _make_task("task2")]
        task_runner.run.side_effect = [
            _make_task_result("task1"),
            _make_task_result("task2"),
        ]

        result = await component_runner.run(
            comp_dir, "https://github.com/t/r", None, "feat", {}, config, CLIOverrides()
        )

        run_dir = run_manager._runs_dir / result.run_id
        # Only task1 has claude_md; task2 has prompt
        (run_dir / "claude_md_task1.md").write_text("# Rules for task1")
        (run_dir / "prompt_task2.md").write_text("Do task2 work")

        component_runner._save_prompts_log(result.run_id, comp_dir.name, result.task_results)

        content = (run_dir / "prompts_log.md").read_text()
        assert "## Task 1: task1" in content
        assert "## Task 2: task2" in content
        assert "Rules for task1" in content
        assert "Do task2 work" in content


class TestAgentMdFileEdgeCases:
    """Gap 2: Additional agent_md_file edge cases."""

    async def test_agent_md_file_none_uses_inline(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When agent_md_file is None, inline agent_md is used as-is."""
        comp_dir = _create_manifest_component_dir(tmp_path, num_tasks=1, agent_md="# Inline")
        task_loader.load_manifest.return_value = _mock_manifest(
            agent_md="# Inline",
            agent_md_file=None,
            tasks=[_mock_task_ref("01-task1.yaml")],
        )
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

        call_kwargs = task_runner.run.call_args[1]
        assert call_kwargs["component_agent_md"] == "# Inline"

    async def test_agent_md_file_empty_content_treated_as_falsy(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When agent_md_file exists but is empty, manifest.agent_md becomes empty string."""
        comp_dir = _create_manifest_component_dir(tmp_path, num_tasks=1)
        empty_file = tmp_path / "empty_claude.md"
        empty_file.write_text("")

        task_loader.load_manifest.return_value = _mock_manifest(
            agent_md="# Original Inline",
            agent_md_file=str(empty_file),
            tasks=[_mock_task_ref("01-task1.yaml")],
        )
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

        call_kwargs = task_runner.run.call_args[1]
        # Empty file overwrites inline agent_md → component_agent_md = ""
        assert call_kwargs["component_agent_md"] == ""

    async def test_no_agent_md_and_no_file_passes_none(
        self,
        component_runner: ComponentRunner,
        sandbox: AsyncMock,
        task_loader: MagicMock,
        task_runner: AsyncMock,
        config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """No inline agent_md and no agent_md_file → component_agent_md is None."""
        comp_dir = _create_manifest_component_dir(tmp_path, num_tasks=1)
        task_loader.load_manifest.return_value = _mock_manifest(
            agent_md=None,
            agent_md_file=None,
            tasks=[_mock_task_ref("01-task1.yaml")],
        )
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

        call_kwargs = task_runner.run.call_args[1]
        assert call_kwargs["component_agent_md"] is None
