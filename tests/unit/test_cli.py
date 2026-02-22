from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from dkmv.cli import app

runner = CliRunner()


class TestMainCallback:
    def test_help_shows_all_commands(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for cmd in ["build", "dev", "qa", "judge", "docs", "runs", "show", "attach", "stop"]:
            assert cmd in result.output
        assert "--verbose" in result.output
        assert "--dry-run" in result.output

    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app, [])
        assert "Usage" in result.output

    def test_verbose_flag_accepted(self) -> None:
        result = runner.invoke(app, ["--verbose", "--help"])
        assert result.exit_code == 0

    def test_dry_run_flag_accepted(self) -> None:
        result = runner.invoke(app, ["--dry-run", "--help"])
        assert result.exit_code == 0


class TestBuildCommand:
    def test_build_help(self) -> None:
        result = runner.invoke(app, ["build", "--help"])
        assert result.exit_code == 0
        assert "--no-cache" in result.output
        assert "--claude-version" in result.output

    def test_build_dry_run_skips_execution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = runner.invoke(app, ["--dry-run", "build"])
        assert result.exit_code == 0
        assert "Dry run" in result.output

    def test_fails_when_docker_not_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("dkmv.cli.shutil.which", lambda _: None)
        result = runner.invoke(app, ["build"])
        assert result.exit_code == 1
        assert "Docker is not installed" in result.output

    def test_fails_when_dockerfile_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
        monkeypatch.setattr("dkmv.cli.shutil.which", lambda _: "/usr/bin/docker")
        monkeypatch.setattr(
            "dkmv.cli.load_config", lambda **kw: MagicMock(image_name="test:latest")
        )
        monkeypatch.setattr("dkmv.cli.__file__", str(tmp_path / "cli.py"))
        result = runner.invoke(app, ["build"])
        assert result.exit_code == 1
        assert "Dockerfile not found" in result.output

    def test_build_succeeds(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
        monkeypatch.setattr("dkmv.cli.shutil.which", lambda _: "/usr/bin/docker")
        monkeypatch.setattr(
            "dkmv.cli.load_config", lambda **kw: MagicMock(image_name="test:latest")
        )
        monkeypatch.setattr("dkmv.cli.__file__", str(tmp_path / "cli.py"))
        images_dir = tmp_path / "images"
        images_dir.mkdir()
        (images_dir / "Dockerfile").write_text("FROM ubuntu\n")
        mock_result = MagicMock(returncode=0)
        monkeypatch.setattr("dkmv.cli.subprocess.run", lambda cmd: mock_result)
        result = runner.invoke(app, ["build"])
        assert result.exit_code == 0
        assert "built successfully" in result.output

    def test_build_fails_on_docker_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
        monkeypatch.setattr("dkmv.cli.shutil.which", lambda _: "/usr/bin/docker")
        monkeypatch.setattr(
            "dkmv.cli.load_config", lambda **kw: MagicMock(image_name="test:latest")
        )
        monkeypatch.setattr("dkmv.cli.__file__", str(tmp_path / "cli.py"))
        images_dir = tmp_path / "images"
        images_dir.mkdir()
        (images_dir / "Dockerfile").write_text("FROM ubuntu\n")
        mock_result = MagicMock(returncode=1)
        monkeypatch.setattr("dkmv.cli.subprocess.run", lambda cmd: mock_result)
        result = runner.invoke(app, ["build"])
        assert result.exit_code == 1
        assert "Docker build failed" in result.output

    def test_no_cache_flag_passed_to_docker(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
        monkeypatch.setattr("dkmv.cli.shutil.which", lambda _: "/usr/bin/docker")
        monkeypatch.setattr(
            "dkmv.cli.load_config", lambda **kw: MagicMock(image_name="test:latest")
        )
        monkeypatch.setattr("dkmv.cli.__file__", str(tmp_path / "cli.py"))
        images_dir = tmp_path / "images"
        images_dir.mkdir()
        (images_dir / "Dockerfile").write_text("FROM ubuntu\n")
        captured_cmd: list[str] = []
        mock_result = MagicMock(returncode=0)

        def capture_run(cmd: list[str]) -> MagicMock:
            captured_cmd.extend(cmd)
            return mock_result

        monkeypatch.setattr("dkmv.cli.subprocess.run", capture_run)
        result = runner.invoke(app, ["build", "--no-cache"])
        assert result.exit_code == 0
        assert "--no-cache" in captured_cmd

    def test_claude_version_passed_as_build_arg(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
        monkeypatch.setattr("dkmv.cli.shutil.which", lambda _: "/usr/bin/docker")
        monkeypatch.setattr(
            "dkmv.cli.load_config", lambda **kw: MagicMock(image_name="test:latest")
        )
        monkeypatch.setattr("dkmv.cli.__file__", str(tmp_path / "cli.py"))
        images_dir = tmp_path / "images"
        images_dir.mkdir()
        (images_dir / "Dockerfile").write_text("FROM ubuntu\n")
        captured_cmd: list[str] = []
        mock_result = MagicMock(returncode=0)

        def capture_run(cmd: list[str]) -> MagicMock:
            captured_cmd.extend(cmd)
            return mock_result

        monkeypatch.setattr("dkmv.cli.subprocess.run", capture_run)
        result = runner.invoke(app, ["build", "--claude-version", "1.2.3"])
        assert result.exit_code == 0
        assert "CLAUDE_CODE_VERSION=1.2.3" in captured_cmd


class TestComponentCommandHelp:
    """Verify the 4 component commands accept --help and show correct options."""

    def test_dev_help(self) -> None:
        result = runner.invoke(app, ["dev", "--help"])
        assert result.exit_code == 0
        assert "--prd" in result.output
        assert "--branch" in result.output
        assert "--feedback" in result.output
        assert "--design-docs" in result.output
        assert "--feature-name" in result.output

    def test_qa_help(self) -> None:
        result = runner.invoke(app, ["qa", "--help"])
        assert result.exit_code == 0
        assert "--branch" in result.output
        assert "--prd" in result.output

    def test_judge_help(self) -> None:
        result = runner.invoke(app, ["judge", "--help"])
        assert result.exit_code == 0
        assert "--branch" in result.output
        assert "--prd" in result.output

    def test_docs_help(self) -> None:
        result = runner.invoke(app, ["docs", "--help"])
        assert result.exit_code == 0
        assert "--branch" in result.output
        assert "--create-pr" in result.output
        assert "--pr-base" in result.output


def _mock_config() -> MagicMock:
    """Create a mock DKMVConfig with all needed attributes."""
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


class TestNumericDefaults:
    """Verify explicit zero values for numeric params are preserved in CLIOverrides."""

    def test_dev_max_turns_zero_passes_through(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        prd = tmp_path / "prd.md"
        prd.write_text("# PRD\n")

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
                app, ["dev", str(tmp_path), "--prd", str(prd), "--max-turns", "0"]
            )

        assert result.exit_code == 0
        cli_overrides = mock_runner.run.call_args[1]["cli_overrides"]
        assert cli_overrides.max_turns == 0

    def test_qa_timeout_zero_passes_through(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        prd = tmp_path / "prd.md"
        prd.write_text("# PRD\n")

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
                ["qa", str(tmp_path), "--branch", "feat", "--prd", str(prd), "--timeout", "0"],
            )

        assert result.exit_code == 0
        cli_overrides = mock_runner.run.call_args[1]["cli_overrides"]
        assert cli_overrides.timeout_minutes == 0

    def test_judge_max_budget_zero_passes_through(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        prd = tmp_path / "prd.md"
        prd.write_text("# PRD\n")

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
                    "judge",
                    str(tmp_path),
                    "--branch",
                    "feat",
                    "--prd",
                    str(prd),
                    "--max-budget-usd",
                    "0",
                ],
            )

        assert result.exit_code == 0
        cli_overrides = mock_runner.run.call_args[1]["cli_overrides"]
        assert cli_overrides.max_budget_usd == 0.0


class TestComponentInvocations:
    """Verify CLI commands wire up ComponentRunner correctly."""

    def test_dev_invocation(self, tmp_path: Path) -> None:
        prd = tmp_path / "prd.md"
        prd.write_text("# PRD\n")

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
            result = runner.invoke(app, ["dev", str(tmp_path), "--prd", str(prd)])

        assert result.exit_code == 0
        mock_runner.run.assert_awaited_once()

    def test_qa_invocation(self, tmp_path: Path) -> None:
        prd = tmp_path / "prd.md"
        prd.write_text("# PRD\n")

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
                app, ["qa", str(tmp_path), "--branch", "feat", "--prd", str(prd)]
            )

        assert result.exit_code == 0
        mock_runner.run.assert_awaited_once()

    def test_judge_invocation(self, tmp_path: Path) -> None:
        prd = tmp_path / "prd.md"
        prd.write_text("# PRD\n")

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
                app, ["judge", str(tmp_path), "--branch", "feat", "--prd", str(prd)]
            )

        assert result.exit_code == 0
        mock_runner.run.assert_awaited_once()

    def test_docs_invocation(self, tmp_path: Path) -> None:
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
            result = runner.invoke(app, ["docs", str(tmp_path), "--branch", "feat"])

        assert result.exit_code == 0
        mock_runner.run.assert_awaited_once()
