"""Tests for ClaudeCodeAdapter — unit tests and regression tests."""

from pathlib import Path

import pytest

from dkmv.adapters.base import StreamResult
from dkmv.adapters.claude import ClaudeCodeAdapter


@pytest.fixture
def adapter():
    return ClaudeCodeAdapter()


# ---------------------------------------------------------------------------
# build_command tests
# ---------------------------------------------------------------------------


def test_build_command_basic(adapter):
    cmd = adapter.build_command(
        prompt_file="/tmp/dkmv_prompt.md",
        model="claude-sonnet-4-6",
        max_turns=100,
        timeout_minutes=30,
    )
    assert cmd.startswith("cd /home/dkmv/workspace && ")
    assert 'claude -p "$(cat /tmp/dkmv_prompt.md)"' in cmd
    assert "--dangerously-skip-permissions" in cmd
    assert "--verbose" in cmd
    assert "--output-format stream-json" in cmd
    assert "--model claude-sonnet-4-6" in cmd
    assert "--max-turns 100" in cmd
    assert "< /dev/null > /tmp/dkmv_stream.jsonl" in cmd
    assert "2>/tmp/dkmv_stream.err & echo $!" in cmd


def test_build_command_with_budget(adapter):
    cmd = adapter.build_command(
        prompt_file="/tmp/dkmv_prompt.md",
        model="claude-sonnet-4-6",
        max_turns=100,
        timeout_minutes=30,
        max_budget_usd=5.0,
    )
    assert "--max-budget-usd 5.0" in cmd


def test_build_command_without_budget(adapter):
    cmd = adapter.build_command(
        prompt_file="/tmp/dkmv_prompt.md",
        model="claude-sonnet-4-6",
        max_turns=100,
        timeout_minutes=30,
        max_budget_usd=None,
    )
    assert "--max-budget-usd" not in cmd


def test_build_command_with_env_vars(adapter):
    cmd = adapter.build_command(
        prompt_file="/tmp/dkmv_prompt.md",
        model="claude-sonnet-4-6",
        max_turns=100,
        timeout_minutes=30,
        env_vars={"MY_KEY": "my_value"},
    )
    assert "env MY_KEY=my_value" in cmd


def test_build_command_env_vars_quoted(adapter):
    cmd = adapter.build_command(
        prompt_file="/tmp/dkmv_prompt.md",
        model="claude-sonnet-4-6",
        max_turns=100,
        timeout_minutes=30,
        env_vars={"KEY": "value with spaces"},
    )
    assert "KEY='value with spaces'" in cmd


def test_build_command_resume(adapter):
    cmd = adapter.build_command(
        prompt_file="/tmp/dkmv_prompt.md",
        model="claude-sonnet-4-6",
        max_turns=10,
        timeout_minutes=30,
        resume_session_id="sess-abc123",
    )
    assert "--resume sess-abc123" in cmd
    # Resume mode uses -p as well (appended after --resume)
    assert "-p" in cmd


def test_build_command_custom_working_dir(adapter):
    cmd = adapter.build_command(
        prompt_file="/tmp/dkmv_prompt.md",
        model="claude-sonnet-4-6",
        max_turns=100,
        timeout_minutes=30,
        working_dir="/custom/dir",
    )
    assert cmd.startswith("cd /custom/dir && ")


# ---------------------------------------------------------------------------
# Regression tests — exact command string match
# ---------------------------------------------------------------------------


def test_build_command_regression_basic(adapter):
    """Exact command match against current sandbox.py implementation."""
    cmd = adapter.build_command(
        prompt_file="/tmp/dkmv_prompt.md",
        model="claude-sonnet-4-6",
        max_turns=100,
        timeout_minutes=30,
    )
    expected = (
        "cd /home/dkmv/workspace && "
        'claude -p "$(cat /tmp/dkmv_prompt.md)" '
        "--dangerously-skip-permissions "
        "--verbose "
        "--output-format stream-json "
        "--model claude-sonnet-4-6 "
        "--max-turns 100"
        " < /dev/null > /tmp/dkmv_stream.jsonl 2>/tmp/dkmv_stream.err & echo $!"
    )
    assert cmd == expected


