from unittest.mock import MagicMock

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


STUB_COMMANDS = [
    ("dev", ["https://github.com/test/repo", "--prd", "prd.md"]),
    ("qa", ["https://github.com/test/repo", "--branch", "feat", "--prd", "prd.md"]),
    ("judge", ["https://github.com/test/repo", "--branch", "feat", "--prd", "prd.md"]),
    ("docs", ["https://github.com/test/repo", "--branch", "feat"]),
    ("runs", []),
    ("show", ["run-123"]),
    ("attach", ["run-123"]),
    ("stop", ["run-123"]),
]


@pytest.mark.parametrize("cmd,args", STUB_COMMANDS, ids=[c[0] for c in STUB_COMMANDS])
class TestStubCommands:
    def test_stub_returns_not_implemented(self, cmd: str, args: list[str]) -> None:
        result = runner.invoke(app, [cmd, *args])
        assert result.exit_code == 0
        assert "Not yet implemented" in result.output
