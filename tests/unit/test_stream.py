from __future__ import annotations

import json
from io import StringIO

from rich.console import Console

from dkmv.core.stream import StreamEvent, StreamParser


def _make_console() -> tuple[Console, StringIO]:
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=120)
    return console, buf


class TestParseLine:
    def setup_method(self) -> None:
        self.parser = StreamParser()

    def test_parse_system_event(self) -> None:
        line = json.dumps({"type": "system", "session_id": "s1", "message": "init"})
        event = self.parser.parse_line(line)
        assert event is not None
        assert event.type == "system"
        assert event.session_id == "s1"

    def test_parse_assistant_text(self) -> None:
        line = json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Hello world"}]},
            }
        )
        event = self.parser.parse_line(line)
        assert event is not None
        assert event.type == "assistant"
        assert event.subtype == "text"
        assert event.content == "Hello world"

    def test_parse_assistant_tool_use(self) -> None:
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "ls -la"},
                        }
                    ]
                },
            }
        )
        event = self.parser.parse_line(line)
        assert event is not None
        assert event.type == "assistant"
        assert event.subtype == "tool_use"
        assert event.tool_name == "Bash"
        assert "ls -la" in event.tool_input

    def test_parse_user_tool_result(self) -> None:
        line = json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "content": "output text",
                            "is_error": False,
                        }
                    ]
                },
            }
        )
        event = self.parser.parse_line(line)
        assert event is not None
        assert event.type == "user"
        assert event.subtype == "tool_result"
        assert event.content == "output text"
        assert event.is_error is False

    def test_parse_user_tool_result_error(self) -> None:
        line = json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "content": "error occurred",
                            "is_error": True,
                        }
                    ]
                },
            }
        )
        event = self.parser.parse_line(line)
        assert event is not None
        assert event.is_error is True

    def test_parse_user_tool_result_list_content(self) -> None:
        line = json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "content": [{"text": "part1"}, {"text": "part2"}],
                        }
                    ]
                },
            }
        )
        event = self.parser.parse_line(line)
        assert event is not None
        assert "part1" in event.content
        assert "part2" in event.content

    def test_parse_result_event(self) -> None:
        line = json.dumps(
            {
                "type": "result",
                "total_cost_usd": 0.123,
                "duration_ms": 45000,
                "num_turns": 7,
                "session_id": "sess-abc",
                "is_error": False,
                "result": "All done",
            }
        )
        event = self.parser.parse_line(line)
        assert event is not None
        assert event.type == "result"
        assert event.total_cost_usd == 0.123
        assert event.duration_ms == 45000
        assert event.num_turns == 7
        assert event.session_id == "sess-abc"
        assert event.content == "All done"

    def test_parse_malformed_json(self) -> None:
        event = self.parser.parse_line("not valid json{{{")
        assert event is None

    def test_parse_empty_line(self) -> None:
        assert self.parser.parse_line("") is None
        assert self.parser.parse_line("   ") is None

    def test_parse_unknown_type(self) -> None:
        line = json.dumps({"type": "unknown_event", "data": 42})
        event = self.parser.parse_line(line)
        assert event is not None
        assert event.type == "unknown_event"

    def test_assistant_multi_text_blocks(self) -> None:
        """M4: All text blocks should be concatenated, not just the first."""
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "Part 1"},
                        {"type": "text", "text": "Part 2"},
                    ]
                },
            }
        )
        event = self.parser.parse_line(line)
        assert event is not None
        assert event.subtype == "text"
        assert "Part 1" in event.content
        assert "Part 2" in event.content

    def test_system_event_extracts_subtype(self) -> None:
        """ST-1: System events should extract the subtype field."""
        line = json.dumps(
            {"type": "system", "subtype": "init", "session_id": "s1", "message": "started"}
        )
        event = self.parser.parse_line(line)
        assert event is not None
        assert event.type == "system"
        assert event.subtype == "init"

    def test_result_event_extracts_subtype(self) -> None:
        """ST-2: Result events should extract the subtype field."""
        line = json.dumps(
            {
                "type": "result",
                "subtype": "error_max_turns",
                "total_cost_usd": 0.5,
                "is_error": True,
                "result": "Max turns reached",
            }
        )
        event = self.parser.parse_line(line)
        assert event is not None
        assert event.type == "result"
        assert event.subtype == "error_max_turns"
        assert event.is_error is True

    def test_assistant_text_and_tool_returns_text(self) -> None:
        """When both text and tool_use blocks exist, text takes priority."""
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "Explanation"},
                        {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                    ]
                },
            }
        )
        event = self.parser.parse_line(line)
        assert event is not None
        assert event.subtype == "text"
        assert event.content == "Explanation"


class TestRenderEvent:
    def test_render_system_event(self) -> None:
        console, buf = _make_console()
        parser = StreamParser(console=console)
        event = StreamEvent(type="system", session_id="s1")
        parser.render_event(event)
        output = buf.getvalue()
        assert "session" in output

    def test_render_assistant_text(self) -> None:
        console, buf = _make_console()
        parser = StreamParser(console=console)
        event = StreamEvent(type="assistant", subtype="text", content="Hello world")
        parser.render_event(event)
        assert "Hello world" in buf.getvalue()

    def test_render_tool_use_bash(self) -> None:
        console, buf = _make_console()
        parser = StreamParser(console=console)
        event = StreamEvent(
            type="assistant",
            subtype="tool_use",
            tool_name="Bash",
            tool_input=json.dumps({"command": "ls -la"}),
        )
        parser.render_event(event)
        output = buf.getvalue()
        assert "$ ls -la" in output

    def test_render_tool_use_other(self) -> None:
        console, buf = _make_console()
        parser = StreamParser(console=console)
        event = StreamEvent(
            type="assistant",
            subtype="tool_use",
            tool_name="Read",
            tool_input="{}",
        )
        parser.render_event(event)
        assert "[tool: Read]" in buf.getvalue()

    def test_render_user_truncated(self) -> None:
        console, buf = _make_console()
        parser = StreamParser(console=console)
        long_content = "x" * 600
        event = StreamEvent(type="user", content=long_content)
        parser.render_event(event)
        output = buf.getvalue()
        assert "..." in output

    def test_render_result_success(self) -> None:
        console, buf = _make_console()
        parser = StreamParser(console=console)
        event = StreamEvent(
            type="result",
            total_cost_usd=0.05,
            duration_ms=5000,
            num_turns=3,
        )
        parser.render_event(event)
        output = buf.getvalue()
        assert "3 turns" in output
        assert "$0.0500" in output

    def test_render_result_error(self) -> None:
        console, buf = _make_console()
        parser = StreamParser(console=console)
        event = StreamEvent(
            type="result",
            is_error=True,
            content="Something failed",
        )
        parser.render_event(event)
        output = buf.getvalue()
        assert "Error" in output
        assert "Something failed" in output

    def test_verbose_mode_prints_raw_json(self) -> None:
        console, buf = _make_console()
        parser = StreamParser(console=console, verbose=True)
        event = StreamEvent(
            type="system",
            session_id="s1",
            raw={"type": "system", "session_id": "s1"},
        )
        parser.render_event(event)
        output = buf.getvalue()
        assert "session_id" in output
