from __future__ import annotations

import json

from dkmv.tasks.component import ComponentRunner
from dkmv.tasks.pause import PauseQuestion, PauseRequest, PauseResponse


class TestPauseModels:
    def test_pause_question_minimal(self) -> None:
        q = PauseQuestion(id="q1", question="Which framework?")
        assert q.id == "q1"
        assert q.options == []
        assert q.default is None

    def test_pause_question_with_options(self) -> None:
        q = PauseQuestion(
            id="q1",
            question="Which framework?",
            options=[
                {"value": "fastapi", "label": "FastAPI", "description": "Modern async"},
                {"value": "flask", "label": "Flask", "description": "Simple and mature"},
            ],
            default="fastapi",
        )
        assert len(q.options) == 2
        assert q.default == "fastapi"

    def test_pause_request_minimal(self) -> None:
        req = PauseRequest(task_name="analyze", questions=[])
        assert req.task_name == "analyze"
        assert req.questions == []
        assert req.context == {}

    def test_pause_request_with_context(self) -> None:
        req = PauseRequest(
            task_name="analyze",
            questions=[PauseQuestion(id="q1", question="Pick one")],
            context={"analysis.json": '{"features": []}'},
        )
        assert len(req.questions) == 1
        assert "analysis.json" in req.context

    def test_pause_response(self) -> None:
        resp = PauseResponse(answers={"q1": "fastapi", "q2": "postgres"})
        assert resp.answers["q1"] == "fastapi"
        assert len(resp.answers) == 2

    def test_pause_response_skip_remaining_defaults_false(self) -> None:
        resp = PauseResponse(answers={"q1": "a"})
        assert resp.skip_remaining is False

    def test_pause_response_skip_remaining_true(self) -> None:
        resp = PauseResponse(answers={"action": "ship"}, skip_remaining=True)
        assert resp.skip_remaining is True
        assert resp.answers["action"] == "ship"


class TestBuildPauseRequest:
    def test_extracts_questions_from_json_output(self) -> None:
        output_content = json.dumps(
            {
                "features": [],
                "questions": [
                    {
                        "id": "q1",
                        "question": "Which DB?",
                        "options": [
                            {"value": "pg", "label": "PostgreSQL", "description": "Relational"},
                            {"value": "mongo", "label": "MongoDB", "description": "Document"},
                        ],
                        "default": "pg",
                    }
                ],
            }
        )
        result = ComponentRunner._build_pause_request("analyze", {"analysis.json": output_content})
        assert len(result.questions) == 1
        assert result.questions[0].id == "q1"
        assert result.questions[0].default == "pg"
        assert len(result.questions[0].options) == 2

    def test_returns_empty_questions_for_no_questions_field(self) -> None:
        output_content = json.dumps({"features": [], "constraints": []})
        result = ComponentRunner._build_pause_request("analyze", {"analysis.json": output_content})
        assert result.questions == []

    def test_returns_empty_questions_for_non_json_output(self) -> None:
        result = ComponentRunner._build_pause_request("analyze", {"output.txt": "plain text"})
        assert result.questions == []

    def test_skips_malformed_questions(self) -> None:
        output_content = json.dumps(
            {
                "questions": [
                    {"id": "q1", "question": "Good question"},
                    {"id": "q2"},  # missing question text
                    {"question": "No ID"},  # missing id
                    "not a dict",
                ]
            }
        )
        result = ComponentRunner._build_pause_request("analyze", {"out.json": output_content})
        assert len(result.questions) == 1
        assert result.questions[0].id == "q1"

    def test_truncates_context_to_2000_chars(self) -> None:
        long_content = json.dumps({"data": "x" * 3000})
        result = ComponentRunner._build_pause_request("analyze", {"big.json": long_content})
        assert len(result.context["big.json"]) == 2000

    def test_handles_multiple_outputs(self) -> None:
        out1 = json.dumps({"questions": [{"id": "q1", "question": "From file 1"}]})
        out2 = json.dumps({"questions": [{"id": "q2", "question": "From file 2"}]})
        result = ComponentRunner._build_pause_request("analyze", {"a.json": out1, "b.json": out2})
        assert len(result.questions) == 2
        ids = {q.id for q in result.questions}
        assert ids == {"q1", "q2"}

    def test_skips_options_with_missing_value_or_label(self) -> None:
        output_content = json.dumps(
            {
                "questions": [
                    {
                        "id": "q1",
                        "question": "Pick",
                        "options": [
                            {"value": "a", "label": "A"},
                            {"label": "B"},  # missing value
                            {"value": "c"},  # missing label
                        ],
                    }
                ]
            }
        )
        result = ComponentRunner._build_pause_request("analyze", {"out.json": output_content})
        assert len(result.questions[0].options) == 1
        assert result.questions[0].options[0]["value"] == "a"

    def test_empty_outputs_dict(self) -> None:
        result = ComponentRunner._build_pause_request("analyze", {})
        assert result.questions == []
        assert result.context == {}

    def test_task_name_propagated(self) -> None:
        result = ComponentRunner._build_pause_request("my-task", {})
        assert result.task_name == "my-task"
