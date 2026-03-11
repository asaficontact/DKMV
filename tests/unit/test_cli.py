import json
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
        for cmd in [
            "build",
            "clean",
            "components",
            "dev",
            "plan",
            "qa",
            "docs",
            "ship",
            "init",
            "register",
            "runs",
            "show",
            "attach",
            "stop",
            "unregister",
        ]:
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
        assert "--impl-docs" in result.output
        assert "--branch" in result.output
        assert "--feature-name" in result.output

    def test_qa_help(self) -> None:
        result = runner.invoke(app, ["qa", "--help"])
        assert result.exit_code == 0
        assert "--branch" in result.output
        assert "--impl-docs" in result.output
        assert "--auto" in result.output
        assert "--feature-name" in result.output

    def test_docs_help(self) -> None:
        result = runner.invoke(app, ["docs", "--help"])
        assert result.exit_code == 0
        assert "--branch" in result.output
        assert "--impl-docs" in result.output
        assert "--pr-base" in result.output
        assert "--feature-name" in result.output
        assert "--create-pr" not in result.output

    def test_plan_help(self) -> None:
        result = runner.invoke(app, ["plan", "--help"])
        assert result.exit_code == 0
        assert "--prd" in result.output
        assert "--design-docs" in result.output
        assert "--feature-name" in result.output
        assert "--repo" in result.output
        assert "--auto" in result.output

    def test_ship_help(self) -> None:
        result = runner.invoke(app, ["ship", "--help"])
        assert result.exit_code == 0
        assert "--prd" in result.output
        assert "--design-docs" in result.output
        assert "--pr-base" in result.output
        assert "--max-iterations" in result.output
        assert "--feature-name" in result.output
        assert "--repo" in result.output
        assert "--auto" in result.output


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
        impl_docs = tmp_path / "feature-impl"
        impl_docs.mkdir()
        (impl_docs / "phase1_foundation.md").write_text("# Phase 1\n")

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
                    "dev",
                    "--repo",
                    str(tmp_path),
                    "--impl-docs",
                    str(impl_docs),
                    "--max-turns",
                    "0",
                ],
            )

        assert result.exit_code == 0
        cli_overrides = mock_runner.run.call_args[1]["cli_overrides"]
        assert cli_overrides.max_turns == 0

    def test_qa_timeout_zero_passes_through(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        impl_docs = tmp_path / "impl-docs"
        impl_docs.mkdir()

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
                    "qa",
                    "--repo",
                    str(tmp_path),
                    "--branch",
                    "feat",
                    "--impl-docs",
                    str(impl_docs),
                    "--timeout",
                    "0",
                ],
            )

        assert result.exit_code == 0
        cli_overrides = mock_runner.run.call_args[1]["cli_overrides"]
        assert cli_overrides.timeout_minutes == 0


class TestComponentInvocations:
    """Verify CLI commands wire up ComponentRunner correctly."""

    def test_dev_invocation(self, tmp_path: Path) -> None:
        impl_docs = tmp_path / "feature-impl"
        impl_docs.mkdir()
        (impl_docs / "phase1_foundation.md").write_text("# Phase 1\n")

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
                ["dev", "--repo", str(tmp_path), "--impl-docs", str(impl_docs)],
            )

        assert result.exit_code == 0
        mock_runner.run.assert_awaited_once()

    def test_dev_start_phase_filters_phases(self, tmp_path: Path) -> None:
        impl_docs = tmp_path / "feature-impl"
        impl_docs.mkdir()
        (impl_docs / "phase1_foundation.md").write_text("# Phase 1\n")
        (impl_docs / "phase2_core.md").write_text("# Phase 2\n")
        (impl_docs / "phase3_polish.md").write_text("# Phase 3\n")

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
                    "dev",
                    "--repo",
                    str(tmp_path),
                    "--impl-docs",
                    str(impl_docs),
                    "--start-phase",
                    "2",
                ],
            )

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        phases = call_kwargs["variables"]["phases"]
        assert len(phases) == 2
        assert phases[0]["phase_number"] == 2
        assert phases[1]["phase_number"] == 3

    def test_dev_start_phase_invalid_shows_error(self, tmp_path: Path) -> None:
        impl_docs = tmp_path / "feature-impl"
        impl_docs.mkdir()
        (impl_docs / "phase1_foundation.md").write_text("# Phase 1\n")
        (impl_docs / "phase2_core.md").write_text("# Phase 2\n")

        with patch("dkmv.cli.load_config", return_value=_mock_config()):
            result = runner.invoke(
                app,
                [
                    "dev",
                    "--repo",
                    str(tmp_path),
                    "--impl-docs",
                    str(impl_docs),
                    "--start-phase",
                    "5",
                ],
            )

        assert result.exit_code == 1
        assert "No phases" in result.output

    def test_dev_start_phase_1_runs_all(self, tmp_path: Path) -> None:
        impl_docs = tmp_path / "feature-impl"
        impl_docs.mkdir()
        (impl_docs / "phase1_foundation.md").write_text("# Phase 1\n")
        (impl_docs / "phase2_core.md").write_text("# Phase 2\n")

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
                    "dev",
                    "--repo",
                    str(tmp_path),
                    "--impl-docs",
                    str(impl_docs),
                    "--start-phase",
                    "1",
                ],
            )

        assert result.exit_code == 0
        call_kwargs = mock_runner.run.call_args[1]
        phases = call_kwargs["variables"]["phases"]
        assert len(phases) == 2

    def test_dev_help_shows_start_phase(self) -> None:
        result = runner.invoke(app, ["dev", "--help"])
        assert "--start-phase" in result.output

    def test_qa_invocation(self, tmp_path: Path) -> None:
        impl_docs = tmp_path / "impl-docs"
        impl_docs.mkdir()

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
                    "qa",
                    "--repo",
                    str(tmp_path),
                    "--branch",
                    "feat",
                    "--impl-docs",
                    str(impl_docs),
                ],
            )

        assert result.exit_code == 0
        mock_runner.run.assert_awaited_once()

    def test_plan_invocation(self, tmp_path: Path) -> None:
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
            result = runner.invoke(app, ["plan", "--repo", str(tmp_path), "--prd", str(prd)])

        assert result.exit_code == 0
        mock_runner.run.assert_awaited_once()

    def test_docs_invocation(self, tmp_path: Path) -> None:
        impl_docs = tmp_path / "impl-docs"
        impl_docs.mkdir()

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
                    "docs",
                    "--repo",
                    str(tmp_path),
                    "--branch",
                    "feat",
                    "--impl-docs",
                    str(impl_docs),
                ],
            )

        assert result.exit_code == 0
        mock_runner.run.assert_awaited_once()


