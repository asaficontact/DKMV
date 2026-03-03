from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from dkmv.tasks.models import (
    ComponentResult,
    TaskDefinition,
    TaskInput,
    TaskOutput,
    TaskResult,
)


class TestTaskInput:
    def test_valid_file_input(self) -> None:
        inp = TaskInput(name="prd", type="file", src="/host/prd.md", dest="/workspace/prd.md")
        assert inp.type == "file"
        assert inp.src == "/host/prd.md"
        assert inp.dest == "/workspace/prd.md"

    def test_valid_text_input(self) -> None:
        inp = TaskInput(name="config", type="text", content="hello", dest="/workspace/config.txt")
        assert inp.type == "text"
        assert inp.content == "hello"

    def test_valid_env_input(self) -> None:
        inp = TaskInput(name="token", type="env", key="API_KEY", value="secret")
        assert inp.type == "env"
        assert inp.key == "API_KEY"
        assert inp.value == "secret"

    def test_file_without_src_raises(self) -> None:
        with pytest.raises(ValidationError, match="'file' input requires 'src'"):
            TaskInput(name="x", type="file", dest="/workspace/x")

    def test_file_without_dest_raises(self) -> None:
        with pytest.raises(ValidationError, match="'file' input requires 'dest'"):
            TaskInput(name="x", type="file", src="/host/x")

    def test_text_without_content_raises(self) -> None:
        with pytest.raises(ValidationError, match="'text' input requires 'content'"):
            TaskInput(name="x", type="text", dest="/workspace/x")

    def test_text_without_dest_raises(self) -> None:
        with pytest.raises(ValidationError, match="'text' input requires 'dest'"):
            TaskInput(name="x", type="text", content="stuff")

    def test_env_without_key_raises(self) -> None:
        with pytest.raises(ValidationError, match="'env' input requires 'key'"):
            TaskInput(name="x", type="env", value="val")

    def test_env_without_value_raises(self) -> None:
        with pytest.raises(ValidationError, match="'env' input requires 'value'"):
            TaskInput(name="x", type="env", key="KEY")

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            TaskInput(name="x", type="bad", key="k", value="v")  # type: ignore[arg-type]

    def test_optional_defaults_to_false(self) -> None:
        inp = TaskInput(name="x", type="file", src="/a", dest="/b")
        assert inp.optional is False

    def test_optional_can_be_set(self) -> None:
        inp = TaskInput(name="x", type="file", src="/a", dest="/b", optional=True)
        assert inp.optional is True

    def test_optional_file_skips_validation_with_empty_src(self) -> None:
        inp = TaskInput(name="x", type="file", src="", dest="/b", optional=True)
        assert inp.optional is True
        assert inp.src == ""

    def test_optional_file_skips_validation_with_none_src(self) -> None:
        inp = TaskInput(name="x", type="file", src=None, dest="/b", optional=True)
        assert inp.optional is True

    def test_optional_text_skips_validation_with_empty_content(self) -> None:
        inp = TaskInput(name="x", type="text", content="", dest="/b", optional=True)
        assert inp.optional is True

    def test_optional_env_skips_validation_with_empty_key_value(self) -> None:
        inp = TaskInput(name="x", type="env", key="", value="", optional=True)
        assert inp.optional is True

    @pytest.mark.parametrize(
        "input_type, fields",
        [
            ("file", {"src": "/a", "dest": "/b"}),
            ("text", {"content": "c", "dest": "/b"}),
            ("env", {"key": "K", "value": "V"}),
        ],
    )
    def test_each_type_valid(self, input_type: str, fields: dict[str, str]) -> None:
        inp = TaskInput(name="test", type=input_type, **fields)  # type: ignore[arg-type]
        assert inp.type == input_type

    def test_relative_dest_normalized(self) -> None:
        inp = TaskInput(name="prd", type="file", src="/a", dest="prd.md")
        assert inp.dest == "/home/dkmv/workspace/.agent/prd.md"

    def test_absolute_dest_unchanged(self) -> None:
        inp = TaskInput(name="prd", type="file", src="/a", dest="/custom/prd.md")
        assert inp.dest == "/custom/prd.md"

    def test_env_dest_stays_none(self) -> None:
        inp = TaskInput(name="tok", type="env", key="K", value="V")
        assert inp.dest is None


