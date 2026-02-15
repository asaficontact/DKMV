# DKMV — Agent Guidelines

DKMV is a Python CLI tool that orchestrates AI agents via Claude Code in Docker containers (SWE-ReX) to implement software features end-to-end.

## Quick Reference

```bash
uv sync                        # Install dependencies
uv run dkmv --help             # Show CLI commands
uv run pytest                  # Run unit + integration tests
uv run pytest -m "not e2e"     # Skip expensive E2E tests
uv run ruff check .            # Lint
uv run ruff format --check .   # Format check
uv run mypy dkmv/              # Type check
```

## Code Style

- Python 3.12+, modern type hints: `str | None` not `Optional[str]`, `list[str]` not `List[str]`
- Pydantic v2 models (BaseModel, BaseSettings from pydantic-settings)
- No docstrings on obvious code; add comments only where logic isn't self-evident
- `ruff` for linting/formatting (line-length=100, target py312)
- `mypy` for type checking

## Testing

- pytest with `asyncio_mode = "auto"`
- 80% coverage target (`--cov-fail-under=80`)
- `@pytest.mark.e2e` for tests requiring Docker + API key (nightly only)
- Test files mirror source: `dkmv/core/stream.py` -> `tests/unit/test_stream.py`
- Use `tmp_path` for file I/O, `monkeypatch.setenv()` for config, `AsyncMock` for sandbox
- polyfactory for Pydantic model factories in `tests/factories.py`

## Architecture

```
dkmv/
  cli.py              # Typer app, all commands
  config.py            # DKMVConfig (pydantic-settings, env vars + .env)
  utils/               # async_command decorator
  core/                # SandboxManager, RunManager, StreamParser, shared models
  components/          # Self-contained component subpackages (dev/, qa/, judge/, docs/)
    base.py            # BaseComponent ABC — 12-step run() lifecycle
    {name}/            # component.py, models.py, prompt.md, __init__.py
  images/              # Dockerfile for dkmv-sandbox
```

**Isolation rules:**
- Components import from `core/` for infrastructure, **never** from each other
- Shared types (BaseResult, BaseComponentConfig) live in `core/models.py`
- Component-specific types live in their own `models.py`
- Prompt templates are co-located as `prompt.md` inside each component subpackage
- Prompt templates (.md files) require hatchling force-include config in pyproject.toml

## Git Conventions

Conventional Commits: `<type>[scope]: <description>`

- **Types:** `feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, `chore`
- **Scopes:** `cli`, `sandbox`, `runner`, `stream`, `dev`, `qa`, `judge`, `docs-component`, `docker`, `config`
- Agent commits use `[dkmv-<component>]` suffix

## Key Design Decisions

- **No YAML config** — env vars + `.env` file only (pydantic-settings)
- **One container per component invocation** — clean state, isolation
- **Git branches as inter-component communication** — components share zero state except the branch
- **stream-json output** — Claude Code headless mode with real-time parsing
- **File-based streaming** — SWE-ReX blocks on commands; Claude Code stdout redirected to file, tailed from second session
- **SWE-ReX** — container lifecycle management (DockerDeployment, RemoteRuntime)

## Configuration (env vars)

```
ANTHROPIC_API_KEY    # Required
GITHUB_TOKEN         # Required for private repos / PR creation
DKMV_MODEL           # Default: claude-sonnet-4-20250514
DKMV_MAX_TURNS       # Default: 100
DKMV_IMAGE           # Default: dkmv-sandbox:latest
DKMV_OUTPUT_DIR      # Default: ./outputs
DKMV_TIMEOUT         # Default: 30 (minutes)
DKMV_MEMORY          # Default: 8g
DKMV_MAX_BUDGET_USD  # Optional: cost cap per Claude Code invocation (dollars)
```

## Documentation

- Full PRD: `docs/core/plan_dkmv_v1.md` (read-only, source of truth)
- Task list: `docs/implementation/tasks.md` (update checkboxes as you work)
- Progress log: `docs/implementation/progress.md` (add session entries)
- Phase details: `docs/implementation/phase{0-4}_*.md`
- ADRs: `docs/decisions/NNNN-short-title.md` (MADR 4.0 template)

## Dependencies

Runtime: `typer`, `pydantic`, `pydantic-settings`, `swe-rex>=1.4`, `rich`
Dev: `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-timeout`, `syrupy`, `polyfactory`, `ruff`, `mypy`, `commitizen`, `pre-commit`
