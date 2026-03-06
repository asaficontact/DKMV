"""Tests for CodexCLIAdapter."""

from __future__ import annotations

from dkmv.adapters.codex import CodexCLIAdapter


# ---------------------------------------------------------------------------
# build_command tests
# ---------------------------------------------------------------------------


def test_build_command_basic():
    adapter = CodexCLIAdapter()
    cmd = adapter.build_command("/tmp/p.md", "gpt-5.3-codex", 100, 30)
    assert "codex exec" in cmd
    assert "--json" in cmd
    assert "--full-auto" in cmd
    assert "--sandbox danger-full-access" in cmd
    assert "--skip-git-repo-check" in cmd
    assert "-m gpt-5.3-codex" in cmd
    assert "$(cat /tmp/p.md)" in cmd
    assert "/tmp/dkmv_stream.jsonl" in cmd
    assert "/tmp/dkmv_stream.err" in cmd
    assert "echo $!" in cmd


def test_build_command_no_yolo_no_ephemeral():
    adapter = CodexCLIAdapter()
    cmd = adapter.build_command("/tmp/p.md", "gpt-5.3-codex", 100, 30)
    assert "--yolo" not in cmd
    assert "--ephemeral" not in cmd


def test_build_command_resume():
    adapter = CodexCLIAdapter()
    cmd = adapter.build_command("/tmp/p.md", "gpt-5.3-codex", 100, 30, resume_session_id="sess-123")
    assert "codex exec resume sess-123" in cmd
    assert "--json" in cmd
    assert "--full-auto" in cmd


def test_build_command_env_vars():
    adapter = CodexCLIAdapter()
    cmd = adapter.build_command(
        "/tmp/p.md", "gpt-5.3-codex", 100, 30, env_vars={"CODEX_API_KEY": "sk-test"}
    )
    assert "env CODEX_API_KEY=" in cmd
    assert "sk-test" in cmd


def test_build_command_ignores_max_turns_and_budget():
    adapter = CodexCLIAdapter()
    cmd = adapter.build_command("/tmp/p.md", "gpt-5.3-codex", 50, 30, max_budget_usd=5.0)
    assert "--max-turns" not in cmd
    assert "--max-budget-usd" not in cmd


def test_build_command_working_dir():
    adapter = CodexCLIAdapter()
    cmd = adapter.build_command("/tmp/p.md", "gpt-5.3-codex", 100, 30, working_dir="/my/dir")
    assert "cd /my/dir" in cmd


# ---------------------------------------------------------------------------
# parse_event tests
# ---------------------------------------------------------------------------


def test_parse_event_thread_started():
    adapter = CodexCLIAdapter()
    event = adapter.parse_event(
        {"type": "thread.started", "thread_id": "0199a213-81c0-7800-8aa1-bbab2a035a53"}
    )
    assert event is not None
    assert event.type == "system"
    assert event.session_id == "0199a213-81c0-7800-8aa1-bbab2a035a53"


def test_parse_event_turn_started_returns_none():
    adapter = CodexCLIAdapter()
    result = adapter.parse_event({"type": "turn.started"})
    assert result is None


def test_parse_event_turn_completed_returns_none():
    adapter = CodexCLIAdapter()
    result = adapter.parse_event(
        {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}}
    )
    assert result is None


def test_parse_event_item_completed_agent_message():
    adapter = CodexCLIAdapter()
    event = adapter.parse_event(
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "Hello world"},
        }
    )
    assert event is not None
    assert event.type == "assistant"
    assert event.subtype == "text"
    assert event.content == "Hello world"


def test_parse_event_item_started_command_execution():
    adapter = CodexCLIAdapter()
    event = adapter.parse_event(
        {
            "type": "item.started",
            "item": {"type": "command_execution", "command": "ls -la"},
        }
    )
    assert event is not None
    assert event.type == "assistant"
    assert event.subtype == "tool_use"
    assert event.tool_name == "shell"
    assert event.tool_input == "ls -la"


def test_parse_event_item_completed_command_execution():
    adapter = CodexCLIAdapter()
    event = adapter.parse_event(
        {
            "type": "item.completed",
            "item": {"type": "command_execution", "aggregated_output": "file.txt\n"},
        }
    )
    assert event is not None
    assert event.type == "user"
    assert event.subtype == "tool_result"
    assert event.content == "file.txt\n"


def test_parse_event_item_completed_file_change():
    adapter = CodexCLIAdapter()
    event = adapter.parse_event(
        {
            "type": "item.completed",
            "item": {"type": "file_change", "path": "src/foo.py"},
        }
    )
    assert event is not None
    assert event.type == "assistant"
    assert event.subtype == "tool_use"
    assert event.tool_name == "edit_file"


def test_parse_event_thread_closed():
    adapter = CodexCLIAdapter()
    # Accumulate some turns
    adapter.parse_event({"type": "turn.started"})
    adapter.parse_event(
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}
    )
    adapter.parse_event({"type": "turn.started"})
    adapter.parse_event(
        {"type": "turn.completed", "usage": {"input_tokens": 20, "output_tokens": 10}}
    )

    event = adapter.parse_event({"type": "thread.closed"})
    assert event is not None
    assert event.type == "result"
    assert event.num_turns == 2
    assert event.total_cost_usd == 0.0


