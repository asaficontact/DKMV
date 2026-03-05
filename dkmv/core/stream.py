from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.text import Text

if TYPE_CHECKING:
    from dkmv.adapters.base import AgentAdapter

logger = logging.getLogger(__name__)


@dataclass
class StreamEvent:
    type: str = ""
    subtype: str = ""
    content: str = ""
    tool_name: str = ""
    tool_input: str = ""
    total_cost_usd: float = 0.0
    duration_ms: float = 0.0
    num_turns: int = 0
    session_id: str = ""
    is_error: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


class StreamParser:
    def __init__(
        self,
        console: Console | None = None,
        verbose: bool = False,
        adapter: AgentAdapter | None = None,
    ) -> None:
        self.console = console or Console()
        self.verbose = verbose
        self._adapter = adapter

    def parse_line(self, line: str) -> StreamEvent | None:
        line = line.strip()
        if not line:
            return None

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Failed to parse stream line: %s", line[:200])
            return None

        if self._adapter is not None:
            return self._adapter.parse_event(data)

        return self._parse_claude_event(data)

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

    def render_event(self, event: StreamEvent) -> None:
        if self.verbose:
            self.console.print_json(json.dumps(event.raw))
            return

        if event.type == "system":
            text = Text(f"[session: {event.session_id}]", style="dim")
            self.console.print(text)

        elif event.type == "assistant":
            if event.subtype == "text":
                self.console.print(event.content)
            elif event.subtype == "tool_use":
                if event.tool_name.lower() in ("bash", "execute"):
                    try:
                        input_data = json.loads(event.tool_input)
                        cmd = input_data.get("command", event.tool_input)
                    except json.JSONDecodeError:
                        cmd = event.tool_input
                    self.console.print(Text(f"$ {cmd}", style="cyan"))
                else:
                    self.console.print(Text(f"[tool: {event.tool_name}]", style="cyan"))

        elif event.type == "user":
            content = event.content
            if len(content) > 500:
                content = content[:500] + "..."
            text = Text(content, style="dim")
            self.console.print(text)

        elif event.type == "result":
            if event.is_error:
                self.console.print(Text(f"Error: {event.content}", style="red bold"))
            else:
                cost = f"${event.total_cost_usd:.4f}"
                duration = f"{event.duration_ms / 1000:.1f}s"
                self.console.print(
                    Text(
                        f"Done: {event.num_turns} turns, {cost}, {duration}",
                        style="green bold",
                    )
                )
