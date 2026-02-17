from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from dkmv.cli import _format_duration, _format_relative_time, app
from dkmv.core.models import RunDetail, RunSummary

runner = CliRunner()


def _mock_config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.output_dir = tmp_path
    return cfg


class TestFormatRelativeTime:
    def test_just_now(self) -> None:
        assert _format_relative_time(datetime.now(UTC)) == "just now"

    def test_minutes_ago(self) -> None:
        dt = datetime.now(UTC) - timedelta(minutes=5)
        assert _format_relative_time(dt) == "5m ago"

    def test_hours_ago(self) -> None:
        dt = datetime.now(UTC) - timedelta(hours=2)
        assert _format_relative_time(dt) == "2h ago"

    def test_days_ago(self) -> None:
        dt = datetime.now(UTC) - timedelta(days=3)
        assert _format_relative_time(dt) == "3d ago"


class TestFormatDuration:
    def test_seconds_only(self) -> None:
        assert _format_duration(30) == "30s"

    def test_minutes_and_seconds(self) -> None:
        assert _format_duration(120) == "2m 0s"

    def test_mixed(self) -> None:
        assert _format_duration(90) == "1m 30s"

    def test_zero(self) -> None:
        assert _format_duration(0) == "0s"


class TestRunsCommand:
    def test_runs_empty_shows_message(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.list_runs.return_value = []

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
        ):
            result = runner.invoke(app, ["runs"])

        assert result.exit_code == 0
        assert "No runs found" in result.output

    def test_runs_shows_table(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.list_runs.return_value = [
            RunSummary(
                run_id="abc12345",
                component="dev",
                status="completed",
                feature_name="auth",
                total_cost_usd=0.05,
                duration_seconds=120.0,
            ),
        ]

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
        ):
            result = runner.invoke(app, ["runs"])

        assert result.exit_code == 0
        assert "abc12345" in result.output
        assert "dev" in result.output
        assert "completed" in result.output
        assert "auth" in result.output

    def test_runs_component_filter(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.list_runs.return_value = []

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
        ):
            runner.invoke(app, ["runs", "--component", "dev"])

        mock_mgr.list_runs.assert_called_once_with(component="dev", status=None, limit=20)

    def test_runs_status_filter(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.list_runs.return_value = []

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
        ):
            runner.invoke(app, ["runs", "--status", "completed"])

        mock_mgr.list_runs.assert_called_once_with(component=None, status="completed", limit=20)

    def test_runs_limit(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.list_runs.return_value = []

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
        ):
            runner.invoke(app, ["runs", "--limit", "5"])

        mock_mgr.list_runs.assert_called_once_with(component=None, status=None, limit=5)

    def test_runs_cost_formatted(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.list_runs.return_value = [
            RunSummary(
                run_id="abc12345",
                component="dev",
                status="completed",
                total_cost_usd=0.05,
                duration_seconds=120.0,
            ),
        ]

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
        ):
            result = runner.invoke(app, ["runs"])

        assert "$0.05" in result.output

    def test_runs_duration_formatted(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.list_runs.return_value = [
            RunSummary(
                run_id="abc12345",
                component="dev",
                status="completed",
                duration_seconds=120.0,
            ),
        ]

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
        ):
            result = runner.invoke(app, ["runs"])

        assert "2m 0s" in result.output

    def test_runs_help(self) -> None:
        result = runner.invoke(app, ["runs", "--help"])
        assert result.exit_code == 0
        assert "--component" in result.output
        assert "--status" in result.output
        assert "--limit" in result.output