def test_build_command_regression_with_budget(adapter):
    """Exact command match for budget flag."""
    cmd = adapter.build_command(
        prompt_file="/tmp/dkmv_prompt.md",
        model="claude-sonnet-4-6",
        max_turns=100,
        timeout_minutes=30,
        max_budget_usd=2.5,
    )
    expected = (
        "cd /home/dkmv/workspace && "
        'claude -p "$(cat /tmp/dkmv_prompt.md)" '
        "--dangerously-skip-permissions "
        "--verbose "
        "--output-format stream-json "
        "--model claude-sonnet-4-6 "
        "--max-turns 100"
        " --max-budget-usd 2.5"
        " < /dev/null > /tmp/dkmv_stream.jsonl 2>/tmp/dkmv_stream.err & echo $!"
    )
    assert cmd == expected


def test_build_command_regression_resume(adapter):
    """Exact command match for resume mode."""
    cmd = adapter.build_command(
        prompt_file="/tmp/dkmv_prompt.md",
        model="claude-sonnet-4-6",
        max_turns=10,
        timeout_minutes=30,
        resume_session_id="sess-xyz",
    )
    expected = (
        "cd /home/dkmv/workspace && "
        "claude --resume sess-xyz "
        '-p "$(cat /tmp/dkmv_prompt.md)" '
        "--dangerously-skip-permissions "
        "--verbose "
        "--output-format stream-json "
        "--model claude-sonnet-4-6 "
        "--max-turns 10"
        " < /dev/null > /tmp/dkmv_stream.jsonl 2>/tmp/dkmv_stream.err & echo $!"
    )
    assert cmd == expected


# ---------------------------------------------------------------------------
# parse_event tests
# ---------------------------------------------------------------------------


def test_parse_event_system(adapter):
    event = adapter.parse_event(
        {
            "type": "system",
            "subtype": "init",
            "session_id": "sess-123",
            "message": "System ready",
        }
    )
    assert event is not None
    assert event.type == "system"
    assert event.session_id == "sess-123"
    assert event.content == "System ready"
    assert event.raw["type"] == "system"


def test_parse_event_assistant_text(adapter):
    event = adapter.parse_event(
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Hello world"}]},
        }
    )
    assert event is not None
    assert event.type == "assistant"
    assert event.subtype == "text"
    assert event.content == "Hello world"


def test_parse_event_assistant_tool_use(adapter):
    event = adapter.parse_event(
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "name": "bash", "input": {"command": "ls"}}]
            },
        }
    )
    assert event is not None
    assert event.type == "assistant"
    assert event.subtype == "tool_use"
    assert event.tool_name == "bash"
    assert '"command": "ls"' in event.tool_input


def test_parse_event_user_tool_result(adapter):
    event = adapter.parse_event(
        {
            "type": "user",
            "message": {
                "content": [{"type": "tool_result", "content": "file.txt", "is_error": False}]
            },
        }
    )
    assert event is not None
    assert event.type == "user"
    assert event.subtype == "tool_result"
    assert event.content == "file.txt"
    assert event.is_error is False


def test_parse_event_result(adapter):
    event = adapter.parse_event(
        {
            "type": "result",
            "total_cost_usd": 0.15,
            "duration_ms": 45000,
            "num_turns": 5,
            "session_id": "sess-123",
            "is_error": False,
        }
    )
    assert event is not None
    assert event.type == "result"
    assert event.total_cost_usd == 0.15
    assert event.num_turns == 5
    assert event.session_id == "sess-123"
    assert event.is_error is False


def test_parse_event_unknown_type(adapter):
    event = adapter.parse_event({"type": "unknown_event", "data": "x"})
    assert event is not None
    assert event.type == "unknown_event"
    assert event.raw == {"type": "unknown_event", "data": "x"}


def test_parse_event_raw_preserved(adapter):
    raw = {"type": "system", "session_id": "s1", "message": "msg"}
    event = adapter.parse_event(raw)
    assert event is not None
    assert event.raw is raw


# ---------------------------------------------------------------------------
# is_result_event tests
# ---------------------------------------------------------------------------


def test_is_result_event_true(adapter):
    assert adapter.is_result_event({"type": "result"}) is True


def test_is_result_event_false_assistant(adapter):
    assert adapter.is_result_event({"type": "assistant"}) is False


def test_is_result_event_false_empty(adapter):
    assert adapter.is_result_event({}) is False


# ---------------------------------------------------------------------------
# extract_result tests
# ---------------------------------------------------------------------------


