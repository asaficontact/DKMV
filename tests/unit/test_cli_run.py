from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from dkmv.cli import _parse_vars, app

runner = CliRunner()


def _mock_config() -> MagicMock:
    cfg = MagicMock()
    cfg.default_model = "claude-sonnet-4-6"
    cfg.default_max_turns = 100
    cfg.timeout_minutes = 30
    cfg.max_budget_usd = None
    cfg.output_dir = Path("./outputs")
    cfg.anthropic_api_key = "sk-ant-test"
    cfg.github_token = "ghp_test"
    cfg.image_name = "dkmv-sandbox:latest"
    cfg.memory_limit = "8g"
    return cfg


class TestRunHelp:
    def test_run_help_shows_all_options(self) -> None:
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        for opt in [
            "--repo",
            "--branch",
            "--var",
            "--model",
            "--max-turns",
            "--timeout",
            "--max-budget-usd",
            "--keep-alive",
            "--feature-name",
        ]:
            assert opt in result.output

    def test_run_appears_in_main_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "run" in result.output


class TestParseVars:
    def test_valid_var_parsing(self) -> None:
        assert _parse_vars(["key=value"]) == {"key": "value"}

    def test_multiple_vars(self) -> None:
        result = _parse_vars(["a=1", "b=2"])
        assert result == {"a": "1", "b": "2"}

    def test_empty_value_allowed(self) -> None:
        assert _parse_vars(["flag="]) == {"flag": ""}

    def test_value_with_equals(self) -> None:
        assert _parse_vars(["url=http://x?a=b"]) == {"url": "http://x?a=b"}

    def test_invalid_var_format_error(self) -> None:
        with pytest.raises(Exception, match="Invalid --var format"):
            _parse_vars(["noequals"])

    def test_none_returns_empty(self) -> None:
        assert _parse_vars(None) == {}

    def test_empty_list_returns_empty(self) -> None:
        assert _parse_vars([]) == {}


class TestRunInvocation:
    def test_run_invokes_component_runner(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "my-comp"
        comp_dir.mkdir()
        (comp_dir / "01-task.yaml").write_text("name: t\ninstructions: x\nprompt: y\n")

        mock_runner = MagicMock()
        mock_result = MagicMock(run_id="r1", status="completed", error_message="")
        mock_runner.run = AsyncMock(return_value=mock_result)

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config()),
            patch("dkmv.tasks.ComponentRunner", return_value=mock_runner),
            patch("dkmv.core.runner.RunManager"),
            patch("dkmv.core.sandbox.SandboxManager"),
            patch("dkmv.core.stream.StreamParser"),
            patch("dkmv.tasks.loader.TaskLoader"),
            patch("dkmv.tasks.runner.TaskRunner"),
        ):
            result = runner.invoke(app, ["run", str(comp_dir), "--repo", "https://github.com/t/r"])

        assert result.exit_code == 0
        mock_runner.run.assert_awaited_once()

    def test_cli_overrides_preserve_none(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "my-comp"
        comp_dir.mkdir()
        (comp_dir / "01-task.yaml").write_text("name: t\ninstructions: x\nprompt: y\n")

        mock_runner = MagicMock()
        mock_result = MagicMock(run_id="r1", status="completed", error_message="")
        mock_runner.run = AsyncMock(return_value=mock_result)

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config()),
            patch("dkmv.tasks.ComponentRunner", return_value=mock_runner),
            patch("dkmv.core.runner.RunManager"),
            patch("dkmv.core.sandbox.SandboxManager"),
            patch("dkmv.core.stream.StreamParser"),
            patch("dkmv.tasks.loader.TaskLoader"),
            patch("dkmv.tasks.runner.TaskRunner"),
        ):
            result = runner.invoke(app, ["run", str(comp_dir), "--repo", "https://github.com/t/r"])

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        cli_overrides = call_kwargs["cli_overrides"]
        assert cli_overrides.model is None
        assert cli_overrides.max_turns is None
        assert cli_overrides.timeout_minutes is None
        assert cli_overrides.max_budget_usd is None

    def test_cli_overrides_pass_values(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "my-comp"
        comp_dir.mkdir()
        (comp_dir / "01-task.yaml").write_text("name: t\ninstructions: x\nprompt: y\n")

        mock_runner = MagicMock()
        mock_result = MagicMock(run_id="r1", status="completed", error_message="")
        mock_runner.run = AsyncMock(return_value=mock_result)

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config()),
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
                    "--model",
                    "claude-opus-4-6",
                    "--max-turns",
                    "50",
                    "--timeout",
                    "10",
                    "--max-budget-usd",
                    "5.0",
                ],
            )

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        cli_overrides = call_kwargs["cli_overrides"]
        assert cli_overrides.model == "claude-opus-4-6"
        assert cli_overrides.max_turns == 50
        assert cli_overrides.timeout_minutes == 10
        assert cli_overrides.max_budget_usd == 5.0

    def test_feature_name_defaults_to_component_name(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "my-comp"
        comp_dir.mkdir()
        (comp_dir / "01-task.yaml").write_text("name: t\ninstructions: x\nprompt: y\n")

        mock_runner = MagicMock()
        mock_result = MagicMock(run_id="r1", status="completed", error_message="")
        mock_runner.run = AsyncMock(return_value=mock_result)

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config()),
            patch("dkmv.tasks.ComponentRunner", return_value=mock_runner),
            patch("dkmv.core.runner.RunManager"),
            patch("dkmv.core.sandbox.SandboxManager"),
            patch("dkmv.core.stream.StreamParser"),
            patch("dkmv.tasks.loader.TaskLoader"),
            patch("dkmv.tasks.runner.TaskRunner"),
        ):
            result = runner.invoke(app, ["run", str(comp_dir), "--repo", "https://github.com/t/r"])

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        assert call_kwargs["feature_name"] == "my-comp"

    def test_missing_repo_shows_error(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "my-comp"
        comp_dir.mkdir()
        (comp_dir / "01-task.yaml").write_text("name: t\ninstructions: x\nprompt: y\n")

        result = runner.invoke(app, ["run", str(comp_dir)])
        assert result.exit_code != 0

    def test_invalid_component_path_shows_error(self) -> None:
        with patch("dkmv.cli.load_config", return_value=_mock_config()):
            result = runner.invoke(
                app, ["run", "/nonexistent/path/comp", "--repo", "https://github.com/t/r"]
            )
        assert result.exit_code != 0
