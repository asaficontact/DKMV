"""Tests for adapter registry and base types."""

import logging

import pytest

from dkmv.adapters import (
    AgentAdapter,
    StreamResult,
    get_adapter,
    infer_agent_from_model,
    validate_agent_model,
)
from dkmv.adapters.claude import ClaudeCodeAdapter
from dkmv.adapters.codex import CodexCLIAdapter


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


def test_get_adapter_codex():
    adapter = get_adapter("codex")
    assert isinstance(adapter, CodexCLIAdapter)
    assert adapter.name == "codex"


def test_codex_adapter_satisfies_protocol():
    adapter = CodexCLIAdapter()
    assert isinstance(adapter, AgentAdapter)


# ---------------------------------------------------------------------------
# infer_agent_from_model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-sonnet-4-6", "claude"),
        ("claude-opus-4-6", "claude"),
        ("gpt-5.3-codex", "codex"),
        ("gpt-5.3-codex-spark", "codex"),
        ("o3", "codex"),
        ("o4-mini", "codex"),
        ("unknown-model", None),
        ("llama-3", None),
    ],
)
def test_infer_agent_from_model(model, expected):
    assert infer_agent_from_model(model) == expected


# ---------------------------------------------------------------------------
# validate_agent_model
# ---------------------------------------------------------------------------


def test_validate_agent_model_compatible():
    result = validate_agent_model("claude", "claude-sonnet-4-6")
    assert result == "claude-sonnet-4-6"


def test_validate_agent_model_codex_compatible():
    result = validate_agent_model("codex", "gpt-5.3-codex")
    assert result == "gpt-5.3-codex"


def test_validate_agent_model_explicit_mismatch_raises():
    with pytest.raises(ValueError, match="not compatible"):
        validate_agent_model("codex", "claude-opus-4-6", agent_explicit=True, model_explicit=True)


def test_validate_agent_model_auto_substitute_returns_default(caplog):
    with caplog.at_level(logging.INFO, logger="dkmv.adapters"):
        result = validate_agent_model(
            "codex", "claude-sonnet-4-6", agent_explicit=True, model_explicit=False
        )
    assert result == "gpt-5.4"
    assert (
        "gpt-5.4" in caplog.text
        or "using default" in caplog.text
        or "not compatible" in caplog.text
    )


def test_validate_agent_model_auto_substitute_claude(caplog):
    with caplog.at_level(logging.INFO, logger="dkmv.adapters"):
        result = validate_agent_model(
            "claude", "gpt-5.3-codex", agent_explicit=False, model_explicit=True
        )
    assert result == "claude-sonnet-4-6"
