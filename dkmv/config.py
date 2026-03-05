from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import typer
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from dkmv.project import AuthMethod


class DKMVConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    claude_oauth_token: str = Field(default="", validation_alias="CLAUDE_CODE_OAUTH_TOKEN")
    github_token: str = Field(default="", validation_alias="GITHUB_TOKEN")
    default_model: str = Field(default="claude-sonnet-4-6", validation_alias="DKMV_MODEL")
    default_max_turns: int = Field(default=100, validation_alias="DKMV_MAX_TURNS")
    image_name: str = Field(default="dkmv-sandbox:latest", validation_alias="DKMV_IMAGE")
    output_dir: Path = Field(default=Path("./outputs"), validation_alias="DKMV_OUTPUT_DIR")
    timeout_minutes: int = Field(default=30, validation_alias="DKMV_TIMEOUT")
    memory_limit: str = Field(default="8g", validation_alias="DKMV_MEMORY")
    max_budget_usd: float | None = Field(default=None, validation_alias="DKMV_MAX_BUDGET_USD")

    # Codex auth
    codex_api_key: str = Field(default="", validation_alias="CODEX_API_KEY")

    # Agent selection
    default_agent: str = Field(default="claude", validation_alias="DKMV_AGENT")

    # Set by load_config() from project config; not loaded from env vars.
    # The validation_alias prevents pydantic-settings from reading AUTH_METHOD env var.
    auth_method: AuthMethod = Field(default="api_key", validation_alias="__DKMV_AUTH_METHOD")


def _fetch_gh_auth_token() -> str:
    """Run `gh auth token` to get GitHub token. Returns empty string on failure."""
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def _fetch_oauth_credentials() -> str:
    """Read Claude Code OAuth credentials from macOS Keychain.

    On macOS, Claude Code stores credentials in the system Keychain under
    the service name "Claude Code-credentials".  On Linux the credentials
    live in ~/.claude/.credentials.json (handled elsewhere).

    Returns the raw JSON string on success, or empty string on failure.
    """
    if sys.platform != "darwin":
        return ""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def load_config(require_api_key: bool = True) -> DKMVConfig:
    from dkmv.project import find_project_root, load_project_config

    project_root = find_project_root()

    # .env resolution from subdirectories: when CWD is project/src/,
    # find .env at project root instead of looking in src/
    env_file = project_root / ".env" if (project_root / ".env").exists() else ".env"
    config = DKMVConfig(_env_file=env_file)  # type: ignore[call-arg]

    project = load_project_config(project_root)

    if project:
        # Apply project defaults ONLY where no env var / .env overrode the built-in.
        # model_fields_set contains fields explicitly set by ANY source (env, .env, kwargs).
        # Fields NOT in this set are still at their built-in defaults → safe to override.
        if project.defaults.model is not None and "default_model" not in config.model_fields_set:
            config.default_model = project.defaults.model
        if (
            project.defaults.max_turns is not None
            and "default_max_turns" not in config.model_fields_set
        ):
            config.default_max_turns = project.defaults.max_turns
        if (
            project.defaults.timeout_minutes is not None
            and "timeout_minutes" not in config.model_fields_set
        ):
            config.timeout_minutes = project.defaults.timeout_minutes
        if (
            project.defaults.max_budget_usd is not None
            and "max_budget_usd" not in config.model_fields_set
        ):
            config.max_budget_usd = project.defaults.max_budget_usd
        if project.defaults.memory is not None and "memory_limit" not in config.model_fields_set:
            config.memory_limit = project.defaults.memory
        if project.sandbox.image is not None and "image_name" not in config.model_fields_set:
            config.image_name = project.sandbox.image
        if project.defaults.agent is not None and "default_agent" not in config.model_fields_set:
            config.default_agent = project.defaults.agent

        # Relocate output_dir to .dkmv/ when project config exists,
        # unless DKMV_OUTPUT_DIR was explicitly set
        if "output_dir" not in config.model_fields_set:
            config.output_dir = project_root / ".dkmv"

    # OPENAI_API_KEY fallback for Codex
    if not config.codex_api_key:
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if openai_key:
            config.codex_api_key = openai_key

    if not config.github_token:
        gh_token = os.environ.get("GH_TOKEN", "")
        if not gh_token and project and project.credentials.github_token_source == "gh auth token":
            gh_token = _fetch_gh_auth_token()
        if gh_token:
            config.github_token = gh_token

    # Determine auth method from project config; default to api_key
    auth_method: AuthMethod = project.credentials.auth_method if project else "api_key"
    config.auth_method = auth_method

    if require_api_key:
        if auth_method == "oauth" and not config.claude_oauth_token:
            has_creds = bool(_fetch_oauth_credentials())
            if not has_creds:
                has_creds = (Path.home() / ".claude" / ".credentials.json").exists()
            if not has_creds:
                typer.echo(
                    "Error: CLAUDE_CODE_OAUTH_TOKEN not set and no OAuth credentials found. "
                    "Log in with 'claude' or run 'claude setup-token' to generate credentials.",
                    err=True,
                )
                raise typer.Exit(code=1)
        if auth_method == "api_key" and not config.anthropic_api_key:
            typer.echo(
                "Error: ANTHROPIC_API_KEY not set. Set it via environment variable or .env file.",
                err=True,
            )
            raise typer.Exit(code=1)

    return config
