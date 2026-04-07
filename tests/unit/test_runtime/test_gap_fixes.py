"""Tests for the ODIN follow-up gap fixes (Phases 1-6)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dkmv.core.models import BaseComponentConfig
from dkmv.core.runner import RunManager
from dkmv.runtime._artifacts import ArtifactRef, get_artifact, list_artifacts
from dkmv.runtime._facade import EmbeddedRuntime
from dkmv.runtime._handle import RunHandle
from dkmv.runtime._introspection import (
    ComponentInfo,
    TaskInfo,
    _task_def_to_info,
    inspect_component,
)
from dkmv.runtime._observer import EventBus, _raw_to_event
from dkmv.runtime._types import (
    ContainerStatus,
    ExecutionSource,
    ExecutionSourceType,
    SourceProvenance,
)


# ── Phase 1: Durable Stop/Cancel ────────────────────────────────────


class TestRunHandleCancelEvent:
    def test_cancel_event_exists(self) -> None:
        bus = EventBus()
        handle = RunHandle(run_id="run-1", event_bus=bus)
        assert isinstance(handle.cancel_event, asyncio.Event)
        assert not handle.cancel_event.is_set()

    @pytest.mark.asyncio
    async def test_cooperative_stop_sets_cancel_event(self) -> None:
        bus = EventBus()
        handle = RunHandle(run_id="run-1", event_bus=bus)

        async def slow() -> None:
            await asyncio.sleep(10)

        task = asyncio.create_task(slow())
        handle._set_task(task)

        await handle.stop(force=False)
        assert handle.cancel_event.is_set()
        assert handle.status == "stopping"

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_force_stop_also_sets_cancel_event(self) -> None:
        bus = EventBus()
        handle = RunHandle(run_id="run-1", event_bus=bus)

        async def slow() -> None:
            await asyncio.sleep(10)

        task = asyncio.create_task(slow())
        handle._set_task(task)

        await handle.stop(force=True)
        assert handle.cancel_event.is_set()

        try:
            await task
        except asyncio.CancelledError:
            pass


class TestReconcileStaleRuns:
    def test_reconcile_writes_result_for_dead_container(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "stale-run"
        run_dir.mkdir(parents=True)
        (run_dir / "config.json").write_text(
            json.dumps({"_component": "dev", "_run_id": "stale-run"})
        )
        (run_dir / "container.txt").write_text("dead-container-123")

        rt = EmbeddedRuntime(output_dir=tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            reconciled = rt.reconcile_stale_runs()

        assert "stale-run" in reconciled
        result = json.loads((run_dir / "result.json").read_text())
        assert result["status"] == "cancelled"
        assert "Reconciled" in result["error_message"]

    def test_reconcile_skips_alive_container(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "alive-run"
        run_dir.mkdir(parents=True)
        (run_dir / "config.json").write_text(json.dumps({"_component": "dev"}))
        (run_dir / "container.txt").write_text("alive-container")

        rt = EmbeddedRuntime(output_dir=tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="running\n")
            reconciled = rt.reconcile_stale_runs()

        assert reconciled == []
        assert not (run_dir / "result.json").exists()

    def test_reconcile_skips_runs_with_result(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "done-run"
        run_dir.mkdir(parents=True)
        (run_dir / "config.json").write_text(json.dumps({"_component": "dev"}))
        (run_dir / "result.json").write_text(json.dumps({"status": "completed"}))

        rt = EmbeddedRuntime(output_dir=tmp_path)
        reconciled = rt.reconcile_stale_runs()
        assert reconciled == []

    def test_reconcile_no_container_txt(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "no-container-run"
        run_dir.mkdir(parents=True)
        (run_dir / "config.json").write_text(json.dumps({"_component": "dev"}))
        # No container.txt — should be reconciled as dead

        rt = EmbeddedRuntime(output_dir=tmp_path)
        reconciled = rt.reconcile_stale_runs()
        assert "no-container-run" in reconciled

    def test_reconcile_empty_runs_dir(self, tmp_path: Path) -> None:
        rt = EmbeddedRuntime(output_dir=tmp_path)
        reconciled = rt.reconcile_stale_runs()
        assert reconciled == []


# ── Phase 2: Event Fidelity ─────────────────────────────────────────


class TestTimestampInjection:
    def test_append_stream_injects_ts(self, tmp_path: Path) -> None:
        rm = RunManager(tmp_path)
        run_id = rm.start_run(
            "dev",
            BaseComponentConfig(repo="r", feature_name="f"),
        )
        rm.append_stream(run_id, {"type": "test"})

        stream = (rm._run_dir(run_id) / "stream.jsonl").read_text().strip()
        event = json.loads(stream)
        assert "_ts" in event
        # Verify it's a valid ISO timestamp
        datetime.fromisoformat(event["_ts"])

    def test_append_stream_preserves_existing_ts(self, tmp_path: Path) -> None:
        rm = RunManager(tmp_path)
        run_id = rm.start_run(
            "dev",
            BaseComponentConfig(repo="r", feature_name="f"),
        )
        existing_ts = "2026-01-01T00:00:00+00:00"
        rm.append_stream(run_id, {"type": "test", "_ts": existing_ts})

        stream = (rm._run_dir(run_id) / "stream.jsonl").read_text().strip()
        event = json.loads(stream)
        assert event["_ts"] == existing_ts


class TestObserverPersistedTimestamp:
    def test_raw_to_event_uses_persisted_ts(self) -> None:
        ts = "2026-03-15T12:00:00+00:00"
        raw = {"type": "stream", "_ts": ts}
        event = _raw_to_event(raw)
        assert event.timestamp == datetime.fromisoformat(ts)

    def test_raw_to_event_falls_back_to_now(self) -> None:
        raw = {"type": "stream"}
        before = datetime.now(UTC)
        event = _raw_to_event(raw)
        assert event.timestamp >= before

    def test_raw_to_event_reads_task_context_from_raw(self) -> None:
        raw = {"type": "assistant", "_task_name": "step-2", "_task_idx": 3}
        event = _raw_to_event(raw, task_name="default", task_index=0)
        assert event.task_name == "step-2"
        assert event.task_index == 3

    def test_raw_to_event_lifecycle_ignores_raw_task_context(self) -> None:
        raw = {
            "type": "task_completed",
            "lifecycle": True,
            "task_name": "real-task",
            "task_index": 1,
            "_task_name": "injected",
            "_task_idx": 99,
        }
        event = _raw_to_event(raw, task_name="default", task_index=0)
        # Lifecycle events use their own task_name/task_index, not _task_name/_task_idx
        assert event.task_name == "real-task"
        assert event.task_index == 1


class TestReplayPreservesTimestamps:
    def test_replay_uses_persisted_ts(self, tmp_path: Path) -> None:
        from dkmv.runtime._observer import replay_events

        ts = "2026-03-15T12:00:00+00:00"
        runs_dir = tmp_path / "runs" / "run-ts"
        runs_dir.mkdir(parents=True)
        (runs_dir / "stream.jsonl").write_text(json.dumps({"type": "test", "_ts": ts}) + "\n")

        events = replay_events("run-ts", tmp_path)
        assert len(events) == 1
        assert events[0].timestamp == datetime.fromisoformat(ts)


# ── Phase 3: Artifact Provenance ────────────────────────────────────


class TestSaveTaskArtifact:
    def test_saves_under_tasks_subdir(self, tmp_path: Path) -> None:
        rm = RunManager(tmp_path)
        run_id = rm.start_run("dev", BaseComponentConfig(repo="r", feature_name="f"))

        path = rm.save_task_artifact(
            run_id, "step-1", "plan.json", '{"key": "val"}', "/orig/plan.json"
        )

        assert path.exists()
        assert "tasks/step-1/plan.json" in str(path)
        assert path.read_text() == '{"key": "val"}'

        # Check metadata sidecar
        meta_path = path.parent / "plan.json.meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["task_name"] == "step-1"
        assert meta["original_path"] == "/orig/plan.json"

    def test_no_collision_same_filename_different_tasks(self, tmp_path: Path) -> None:
        rm = RunManager(tmp_path)
        run_id = rm.start_run("dev", BaseComponentConfig(repo="r", feature_name="f"))

        rm.save_task_artifact(run_id, "task-a", "result.json", "content-a")
        rm.save_task_artifact(run_id, "task-b", "result.json", "content-b")

        a = (rm._run_dir(run_id) / "tasks" / "task-a" / "result.json").read_text()
        b = (rm._run_dir(run_id) / "tasks" / "task-b" / "result.json").read_text()
        assert a == "content-a"
        assert b == "content-b"


class TestListArtifactsWithTasks:
    def test_list_includes_task_artifacts(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-art"
        run_dir.mkdir(parents=True)
        (run_dir / "config.json").write_text("{}")

        task_dir = run_dir / "tasks" / "step-1"
        task_dir.mkdir(parents=True)
        (task_dir / "plan.json").write_text('{"plan": true}')
        (task_dir / "plan.json.meta.json").write_text(
            json.dumps({"task_name": "step-1", "original_path": "/orig/plan.json"})
        )

        artifacts = list_artifacts("run-art", tmp_path)
        names = {a.filename for a in artifacts}
        assert "tasks/step-1/plan.json" in names
        assert "config.json" in names

        # Check the task artifact has provenance
        task_art = next(
            a for a in artifacts if "plan.json" in a.filename and "tasks/" in a.filename
        )
        assert task_art.original_path == "/orig/plan.json"
        assert task_art.step_instance == "step-1"

    def test_list_excludes_meta_json(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-meta"
        run_dir.mkdir(parents=True)
        task_dir = run_dir / "tasks" / "s1"
        task_dir.mkdir(parents=True)
        (task_dir / "file.txt").write_text("content")
        (task_dir / "file.txt.meta.json").write_text("{}")

        artifacts = list_artifacts("run-meta", tmp_path)
        names = {a.filename for a in artifacts}
        assert "tasks/s1/file.txt" in names
        assert "tasks/s1/file.txt.meta.json" not in names

    def test_get_artifact_from_task_subdir(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-get"
        task_dir = run_dir / "tasks" / "step-1"
        task_dir.mkdir(parents=True)
        (task_dir / "output.md").write_text("hello")

        content = get_artifact("run-get", "tasks/step-1/output.md", tmp_path)
        assert content == "hello"


class TestArtifactRefNewFields:
    def test_default_values(self) -> None:
        ref = ArtifactRef(
            run_id="r", filename="f", path=Path("."), size_bytes=0, artifact_type="output"
        )
        assert ref.original_path == ""
        assert ref.step_instance == ""


# ── Phase 4: Introspection Depth ────────────────────────────────────


class TestTaskInfoDepth:
    def test_task_info_includes_prompt_and_instructions(self) -> None:
        from dkmv.tasks.models import TaskDefinition

        task = TaskDefinition(
            name="my-task",
            prompt="Do the thing",
            instructions="Follow these rules",
            max_budget_usd=5.0,
        )
        info = _task_def_to_info(task, Path("."))
        assert info.prompt == "Do the thing"
        assert info.instructions == "Follow these rules"
        assert info.max_budget_usd == 5.0

    def test_task_info_includes_serialized_inputs_outputs(self) -> None:
        from dkmv.tasks.models import TaskDefinition, TaskInput, TaskOutput

        task = TaskDefinition(
            name="io-task",
            prompt="go",
            inputs=[TaskInput(name="env-var", type="env", key="FOO", value="bar")],
            outputs=[TaskOutput(path="/workspace/out.json", required=True)],
        )
        info = _task_def_to_info(task, Path("."))
        assert len(info.inputs) == 1
        assert info.inputs[0]["name"] == "env-var"
        assert len(info.outputs) == 1
        assert info.outputs[0]["required"] is True

    def test_task_info_defaults(self) -> None:
        info = TaskInfo(name="t")
        assert info.prompt is None
        assert info.instructions is None
        assert info.inputs == []
        assert info.outputs == []
        assert info.max_budget_usd is None


class TestComponentInfoDepth:
    def test_inspect_builtin_has_new_fields(self) -> None:
        info = inspect_component("dev")
        # Built-in dev component — should have default empty values
        assert isinstance(info.manifest_inputs, list)
        assert isinstance(info.workspace_dirs, list)
        assert isinstance(info.state_files, list)

    def test_component_info_defaults(self) -> None:
        info = ComponentInfo(name="test", path=Path("."))
        assert info.manifest_inputs == []
        assert info.workspace_dirs == []
        assert info.state_files == []
        assert info.agent_md is None


# ── Phase 5: Source Provenance ──────────────────────────────────────


class TestSourceProvenance:
    def test_model_construction(self) -> None:
        prov = SourceProvenance(
            source_type="local_snapshot",
            local_path="/home/user/project",
            head_sha="abc123",
            branch="main",
            dirty=True,
            include_uncommitted=True,
            include_untracked=True,
        )
        assert prov.source_type == "local_snapshot"
        assert prov.head_sha == "abc123"
        assert prov.dirty is True

    def test_defaults(self) -> None:
        prov = SourceProvenance(source_type="remote")
        assert prov.local_path == ""
        assert prov.head_sha == ""
        assert prov.dirty is False
        assert prov.include_untracked is True

    def test_execution_source_include_untracked(self) -> None:
        src = ExecutionSource(
            type=ExecutionSourceType.LOCAL_SNAPSHOT,
            local_path=Path("."),
            include_untracked=False,
        )
        assert src.include_untracked is False

    def test_execution_source_default_include_untracked(self) -> None:
        src = ExecutionSource(type=ExecutionSourceType.REMOTE, repo="https://example.com")
        assert src.include_untracked is True

    def test_provenance_saved_and_retrievable(self, tmp_path: Path) -> None:
        # Create a run with provenance
        run_dir = tmp_path / "runs" / "run-prov"
        run_dir.mkdir(parents=True)
        prov = SourceProvenance(
            source_type="local_snapshot",
            head_sha="deadbeef",
            branch="main",
        )
        (run_dir / "source_provenance.json").write_text(prov.model_dump_json(indent=2))

        rt = EmbeddedRuntime(output_dir=tmp_path)
        loaded = rt.get_source_provenance("run-prov")
        assert loaded is not None
        assert loaded.head_sha == "deadbeef"

    def test_provenance_returns_none_for_missing(self, tmp_path: Path) -> None:
        (tmp_path / "runs" / "run-noprov").mkdir(parents=True)
        rt = EmbeddedRuntime(output_dir=tmp_path)
        assert rt.get_source_provenance("run-noprov") is None


# ── Phase 6: Retained Sandbox Inspection ────────────────────────────


class TestContainerStatus:
    def test_model_construction(self) -> None:
        cs = ContainerStatus(run_id="r1", container_name="c1", alive=True, state="running")
        assert cs.alive is True
        assert cs.state == "running"

    def test_defaults(self) -> None:
        cs = ContainerStatus(run_id="r1")
        assert cs.alive is False
        assert cs.state == "unknown"
        assert cs.error == ""


class TestGetContainerStatus:
    def test_running_container(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-c1"
        run_dir.mkdir(parents=True)
        (run_dir / "container.txt").write_text("my-container")

        rt = EmbeddedRuntime(output_dir=tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="running\n")
            status = rt.get_container_status("run-c1")

        assert status.alive is True
        assert status.state == "running"
        assert status.container_name == "my-container"

    def test_exited_container(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-c2"
        run_dir.mkdir(parents=True)
        (run_dir / "container.txt").write_text("exited-container")

        rt = EmbeddedRuntime(output_dir=tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="exited\n")
            status = rt.get_container_status("run-c2")

        assert status.alive is False
        assert status.state == "exited"

    def test_removed_container(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-c3"
        run_dir.mkdir(parents=True)
        (run_dir / "container.txt").write_text("removed-container")

        rt = EmbeddedRuntime(output_dir=tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            status = rt.get_container_status("run-c3")

        assert status.alive is False
        assert status.state == "removed"

    def test_no_container_txt(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-c4"
        run_dir.mkdir(parents=True)

        rt = EmbeddedRuntime(output_dir=tmp_path)
        status = rt.get_container_status("run-c4")
        assert status.state == "removed"
        assert "No container.txt" in status.error


class TestExecuteInContainer:
    def test_success(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-exec"
        run_dir.mkdir(parents=True)
        (run_dir / "container.txt").write_text("exec-container")

        rt = EmbeddedRuntime(output_dir=tmp_path)
        with patch("subprocess.run") as mock_run:
            # First call: docker inspect (get_container_status)
            # Second call: docker exec
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="running\n"),
                MagicMock(returncode=0, stdout="hello world\n", stderr=""),
            ]
            result = rt.execute_in_container("run-exec", "echo hello world")

        assert result == "hello world\n"

    def test_not_running_raises(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-exec2"
        run_dir.mkdir(parents=True)
        (run_dir / "container.txt").write_text("stopped-container")

        rt = EmbeddedRuntime(output_dir=tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="exited\n")
            with pytest.raises(RuntimeError, match="not running"):
                rt.execute_in_container("run-exec2", "ls")


class TestExportWorkspace:
    def test_success(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-export"
        run_dir.mkdir(parents=True)
        (run_dir / "container.txt").write_text("export-container")

        output_path = tmp_path / "exported"

        rt = EmbeddedRuntime(output_dir=tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="exited\n"),  # docker inspect
                MagicMock(returncode=0, stdout="", stderr=""),  # docker cp
            ]
            result = rt.export_workspace("run-export", output_path)

        assert result == output_path

    def test_no_container_raises(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-export2"
        run_dir.mkdir(parents=True)

        rt = EmbeddedRuntime(output_dir=tmp_path)
        with pytest.raises(RuntimeError, match="No container"):
            rt.export_workspace("run-export2", tmp_path / "out")


# ── Imports verification ────────────────────────────────────────────


class TestPublicImports:
    def test_source_provenance_importable(self) -> None:
        from dkmv.runtime import SourceProvenance

        assert SourceProvenance is not None

    def test_container_status_importable(self) -> None:
        from dkmv.runtime import ContainerStatus

        assert ContainerStatus is not None


# ── Issue Fix 1: Lifecycle event type for cancelled runs ────────────


class TestLifecycleEventTypes:
    def test_raw_to_event_cancelled_lifecycle(self) -> None:
        """Cancelled runs should produce run_cancelled, not run_failed."""
        # This tests the observer receiving a run_cancelled event type
        raw = {
            "type": "run_cancelled",
            "lifecycle": True,
            "status": "cancelled",
            "component": "dev",
        }
        event = _raw_to_event(raw, run_id="r1")
        assert event.event_type == "run_cancelled"

    def test_raw_to_event_timed_out_lifecycle(self) -> None:
        raw = {
            "type": "run_timed_out",
            "lifecycle": True,
            "status": "timed_out",
            "component": "dev",
        }
        event = _raw_to_event(raw, run_id="r1")
        assert event.event_type == "run_timed_out"


# ── Issue Fix 2: for_each artifact collision safety ─────────────────


class TestForEachArtifactIsolation:
    def test_same_task_name_different_for_each_index(self, tmp_path: Path) -> None:
        rm = RunManager(tmp_path)
        run_id = rm.start_run("dev", BaseComponentConfig(repo="r", feature_name="f"))

        # Simulate two for_each iterations with same task name
        rm.save_task_artifact(
            run_id, "process__idx_0", "output.json", '{"idx": 0}', "/out/output.json"
        )
        rm.save_task_artifact(
            run_id, "process__idx_1", "output.json", '{"idx": 1}', "/out/output.json"
        )

        run_dir = rm._run_dir(run_id)
        assert (run_dir / "tasks" / "process__idx_0" / "output.json").read_text() == '{"idx": 0}'
        assert (run_dir / "tasks" / "process__idx_1" / "output.json").read_text() == '{"idx": 1}'

    def test_list_artifacts_shows_both_for_each_instances(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run-fe"
        run_dir.mkdir(parents=True)
        (run_dir / "config.json").write_text("{}")

        for idx in range(3):
            task_dir = run_dir / "tasks" / f"step__idx_{idx}"
            task_dir.mkdir(parents=True)
            (task_dir / "result.json").write_text(f'{{"idx": {idx}}}')
            (task_dir / "result.json.meta.json").write_text(
                json.dumps({"task_name": "step", "original_path": "/out/result.json"})
            )

        artifacts = list_artifacts("run-fe", tmp_path)
        task_arts = [a for a in artifacts if "tasks/" in a.filename]
        assert len(task_arts) == 3
        # Each has a distinct step_instance
        instances = {a.step_instance for a in task_arts}
        assert len(instances) == 3


# ── Issue Fix 3: step_instance on RuntimeEvent ──────────────────────


class TestRuntimeEventStepInstance:
    def test_step_instance_from_raw_dict(self) -> None:
        raw = {"type": "assistant", "_step_instance": "plan__idx_2"}
        event = _raw_to_event(raw, task_name="plan", task_index=2)
        assert event.step_instance == "plan__idx_2"

    def test_step_instance_derived_from_for_each_index(self) -> None:
        raw = {"type": "task_start", "task_name": "deploy", "for_each_index": 5, "lifecycle": True}
        event = _raw_to_event(raw, task_name="deploy")
        assert event.step_instance == "deploy__idx_5"

    def test_step_instance_equals_task_name_without_for_each(self) -> None:
        raw = {"type": "assistant", "_task_name": "build"}
        event = _raw_to_event(raw, task_name="build")
        assert event.step_instance == "build"

    def test_step_instance_empty_when_no_task_context(self) -> None:
        raw = {"type": "system"}
        event = _raw_to_event(raw)
        assert event.step_instance == ""

    def test_step_instance_default_on_model(self) -> None:
        from dkmv.runtime._observer import RuntimeEvent

        event = RuntimeEvent(timestamp=datetime.now(UTC))
        assert event.step_instance == ""
