"""Tests for adapter registry and base types."""

import pytest

from dkmv.adapters import AgentAdapter, StreamResult, get_adapter
from dkmv.adapters.claude import ClaudeCodeAdapter


def test_get_adapter_claude():
    adapter = get_adapter("claude")
    assert isinstance(adapter, ClaudeCodeAdapter)
    assert adapter.name == "claude"


def test_get_adapter_unknown_raises():
    with pytest.raises(ValueError, match="Unknown agent 'unknown'"):
        get_adapter("unknown")


def test_get_adapter_error_lists_available():
    with pytest.raises(ValueError, match="claude"):
        get_adapter("nonexistent")


def test_claude_adapter_satisfies_protocol():
    adapter = ClaudeCodeAdapter()
    assert isinstance(adapter, AgentAdapter)


def test_stream_result_defaults():
    result = StreamResult()
    assert result.cost == 0.0
    assert result.turns == 0
    assert result.session_id == ""


def test_stream_result_custom_values():
    result = StreamResult(cost=1.23, turns=5, session_id="sess-abc")
    assert result.cost == 1.23
    assert result.turns == 5
    assert result.session_id == "sess-abc"