class TestTaskOutput:
    def test_defaults(self) -> None:
        out = TaskOutput(path="/workspace/output.txt")
        assert out.required is False
        assert out.save is True

    def test_override_required_and_save(self) -> None:
        out = TaskOutput(path="/workspace/out", required=True, save=False)
        assert out.required is True
        assert out.save is False

    def test_path_is_required(self) -> None:
        with pytest.raises(ValidationError):
            TaskOutput()  # type: ignore[call-arg]

    def test_relative_path_normalized(self) -> None:
        out = TaskOutput(path="plan.md")
        assert out.path == "/home/dkmv/workspace/.agent/plan.md"

    def test_absolute_path_unchanged(self) -> None:
        out = TaskOutput(path="/custom/output.txt")
        assert out.path == "/custom/output.txt"


class TestTaskOutputRequiredFields:
    def test_required_fields_default_empty(self) -> None:
        out = TaskOutput(path="/workspace/output.json")
        assert out.required_fields == []

    def test_required_fields_set(self) -> None:
        out = TaskOutput(
            path="/workspace/output.json",
            required_fields=["output_dir", "features"],
        )
        assert out.required_fields == ["output_dir", "features"]


class TestTaskDefinition:
    def test_valid_complete_definition(self) -> None:
        td = TaskDefinition(
            name="plan",
            description="Plan the feature",
            commit=False,
            push=False,
            model="claude-opus-4-6",
            max_turns=50,
            timeout_minutes=15,
            max_budget_usd=2.0,
            inputs=[TaskInput(name="prd", type="file", src="/a", dest="/b")],
            outputs=[TaskOutput(path="/workspace/plan.md")],
            instructions="Do the thing",
            prompt="Go implement",
        )
        assert td.name == "plan"
        assert td.model == "claude-opus-4-6"
        assert len(td.inputs) == 1
        assert len(td.outputs) == 1

    def test_valid_minimal_definition(self) -> None:
        td = TaskDefinition(name="task1", instructions="Do stuff", prompt="Go")
        assert td.name == "task1"
        assert td.description == ""
        assert td.commit is True
        assert td.push is True

    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            TaskDefinition(instructions="x", prompt="y")  # type: ignore[call-arg]

    def test_both_prompt_and_prompt_file_raises(self) -> None:
        with pytest.raises(ValidationError, match="got both"):
            TaskDefinition(name="t", instructions="x", prompt="a", prompt_file="b.md")

    def test_neither_prompt_nor_prompt_file_allowed(self) -> None:
        td = TaskDefinition(name="t", instructions="x")
        assert td.prompt is None
        assert td.prompt_file is None

    def test_both_instructions_and_instructions_file_raises(self) -> None:
        with pytest.raises(ValidationError, match="got both"):
            TaskDefinition(
                name="t",
                instructions="x",
                instructions_file="y.md",
                prompt="go",
            )

    def test_neither_instructions_nor_instructions_file_allowed(self) -> None:
        td = TaskDefinition(name="t", prompt="go")
        assert td.instructions is None
        assert td.instructions_file is None

    def test_execution_fields_default_to_none(self) -> None:
        td = TaskDefinition(name="t", instructions="x", prompt="go")
        assert td.model is None
        assert td.max_turns is None
        assert td.timeout_minutes is None
        assert td.max_budget_usd is None

    def test_commit_defaults_to_true(self) -> None:
        td = TaskDefinition(name="t", instructions="x", prompt="go")
        assert td.commit is True
        assert td.push is True

    def test_empty_inputs_outputs_accepted(self) -> None:
        td = TaskDefinition(name="t", instructions="x", prompt="go")
        assert td.inputs == []
        assert td.outputs == []

    def test_json_round_trip(self) -> None:
        td = TaskDefinition(
            name="t",
            instructions="do it",
            prompt="go",
            model="claude-opus-4-6",
        )
        data = json.loads(td.model_dump_json())
        restored = TaskDefinition.model_validate(data)
        assert restored.name == td.name
        assert restored.model == td.model

    def test_prompt_file_without_prompt_is_valid(self) -> None:
        td = TaskDefinition(name="t", instructions="x", prompt_file="prompt.md")
        assert td.prompt is None
        assert td.prompt_file == "prompt.md"

    def test_instructions_file_without_instructions_is_valid(self) -> None:
        td = TaskDefinition(name="t", instructions_file="inst.md", prompt="go")
        assert td.instructions is None
        assert td.instructions_file == "inst.md"


