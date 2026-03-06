"""Edge case tests for the adapter system (T093)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from dkmv.adapters import get_adapter, infer_agent_from_model, validate_agent_model
from dkmv.adapters.codex import CodexCLIAdapter


# ---------------------------------------------------------------------------
# Unknown agent names
# ---------------------------------------------------------------------------


def test_unknown_agent_raises():
    with pytest.raises(ValueError, match="Unknown agent"):
        get_adapter("gpt-agent")


def test_unknown_agent_lists_available():
    with pytest.raises(ValueError, match="claude"):
        get_adapter("not-an-agent")


def test_get_adapter_empty_string_raises():
    with pytest.raises(ValueError, match="Unknown agent"):
        get_adapter("")


# ---------------------------------------------------------------------------
# Codex adapter with no API key
# ---------------------------------------------------------------------------


def test_codex_empty_api_key_returns_empty_auth():
    """Codex adapter with no API key should return empty auth env vars."""
    adapter = get_adapter("codex")
    config = MagicMock()
    config.codex_api_key = ""
    env_vars, docker_args, temp_file = adapter.get_auth_config(config)
    assert env_vars == {}
    assert docker_args == []
    assert temp_file is None


def test_codex_with_api_key_returns_env_var():
    adapter = get_adapter("codex")
    config = MagicMock()
    config.codex_api_key = "sk-test-key"
    env_vars, docker_args, temp_file = adapter.get_auth_config(config)
    assert env_vars.get("CODEX_API_KEY") == "sk-test-key"
    assert docker_args == []
    assert temp_file is None


# ---------------------------------------------------------------------------
# Model inference edge cases
# ---------------------------------------------------------------------------


def test_infer_agent_from_model_unknown_returns_none():
    """Unknown model names should return None from inference."""
    assert infer_agent_from_model("unknown-model") is None
    assert infer_agent_from_model("llama-3") is None
    assert infer_agent_from_model("gemini-pro") is None
    assert infer_agent_from_model("") is None


def test_infer_agent_from_model_gpt_prefix():
    assert infer_agent_from_model("gpt-4") == "codex"
    assert infer_agent_from_model("gpt-5.3-codex") == "codex"


def test_infer_agent_from_model_o_series():
    assert infer_agent_from_model("o3") == "codex"
    assert infer_agent_from_model("o4-mini") == "codex"


def test_infer_agent_from_model_claude_prefix():
    assert infer_agent_from_model("claude-sonnet-4-6") == "claude"
    assert infer_agent_from_model("claude-opus-4-6") == "claude"


# ---------------------------------------------------------------------------
# validate_agent_model edge cases
# ---------------------------------------------------------------------------


def test_validate_agent_model_compatible_claude():
    result = validate_agent_model("claude", "claude-sonnet-4-6")
    assert result == "claude-sonnet-4-6"


def test_validate_agent_model_compatible_codex():
    result = validate_agent_model("codex", "gpt-5.3-codex")
    assert result == "gpt-5.3-codex"


def test_validate_agent_model_auto_substitute_codex(caplog):
    """Codex agent + claude model (not explicit) should auto-substitute."""
    with caplog.at_level(logging.INFO, logger="dkmv.adapters"):
        result = validate_agent_model(
            "codex", "claude-sonnet-4-6", agent_explicit=True, model_explicit=False
        )
    assert result == "gpt-5.4"


def test_validate_agent_model_auto_substitute_claude(caplog):
    """Claude agent + gpt model (not explicit) should auto-substitute."""
    with caplog.at_level(logging.INFO, logger="dkmv.adapters"):
        result = validate_agent_model(
            "claude", "gpt-5.3-codex", agent_explicit=False, model_explicit=True
        )
    assert result == "claude-sonnet-4-6"


def test_validate_agent_model_explicit_both_raises():
    with pytest.raises(ValueError, match="not compatible"):
        validate_agent_model("codex", "claude-opus-4-6", agent_explicit=True, model_explicit=True)


def test_validate_agent_model_unknown_agent_raises():
    with pytest.raises(ValueError, match="Unknown agent"):
        validate_agent_model("gpt-agent", "gpt-4")


# ---------------------------------------------------------------------------
# Codex adapter state tracking across multiple turns
# ---------------------------------------------------------------------------


def test_codex_multiple_turns_accumulated():
    """Turn count accumulates correctly across multiple turn.completed events."""
    adapter = CodexCLIAdapter()

    turn1 = {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 50}}
    turn2 = {"type": "turn.completed", "usage": {"input_tokens": 200, "output_tokens": 75}}

    adapter.parse_event(turn1)
    adapter.parse_event(turn2)

    assert adapter._turn_count == 2
    assert adapter._total_input_tokens == 300
    assert adapter._total_output_tokens == 125


def test_codex_session_id_from_thread_started():
    adapter = CodexCLIAdapter()
    event = {"type": "thread.started", "thread_id": "thread-abc123"}
    result = adapter.parse_event(event)
    assert adapter._session_id == "thread-abc123"
    assert result is not None
    assert result.session_id == "thread-abc123"


# ---------------------------------------------------------------------------
# Codex resume uses correct command format
# ---------------------------------------------------------------------------


def test_codex_resume_command_format():
    adapter = CodexCLIAdapter()
    cmd = adapter.build_command(
        "/tmp/p.md", "gpt-5.3-codex", 100, 30, resume_session_id="thread-xyz"
    )
    assert "codex exec resume thread-xyz" in cmd
    assert "--json" in cmd
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd


def test_codex_no_resume_uses_exec():
    adapter = CodexCLIAdapter()
    cmd = adapter.build_command("/tmp/p.md", "gpt-5.3-codex", 100, 30)
    assert "codex exec" in cmd
    assert "resume" not in cmd


# ---------------------------------------------------------------------------
# Capability flags
# ---------------------------------------------------------------------------


def test_codex_does_not_support_budget():
    adapter = get_adapter("codex")
    assert adapter.supports_budget() is False


def test_codex_does_not_support_max_turns():
    adapter = get_adapter("codex")
    assert adapter.supports_max_turns() is False


def test_claude_supports_budget():
    adapter = get_adapter("claude")
    assert adapter.supports_budget() is True


def test_claude_supports_max_turns():
    adapter = get_adapter("claude")
    assert adapter.supports_max_turns() is True


# ---------------------------------------------------------------------------
# Claude adapter parse_event edge cases (increase coverage)
# ---------------------------------------------------------------------------


def test_claude_parse_event_assistant_empty_content_blocks():
    """Assistant message with no text and no tool_use returns generic event."""
    from dkmv.adapters.claude import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    raw = {"type": "assistant", "message": {"content": []}}
    event = adapter.parse_event(raw)
    assert event is not None
    assert event.type == "assistant"


def test_claude_parse_event_user_no_tool_result():
    """User message with no tool_result block returns generic user event."""
    from dkmv.adapters.claude import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    raw = {"type": "user", "message": {"content": [{"type": "other"}]}}
    event = adapter.parse_event(raw)
    assert event is not None
    assert event.type == "user"


def test_claude_parse_event_user_tool_result_list_content():
    """User tool_result with list content joins text items."""
    from dkmv.adapters.claude import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    raw = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "content": [
                        {"type": "text", "text": "hello"},
                        {"type": "text", "text": " world"},
                    ],
                    "is_error": False,
                }
            ]
        },
    }
    event = adapter.parse_event(raw)
    assert event is not None
    assert "hello" in event.content
    assert "world" in event.content


# ---------------------------------------------------------------------------
# Codex adapter parse_event edge cases (increase coverage)
# ---------------------------------------------------------------------------


def test_codex_parse_event_agent_message_item_started_returns_none():
    """agent_message item.started event should return None (not completed)."""
    adapter = CodexCLIAdapter()
    raw = {"type": "item.started", "item": {"type": "agent_message", "text": "hi"}}
    result = adapter.parse_event(raw)
    assert result is None


def test_codex_parse_event_command_execution_other_event_generic():
    """command_execution item that is not started/completed falls through to generic fallback."""
    adapter = CodexCLIAdapter()
    # item.started with command_execution returns a tool_use event
    raw = {"type": "item.started", "item": {"type": "command_execution", "command": "ls"}}
    result = adapter.parse_event(raw)
    assert result is not None
    assert result.subtype == "tool_use"


def test_codex_parse_event_file_change_started_returns_none():
    """file_change item.started event returns None (only completed is handled)."""
    adapter = CodexCLIAdapter()
    raw = {"type": "item.started", "item": {"type": "file_change", "path": "foo.py"}}
    result = adapter.parse_event(raw)
    assert result is None


def test_codex_parse_event_reasoning_item_started_returns_none():
    """reasoning item.started returns None (only completed is handled)."""
    adapter = CodexCLIAdapter()
    raw = {"type": "item.started", "item": {"type": "reasoning", "content": "thinking..."}}
    result = adapter.parse_event(raw)
    assert result is None


def test_codex_parse_event_plan_item_completed():
    """plan item.completed returns assistant text event."""
    adapter = CodexCLIAdapter()
    raw = {
        "type": "item.completed",
        "item": {"type": "plan", "content": "the plan", "text": "fallback"},
    }
    result = adapter.parse_event(raw)
    assert result is not None
    assert result.type == "assistant"
    assert result.content == "the plan"


def test_codex_parse_event_generic_item_type():
    """Unknown item type falls through to generic fallback event."""
    adapter = CodexCLIAdapter()
    raw = {"type": "item.completed", "item": {"type": "unknown_thing"}}
    result = adapter.parse_event(raw)
    assert result is not None
    assert "unknown_thing" in result.type