def test_extract_result(adapter):
    raw = {
        "type": "result",
        "total_cost_usd": 0.42,
        "num_turns": 7,
        "session_id": "sess-abc",
    }
    result = adapter.extract_result(raw)
    assert isinstance(result, StreamResult)
    assert result.cost == 0.42
    assert result.turns == 7
    assert result.session_id == "sess-abc"


def test_extract_result_missing_fields(adapter):
    result = adapter.extract_result({"type": "result"})
    assert result.cost == 0.0
    assert result.turns == 0
    assert result.session_id == ""


# ---------------------------------------------------------------------------
# Properties tests
# ---------------------------------------------------------------------------


def test_instructions_path(adapter):
    assert adapter.instructions_path == ".claude/CLAUDE.md"


def test_gitignore_entries(adapter):
    assert adapter.gitignore_entries == [".claude/"]


def test_prepend_instructions_false(adapter):
    assert adapter.prepend_instructions is False


def test_get_env_overrides_empty(adapter):
    assert adapter.get_env_overrides() == {}


def test_supports_resume_true(adapter):
    assert adapter.supports_resume() is True


def test_supports_budget_true(adapter):
    assert adapter.supports_budget() is True


def test_supports_max_turns_true(adapter):
    assert adapter.supports_max_turns() is True


def test_default_model(adapter):
    assert adapter.default_model == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# validate_model tests
# ---------------------------------------------------------------------------


def test_validate_model_claude(adapter):
    assert adapter.validate_model("claude-sonnet-4-6") is True
    assert adapter.validate_model("claude-opus-4-6") is True
    assert adapter.validate_model("claude-haiku-4-5") is True


def test_validate_model_non_claude(adapter):
    assert adapter.validate_model("gpt-4o") is False
    assert adapter.validate_model("o3") is False
    assert adapter.validate_model("gemini-pro") is False


# ---------------------------------------------------------------------------
# get_auth_config tests
# ---------------------------------------------------------------------------


def test_get_auth_config_api_key(adapter):
    from unittest.mock import MagicMock

    config = MagicMock()
    config.auth_method = "api_key"
    config.anthropic_api_key = "sk-test-key"
    env_vars, docker_args, temp_file = adapter.get_auth_config(config)
    assert env_vars == {"ANTHROPIC_API_KEY": "sk-test-key"}
    assert docker_args == []
    assert temp_file is None


def test_get_auth_config_oauth_no_creds_file_with_token(adapter):
    from unittest.mock import MagicMock, patch

    config = MagicMock()
    config.auth_method = "oauth"
    config.claude_oauth_token = "oauth-token-xyz"
    with (
        patch("dkmv.config._fetch_oauth_credentials", return_value=""),
        patch("dkmv.adapters.claude.Path.home", return_value=Path("/nonexistent")),
    ):
        env_vars, docker_args, temp_file = adapter.get_auth_config(config)
    assert env_vars == {"CLAUDE_CODE_OAUTH_TOKEN": "oauth-token-xyz"}
    assert docker_args == []
    assert temp_file is None


def test_get_auth_config_oauth_no_creds_file_no_token(adapter):
    from unittest.mock import MagicMock, patch

    config = MagicMock()
    config.auth_method = "oauth"
    config.claude_oauth_token = ""
    with (
        patch("dkmv.config._fetch_oauth_credentials", return_value=""),
        patch("dkmv.adapters.claude.Path.home", return_value=Path("/nonexistent")),
    ):
        env_vars, docker_args, temp_file = adapter.get_auth_config(config)
    assert env_vars == {}
    assert docker_args == []
    assert temp_file is None


def test_get_auth_config_oauth_keychain_skips_env_var(adapter):
    """When Keychain creds are available, env var is NOT set (avoids stale token)."""
    from unittest.mock import MagicMock, patch

    config = MagicMock()
    config.auth_method = "oauth"
    config.claude_oauth_token = "oauth-token-xyz"
    creds_json = '{"claudeAiOauth":{"accessToken":"at","refreshToken":"rt"}}'
    with patch("dkmv.config._fetch_oauth_credentials", return_value=creds_json):
        env_vars, docker_args, temp_file = adapter.get_auth_config(config)
    try:
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in env_vars
        assert "ANTHROPIC_API_KEY" not in env_vars
        assert "-v" in docker_args
        assert temp_file is not None
    finally:
        if temp_file:
            temp_file.unlink(missing_ok=True)
