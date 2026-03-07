from __future__ import annotations

from pathlib import Path
from typing import Literal

import typer
from pydantic import BaseModel, field_validator

AuthMethod = Literal["api_key", "oauth", "codex"]


class CredentialSources(BaseModel):
    auth_method: AuthMethod = "api_key"
    anthropic_api_key_source: str = "env"
    oauth_token_source: str = "none"
    github_token_source: str = "env"
    codex_api_key_source: str = "none"


class ProjectDefaults(BaseModel):
    model: str | None = None
    max_turns: int | None = None
    timeout_minutes: int | None = None
    max_budget_usd: float | None = None
    memory: str | None = None
    agent: str | None = None


class SandboxSettings(BaseModel):
    image: str | None = None
    docker_socket: bool = False


class ProjectConfig(BaseModel):
    version: int = 1
    project_name: str
    repo: str
    default_branch: str = "main"
    credentials: CredentialSources = CredentialSources()
    defaults: ProjectDefaults = ProjectDefaults()
    sandbox: SandboxSettings = SandboxSettings()

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: int) -> int:
        if v != 1:
            msg = (
                f"Unsupported config version {v}. "
                "This project was initialized with a newer version of DKMV. "
                "Please upgrade DKMV or run 'dkmv init' to reinitialize."
            )
            raise ValueError(msg)
        return v


def find_project_root() -> Path:
    """Walk up from CWD to find .dkmv/config.json. Returns CWD if not found."""
    current = Path.cwd()
    for directory in (current, *current.parents):
        if (directory / ".dkmv" / "config.json").is_file():
            return directory
    return current


def load_project_config(project_root: Path | None = None) -> ProjectConfig | None:
    """Load .dkmv/config.json if it exists. Returns None if not initialized."""
    root = project_root or find_project_root()
    config_path = root / ".dkmv" / "config.json"
    if not config_path.exists():
        return None
    return ProjectConfig.model_validate_json(config_path.read_text())


def get_repo(cli_repo: str | None) -> str:
    """Resolve repo from CLI arg or project config. Exits with error if neither available."""
    if cli_repo is not None:
        return cli_repo
    project = load_project_config()
    if project:
        return project.repo
    typer.echo(
        "Error: --repo is required (or run 'dkmv init' to set a default).",
        err=True,
    )
    raise typer.Exit(code=1)
