from __future__ import annotations

from pydantic import BaseModel


class PauseQuestion(BaseModel):
    id: str
    question: str
    options: list[dict[str, str]] = []
    default: str | None = None


class PauseRequest(BaseModel):
    task_name: str
    questions: list[PauseQuestion]
    context: dict[str, str] = {}


class PauseResponse(BaseModel):
    answers: dict[str, str]
    skip_remaining: bool = False
