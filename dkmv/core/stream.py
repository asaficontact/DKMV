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

        # Default to Claude adapter when no adapter is set
        from dkmv.adapters.claude import ClaudeCodeAdapter

        return ClaudeCodeAdapter().parse_event(data)

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
