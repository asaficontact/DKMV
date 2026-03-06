"""Tests for dkmv build --codex-version flag."""

from typer.testing import CliRunner

from dkmv.cli import app

runner = CliRunner()


def test_build_has_codex_version_flag() -> None:
    result = runner.invoke(app, ["build", "--help"])
    assert "--codex-version" in result.output


def test_build_has_claude_version_flag() -> None:
    result = runner.invoke(app, ["build", "--help"])
    assert "--claude-version" in result.output


def test_build_both_version_flags_in_help() -> None:
    result = runner.invoke(app, ["build", "--help"])
    assert "--codex-version" in result.output
    assert "--claude-version" in result.output
