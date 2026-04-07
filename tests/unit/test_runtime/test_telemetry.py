"""Tests for dkmv.runtime._telemetry."""

from __future__ import annotations

import json
from pathlib import Path

from dkmv.runtime._telemetry import RunStats, get_run_stats


class TestRunStats:
    def test_defaults(self) -> None:
        stats = RunStats()
        assert stats.total_runs == 0
        assert stats.completed == 0
        assert stats.failed == 0
        assert stats.timed_out == 0
        assert stats.cancelled == 0
        assert stats.total_cost_usd == 0.0
        assert stats.avg_cost_usd == 0.0
        assert stats.components_used == {}


def _write_result(runs_dir: Path, run_id: str, data: dict) -> None:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "result.json").write_text(json.dumps(data))


class TestGetRunStats:
    def test_empty(self, tmp_path: Path) -> None:
        stats = get_run_stats(tmp_path)
        assert stats.total_runs == 0

    def test_no_runs_dir(self, tmp_path: Path) -> None:
        stats = get_run_stats(tmp_path / "nonexistent")
        assert stats.total_runs == 0

    def test_single_completed(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_result(
            runs_dir,
            "run-1",
            {
                "component": "dev",
                "status": "completed",
                "total_cost_usd": 2.5,
                "duration_seconds": 120.0,
            },
        )

        stats = get_run_stats(tmp_path)
        assert stats.total_runs == 1
        assert stats.completed == 1
        assert stats.total_cost_usd == 2.5
        assert stats.avg_cost_usd == 2.5
        assert stats.components_used == {"dev": 1}

    def test_multiple_statuses(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_result(
            runs_dir,
            "run-1",
            {
                "component": "dev",
                "status": "completed",
                "total_cost_usd": 1.0,
                "duration_seconds": 60.0,
            },
        )
        _write_result(
            runs_dir,
            "run-2",
            {
                "component": "qa",
                "status": "failed",
                "total_cost_usd": 0.5,
                "duration_seconds": 30.0,
            },
        )
        _write_result(
            runs_dir,
            "run-3",
            {
                "component": "dev",
                "status": "timed_out",
                "total_cost_usd": 3.0,
                "duration_seconds": 1800.0,
            },
        )

        stats = get_run_stats(tmp_path)
        assert stats.total_runs == 3
        assert stats.completed == 1
        assert stats.failed == 1
        assert stats.timed_out == 1
        assert stats.total_cost_usd == 4.5
        assert stats.components_used == {"dev": 2, "qa": 1}

    def test_filter_by_component(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_result(
            runs_dir,
            "run-1",
            {
                "component": "dev",
                "status": "completed",
                "total_cost_usd": 1.0,
                "duration_seconds": 60.0,
            },
        )
        _write_result(
            runs_dir,
            "run-2",
            {
                "component": "qa",
                "status": "completed",
                "total_cost_usd": 2.0,
                "duration_seconds": 90.0,
            },
        )

        stats = get_run_stats(tmp_path, component="dev")
        assert stats.total_runs == 1
        assert stats.total_cost_usd == 1.0
        assert stats.components_used == {"dev": 1}

    def test_averages(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_result(
            runs_dir,
            "run-1",
            {
                "component": "dev",
                "status": "completed",
                "total_cost_usd": 4.0,
                "duration_seconds": 200.0,
            },
        )
        _write_result(
            runs_dir,
            "run-2",
            {
                "component": "dev",
                "status": "completed",
                "total_cost_usd": 6.0,
                "duration_seconds": 100.0,
            },
        )

        stats = get_run_stats(tmp_path)
        assert stats.avg_cost_usd == 5.0
        assert stats.avg_duration_seconds == 150.0

    def test_skips_invalid_json(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs" / "run-bad"
        runs_dir.mkdir(parents=True)
        (runs_dir / "result.json").write_text("not json")

        _write_result(
            tmp_path / "runs",
            "run-good",
            {
                "component": "dev",
                "status": "completed",
                "total_cost_usd": 1.0,
                "duration_seconds": 60.0,
            },
        )

        stats = get_run_stats(tmp_path)
        assert stats.total_runs == 1

    def test_cancelled_status(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_result(
            runs_dir,
            "run-1",
            {
                "component": "dev",
                "status": "cancelled",
                "total_cost_usd": 0.3,
                "duration_seconds": 10.0,
            },
        )

        stats = get_run_stats(tmp_path)
        assert stats.cancelled == 1
