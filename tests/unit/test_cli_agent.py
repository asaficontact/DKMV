"""Tests for --agent CLI flag on run commands."""

from __future__ import annotations

from typer.testing import CliRunner

from dkmv.cli import app

runner = CliRunner()


def test_dev_help_shows_agent_flag():
    result = runner.invoke(app, ["dev", "--help"])
    assert result.exit_code == 0
    assert "--agent" in result.output


def test_plan_help_shows_agent_flag():
    result = runner.invoke(app, ["plan", "--help"])
    assert result.exit_code == 0
    assert "--agent" in result.output


def test_qa_help_shows_agent_flag():
    result = runner.invoke(app, ["qa", "--help"])
    assert result.exit_code == 0
    assert "--agent" in result.output


def test_docs_help_shows_agent_flag():
    result = runner.invoke(app, ["docs", "--help"])
    assert result.exit_code == 0
    assert "--agent" in result.output


def test_run_help_shows_agent_flag():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--agent" in result.output


def test_agent_flag_description_mentions_claude_codex():
    """Verify the help text mentions the supported agents."""
    result = runner.invoke(app, ["dev", "--help"])
    assert "claude" in result.output.lower() or "codex" in result.output.lower()


def test_dev_without_agent_flag_still_shows_help():
    """Commands work normally without --agent."""
    result = runner.invoke(app, ["dev", "--help"])
    assert result.exit_code == 0
    assert "--model" in result.output  # Other flags still present
