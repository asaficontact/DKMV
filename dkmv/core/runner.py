from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dkmv.core.models import (
    BaseComponentConfig,
    BaseResult,
    ComponentName,
    RunDetail,
    RunStatus,
    RunSummary,
)


class RunManager:
    def __init__(self, output_dir: Path) -> None:
        self._runs_dir = output_dir / "runs"
        self._runs_dir.mkdir(parents=True, exist_ok=True)

    def _run_dir(self, run_id: str) -> Path:
        return self._runs_dir / run_id

    def start_run(self, component: ComponentName, config: BaseComponentConfig) -> str:
        run_id = uuid.uuid4().hex[:8]
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True)
        (run_dir / "logs").mkdir()

        config_data = config.model_dump(mode="json")
        config_data["_run_id"] = run_id
        config_data["_component"] = component
        config_data["_started_at"] = datetime.now(UTC).isoformat()

        (run_dir / "config.json").write_text(json.dumps(config_data, indent=2))
        return run_id

    def save_result(self, run_id: str, result: BaseResult) -> None:
        run_dir = self._run_dir(run_id)
        tmp_path = run_dir / "result.json.tmp"
        final_path = run_dir / "result.json"
        tmp_path.write_text(result.model_dump_json(indent=2))
        os.replace(tmp_path, final_path)

    def append_stream(self, run_id: str, event: dict[str, Any]) -> None:
        run_dir = self._run_dir(run_id)
        with (run_dir / "stream.jsonl").open("a") as f:
            f.write(json.dumps(event) + "\n")

    def save_container_name(self, run_id: str, container_name: str) -> None:
        (self._run_dir(run_id) / "container.txt").write_text(container_name)

    def get_container_name(self, run_id: str) -> str | None:
        path = self._run_dir(run_id) / "container.txt"
        if path.exists():
            name = path.read_text().strip()
            return name if name else None
        return None

    def save_prompt(self, run_id: str, prompt: str) -> None:
        run_dir = self._run_dir(run_id)
        (run_dir / "prompt.md").write_text(prompt)

    def list_runs(
        self,
        component: ComponentName | None = None,
        feature: str | None = None,
        status: RunStatus | None = None,
        limit: int = 20,
    ) -> list[RunSummary]:
        summaries: list[RunSummary] = []

        if not self._runs_dir.exists():
            return summaries

        for run_dir in self._runs_dir.iterdir():
            if not run_dir.is_dir():
                continue

            result_file = run_dir / "result.json"
            config_file = run_dir / "config.json"

            try:
                if result_file.exists():
                    data = json.loads(result_file.read_text())
                    summary = RunSummary(
                        run_id=data["run_id"],
                        component=data["component"],
                        status=data["status"],
                        feature_name=data.get("feature_name", ""),
                        timestamp=data.get("timestamp", "1970-01-01T00:00:00+00:00"),
                        total_cost_usd=data.get("total_cost_usd", 0.0),
                        duration_seconds=data.get("duration_seconds", 0.0),
                    )
                elif config_file.exists():
                    data = json.loads(config_file.read_text())
                    summary = RunSummary(
                        run_id=data.get("_run_id", run_dir.name),
                        component=data.get("_component", "dev"),
                        status="running",
                        feature_name=data.get("feature_name", ""),
                        timestamp=data.get("_started_at", "1970-01-01T00:00:00+00:00"),
                    )
                else:
                    continue
            except (json.JSONDecodeError, KeyError, ValidationError):
                continue

            if component and summary.component != component:
                continue
            if status and summary.status != status:
                continue
            if feature and feature.lower() not in summary.feature_name.lower():
                continue

            summaries.append(summary)

        summaries.sort(key=lambda s: s.timestamp, reverse=True)
        return summaries[:limit]

    def get_run(self, run_id: str) -> RunDetail:
        run_dir = self._run_dir(run_id)
        if not run_dir.exists():
            msg = f"Run {run_id} not found"
            raise FileNotFoundError(msg)

        result_file = run_dir / "result.json"
        config_file = run_dir / "config.json"
        prompt_file = run_dir / "prompt.md"
        stream_file = run_dir / "stream.jsonl"
        log_path = run_dir / "logs" / "run.log"

        config_data: dict[str, Any] = {}
        if config_file.exists():
            config_data = json.loads(config_file.read_text())

        if result_file.exists():
            result_data = json.loads(result_file.read_text())
        else:
            result_data = {
                "run_id": run_id,
                "component": config_data.get("_component", "dev"),
                "status": "running",
            }

        prompt = prompt_file.read_text() if prompt_file.exists() else ""

        stream_events_count = 0
        if stream_file.exists():
            with stream_file.open() as f:
                stream_events_count = sum(1 for _ in f)

        timestamp_str = result_data.get(
            "timestamp", config_data.get("_started_at", "1970-01-01T00:00:00+00:00")
        )

        try:
            return RunDetail(
                run_id=result_data.get("run_id", run_id),
                component=result_data.get("component", config_data.get("_component", "dev")),
                status=result_data.get("status", "running"),
                repo=result_data.get("repo", ""),
                branch=result_data.get("branch", ""),
                feature_name=result_data.get("feature_name", ""),
                model=result_data.get("model", ""),
                total_cost_usd=result_data.get("total_cost_usd", 0.0),
                duration_seconds=result_data.get("duration_seconds", 0.0),
                num_turns=result_data.get("num_turns", 0),
                timestamp=timestamp_str,
                session_id=result_data.get("session_id", ""),
                error_message=result_data.get("error_message", ""),
                config=config_data,
                stream_events_count=stream_events_count,
                prompt=prompt,
                log_path=str(log_path) if log_path.exists() else "",
            )
        except ValidationError:
            # Corrupt data in result.json — return degraded detail
            return RunDetail(
                run_id=run_id,
                component=config_data.get("_component", "dev"),
                status="failed",
                error_message="Corrupt run data",
                config=config_data,
                stream_events_count=stream_events_count,
                prompt=prompt,
            )