class TestShowCommand:
    def test_show_displays_detail(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.get_run.return_value = RunDetail(
            run_id="abc12345",
            component="dev",
            status="completed",
            repo="https://github.com/test/repo",
            branch="feature/auth",
            model="claude-sonnet-4-20250514",
            feature_name="auth",
            total_cost_usd=0.05,
            duration_seconds=120.0,
            num_turns=5,
            stream_events_count=10,
        )

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
        ):
            result = runner.invoke(app, ["show", "abc12345"])

        assert result.exit_code == 0
        assert "abc12345" in result.output
        assert "dev" in result.output
        assert "completed" in result.output
        assert "feature/auth" in result.output
        assert "$0.05" in result.output

    def test_show_invalid_run_id(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.get_run.side_effect = FileNotFoundError("Run not-exist not found")

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
        ):
            result = runner.invoke(app, ["show", "not-exist"])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_show_error_message_displayed(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.get_run.return_value = RunDetail(
            run_id="abc12345",
            component="dev",
            status="failed",
            error_message="Something went wrong",
        )

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
        ):
            result = runner.invoke(app, ["show", "abc12345"])

        assert result.exit_code == 0
        assert "Something went wrong" in result.output

    def test_show_session_id_displayed(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.get_run.return_value = RunDetail(
            run_id="abc12345",
            component="dev",
            status="completed",
            session_id="sess-abc-123",
        )

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
        ):
            result = runner.invoke(app, ["show", "abc12345"])

        assert result.exit_code == 0
        assert "sess-abc-123" in result.output


class TestAttachCommand:
    def test_attach_success(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.get_run.return_value = MagicMock()
        mock_mgr.get_container_name.return_value = "dkmv-dev-abc123"

        inspect_mock = MagicMock(returncode=0, stdout="true\n")
        exec_mock = MagicMock(returncode=0)

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
            patch("dkmv.cli.subprocess.run", side_effect=[inspect_mock, exec_mock]),
        ):
            result = runner.invoke(app, ["attach", "abc12345"])

        assert "Attaching to container" in result.output

    def test_attach_run_not_found(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.get_run.side_effect = FileNotFoundError("not found")

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
        ):
            result = runner.invoke(app, ["attach", "not-exist"])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_attach_no_container_name(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.get_run.return_value = MagicMock()
        mock_mgr.get_container_name.return_value = None

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
        ):
            result = runner.invoke(app, ["attach", "abc12345"])

        assert result.exit_code == 1
        assert "No container name" in result.output
        assert "--keep-alive" in result.output

    def test_attach_container_not_running(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.get_run.return_value = MagicMock()
        mock_mgr.get_container_name.return_value = "dkmv-dev-abc123"

        inspect_mock = MagicMock(returncode=0, stdout="false\n")

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
            patch("dkmv.cli.subprocess.run", return_value=inspect_mock),
        ):
            result = runner.invoke(app, ["attach", "abc12345"])

        assert result.exit_code == 1
        assert "is not running" in result.output


class TestStopCommand:
    def test_stop_success(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.get_run.return_value = MagicMock()
        mock_mgr.get_container_name.return_value = "dkmv-dev-abc123"

        inspect_mock = MagicMock(returncode=0)
        stop_mock = MagicMock(returncode=0)
        rm_mock = MagicMock(returncode=0)

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
            patch("dkmv.cli.subprocess.run", side_effect=[inspect_mock, stop_mock, rm_mock]),
        ):
            result = runner.invoke(app, ["stop", "abc12345"])

        assert result.exit_code == 0
        assert "stopped and removed" in result.output

    def test_stop_run_not_found(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.get_run.side_effect = FileNotFoundError("not found")

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
        ):
            result = runner.invoke(app, ["stop", "not-exist"])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_stop_no_container_name(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.get_run.return_value = MagicMock()
        mock_mgr.get_container_name.return_value = None

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
        ):
            result = runner.invoke(app, ["stop", "abc12345"])

        assert result.exit_code == 1
        assert "No container name" in result.output

    def test_stop_already_removed(self, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_mgr.get_run.return_value = MagicMock()
        mock_mgr.get_container_name.return_value = "dkmv-dev-abc123"

        inspect_mock = MagicMock(returncode=1)

        with (
            patch("dkmv.cli.load_config", return_value=_mock_config(tmp_path)),
            patch("dkmv.core.runner.RunManager", return_value=mock_mgr),
            patch("dkmv.cli.subprocess.run", return_value=inspect_mock),
        ):
            result = runner.invoke(app, ["stop", "abc12345"])

        assert result.exit_code == 0
        assert "already removed" in result.output
