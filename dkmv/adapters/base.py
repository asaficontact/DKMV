from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from dkmv.core.stream import StreamEvent


@dataclass
class StreamResult:
    cost: float = 0.0
    turns: int = 0
    session_id: str = ""


@runtime_checkable
class AgentAdapter(Protocol):
    @property
    def name(self) -> str: ...

    def build_command(
        self,
        prompt_file: str,
        model: str,
        max_turns: int,
        timeout_minutes: int,
        max_budget_usd: float | None = None,
        env_vars: dict[str, str] | None = None,
        resume_session_id: str | None = None,
        working_dir: str = "/home/dkmv/workspace",
    ) -> str: ...

    def parse_event(self, raw: dict[str, Any]) -> StreamEvent | None: ...
    def is_result_event(self, raw: dict[str, Any]) -> bool: ...
    def extract_result(self, raw: dict[str, Any]) -> StreamResult: ...

    @property
    def instructions_path(self) -> str: ...

    @property
    def prepend_instructions(self) -> bool: ...

    @property
    def gitignore_entries(self) -> list[str]: ...

    def get_auth_config(self, config: Any) -> tuple[dict[str, str], list[str], Path | None]: ...
    def get_env_overrides(self) -> dict[str, str]: ...

    def supports_resume(self) -> bool: ...
    def supports_budget(self) -> bool: ...
    def supports_max_turns(self) -> bool: ...

    @property
    def default_model(self) -> str: ...

    def validate_model(self, model: str) -> bool: ...