def test_parse_event_error():
    adapter = CodexCLIAdapter()
    event = adapter.parse_event({"type": "error", "message": "Something went wrong"})
    assert event is not None
    assert event.type == "result"
    assert event.is_error is True
    assert event.content == "Something went wrong"


def test_parse_event_turn_failed():
    adapter = CodexCLIAdapter()
    event = adapter.parse_event({"type": "turn.failed", "error": "Rate limit exceeded"})
    assert event is not None
    assert event.type == "result"
    assert event.is_error is True
    assert "Rate limit exceeded" in event.content


def test_parse_event_unknown():
    adapter = CodexCLIAdapter()
    event = adapter.parse_event({"type": "some.unknown.event", "data": 42})
    assert event is not None
    assert event.type == "some.unknown.event"
    assert event.raw == {"type": "some.unknown.event", "data": 42}


# ---------------------------------------------------------------------------
# Turn accumulation
# ---------------------------------------------------------------------------


def test_turn_accumulation():
    adapter = CodexCLIAdapter()
    adapter.parse_event({"type": "thread.started", "thread_id": "sess-abc"})

    adapter.parse_event({"type": "turn.started"})
    r1 = adapter.parse_event(
        {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}}
    )
    assert r1 is None  # Not emitted

    adapter.parse_event({"type": "turn.started"})
    r2 = adapter.parse_event(
        {"type": "turn.completed", "usage": {"input_tokens": 200, "output_tokens": 40}}
    )
    assert r2 is None

    event = adapter.parse_event({"type": "thread.closed"})
    assert event is not None
    assert event.type == "result"
    assert event.num_turns == 2
    assert event.total_cost_usd == 0.0
    assert event.session_id == "sess-abc"


# ---------------------------------------------------------------------------
# is_result_event and extract_result
# ---------------------------------------------------------------------------


def test_is_result_event_thread_closed():
    adapter = CodexCLIAdapter()
    assert adapter.is_result_event({"type": "thread.closed"}) is True


def test_is_result_event_error():
    adapter = CodexCLIAdapter()
    assert adapter.is_result_event({"type": "error"}) is True


def test_is_result_event_turn_failed():
    adapter = CodexCLIAdapter()
    assert adapter.is_result_event({"type": "turn.failed"}) is True


def test_is_result_event_false():
    adapter = CodexCLIAdapter()
    assert adapter.is_result_event({"type": "item.completed"}) is False
    assert adapter.is_result_event({"type": "turn.completed"}) is False
    assert adapter.is_result_event({"type": "thread.started"}) is False


def test_extract_result():
    adapter = CodexCLIAdapter()
    adapter.parse_event({"type": "thread.started", "thread_id": "sess-xyz"})
    adapter.parse_event({"type": "turn.started"})
    adapter.parse_event(
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}
    )

    result = adapter.extract_result({"type": "thread.closed"})
    assert result.cost == 0.0
    assert result.turns == 1
    assert result.session_id == "sess-xyz"


# ---------------------------------------------------------------------------
# Adapter properties and capabilities
# ---------------------------------------------------------------------------


def test_name():
    assert CodexCLIAdapter().name == "codex"


def test_instructions_path():
    assert CodexCLIAdapter().instructions_path == "AGENTS.md"


def test_prepend_instructions_true():
    assert CodexCLIAdapter().prepend_instructions is True


def test_gitignore_entries():
    assert CodexCLIAdapter().gitignore_entries == [".codex/"]


def test_supports_resume_true():
    assert CodexCLIAdapter().supports_resume() is True


def test_supports_budget_false():
    assert CodexCLIAdapter().supports_budget() is False


def test_supports_max_turns_false():
    assert CodexCLIAdapter().supports_max_turns() is False


def test_default_model():
    assert CodexCLIAdapter().default_model == "gpt-5.4"


def test_validate_model_gpt():
    assert CodexCLIAdapter().validate_model("gpt-5.3-codex") is True
    assert CodexCLIAdapter().validate_model("gpt-4o") is True


def test_validate_model_o_series():
    assert CodexCLIAdapter().validate_model("o3") is True
    assert CodexCLIAdapter().validate_model("o4-mini") is True


def test_validate_model_claude_rejected():
    assert CodexCLIAdapter().validate_model("claude-sonnet-4-6") is False
    assert CodexCLIAdapter().validate_model("claude-opus-4-6") is False


def test_get_env_overrides_empty():
    assert CodexCLIAdapter().get_env_overrides() == {}


def test_get_auth_config_with_key():
    from unittest.mock import MagicMock

    config = MagicMock()
    config.codex_api_key = "sk-mykey"
    env_vars, docker_args, temp_file = CodexCLIAdapter().get_auth_config(config)
    assert env_vars == {"CODEX_API_KEY": "sk-mykey"}
    assert docker_args == []
    assert temp_file is None


def test_get_auth_config_empty_key():
    from unittest.mock import MagicMock

    config = MagicMock()
    config.codex_api_key = ""
    env_vars, docker_args, temp_file = CodexCLIAdapter().get_auth_config(config)
    assert env_vars == {}
    assert docker_args == []
    assert temp_file is None
