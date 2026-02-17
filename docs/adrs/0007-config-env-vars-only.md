# Configuration: Environment Variables Only (No YAML)

## Status

Accepted

## Context and Problem Statement

DKMV needs a configuration mechanism for API keys, Docker settings, model selection, and other runtime parameters. Should we use config files (YAML/TOML), environment variables, or a combination?

## Decision Drivers

- API keys and tokens must not be committed to version control
- Configuration should be simple for a CLI tool (not a web service)
- Must work in CI/CD environments where env vars are the standard
- Should support `.env` files for local development convenience
- Minimal configuration surface — sensible defaults for most settings

## Considered Options

- Environment variables + `.env` file via pydantic-settings — no config file
- YAML config file (`~/.dkmv/config.yaml`) + env var overrides
- TOML config in `pyproject.toml` `[tool.dkmv]` section + env vars
- JSON config file + env vars

## Decision Outcome

Chosen option: "Environment variables + .env file via pydantic-settings", because environment variables are the standard for secrets management, pydantic-settings provides type-safe validation with sensible defaults, and a `.env` file covers the local development convenience use case without introducing config file complexity.

### Configuration Loading Flow

```
┌──────────────┐     ┌──────────────┐
│  .env file   │     │ Shell env    │
│              │     │ variables    │
│ ANTHROPIC_   │     │              │
│ API_KEY=sk.. │     │ export DKMV_ │
│ GITHUB_TOKEN │     │ MODEL=opus   │
│ =ghp_xxx     │     │              │
└──────┬───────┘     └──────┬───────┘
       │                    │
       │  SettingsConfigDict│  env var
       │  (env_file=".env") │  precedence
       ▼                    ▼
┌──────────────────────────────────────┐
│  DKMVConfig (pydantic-settings)      │
│  BaseSettings                        │
│                                      │
│  ┌────────────────────────────────┐  │
│  │ Field validation + defaults:   │  │
│  │                                │  │
│  │ anthropic_api_key: str = ""    │  │
│  │ github_token: str = ""         │  │
│  │ default_model: str = "claude.. │  │
│  │ default_max_turns: int = 100   │  │
│  │ image_name: str = "dkmv-sand.. │  │
│  │ output_dir: Path = ./outputs   │  │
│  │ timeout_minutes: int = 30      │  │
│  │ memory_limit: str = "8g"       │  │
│  │ max_budget_usd: float | None   │  │
│  └────────────────────────────────┘  │
│                                      │
│  load_config(require_api_key=True)   │
│  └── Validates ANTHROPIC_API_KEY set │
└──────────────────┬───────────────────┘
                   │ injected into
                   ▼
┌──────────────────────────────────────┐
│  CLI Commands                        │
│  ├── dev:   model, max_turns, etc.   │
│  ├── qa:    model, max_turns, etc.   │
│  ├── judge: model, max_turns, etc.   │
│  └── docs:  model, max_turns, etc.   │
│                                      │
│  Overridable per-command via flags:  │
│  --model, --max-turns, --timeout,    │
│  --max-budget-usd                    │
└──────────────────────────────────────┘
```

### Precedence

1. CLI flags (`--model`, `--timeout`, etc.) — highest priority
2. Shell environment variables (`export DKMV_MODEL=...`)
3. `.env` file values
4. Default values in `DKMVConfig` — lowest priority

### Consequences

- Good: Secrets (API keys, tokens) never live in version-controlled config files.
- Good: pydantic-settings `BaseSettings` provides automatic env var loading, type coercion, and validation.
- Good: `.env` file support via `SettingsConfigDict(env_file=".env")` for local development.
- Good: All 9 settings have sensible defaults — only `ANTHROPIC_API_KEY` is truly required.
- Good: CI/CD environments can set env vars directly without config file management.
- Good: No file format to parse, no schema to maintain, no config migration to handle.
- Bad: No per-project configuration (every project uses the same env vars or `.env` file).
- Bad: Complex nested configuration is awkward with flat env vars (not needed for v1).
- Neutral: `.env.example` documents all available settings for new users.

## Configuration Reference

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `ANTHROPIC_API_KEY` | — | Yes | Anthropic API key for Claude Code |
| `GITHUB_TOKEN` | — | For private repos/PRs | GitHub personal access token |
| `DKMV_MODEL` | `claude-sonnet-4-20250514` | No | Default Claude model |
| `DKMV_MAX_TURNS` | `100` | No | Max Claude Code turns per invocation |
| `DKMV_IMAGE` | `dkmv-sandbox:latest` | No | Docker image name |
| `DKMV_OUTPUT_DIR` | `./outputs` | No | Run output directory |
| `DKMV_TIMEOUT` | `30` | No | Timeout in minutes |
| `DKMV_MEMORY` | `8g` | No | Docker memory limit |
| `DKMV_MAX_BUDGET_USD` | — | No | Optional cost cap per invocation |
