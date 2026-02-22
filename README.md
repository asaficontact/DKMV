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
│  ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ dkmv dev│ │ dkmv qa │ │dkmv judge│ │dkmv docs │ │ dkmv run │ │
│  └────┬────┘ └────┬────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ │
│       │           │           │             │           │     │
│       ▼           ▼           ▼             ▼           ▼     │
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

DKMV ships with four built-in components. Each component runs in its own isolated Docker container (tasks within a component share the same container):

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

## Task System

DKMV uses a YAML-based task system for defining components. Each component is a directory of YAML task files that are executed sequentially inside a single Docker container. The four built-in components (Dev, QA, Judge, Docs) are themselves YAML task files in `dkmv/builtins/`.

```bash
# Run a built-in component
dkmv run dev --repo https://github.com/org/repo --var prd_path=./prd.md

# Run a custom component directory
dkmv run ./my-component --repo https://github.com/org/repo --var key=value
```

### Task YAML Structure

Each task file defines what context to inject, what prompt to send, and what outputs to capture:

```yaml
name: implement
description: Write code based on the plan
commit: true
push: true
commit_message: "feat({{ component }}): {{ feature_name }} [dkmv]"

model: claude-sonnet-4-6      # Override per task (optional)
max_turns: 100
max_budget_usd: 3.00

inputs:
  - name: prd
    type: file                 # file, text, or env
    src: "{{ prd_path }}"      # Path on your machine (Jinja2 template)
    dest: /home/dkmv/workspace/.dkmv/prd.md  # Path inside container

outputs:
  - path: /home/dkmv/workspace/.dkmv/changes.md
    required: false            # Fail the task if missing?
    save: true                 # Copy to run output directory?

instructions: |
  - Follow the plan at `.dkmv/plan.md` precisely
  - Run tests before finishing

prompt: |
  Implement the feature described in the PRD at `.dkmv/prd.md`.
```

### Execution Parameter Cascade

Execution parameters (`model`, `max_turns`, `timeout_minutes`, `max_budget_usd`) are resolved with a three-level cascade: **task YAML > CLI flags > global config**. This lets you set per-task overrides (e.g., a cheaper model for planning) while keeping sensible defaults.

### Template Variables

Task files support Jinja2 templates. Variables are available in prompts, input paths, content, and commit messages:

| Variable | Source |
|----------|--------|
| `{{ repo }}`, `{{ branch }}`, `{{ feature_name }}` | CLI arguments |
| `{{ component }}`, `{{ model }}`, `{{ run_id }}` | Runtime |
| `{{ prd_path }}`, `{{ any_key }}` | CLI `--var KEY=VALUE` flags |
| `{{ tasks.plan.status }}`, `{{ tasks.plan.cost }}` | Previous task results |

### Creating Custom Components

Create a directory with numbered YAML task files:

```
my-component/
├── 01-analyze.yaml    # Task 1: runs first
├── 02-implement.yaml  # Task 2: runs second
└── 03-verify.yaml     # Task 3: runs third
```

Tasks execute in filename order. All tasks share the same container, so files written by one task are automatically available to the next. Run it with:

```bash
dkmv run ./my-component --repo https://github.com/org/repo --var key=value
```

See the [Task YAML Schema](docs/implementation/v1%20-%20dkmv%20+%20tasks/task_definition.md) for the full reference.

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
# 1. Write a PRD describing the feature you want to implement

# 2. Run the Dev agent to implement a feature
uv run dkmv dev https://github.com/user/repo --prd prd.md --branch feature/auth

# 3. Run QA against the branch
uv run dkmv qa https://github.com/user/repo --branch feature/auth --prd prd.md

# 4. Run Judge to evaluate quality
uv run dkmv judge https://github.com/user/repo --branch feature/auth --prd prd.md

# 5. Generate documentation
uv run dkmv docs https://github.com/user/repo --branch feature/auth --create-pr

# Alternative: use the generic `dkmv run` command
uv run dkmv run dev --repo https://github.com/user/repo --var prd_path=prd.md
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

### Task System Commands

