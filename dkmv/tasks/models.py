from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, model_validator

from dkmv.tasks.manifest import _normalize_dest


class TaskInput(BaseModel):
    name: str
    type: Literal["file", "text", "env"]
    src: str | None = None
    dest: str | None = None
    content: str | None = None
    key: str | None = None
    value: str | None = None
    optional: bool = False

    @model_validator(mode="after")
    def validate_type_fields(self) -> Self:
        if self.optional:
            return self
        match self.type:
            case "file":
                if not self.src:
                    raise ValueError("'file' input requires 'src'")
                if not self.dest:
                    raise ValueError("'file' input requires 'dest'")
            case "text":
                if not self.content:
                    raise ValueError("'text' input requires 'content'")
                if not self.dest:
                    raise ValueError("'text' input requires 'dest'")
            case "env":
                if not self.key:
                    raise ValueError("'env' input requires 'key'")
                if not self.value:
                    raise ValueError("'env' input requires 'value'")
        return self

    @model_validator(mode="after")
    def normalize_dest(self) -> Self:
        self.dest = _normalize_dest(self.dest)
        return self


class TaskOutput(BaseModel):
    path: str
    required: bool = False
    save: bool = True
    required_fields: list[str] = []

    @model_validator(mode="after")
    def normalize_path(self) -> Self:
        self.path = _normalize_dest(self.path) or self.path
        return self


class TaskDefinition(BaseModel):
    name: str
    description: str = ""
    commit: bool = True
    push: bool = True

    agent: str | None = None
    model: str | None = None
    max_turns: int | None = None
    timeout_minutes: int | None = None
    max_budget_usd: float | None = None

    inputs: list[TaskInput] = []
    outputs: list[TaskOutput] = []

    instructions: str | None = None
    instructions_file: str | None = None

    prompt: str | None = None
    prompt_file: str | None = None

    @model_validator(mode="after")
    def validate_instructions_xor(self) -> Self:
        has_instructions = self.instructions is not None
        has_file = self.instructions_file is not None
        if has_instructions and has_file:
            raise ValueError(
                "Exactly one of 'instructions' or 'instructions_file' must be set, got both"
            )
        return self

    @model_validator(mode="after")
    def validate_prompt_xor(self) -> Self:
        has_prompt = self.prompt is not None
        has_file = self.prompt_file is not None
        if has_prompt and has_file:
            raise ValueError("Exactly one of 'prompt' or 'prompt_file' must be set, got both")
        return self


class TaskResult(BaseModel):
    task_name: str
    description: str = ""
    status: Literal["completed", "failed", "timed_out", "skipped", "pre-existing"]
    total_cost_usd: float = 0.0
    duration_seconds: float = 0.0
    num_turns: int = 0
    session_id: str = ""
    error_message: str = ""
    outputs: dict[str, str] = {}


class ComponentResult(BaseModel):
    run_id: str
    component: str
    status: Literal["completed", "failed", "timed_out"]
    repo: str
    branch: str
    feature_name: str
    total_cost_usd: float
    duration_seconds: float
    task_results: list[TaskResult]
    error_message: str = ""


@dataclass
class CLIOverrides:
    model: str | None = None
    max_turns: int | None = None
    timeout_minutes: int | None = None
    max_budget_usd: float | None = None
    agent: str | None = None
