# Changelog

All notable changes to DKMV will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

#### Multi-Agent Adapter Architecture
- `dkmv/adapters/` package — `AgentAdapter` Protocol with `ClaudeCodeAdapter` and `CodexCLIAdapter` implementations
- `--agent` flag on all run commands (`plan`, `dev`, `qa`, `docs`, `run`) to select the AI backend (`claude` or `codex`)
- `DKMV_AGENT` environment variable for setting the default agent globally
- `CODEX_API_KEY` config field and `OPENAI_API_KEY` accepted as fallback for Codex authentication
- `infer_agent_from_model()` — automatically selects agent from model prefix (`claude-*` → claude, `gpt-*` / `o<digit>*` → codex)
- `validate_agent_model()` — validates model-agent compatibility and substitutes safe defaults on mismatch
- 7-level agent resolution cascade: task YAML → task ref → manifest → CLI flag → project config → `DKMVConfig` → default
- Mixed-agent component support: components can run different tasks with different agents; credentials for all required agents are passed into the container
- `AGENTS.md` prepend behavior for Codex: task instructions are prepended to the prompt file

#### Dockerfile
- Codex CLI installed in `dkmv-sandbox` image alongside Claude Code
- `--codex-version` flag on `dkmv build` to pin the Codex CLI npm package version

#### Init
- `dkmv init` discovers Codex API keys from `CODEX_API_KEY`, `OPENAI_API_KEY`, and `.env`
- `dkmv init` auto-selects `codex` as the default agent when a Codex key is found and no Claude auth is available
- `codex` auth method added: stored as `auth_method: "codex"` in `.dkmv/config.json`

#### CLI
- `--start-task <name-or-index>` on all run commands to resume from a specific task after a failure
- `--start-phase <n>` on `dkmv dev` to resume from a specific phase number

#### Task YAML
- `agent` field on task definitions and component manifests — override the agent at task or component level

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