```bash
# Run any component (built-in or custom directory)
dkmv run <component> --repo <url> [--branch <name>] [--feature-name <name>]
                     [--var KEY=VALUE ...] [--model <model>] [--max-turns <n>]
                     [--timeout <min>] [--max-budget-usd <n>]
                     [--keep-alive] [--verbose]

# Examples:
dkmv run dev --repo https://github.com/org/repo --var prd_path=./auth.md
dkmv run qa --repo https://github.com/org/repo --var prd_path=./auth.md
dkmv run ./custom-tasks --repo https://github.com/org/repo --var key=value
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

# Remove all DKMV sandbox containers (running and stopped)
dkmv clean
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
| `DKMV_MODEL` | `claude-sonnet-4-6` | Default Claude model |
| `DKMV_MAX_TURNS` | `100` | Max Claude Code turns per invocation |
| `DKMV_IMAGE` | `dkmv-sandbox:latest` | Docker image name |
| `DKMV_OUTPUT_DIR` | `./outputs` | Directory for run output and logs |
| `DKMV_TIMEOUT` | `30` | Timeout per component run (minutes) |
| `DKMV_MEMORY` | `8g` | Docker container memory limit |
| `DKMV_MAX_BUDGET_USD` | *(none)* | Optional cost cap per Claude invocation |

## How It Works

### Component Lifecycle

Each component is a directory of YAML task files. When you run a component, `ComponentRunner` orchestrates the full lifecycle:

```
┌─────────────────────────────────────────────────────┐
│              ComponentRunner.run()                    │
│                                                     │
│  1. Scan component directory for YAML task files    │
│  2. Create run (generate ID, create output dir)     │
│  3. Start sandbox (Docker container via SWE-ReX)    │
│  4. Setup workspace (git clone, branch, gh auth)    │
│  5. For each task (in filename order):              │
│     a. Resolve template variables (Jinja2)          │
│     b. Inject inputs (files, text, env vars)        │
│     c. Write .claude/CLAUDE.md (instructions)       │
│     d. Stream Claude Code (file-based streaming)    │
│     e. Collect and validate outputs                 │
│     f. Git teardown (add, commit, push per task)    │
│     g. On failure → skip remaining tasks            │
│  6. Aggregate results (cost, duration, status)      │
│  7. Save result to disk                             │
│  8. Stop container                                  │
│                                                     │
│  On error: save failed status, stop container       │
│  On timeout: save timed_out status, stop container  │
└─────────────────────────────────────────────────────┘
```

All tasks in a component share the **same container** — files written by one task are visible to the next. If any task fails, the pipeline stops and remaining tasks are marked as skipped.

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
├── config.json              # Run configuration
├── result.json              # Final result (status, cost, duration)
├── tasks_result.json        # Per-task results (name, status, cost, turns)
├── stream.jsonl             # Raw stream-json events
├── container.txt            # Container name (for attach/stop)
├── prompt_plan.md           # Prompt sent for "plan" task
├── prompt_implement.md      # Prompt sent for "implement" task
└── plan.md                  # Saved output artifacts (from save: true)
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
├── cli.py                 # Typer CLI app with all commands
├── config.py              # DKMVConfig (pydantic-settings)
├── utils/                 # async_command decorator
├── core/
│   ├── models.py          # Shared types (BaseResult, BaseComponentConfig)
│   ├── sandbox.py         # SandboxManager (SWE-ReX wrapper)
│   ├── runner.py          # RunManager (run tracking, logs, cost)
│   └── stream.py          # StreamParser (stream-json → terminal)
├── tasks/                 # Task engine (YAML-based declarative system)
│   ├── models.py          # TaskDefinition, TaskInput, TaskOutput, CLIOverrides
│   ├── loader.py          # TaskLoader (Jinja2 + YAML + Pydantic)
│   ├── runner.py          # TaskRunner (single task execution)
│   ├── component.py       # ComponentRunner (multi-task orchestration)
│   └── discovery.py       # resolve_component() for built-ins and paths
├── builtins/              # Built-in YAML components
│   ├── dev/               # 01-plan.yaml, 02-implement.yaml
│   ├── qa/                # 01-evaluate.yaml
│   ├── judge/             # 01-verdict.yaml
│   └── docs/              # 01-generate.yaml
├── components/            # Legacy Python components (still functional)
│   ├── base.py            # BaseComponent ABC (12-step lifecycle)
│   ├── dev/               # Dev agent
│   ├── qa/                # QA agent
│   ├── judge/             # Judge agent
│   └── docs/              # Docs agent
└── images/
    └── Dockerfile         # dkmv-sandbox image definition
```

## Documentation

- **PRD**: [`docs/implementation/v1 - dkmv [DONE]/plan_dkmv_v1[DONE].md`](docs/implementation/v1%20-%20dkmv%20%5BDONE%5D/plan_dkmv_v1%5BDONE%5D.md) — Full product requirements document
- **Task System PRD**: [`docs/implementation/v1 - dkmv + tasks/prd_tasks_v1.md`](docs/implementation/v1%20-%20dkmv%20+%20tasks/prd_tasks_v1.md) — Task system requirements
- **Task YAML Schema**: [`docs/implementation/v1 - dkmv + tasks/task_definition.md`](docs/implementation/v1%20-%20dkmv%20+%20tasks/task_definition.md) — YAML task format reference
- **ADRs**: [`docs/adrs/`](docs/adrs/) — Architecture decision records (MADR 4.0)
- **Changelog**: [`CHANGELOG.md`](CHANGELOG.md) — Release notes

## License

[Add license information]
