"""Run telemetry and aggregate statistics."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel


class RunStats(BaseModel):
    """Aggregate statistics across runs."""

    total_runs: int = 0
    completed: int = 0
    failed: int = 0
    timed_out: int = 0
    cancelled: int = 0
    total_cost_usd: float = 0.0
    total_duration_seconds: float = 0.0
    avg_cost_usd: float = 0.0
    avg_duration_seconds: float = 0.0
    components_used: dict[str, int] = {}


def get_run_stats(
    output_dir: Path,
    component: str | None = None,
) -> RunStats:
    """Aggregate statistics from run results.

    Args:
        output_dir: Base output directory containing runs/.
        component: Optional filter by component name.

    Returns:
        Aggregated RunStats.
    """
    runs_dir = output_dir / "runs"
    if not runs_dir.exists():
        return RunStats()

    total = 0
    completed = 0
    failed = 0
    timed_out = 0
    cancelled = 0
    total_cost = 0.0
    total_duration = 0.0
    components: dict[str, int] = {}

    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        result_path = run_dir / "result.json"
        if not result_path.exists():
            continue
        try:
            data = json.loads(result_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        run_component = data.get("component", "")
        if component and run_component != component:
            continue

        total += 1
        status = data.get("status", "")
        if status == "completed":
            completed += 1
        elif status == "failed":
            failed += 1
        elif status == "timed_out":
            timed_out += 1
        elif status == "cancelled":
            cancelled += 1

        total_cost += data.get("total_cost_usd", 0.0)
        total_duration += data.get("duration_seconds", 0.0)
        components[run_component] = components.get(run_component, 0) + 1

    return RunStats(
        total_runs=total,
        completed=completed,
        failed=failed,
        timed_out=timed_out,
        cancelled=cancelled,
        total_cost_usd=total_cost,
        total_duration_seconds=total_duration,
        avg_cost_usd=total_cost / total if total else 0.0,
        avg_duration_seconds=total_duration / total if total else 0.0,
        components_used=components,
    )
