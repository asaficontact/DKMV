# Package Manager: uv

## Status

Accepted

## Context and Problem Statement

DKMV is a Python CLI tool that needs a package manager for dependency resolution, virtual environment management, and development workflow. Which Python package manager should we use?

## Decision Drivers

- Fast dependency resolution and installation
- Lockfile support for reproducible builds
- Compatible with `pyproject.toml` and PEP 621
- Good developer experience for CLI tool development
- CI-friendly with caching support

## Considered Options

- `uv` — Fast Python package manager from Astral (creators of ruff)
- `pip` + `pip-tools` — Traditional pip with compiled requirements
- `poetry` — Dependency management and packaging tool
- `pdm` — PEP 621-compliant package manager

## Decision Outcome

Chosen option: "uv", because it provides the fastest dependency resolution, native lockfile support, and seamless integration with `pyproject.toml` — all critical for developer productivity and CI performance.

### Consequences

- Good: `uv sync` installs all dependencies in seconds (10-100x faster than pip).
- Good: `uv.lock` provides deterministic, cross-platform lockfile for reproducible builds.
- Good: `uv run dkmv` executes the CLI without manual virtual environment activation.
- Good: CI integration via `astral-sh/setup-uv` action provides consistent uv version and caching.
- Good: Native compatibility with hatchling build system and PEP 621 metadata in `pyproject.toml`.
- Bad: Relatively new tool (less battle-tested than pip/poetry in production).
- Neutral: Requires developers to install uv separately (`curl -LsSf https://astral.sh/uv/install.sh | sh`).

## Usage Patterns

```bash
uv sync                        # Install all dependencies (runtime + dev)
uv run dkmv --help             # Run the CLI
uv run pytest                  # Run tests
uv run ruff check .            # Lint
uv run mypy dkmv/              # Type check
```
