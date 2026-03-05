from __future__ import annotations

import json
import shlex
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dkmv.adapters.base import StreamResult
from dkmv.core.stream import StreamEvent

if TYPE_CHECKING:
    from dkmv.config import DKMVConfig


class ClaudeCodeAdapter:
    @property
    def name(self) -> str:
        return "claude"

    @property
    def display_name(self) -> str:
        return "Claude Code"

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
        budget_flag = (
            f" --max-budget-usd {shlex.quote(str(max_budget_usd))}"
            if max_budget_usd is not None
            else ""
        )
        env_prefix = ""
        if env_vars:
            pairs = " ".join(f"{k}={shlex.quote(v)}" for k, v in env_vars.items())
            env_prefix = f"env {pairs} "

        if resume_session_id:
            claude_cmd = (
                f"{env_prefix}claude "
                f"--resume {shlex.quote(resume_session_id)} "
                f'-p "$(cat {prompt_file})" '
            )
        else:
            claude_cmd = f'{env_prefix}claude -p "$(cat {prompt_file})" '

        return (
            f"cd {shlex.quote(working_dir)} && "
            f"{claude_cmd}"
            "--dangerously-skip-permissions "
            "--verbose "
            "--output-format stream-json "
            f"--model {shlex.quote(model)} "
            f"--max-turns {shlex.quote(str(max_turns))}"
            f"{budget_flag}"
            " < /dev/null > /tmp/dkmv_stream.jsonl 2>/tmp/dkmv_stream.err & echo $!"
        )

    def parse_event(self, raw: dict[str, Any]) -> StreamEvent | None:
        return self._parse_claude_event(raw)

    def _parse_claude_event(self, data: dict[str, Any]) -> StreamEvent | None:
        event_type = data.get("type", "")

        if event_type == "system":
            return StreamEvent(
                type="system",
                subtype=data.get("subtype", ""),
                session_id=data.get("session_id", ""),
                content=data.get("message", ""),
                raw=data,
            )

        if event_type == "assistant":
            message = data.get("message", {})
            content_blocks = message.get("content", [])

            text_parts: list[str] = []
            last_tool: StreamEvent | None = None

            for block in content_blocks:
                block_type = block.get("type", "")
                if block_type == "text":
                    text_parts.append(block.get("text", ""))
                elif block_type == "tool_use":
                    last_tool = StreamEvent(
                        type="assistant",
                        subtype="tool_use",
                        tool_name=block.get("name", ""),
                        tool_input=json.dumps(block.get("input", {})),
                        raw=data,
                    )

            if text_parts:
                return StreamEvent(
                    type="assistant",
                    subtype="text",
                    content="\n".join(text_parts),
                    raw=data,
                )
            if last_tool:
                return last_tool

            return StreamEvent(type="assistant", raw=data)

        if event_type == "user":
            message = data.get("message", {})
            content_blocks = message.get("content", [])

            for block in content_blocks:
                if block.get("type") == "tool_result":
                    content = block.get("content", "")
                    if isinstance(content, list):
                        content = " ".join(
                            item.get("text", "") for item in content if isinstance(item, dict)
                        )
                    return StreamEvent(
                        type="user",
                        subtype="tool_result",
                        content=str(content),
                        is_error=block.get("is_error", False),
                        raw=data,
                    )

            return StreamEvent(type="user", raw=data)

        if event_type == "result":
            return StreamEvent(
                type="result",
                subtype=data.get("subtype", ""),
                total_cost_usd=data.get("total_cost_usd", 0.0),
                duration_ms=data.get("duration_ms", 0.0),
                num_turns=data.get("num_turns", 0),
                session_id=data.get("session_id", ""),
                is_error=data.get("is_error", False),
                content=str(data.get("result", "")),
                raw=data,
            )

        return StreamEvent(type=event_type, raw=data)

    def is_result_event(self, raw: dict[str, Any]) -> bool:
        return raw.get("type") == "result"

    def extract_result(self, raw: dict[str, Any]) -> StreamResult:
        return StreamResult(
            cost=raw.get("total_cost_usd", 0.0),
            turns=raw.get("num_turns", 0),
            session_id=raw.get("session_id", ""),
        )

    @property
    def instructions_path(self) -> str:
        return ".claude/CLAUDE.md"

    @property
    def prepend_instructions(self) -> bool:
        return False

    @property
    def gitignore_entries(self) -> list[str]:
        return [".claude/"]

    def get_auth_env_vars(self, config: DKMVConfig) -> dict[str, str]:
        if config.auth_method == "oauth":
            if config.claude_oauth_token:
                return {"CLAUDE_CODE_OAUTH_TOKEN": config.claude_oauth_token}
            return {}
        return {"ANTHROPIC_API_KEY": config.anthropic_api_key}

    def get_docker_args(self, config: DKMVConfig) -> tuple[list[str], Path | None]:
        if config.auth_method != "oauth":
            return ([], None)

        from dkmv.config import _fetch_oauth_credentials

        creds_json = _fetch_oauth_credentials()
        host_creds_path = Path.home() / ".claude" / ".credentials.json"

        if creds_json:
            # macOS: write Keychain credentials to a temp file and bind-mount it
            tf = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", prefix="dkmv-creds-", delete=False
            )
            tf.write(creds_json)
            tf.close()
            temp_creds_file = Path(tf.name)
            docker_args = [
                "-v",
                f"{temp_creds_file}:/home/dkmv/.claude/.credentials.json:ro",
            ]
            return (docker_args, temp_creds_file)
        elif host_creds_path.exists():
            # Linux: bind-mount the credentials file directly
            docker_args = [
                "-v",
                f"{host_creds_path}:/home/dkmv/.claude/.credentials.json:ro",
            ]
            return (docker_args, None)
        else:
            return ([], None)

    def get_env_overrides(self) -> dict[str, str]:
        return {}

    def supports_resume(self) -> bool:
        return True

    def supports_budget(self) -> bool:
        return True

    def supports_max_turns(self) -> bool:
        return True

    @property
    def default_model(self) -> str:
        return "claude-sonnet-4-6"

    def validate_model(self, model: str) -> bool:
        return model.startswith("claude-")
