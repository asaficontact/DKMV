# DKMV (Don't Kill My Vibe)

A Python CLI tool that orchestrates AI agents via Claude Code in Docker containers to implement software features end-to-end.

Given a Product Requirements Document (PRD), DKMV runs a pipeline of specialized agents — **Dev**, **QA**, **Judge**, and **Docs** — each operating inside isolated Docker containers via [SWE-ReX](https://github.com/SWE-ReX/SWE-ReX). Agents run Claude Code in headless mode, producing real code changes on git branches.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     USER (Operator)                     │
│  Writes PRDs, runs CLI commands, inspects git branches  │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│                    DKMV CLI (dkmv)                       │
│                                                         │
│  ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐    │
│  │ dkmv dev│ │ dkmv qa │ │dkmv judge│ │dkmv docs │    │
│  └────┬────┘ └────┬────┘ └────┬─────┘ └────┬─────┘    │
│       │           │           │             │           │
│       ▼           ▼           ▼             ▼           │
│  ┌──────────────────────────────────────────────────┐  │
│  │            Core Framework Layer                   │  │
│  │  SandboxManager  RunManager  StreamParser         │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│              SWE-ReX DockerDeployment                    │
│  Manages container lifecycle, bash sessions, file I/O   │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│           Docker Container (dkmv-sandbox)                │
│                                                         │
│  Claude Code (headless, YOLO mode)                      │
│  ├── Reads PRD from workspace                           │
│  ├── Explores codebase, writes code, runs tests         │
│  ├── Iterates until requirements are met                │
│  └── Commits results to git branch                      │
│                                                         │
│  Pre-installed: git, gh CLI, Node.js 20, Python 3       │
└─────────────────────────────────────────────────────────┘
```

## Components

DKMV uses four specialized agents, each in its own isolated Docker container:

```
PRD ──► Dev ──► QA ──► Judge ──► Docs
         │       │       │         │
         ▼       ▼       ▼         ▼
      feature  tests   verdict   docs PR
      branch   + QA    + score
               report
```

| Component | Purpose | Input | Output |
|-----------|---------|-------|--------|
| **Dev** | Implement features from a PRD | PRD + repo | Code on a feature branch |
| **QA** | Test and validate the implementation | PRD + branch | QA report (`.dkmv/qa_report.json`) |
| **Judge** | Evaluate quality with pass/fail verdict | PRD + branch | Verdict with score (`.dkmv/verdict.json`) |
| **Docs** | Generate documentation | Repo + branch | Docs changes, optional PR |

Components share **zero state** with each other. The only bridge between them is the **git branch**. Each component runs in a fresh container and knows nothing about which component ran before or after it.

## Installation

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- [Docker](https://docs.docker.com/get-docker/)
- An [Anthropic API key](https://console.anthropic.com/)

### Setup

```bash
# Clone the repository
git clone https://github.com/your-org/dkmv.git
cd dkmv

# Install dependencies
uv sync

# Copy environment template and add your API keys
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY and GITHUB_TOKEN

# Build the sandbox Docker image
uv run dkmv build

# Verify installation
uv run dkmv --help
```

## Quick Start

```bash
# 1. Write a PRD (see docs/core/plan_dkmv_v1.md Section 3.3 for format)

# 2. Run the Dev agent to implement a feature
uv run dkmv dev https://github.com/user/repo --prd prd.md --branch feature/auth

# 3. Run QA against the branch
uv run dkmv qa https://github.com/user/repo --branch feature/auth --prd prd.md

# 4. Run Judge to evaluate quality
uv run dkmv judge https://github.com/user/repo --branch feature/auth --prd prd.md

# 5. Generate documentation
uv run dkmv docs https://github.com/user/repo --branch feature/auth --create-pr
```

## CLI Commands

### Agent Commands

```bash
# Dev — implement features from a PRD
dkmv dev <repo> --prd <path> [--branch <name>] [--feedback <path>]
                [--design-docs <dir>] [--feature-name <name>]
                [--model <model>] [--max-turns <n>] [--timeout <min>]
                [--max-budget-usd <n>] [--keep-alive] [--verbose]

# QA — test and validate an implementation
dkmv qa <repo> --branch <name> --prd <path>
               [--model <model>] [--max-turns <n>] [--timeout <min>]
               [--max-budget-usd <n>] [--keep-alive] [--verbose]

# Judge — evaluate implementation quality
dkmv judge <repo> --branch <name> --prd <path>
                  [--model <model>] [--max-turns <n>] [--timeout <min>]
                  [--max-budget-usd <n>] [--keep-alive] [--verbose]

# Docs — generate documentation
dkmv docs <repo> --branch <name> [--create-pr] [--pr-base <branch>]
                 [--model <model>] [--max-turns <n>] [--timeout <min>]
                 [--max-budget-usd <n>] [--keep-alive] [--verbose]
```

### Utility Commands

```bash
# Build the sandbox Docker image
dkmv build [--no-cache] [--claude-version <version>]

# List runs with optional filters
dkmv runs [--component <name>] [--status <status>] [--limit <n>]

# Show detailed run information
dkmv show <run-id>

# Attach to a running container (requires --keep-alive)
dkmv attach <run-id>

# Stop and remove a container
dkmv stop <run-id>
```

### Global Options

```bash
dkmv --verbose    # Enable verbose output
dkmv --dry-run    # Show what would be done without executing
```

## Configuration

All configuration is via environment variables or a `.env` file. No YAML or config files needed.

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | *(required)* | Anthropic API key for Claude Code |
| `GITHUB_TOKEN` | *(optional)* | GitHub token for private repos and PR creation |
| `DKMV_MODEL` | `claude-sonnet-4-20250514` | Default Claude model |
| `DKMV_MAX_TURNS` | `100` | Max Claude Code turns per invocation |
| `DKMV_IMAGE` | `dkmv-sandbox:latest` | Docker image name |
| `DKMV_OUTPUT_DIR` | `./outputs` | Directory for run output and logs |
| `DKMV_TIMEOUT` | `30` | Timeout per component run (minutes) |
| `DKMV_MEMORY` | `8g` | Docker container memory limit |
| `DKMV_MAX_BUDGET_USD` | *(none)* | Optional cost cap per Claude invocation |

## How It Works

### Component Lifecycle

Each component follows a 12-step lifecycle managed by the `BaseComponent` base class:

```
┌─────────────────────────────────────────────────────┐
│              BaseComponent.run()                     │
│                                                     │
│  1. Validate inputs                                 │
│  2. Create run (generate ID, create output dir)     │
│  3. Start sandbox (Docker container via SWE-ReX)    │
│  4. Setup workspace (git clone, branch, gh auth)    │
│  5. Write .claude/CLAUDE.md (agent instructions)    │
│  6. Build prompt (from template + config)           │
│  7. Stream Claude Code (file-based streaming)       │
│  8. Collect results (cost, turns, session ID)       │
│  9. Git teardown (add, commit, push)                │
│ 10. Mark completed                                  │
│ 11. Save result to disk                             │
│ 12. Stop container                                  │
│                                                     │
│  On error: save failed status, stop container       │
│  On timeout: save timed_out status, stop container  │
└─────────────────────────────────────────────────────┘
```

### Streaming Architecture

Claude Code runs inside the container with `--output-format stream-json`. Since SWE-ReX blocks until a command completes, DKMV uses a file-based streaming workaround:

```
Container (dkmv-sandbox)
├── Session 1 (main):  claude -p "..." > /tmp/dkmv_stream.jsonl &
└── Session 2 (tail):  tail -n +N /tmp/dkmv_stream.jsonl
                              │
                              ▼
                    Host (StreamParser)
                    ├── Parse JSON events
                    ├── Render to terminal (Rich)
                    └── Save to outputs/runs/<id>/stream.jsonl
```

### Run Output

Each run produces artifacts in `outputs/runs/<run-id>/`:

```
outputs/runs/abc12345/
├── config.json        # Run configuration
├── prompt.md          # The prompt sent to Claude Code
├── stream.jsonl       # Raw stream-json events
├── result.json        # Final result (status, cost, duration)
└── container.txt      # Container name (for attach/stop)
```

## Development

```bash
# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov --cov-fail-under=80

# Skip E2E tests (require Docker + API key)
uv run pytest -m "not e2e"

# Lint and format
uv run ruff check .
uv run ruff format --check .

# Type check
uv run mypy dkmv/
```

### Project Structure

```
dkmv/
├── cli.py                 # Typer CLI app with all 9 commands
├── config.py              # DKMVConfig (pydantic-settings)
├── utils/                 # async_command decorator
├── core/
│   ├── models.py          # Shared types (BaseResult, BaseComponentConfig)
│   ├── sandbox.py         # SandboxManager (SWE-ReX wrapper)
│   ├── runner.py          # RunManager (run tracking, logs, cost)
│   └── stream.py          # StreamParser (stream-json → terminal)
├── components/
│   ├── base.py            # BaseComponent ABC (12-step lifecycle)
│   ├── dev/               # Dev agent (component.py, models.py, prompt.md)
│   ├── qa/                # QA agent
│   ├── judge/             # Judge agent
│   └── docs/              # Docs agent
└── images/
    └── Dockerfile         # dkmv-sandbox image definition
```

## Documentation

- **PRD**: [`docs/core/plan_dkmv_v1.md`](docs/core/plan_dkmv_v1.md) — Full product requirements document
- **ADRs**: [`docs/decisions/`](docs/decisions/) — Architecture decision records (MADR 4.0)
- **Tasks**: [`docs/implementation/tasks.md`](docs/implementation/tasks.md) — Implementation task tracking
- **Progress**: [`docs/implementation/progress.md`](docs/implementation/progress.md) — Session-by-session log
- **Changelog**: [`CHANGELOG.md`](CHANGELOG.md) — Release notes

## License

[Add license information]
