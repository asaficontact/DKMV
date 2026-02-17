# Changelog

All notable changes to DKMV will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-02-17

Initial release of DKMV v1 — a CLI tool that orchestrates AI agents via Claude Code in Docker containers to implement software features end-to-end.

### Added

#### CLI Commands
- `dkmv dev` — Run the Dev agent to implement features from a PRD
- `dkmv qa` — Run the QA agent to test and validate implementations
- `dkmv judge` — Run the Judge agent to evaluate implementation quality with pass/fail verdict
- `dkmv docs` — Run the Docs agent to generate documentation with optional PR creation
- `dkmv build` — Build the dkmv-sandbox Docker image with `--no-cache` and `--claude-version` options
- `dkmv runs` — List all runs with `--component`, `--status`, and `--limit` filters
- `dkmv show <run-id>` — Display detailed run information
- `dkmv attach <run-id>` — Attach to a running container via `docker exec`
- `dkmv stop <run-id>` — Stop and remove a container
- Global options: `--verbose`, `--dry-run`

#### Core Framework
- **SandboxManager** — SWE-ReX DockerDeployment wrapper for container lifecycle management (start, execute, stream, stop, file I/O)
- **RunManager** — Run tracking with JSONL streaming, result persistence, run listing/detail, container name persistence
- **StreamParser** — Real-time Claude Code stream-json output parsing with Rich terminal rendering
- **BaseComponent** — Abstract base class with 12-step `run()` lifecycle, prompt template loading, workspace setup, git teardown, feedback synthesis

#### Components
- **DevComponent** — Eval criteria stripping, design docs handling, feedback injection, plan-first prompt, fresh/existing branch logic
- **QAComponent** — Full PRD with eval criteria, QA report artifact collection
- **JudgeComponent** — Pass/fail verdict with confidence scoring, PRD requirements tracking, issue categorization
- **DocsComponent** — Documentation generation, PR creation via `gh pr create` with shell injection protection

#### Configuration
- pydantic-settings `BaseSettings` with env var + `.env` file support
- 9 configurable settings: `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `DKMV_MODEL`, `DKMV_MAX_TURNS`, `DKMV_IMAGE`, `DKMV_OUTPUT_DIR`, `DKMV_TIMEOUT`, `DKMV_MEMORY`, `DKMV_MAX_BUDGET_USD`

#### Docker
- `dkmv-sandbox` Dockerfile based on `node:20-bookworm`
- Non-root `dkmv` user (UID 1000) with passwordless sudo
- Pre-installed: Claude Code (npm), SWE-ReX (pipx), git, gh CLI, Python 3, build-essential
- `NODE_OPTIONS=--max-old-space-size=4096` to prevent OOM crashes

#### Testing & Quality
- 297 tests (unit + integration) with 93.89% code coverage
- pytest with `asyncio_mode="auto"`, pytest-cov, pytest-timeout
- syrupy snapshot tests for all 4 prompt templates
- ruff linting/formatting, mypy type checking
- GitHub Actions CI pipeline (lint, typecheck, unit, integration stages)
- Shell injection protection via `shlex.quote()` on all user-supplied values in shell commands

#### Documentation
- Full PRD in `docs/core/plan_dkmv_v1.md`
- 8 Architecture Decision Records (ADRs) in MADR 4.0 format
- Implementation task tracking in `docs/implementation/tasks.md`
- Session-by-session progress log in `docs/implementation/progress.md`
- Phase-specific implementation specs (phase0-phase4)