class TestPlanAutoFlag:
    """Verify the --auto flag on the plan command."""

    def test_plan_help_shows_auto_flag(self) -> None:
        result = runner.invoke(app, ["plan", "--help"])
        assert result.exit_code == 0
        assert "--auto" in result.output

    def test_plan_auto_passes_no_on_pause(self, tmp_path: Path) -> None:
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
                app, ["plan", "--repo", str(tmp_path), "--prd", str(prd), "--auto"]
            )

        assert result.exit_code == 0
        mock_runner.run.assert_awaited_once()
        assert mock_runner.run.call_args[1]["on_pause"] is None

    def test_plan_without_auto_passes_callback(self, tmp_path: Path) -> None:
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
            result = runner.invoke(app, ["plan", "--repo", str(tmp_path), "--prd", str(prd)])

        assert result.exit_code == 0
        mock_runner.run.assert_awaited_once()
        assert mock_runner.run.call_args[1]["on_pause"] is not None


class TestRepoOptionality:
    """Verify --repo is optional when project is initialized."""

    def _create_project_config(
        self, root: Path, repo: str = "https://github.com/test/repo"
    ) -> None:
        dkmv_dir = root / ".dkmv"
        dkmv_dir.mkdir(parents=True, exist_ok=True)
        config = {
            "version": 1,
            "project_name": "test-project",
            "repo": repo,
            "default_branch": "main",
        }
        (dkmv_dir / "config.json").write_text(json.dumps(config))

    def test_plan_without_repo_uses_project_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        self._create_project_config(tmp_path, "https://github.com/test/repo")
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
            result = runner.invoke(app, ["plan", "--prd", str(prd)])

        assert result.exit_code == 0
        mock_runner.run.assert_awaited_once()
        assert mock_runner.run.call_args[1]["repo"] == "https://github.com/test/repo"

    def test_dev_help_shows_repo_as_option(self) -> None:
        result = runner.invoke(app, ["dev", "--help"])
        assert result.exit_code == 0
        assert "--repo" in result.output

    def test_dev_without_repo_uses_project_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        self._create_project_config(tmp_path, "https://github.com/test/repo")
        impl_docs = tmp_path / "feature-impl"
        impl_docs.mkdir()
        (impl_docs / "phase1_foundation.md").write_text("# Phase 1\n")

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
            result = runner.invoke(app, ["dev", "--impl-docs", str(impl_docs)])

        assert result.exit_code == 0
        mock_runner.run.assert_awaited_once()
        assert mock_runner.run.call_args[1]["repo"] == "https://github.com/test/repo"

    def test_dev_without_repo_no_init_shows_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        impl_docs = tmp_path / "feature-impl"
        impl_docs.mkdir()
        (impl_docs / "phase1_foundation.md").write_text("# Phase 1\n")

        with patch("dkmv.cli.load_config", return_value=_mock_config()):
            result = runner.invoke(app, ["dev", "--impl-docs", str(impl_docs)])

        assert result.exit_code == 1
        assert "dkmv init" in result.output

    def test_run_without_repo_uses_project_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        self._create_project_config(tmp_path, "https://github.com/test/repo")

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
            result = runner.invoke(app, ["run", "dev", "--var", "prd_path=prd.md"])

        assert result.exit_code == 0
        mock_runner.run.assert_awaited_once()
        assert mock_runner.run.call_args[1]["repo"] == "https://github.com/test/repo"

    def test_run_without_repo_no_init_shows_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        with patch("dkmv.cli.load_config", return_value=_mock_config()):
            result = runner.invoke(app, ["run", "dev", "--var", "prd_path=prd.md"])

        assert result.exit_code == 1
        assert "dkmv init" in result.output

    def test_explicit_repo_overrides_project_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        self._create_project_config(tmp_path, "https://github.com/test/repo")
        impl_docs = tmp_path / "feature-impl"
        impl_docs.mkdir()
        (impl_docs / "phase1_foundation.md").write_text("# Phase 1\n")

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
                    "dev",
                    "--repo",
                    "https://github.com/other/repo",
                    "--impl-docs",
                    str(impl_docs),
                ],
            )

        assert result.exit_code == 0
        assert mock_runner.run.call_args[1]["repo"] == "https://github.com/other/repo"


