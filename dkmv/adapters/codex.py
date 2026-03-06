from __future__ import annotations

import re
import shlex
from typing import TYPE_CHECKING, Any
from pathlib import Path

from dkmv.adapters.base import StreamResult
from dkmv.core.stream import StreamEvent

if TYPE_CHECKING:
    from dkmv.config import DKMVConfig

_CODEX_RESULT_EVENTS = {"thread.closed", "error", "turn.failed"}


class CodexCLIAdapter:
    def __init__(self) -> None:
        self._turn_count: int = 0
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._session_id: str = ""

    @property
    def name(self) -> str:
        return "codex"

    @property
    def display_name(self) -> str:
        return "Codex"

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
    ) -> str:
        env_prefix = ""
        if env_vars:
            pairs = " ".join(f"{k}={shlex.quote(v)}" for k, v in env_vars.items())
            env_prefix = f"env {pairs} "

        if resume_session_id:
            exec_part = f"codex exec resume {resume_session_id}"
        else:
            exec_part = "codex exec"

        cmd = (
            f"cd {working_dir} && "
            f"{env_prefix}{exec_part} "
            "--json "
            "--full-auto "
            "--sandbox danger-full-access "
            "--skip-git-repo-check "
            f"-m {model} "
            f'"$(cat {prompt_file})"'
            " < /dev/null > /tmp/dkmv_stream.jsonl 2>/tmp/dkmv_stream.err & echo $!"
        )
        return cmd

    def _parse_item_event(self, raw: dict[str, Any]) -> StreamEvent | None:
        item = raw.get("item", {})
        item_type = item.get("type", "")
        event_type = raw.get("type", "")

        if item_type == "agent_message":
            if event_type == "item.completed":
                return StreamEvent(
                    type="assistant",
                    subtype="text",
                    content=item.get("text", ""),
                    raw=raw,
                )
            return None

        if item_type == "command_execution":
            if event_type == "item.started":
                return StreamEvent(
                    type="assistant",
                    subtype="tool_use",
                    tool_name="shell",
                    tool_input=item.get("command", ""),
                    raw=raw,
                )
            if event_type == "item.completed":
                return StreamEvent(
                    type="user",
                    subtype="tool_result",
                    content=item.get("aggregated_output", ""),
                    raw=raw,
                )
            return None

        if item_type == "file_change":
            if event_type == "item.completed":
                return StreamEvent(
                    type="assistant",
                    subtype="tool_use",
                    tool_name="edit_file",
                    tool_input=item.get("path", ""),
                    raw=raw,
                )
            return None

        if item_type in ("reasoning", "plan"):
            if event_type == "item.completed":
                return StreamEvent(
                    type="assistant",
                    subtype="text",
                    content=item.get("content", item.get("text", "")),
                    raw=raw,
                )
            return None

        # Generic fallback
        return StreamEvent(type=f"item.{item_type}", raw=raw)

    def parse_event(self, raw: dict[str, Any]) -> StreamEvent | None:
        event_type = raw.get("type", "")

        if event_type == "thread.started":
            self._session_id = raw.get("thread_id", "")
            return StreamEvent(type="system", session_id=self._session_id, raw=raw)

        if event_type == "turn.started":
            return None

        if event_type == "turn.completed":
            self._turn_count += 1
            usage = raw.get("usage", {})
            self._total_input_tokens += usage.get("input_tokens", 0)
            self._total_output_tokens += usage.get("output_tokens", 0)
            return None

        if event_type in ("item.started", "item.completed"):
            return self._parse_item_event(raw)

        if event_type == "turn.failed":
            error_msg = raw.get("error", "Turn failed")
            return StreamEvent(type="result", is_error=True, content=str(error_msg), raw=raw)

        if event_type == "thread.closed":
            return StreamEvent(
                type="result",
                total_cost_usd=0.0,
                num_turns=self._turn_count,
                session_id=self._session_id,
                raw=raw,
            )

        if event_type == "error":
            return StreamEvent(
                type="result",
                is_error=True,
                content=raw.get("message", "Unknown error"),
                raw=raw,
            )

        # Unknown event type — return with raw data
        return StreamEvent(type=event_type, raw=raw)

    def is_result_event(self, raw: dict[str, Any]) -> bool:
        return raw.get("type", "") in _CODEX_RESULT_EVENTS

    def extract_result(self, raw: dict[str, Any]) -> StreamResult:
        return StreamResult(
            cost=0.0,
            turns=self._turn_count,
            session_id=self._session_id,
        )

    @property
    def instructions_path(self) -> str:
        return "AGENTS.md"

    @property
    def prepend_instructions(self) -> bool:
        return True

    @property
    def gitignore_entries(self) -> list[str]:
        return [".codex/"]

    def get_auth_config(self, config: DKMVConfig) -> tuple[dict[str, str], list[str], Path | None]:
        env_vars: dict[str, str] = {}
        key = config.codex_api_key
        if key:
            env_vars["CODEX_API_KEY"] = key
        return (env_vars, [], None)

    def get_env_overrides(self) -> dict[str, str]:
        return {}

    def supports_resume(self) -> bool:
        return True

    def supports_budget(self) -> bool:
        return False

    def supports_max_turns(self) -> bool:
        return False

    @property
    def default_model(self) -> str:
        return "gpt-5.3-codex"

    def validate_model(self, model: str) -> bool:
        if model.startswith("gpt-"):
            return True
        if re.match(r"^o\d", model):
            return True
        return False
