from __future__ import annotations

from pathlib import Path

import typer
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DKMVConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    github_token: str = Field(default="", validation_alias="GITHUB_TOKEN")
    default_model: str = Field(default="claude-sonnet-4-20250514", validation_alias="DKMV_MODEL")
    default_max_turns: int = Field(default=100, validation_alias="DKMV_MAX_TURNS")
    image_name: str = Field(default="dkmv-sandbox:latest", validation_alias="DKMV_IMAGE")
    output_dir: Path = Field(default=Path("./outputs"), validation_alias="DKMV_OUTPUT_DIR")
    timeout_minutes: int = Field(default=30, validation_alias="DKMV_TIMEOUT")
    memory_limit: str = Field(default="8g", validation_alias="DKMV_MEMORY")
    max_budget_usd: float | None = Field(default=None, validation_alias="DKMV_MAX_BUDGET_USD")


def load_config(require_api_key: bool = True) -> DKMVConfig:
    config = DKMVConfig()
    if require_api_key and not config.anthropic_api_key:
        typer.echo(
            "Error: ANTHROPIC_API_KEY not set. Set it via environment variable or .env file.",
            err=True,
        )
        raise typer.Exit(code=1)
    return config