class TestTaskResult:
    def test_completed_status(self) -> None:
        r = TaskResult(task_name="plan", status="completed")
        assert r.status == "completed"

    def test_failed_status(self) -> None:
        r = TaskResult(task_name="plan", status="failed", error_message="boom")
        assert r.error_message == "boom"

    def test_timed_out_status(self) -> None:
        r = TaskResult(task_name="plan", status="timed_out")
        assert r.status == "timed_out"

    def test_skipped_status(self) -> None:
        r = TaskResult(task_name="plan", status="skipped")
        assert r.status == "skipped"

    def test_defaults(self) -> None:
        r = TaskResult(task_name="t", status="completed")
        assert r.total_cost_usd == 0.0
        assert r.duration_seconds == 0.0
        assert r.num_turns == 0
        assert r.session_id == ""
        assert r.error_message == ""
        assert r.outputs == {}

    def test_outputs_dict(self) -> None:
        r = TaskResult(
            task_name="t",
            status="completed",
            outputs={"/out/plan.md": "# Plan\nDone"},
        )
        assert "/out/plan.md" in r.outputs

    def test_invalid_status_raises(self) -> None:
        with pytest.raises(ValidationError):
            TaskResult(task_name="t", status="bad")  # type: ignore[arg-type]


class TestComponentResult:
    def test_json_round_trip(self) -> None:
        cr = ComponentResult(
            run_id="abc",
            component="dev",
            status="completed",
            repo="https://github.com/test/repo",
            branch="main",
            feature_name="auth",
            total_cost_usd=1.5,
            duration_seconds=300.0,
            task_results=[
                TaskResult(task_name="plan", status="completed", total_cost_usd=0.5),
                TaskResult(task_name="impl", status="completed", total_cost_usd=1.0),
            ],
        )
        data = json.loads(cr.model_dump_json())
        restored = ComponentResult.model_validate(data)
        assert restored.run_id == "abc"
        assert len(restored.task_results) == 2

    def test_task_results_list(self) -> None:
        cr = ComponentResult(
            run_id="x",
            component="qa",
            status="failed",
            repo="r",
            branch="b",
            feature_name="f",
            total_cost_usd=0.0,
            duration_seconds=0.0,
            task_results=[],
            error_message="oops",
        )
        assert cr.error_message == "oops"
        assert cr.task_results == []

    def test_status_values(self) -> None:
        for status in ("completed", "failed", "timed_out"):
            cr = ComponentResult(
                run_id="x",
                component="c",
                status=status,  # type: ignore[arg-type]
                repo="r",
                branch="b",
                feature_name="f",
                total_cost_usd=0.0,
                duration_seconds=0.0,
                task_results=[],
            )
            assert cr.status == status

    def test_invalid_status_raises(self) -> None:
        with pytest.raises(ValidationError):
            ComponentResult(
                run_id="x",
                component="c",
                status="bad",  # type: ignore[arg-type]
                repo="r",
                branch="b",
                feature_name="f",
                total_cost_usd=0.0,
                duration_seconds=0.0,
                task_results=[],
            )
