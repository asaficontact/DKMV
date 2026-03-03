from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, model_validator

AGENT_DIR_PREFIX = "/home/dkmv/workspace/.agent/"


def _normalize_dest(dest: str | None) -> str | None:
    """Prepend the standard .agent/ prefix to relative dest paths."""
    if dest is None or dest.startswith("/"):
        return dest
    return f"{AGENT_DIR_PREFIX}{dest}"


class ManifestInput(BaseModel):
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


class ManifestStateFile(BaseModel):
    dest: str
    content: str


class ManifestDeliverable(BaseModel):
    path: str
    required: bool = True


class ManifestTaskRef(BaseModel):
    file: str
    model: str | None = None
    max_turns: int | None = None
    timeout_minutes: int | None = None
    max_budget_usd: float | None = None
    pause_after: bool = False
    for_each: str | None = None


class ComponentManifest(BaseModel):
    name: str
    description: str = ""
    inputs: list[ManifestInput] = []
    workspace_dirs: list[str] = []
    state_files: list[ManifestStateFile] = []
    agent_md: str | None = None
    agent_md_file: str | None = None
    model: str | None = None
    max_turns: int | None = None
    timeout_minutes: int | None = None
    max_budget_usd: float | None = None
    tasks: list[ManifestTaskRef] = []
    deliverables: list[ManifestDeliverable] = []