class TestDocsPostRunDisplay:
    """Gap 3: Test CLI post-run display logic for docs command."""

    def _invoke_docs(
        self,
        tmp_path: Path,
        run_id: str = "r1",
        status: str = "completed",
        error_message: str = "",
    ) -> tuple:
        """Invoke docs command with pre-configured output_dir and return (result, output_dir).

        The output_dir is at tmp_path/outputs. Create artifact files there
        before calling this method if testing post-run display.
        """
        impl_docs = tmp_path / "impl-docs"
        impl_docs.mkdir(exist_ok=True)
        output_dir = tmp_path / "outputs"

        mock_runner = MagicMock()
        mock_result = MagicMock(run_id=run_id, status=status, error_message=error_message)
        mock_runner.run = AsyncMock(return_value=mock_result)

        cfg = _mock_config()
        cfg.output_dir = output_dir

        with (
            patch("dkmv.cli.load_config", return_value=cfg),
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
                    "docs",
                    "--repo",
                    str(tmp_path),
                    "--branch",
                    "feat",
                    "--impl-docs",
                    str(impl_docs),
                ],
            )

        return result, output_dir

    def _setup_run_dir(self, tmp_path: Path, run_id: str = "r1") -> Path:
        """Create and return the run artifact directory."""
        run_dir = tmp_path / "outputs" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def test_verification_pass_shown_in_output(self, tmp_path: Path) -> None:
        run_dir = self._setup_run_dir(tmp_path)
        (run_dir / "docs_verification.json").write_text(json.dumps({"status": "pass"}))

        result, _ = self._invoke_docs(tmp_path)

        assert result.exit_code == 0
        assert "Docs verification: PASS" in result.output

    def test_verification_fail_shown_in_output(self, tmp_path: Path) -> None:
        run_dir = self._setup_run_dir(tmp_path)
        (run_dir / "docs_verification.json").write_text(json.dumps({"status": "fail"}))

        result, _ = self._invoke_docs(tmp_path)

        assert result.exit_code == 0
        assert "Docs verification: FAIL" in result.output

    def test_pr_url_shown_in_output(self, tmp_path: Path) -> None:
        run_dir = self._setup_run_dir(tmp_path)
        (run_dir / "pr_result.json").write_text(
            json.dumps({"pr_url": "https://github.com/test/repo/pull/42", "status": "created"})
        )

        result, _ = self._invoke_docs(tmp_path)

        assert result.exit_code == 0
        assert "https://github.com/test/repo/pull/42" in result.output
        assert "PR status: created" in result.output

    def test_no_display_when_status_is_failed(self, tmp_path: Path) -> None:
        run_dir = self._setup_run_dir(tmp_path)
        (run_dir / "docs_verification.json").write_text(json.dumps({"status": "pass"}))
        (run_dir / "pr_result.json").write_text(
            json.dumps({"pr_url": "https://github.com/test/repo/pull/42", "status": "created"})
        )

        result, _ = self._invoke_docs(tmp_path, status="failed", error_message="Something broke")

        assert result.exit_code == 0
        # When status is "failed", verification and PR display are skipped
        assert "Docs verification" not in result.output
        assert "pull/42" not in result.output
        # Error message IS shown
        assert "Something broke" in result.output

    def test_error_message_displayed(self, tmp_path: Path) -> None:
        result, _ = self._invoke_docs(
            tmp_path, status="failed", error_message="Component timed out"
        )

        assert result.exit_code == 0
        assert "Component timed out" in result.output
