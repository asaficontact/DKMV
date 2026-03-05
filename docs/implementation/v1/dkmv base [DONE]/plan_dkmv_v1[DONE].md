# Don't Kill My Vibe (DKMV) Pipeline — v1 PRD & Implementation Plan

---

## 1. Executive Summary

The Don't Kill My Vibe (DKMV) is a Python CLI tool that orchestrates autonomous AI agents to implement software features end-to-end. Given a Product Requirements Document (PRD), the DKMV runs a pipeline of specialized agents — Dev, QA, Judge, and Docs — each operating inside isolated Docker containers via SWE-ReX. Agents run Claude Code in headless YOLO mode, producing real code changes on git branches.

**v1 Scope:** A solid, modular foundation. Each component runs independently via CLI commands. Users manually pass results (git branches) between stages, inspecting output at each step. The architecture is plug-and-play: components are self-contained modules that can be swapped, upgraded, or iterated on without touching the core framework.

**What v1 is NOT:** An automated end-to-end pipeline. No auto-chaining. No web UI. No parallel orchestration. Those are v2+ concerns that the architecture explicitly supports but does not implement.

---

## 2. Architecture Decisions (Locked for v1)

These decisions emerged from extensive design discussion and research. They are final for v1.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| CLI Framework | Python + Typer | Type-hint-based CLI (built on Click), less boilerplate, aligns with Pydantic's annotation style. Async via `asyncio.run()` wrapper. `uv sync` to install. |
| Sandbox Layer | SWE-ReX + Docker | Backend-swappable (Docker → Modal → Fargate), proven at scale, persistent sessions |
| Agent Runtime | Claude Code headless (`-p` + `--dangerously-skip-permissions`) inside container | Full autonomous agent with built-in file editing, test running, iteration — no need to reimplement agent logic. **v1 is Claude Code only.** The BaseComponent abstraction and container-based isolation make it possible to swap the agent runtime in v2+ (e.g., Codex, custom agents via Agent SDK) without changing the component interface. |
| Inter-component Communication | Git branches | Durable, portable, inspectable on GitHub, decoupled from local filesystem |
| Container Strategy | One fresh container per component invocation | Clean state, isolation, debuggability, parallelism-ready |
| Docker Image Strategy | Single shared `dkmv-sandbox` image for all components | Same environment, different prompts |
| Branch Strategy (v1) | Single branch per feature, components add commits | Simple. Multi-branch per stage is v2 |
| Local Run Logging | `outputs/runs/<run-id>/` | Diagnostics, cost tracking, logs — but NOT the source of truth for work product (git is) |

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        USER (Operator)                       │
│  Writes PRDs, runs commands, inspects branches between steps │
└───────────────┬─────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────┐
│                     DKMV CLI (`dkmv`)                           │
│                                                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │ dkmv dev  │ │ dkmv qa   │ │ dkmv judge│ │ dkmv docs │        │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘        │
│       │             │             │             │              │
│       ▼             ▼             ▼             ▼              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Core Framework Layer                      │    │
│  │  • SandboxManager (SWE-ReX lifecycle)                 │    │
│  │  • RunManager (run tracking, logging, cost)           │    │
│  │  • Config (settings, paths, image name)               │    │
│  │  • StreamParser (stream-json → terminal output)       │    │
│  └──────────────────────────────────────────────────────┘    │
└───────────────┬─────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────┐
│                   SWE-ReX DockerDeployment                    │
│  • Starts container from dkmv-sandbox image                   │
│  • Provides RemoteRuntime (bash sessions, file I/O)          │
│  • Manages container lifecycle                               │
└───────────────┬─────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────┐
│              Docker Container (dkmv-sandbox)                   │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Claude Code (headless, YOLO mode)                   │    │
│  │  claude -p "<prompt>" --dangerously-skip-permissions  │    │
│  │         --output-format stream-json                   │    │
│  │                                                       │    │
│  │  • Reads PRD from workspace                          │    │
│  │  • Explores codebase                                 │    │
│  │  • Writes code / runs tests / iterates               │    │
│  │  • Commits to git                                    │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                               │
│  Pre-installed: git, gh CLI, node, python, common tools      │
└─────────────────────────────────────────────────────────────┘
```

### 3.1 Component Isolation Model

Each component (Dev, QA, Judge, Docs) is a self-contained Python module that:

1. Accepts typed configuration (Pydantic BaseModel)
2. Builds a prompt from templates + context
3. Calls SandboxManager to start a container
4. Runs Claude Code with the constructed prompt
5. Collects results (stream-json output, git state, cost)
6. Returns a typed result object

Components share ZERO state with each other. The only bridge is the git branch. A component knows nothing about which component ran before it or after it.

```
dkmv/
├── __init__.py
├── __main__.py                    # python -m dkmv support
├── cli.py                         # Typer app, registers all commands
├── config.py                      # DKMVConfig (pydantic-settings)
├── utils/
│   └── async_support.py           # async_command decorator
├── core/
│   ├── __init__.py                # Exports: SandboxManager, RunManager, StreamParser
│   ├── models.py                  # BaseResult, BaseComponentConfig, SandboxConfig
│   ├── sandbox.py                 # SandboxManager — SWE-ReX lifecycle wrapper
│   ├── runner.py                  # RunManager — run tracking, logging, cost
│   └── stream.py                  # StreamParser — parse stream-json, render to terminal
├── components/
│   ├── __init__.py                # Component registry: register_component(), get_component()
│   ├── base.py                    # BaseComponent ABC (Generic[C, R])
│   ├── dev/
│   │   ├── __init__.py            # Exports: DevComponent, DevConfig, DevResult
│   │   ├── component.py           # DevComponent class
│   │   ├── models.py              # DevConfig, DevResult
│   │   └── prompt.md              # Dev prompt template (co-located)
│   ├── qa/
│   │   ├── __init__.py
│   │   ├── component.py
│   │   ├── models.py
│   │   └── prompt.md
│   ├── judge/
│   │   ├── __init__.py
│   │   ├── component.py
│   │   ├── models.py
│   │   └── prompt.md
│   └── docs/
│       ├── __init__.py
│       ├── component.py
│       ├── models.py
│       └── prompt.md
├── images/
│   └── Dockerfile
tests/                                 # At project root, NOT inside dkmv/
├── unit/
│   ├── test_config.py
│   ├── test_runner.py
│   ├── test_stream.py
│   └── test_prompts.py
├── integration/
│   ├── conftest.py                # SWE-ReX mocks
│   └── test_sandbox.py
└── e2e/
    └── test_dev_pipeline.py       # Real Docker + Claude (expensive, nightly only)
```

Key principles:
- Each component is a **subpackage directory** with co-located prompt, models, and logic
- Removing a component = deleting one directory + one CLI registration line
- Components import from `core/` for infrastructure, never from each other
- Component-specific types (DevResult, JudgeVerdict) live in their component's `models.py`
- Shared types (BaseResult, BaseComponentConfig) live in `core/models.py`

### 3.2 Context & Memory Strategy

DKMV uses a layered approach to context and memory. Each layer serves a distinct purpose:

| Layer | What | Scope | How |
|-------|------|-------|-----|
| Layer 1: Git | Code, tests, configs | Cross-component | The branch IS the shared state. All components read/write the same branch. |
| Layer 2: `.dkmv/` artifacts | PRD, plan, design docs, QA report, verdict, feedback | Cross-component | Structured handoff directory. Each file is an explicit communication channel. Component-specific (Dev writes plan, QA writes report, Judge writes verdict). |
| Layer 3: CLAUDE.md | Agent role, repo conventions, component-specific instructions | Per-component-invocation | Written by BaseComponent into `.claude/CLAUDE.md` before each run. Tells the agent its role, what to read, and what conventions to follow. |
| Layer 4: Run artifacts | stream.jsonl, prompt.md, result.json | Per-run, local only | Diagnostic artifacts in `outputs/runs/<run-id>/`. Not shared between components. |

**What v1 does NOT have (deferred to v2+):**
- No vector database or semantic memory
- No cross-feature learning (each feature is independent)
- No inter-engine memory (each `dkmv dev` invocation starts fresh, except what's on the branch)
- No persistent agent memory between runs (CLAUDE.md is regenerated each time)

### 3.3 PRD Structure Convention

PRDs used with DKMV should follow a recommended two-section structure:

1. **`## Requirements`** — What to build. Visible to Dev, QA, and Judge.
2. **`## Evaluation Criteria`** — How to evaluate completeness. Visible to QA and Judge ONLY. Stripped from Dev's prompt.

This is a **convention**, not enforcement. The prompt builder in each component controls what the agent sees. Separating requirements from evaluation criteria prevents "teaching to the test" — Dev builds to requirements, while QA and Judge evaluate against criteria Dev hasn't seen. This follows the SWE-bench pattern where evaluation criteria (test patches) are hidden from the agent.

### 3.4 Documentation Standards

#### Architecture Decision Records (ADRs)

- Store in `docs/decisions/`
- Number sequentially: `0001-short-title.md`
- Use MADR 4.0 minimal template: Status, Context, Decision Drivers, Considered Options, Decision Outcome, Consequences
- Section 2's Architecture Decisions table remains as a summary; ADRs contain the full reasoning
- Initial ADRs to create during implementation:
  1. `0001-record-architecture-decisions.md`
  2. `0002-cli-framework-typer.md`
  3. `0003-docker-base-image-node.md`
  4. `0004-sandbox-layer-swerex.md`
  5. `0005-package-manager-uv.md`
  6. `0006-git-auth-github-token.md`
  7. `0007-config-env-vars-only.md`

#### Documentation Structure

```
docs/
├── core/
│   ├── main_idea.md              # Original vision (preserved)
│   └── plan_dkmv_v1.md           # This PRD
├── getting-started/
│   ├── installation.md           # Dev environment setup (uv, Docker, etc.)
│   └── quickstart.md             # First run in 5 minutes
├── architecture/
│   └── overview.md               # System architecture narrative + diagrams
├── development/
│   ├── contributing.md           # How to contribute, PR process, code style
│   └── testing.md                # How to run tests, test philosophy
├── decisions/
│   └── 0001-record-architecture-decisions.md
└── AGENT_RULES.md                # Rules for AI agents operating in docs/
```

Principles:
- CLI `--help` text is the primary user documentation — invest in Typer help strings and command descriptions
- `docs/architecture/overview.md` is the narrative version of Section 3's diagrams
- Docs are written incrementally during implementation, not as a separate phase

#### Versioning & Changelog

- Follow Semantic Versioning (SemVer) with `major_version_zero = true` during early development
- Maintain `CHANGELOG.md` at project root using Keep a Changelog format
- Version bumps: `feat` commits → minor bump, `fix` → patch, `BREAKING CHANGE` → major
- Tool: Commitizen configured in `pyproject.toml` (auto-bumps version, auto-generates changelog)

#### Commit Conventions

- Follow Conventional Commits 1.0.0: `<type>[scope]: <description>`
- Types: `feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, `chore`
- Scopes: `cli`, `sandbox`, `runner`, `stream`, `dev`, `qa`, `judge`, `docs-component`, `docker`, `config`
- Enforced via Commitizen pre-commit hook
- Agent commits use `[dkmv-<component>]` suffix (already in PRD)

### 3.5 Multi-PRD Features

A complex feature may require multiple PRDs executed sequentially (e.g., PRD1: data model, PRD2: API endpoints, PRD3: frontend). Each `dkmv dev` invocation handles one PRD. Multiple PRDs share a branch via `--branch`, building on each other's commits.

---

## 4. User Stories

### 4.1 Setup & Configuration

| ID | Story | Acceptance Criteria |
|----|-------|-------------------|
| US-01 | As a developer, I want to install the DKMV CLI with a single command so I can start using it immediately | `uv sync` makes `dkmv` available; `uv run dkmv --help` shows all commands |
| US-02 | As a developer, I want to build the sandbox Docker image so components have an environment to run in | `dkmv build` builds the `dkmv-sandbox:latest` image; image includes git, gh, node, python, Claude Code |
| US-03 | As a developer, I want to configure my Anthropic API key and GitHub credentials once so every run uses them | Env vars `ANTHROPIC_API_KEY`, `GITHUB_TOKEN` or `.env` file in project root; validated at startup |
| US-04 | As a developer, I want clear error messages when prerequisites are missing | `dkmv build` fails gracefully if Docker isn't installed; `dkmv dev` fails if image isn't built; API key missing shows specific message |

### 4.2 Dev Component

| ID | Story | Acceptance Criteria |
|----|-------|-------------------|
| US-05 | As a developer, I want to pass a PRD to the dev component and have it implement the feature on a new git branch | `dkmv dev --prd login.md --repo git@github.com:user/app.git` → clones repo, creates `feature/<name>-dev` branch, implements PRD, commits, pushes |
| US-06 | As a developer, I want to see real-time streaming output of what the agent is doing | Terminal shows Claude's reasoning, file edits, and command output as they happen via stream-json parsing |
| US-07 | As a developer, I want the dev agent to iterate on its own work — run tests, fix failures, retry | Claude Code's built-in agent loop handles this; prompt instructs it to run tests and fix failures |
| US-08 | As a developer, I want to continue development on an existing branch (iteration after Judge feedback) | `dkmv dev --prd login.md --repo ... --branch feature/login-dev` checks out existing branch instead of creating new |
| US-09 | As a developer, I want to provide feedback from a previous Judge run to guide the dev agent | `dkmv dev --prd login.md --repo ... --branch feature/login-dev --feedback verdict.json` injects Judge feedback into prompt |
| US-10 | As a developer, I want to control which Claude model the agent uses | `--model claude-sonnet-4-20250514` flag; defaults to configured model |
| US-11 | As a developer, I want to set a max-turns limit to control cost | `--max-turns 50` flag; defaults to sensible limit |
| US-26 | As a developer, I want to provide supplementary design documents (architecture diagrams, API specs, style guides) so the Dev agent has richer context beyond the PRD | `--design-docs PATH` accepts a directory or glob; files copied to `.dkmv/design_docs/` as read-only context |

### 4.3 QA Component

| ID | Story | Acceptance Criteria |
|----|-------|-------------------|
| US-12 | As a developer, I want to run QA against a branch to validate it meets the PRD requirements | `dkmv qa --branch feature/login-dev --repo ... --prd login.md` → clones repo, checks out branch, runs comprehensive QA, produces report |
| US-13 | As a developer, I want the QA agent to run existing tests AND evaluate code quality against the PRD | QA prompt instructs agent to: run test suite, check for regressions, evaluate PRD requirement coverage, review code quality |
| US-14 | As a developer, I want the QA report saved both to git and locally | QA report committed to branch as `.dkmv/qa_report.json`; also saved in `outputs/runs/<run-id>/` |

### 4.4 Judge Component

| ID | Story | Acceptance Criteria |
|----|-------|-------------------|
| US-15 | As a developer, I want an independent Judge to evaluate whether the implementation passes | `dkmv judge --branch feature/login-dev --repo ... --prd login.md` → reviews code + QA report, produces pass/fail verdict with reasoning |
| US-16 | As a developer, I want structured Judge output that I can feed back to Dev | Verdict JSON includes: pass/fail boolean, reasoning string, specific issues array (each with file, line, description, severity), improvement suggestions array |
| US-17 | As a developer, I want the Judge to be strict and independent | Judge prompt emphasizes: no access to Dev's reasoning, evaluate only what's in the code and tests, be critical |

### 4.5 Docs Component

| ID | Story | Acceptance Criteria |
|----|-------|-------------------|
| US-18 | As a developer, I want the Docs agent to generate documentation for the implemented feature | `dkmv docs --branch feature/login-dev --repo ...` → reads code, generates/updates docs, commits to branch |
| US-19 | As a developer, I want the option to auto-create a PR | `--create-pr` flag opens a PR from the feature branch to main with description and summary |

### 4.6 Run Management & Observability

| ID | Story | Acceptance Criteria |
|----|-------|-------------------|
| US-20 | As a developer, I want to list all my previous runs | `dkmv runs` shows table: run-id, component, repo, branch, status, duration, cost, timestamp |
| US-21 | As a developer, I want to inspect a specific run's details | `dkmv show <run-id>` shows full details: config used, cost breakdown, duration, exit status, link to branch, log file path |
| US-22 | As a developer, I want to attach to a running container to see what's happening | `dkmv attach <run-id>` execs into the running container with bash; requires `--keep-alive` on original run |
| US-23 | As a developer, I want to keep a container alive after a run for debugging | `--keep-alive` flag on any component command prevents container teardown |
| US-24 | As a developer, I want to stop a keep-alive container when I'm done | `dkmv stop <run-id>` stops and removes the container |
| US-25 | As a developer, I want to know how much each run cost | Every run's result.json includes `total_cost_usd` from Claude Code's stream-json final message |

---

## 5. User Journey — Primary Flow (One Feature)

```
Step 0: Setup (once)
─────────────────────
$ uv sync
$ export ANTHROPIC_API_KEY=sk-ant-...
$ export GITHUB_TOKEN=ghp_...
$ uv run dkmv build
  → Building dkmv-sandbox:latest...
  → ✓ Image built successfully

Step 1: Write PRD
─────────────────────
$ vim prds/login.md
  (write requirements for login feature)

Step 2: Run Dev (single PRD)
─────────────────────
$ dkmv dev --prd prds/login.md --repo git@github.com:myorg/myapp.git
  → [run-abc123] Starting container...
  → [run-abc123] Cloning repo...
  → [run-abc123] Creating branch feature/login-dev...
  → [run-abc123] Running Claude Code agent...
  → [stream] Reading PRD requirements...
  → [stream] Exploring codebase structure...
  → [stream] Creating src/auth/login.py...
  → [stream] Writing tests in tests/test_login.py...
  → [stream] Running pytest... 3 passed, 1 failed
  → [stream] Fixing test_login_validation...
  → [stream] Running pytest... 4 passed
  → [run-abc123] Committing changes...
  → [run-abc123] Pushing to feature/login-dev...
  → ✓ Complete | branch: feature/login-dev | cost: $0.12 | duration: 3m 42s

# Multi-PRD feature (sequential) — for complex features split across multiple PRDs:
$ dkmv dev --prd prds/login-data-model.md --repo ... --feature-name login
$ dkmv dev --prd prds/login-api.md --repo ... --branch feature/login-dev --feature-name login
$ dkmv dev --prd prds/login-frontend.md --repo ... --branch feature/login-dev --feature-name login

Step 3: Inspect (manual)
─────────────────────
$ git fetch origin
$ git diff main..origin/feature/login-dev
  (review the code changes)

Step 4: Run QA
─────────────────────
$ dkmv qa --branch feature/login-dev --repo git@github.com:myorg/myapp.git --prd prds/login.md
  → [run-def456] Starting container...
  → [stream] Checking out feature/login-dev...
  → [stream] Running full test suite...
  → [stream] Evaluating PRD requirements coverage...
  → [stream] Reviewing code quality...
  → [run-def456] QA report committed to branch
  → ✓ Complete | 12 tests pass, 2 warnings | cost: $0.08

Step 5: Run Judge
─────────────────────
$ dkmv judge --branch feature/login-dev --repo git@github.com:myorg/myapp.git --prd prds/login.md
  → [run-ghi789] Starting container...
  → [stream] Reviewing implementation against PRD...
  → [stream] Evaluating QA report findings...
  → [stream] Assessing code quality...
  → ✓ VERDICT: PASS | 2 minor suggestions | cost: $0.05

  If FAIL:
  → ✗ VERDICT: FAIL | 3 issues found
  → Feedback saved to outputs/runs/ghi789/verdict.json
  → Re-run: dkmv dev --prd prds/login.md --repo ... --branch feature/login-dev --feedback outputs/runs/ghi789/verdict.json

Step 6: Run Docs (on pass)
─────────────────────
$ dkmv docs --branch feature/login-dev --repo git@github.com:myorg/myapp.git --create-pr
  → [run-jkl012] Starting container...
  → [stream] Generating API documentation...
  → [stream] Updating README...
  → [run-jkl012] Creating pull request...
  → ✓ PR #42 opened: https://github.com/myorg/myapp/pull/42 | cost: $0.06
```

---

## 6. Feature Specifications

### Feature F1: CLI Framework & Global Configuration

**Priority:** 1 (must build first — everything depends on this)

**What it does:** Provides the `dkmv` command with Typer subcommands, global config loading, and shared options.

**Technical requirements:**
- `typer.Typer()` app with `@app.command()` subcommands
- Global options via `@app.callback()`: `--verbose`, `--dry-run`
- Config loading: env vars → `.env` file → defaults (no YAML config file)
- Config schema (pydantic-settings `BaseSettings`):
  ```python
  from pydantic_settings import BaseSettings, SettingsConfigDict
  from pydantic import Field
  from pathlib import Path

  class DKMVConfig(BaseSettings):
      model_config = SettingsConfigDict(
          env_file=".env",
          env_file_encoding="utf-8",
      )

      # These use their standard env var names (no prefix)
      anthropic_api_key: str = Field(validation_alias="ANTHROPIC_API_KEY")
      github_token: str = Field(default="", validation_alias="GITHUB_TOKEN")

      # These use DKMV_ prefix
      default_model: str = Field(default="claude-sonnet-4-20250514", validation_alias="DKMV_MODEL")
      default_max_turns: int = Field(default=100, validation_alias="DKMV_MAX_TURNS")
      image_name: str = Field(default="dkmv-sandbox:latest", validation_alias="DKMV_IMAGE")
      output_dir: Path = Field(default=Path("./outputs"), validation_alias="DKMV_OUTPUT_DIR")
      timeout_minutes: int = Field(default=30, validation_alias="DKMV_TIMEOUT")
      memory_limit: str = Field(default="8g", validation_alias="DKMV_MEMORY")
  ```
- Entry point in `pyproject.toml`: `dkmv = "dkmv.cli:app"`
- Async wrapper pattern for Typer commands:
  ```python
  # dkmv/utils/async_support.py
  import asyncio, functools
  from typing import Any, Callable, Coroutine

  def async_command(func: Callable[..., Coroutine]) -> Callable[..., Any]:
      @functools.wraps(func)
      def wrapper(*args, **kwargs):
          return asyncio.run(func(*args, **kwargs))
      return wrapper
  ```
  Usage: `@app.command()` then `@async_command` then `async def dev(...):`

**User stories:** US-01, US-03, US-04

**References:**
- Typer documentation: https://typer.tiangolo.com/
- Pydantic settings: https://docs.pydantic.dev/latest/concepts/pydantic_settings/

---

### Feature F2: Docker Image & Build Command

**Priority:** 2 (required before any component can run)

**What it does:** Defines the `dkmv-sandbox` Docker image and the `dkmv build` command to build it.

**Docker image contents:**
- Base: `node:20-bookworm` (Anthropic's recommended base for Claude Code — Claude Code is a Node.js application)
- System packages: `git`, `curl`, `wget`, `jq`, `build-essential`, `openssh-client`, `sudo`, `python3`, `python3-pip`, `python3-venv`, `pipx`
- Claude Code: `npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}` (pinnable via build arg)
- GitHub CLI (`gh`): installed from official GitHub repo (Debian-packaged version has broken API calls)
- SWE-ReX: installed via `pipx` as `dkmv` user (not root), PATH points to `/home/dkmv/.local/bin`
- Non-root user `dkmv` at UID 1000 with sudo access (Claude Code `--dangerously-skip-permissions` refuses root)
- `IS_SANDBOX=1` env var (signals sandboxed environment to Claude Code)
- `NODE_OPTIONS=--max-old-space-size=4096` (prevents heap OOM on large projects)

**Dockerfile reference structure:**
```dockerfile
FROM node:20-bookworm

ARG DEBIAN_FRONTEND=noninteractive
ARG CLAUDE_CODE_VERSION=latest
ENV TZ=Etc/UTC

# System deps (includes python3 for target projects)
RUN apt-get update && apt-get install -y \
    git curl wget jq build-essential openssh-client sudo \
    python3 python3-pip python3-venv pipx \
    && rm -rf /var/lib/apt/lists/*

# Claude Code (npm pin for reproducibility — Anthropic's own Dockerfile does this)
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

# GitHub CLI (official repo — Debian-packaged version has broken API calls)
RUN wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (Claude Code --dangerously-skip-permissions refuses root)
# node:20 ships with a 'node' user at UID 1000 — remove it, create dkmv at UID 1000
RUN userdel --remove node 2>/dev/null || true \
    && useradd -m -s /bin/bash -u 1000 dkmv \
    && echo "dkmv ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
USER dkmv
WORKDIR /home/dkmv

# SWE-ReX remote server (must be installed as dkmv user for correct PATH)
RUN pipx install swe-rex && pipx ensurepath
ENV PATH="/home/dkmv/.local/bin:${PATH}"

# Sandbox & memory management
ENV IS_SANDBOX=1
ENV NODE_OPTIONS="--max-old-space-size=4096"

SHELL ["/bin/bash", "-c"]
```

**`dkmv build` command:**
- Runs `docker build` using the Dockerfile from the package's `images/` directory
- Tags as configured image name (default: `dkmv-sandbox:latest`)
- Shows build progress
- Validates successful build
- Optional `--no-cache` flag
- Optional `--claude-version TEXT` flag (passes `--build-arg CLAUDE_CODE_VERSION=X.Y.Z` to pin Claude Code version)

**User stories:** US-02, US-04

**References:**
- SWE-agent custom Docker environments: https://swe-agent.com/latest/config/environments/
- Claude Code devcontainer reference: https://code.claude.com/docs/en/devcontainer
- Claude Code root user issue: https://github.com/anthropics/claude-code/issues/2951

---

### Feature F3: SandboxManager (Core Framework)

**Priority:** 3 (required before any component can run)

**What it does:** Wraps SWE-ReX DockerDeployment to provide container lifecycle management. This is the core abstraction that all components use.

**Interface:**
```python
class SandboxManager:
    async def start(self, config: SandboxConfig) -> SandboxSession:
        """Start a Docker container via SWE-ReX. Returns session handle."""

    async def execute(self, session: SandboxSession, command: str, timeout: int = 300) -> CommandResult:
        """Run a command inside the container via SWE-ReX runtime."""

    async def stream_claude(self, session: SandboxSession, prompt: str, model: str, max_turns: int) -> AsyncIterator[StreamEvent]:
        """Run Claude Code headless in the container, yield stream-json events."""

    async def stop(self, session: SandboxSession, keep_alive: bool = False) -> None:
        """Stop and remove the container, unless keep_alive is True."""

    async def write_file(self, session: SandboxSession, path: str, content: str) -> None:
        """Write a file inside the container via SWE-ReX runtime."""

    async def read_file(self, session: SandboxSession, path: str) -> str:
        """Read a file from inside the container via SWE-ReX runtime."""

    def get_container_name(self, session: SandboxSession) -> str:
        """Return Docker container name for docker exec / attach."""
```

`write_file` and `read_file` map directly to SWE-ReX's `WriteFileRequest` and `ReadFileRequest`. The BaseComponent uses these to inject PRD, feedback, and CLAUDE.md files into the container workspace.

**SandboxConfig (Pydantic BaseModel):**
```python
from pydantic import BaseModel, Field

class SandboxConfig(BaseModel):
    image: str = "dkmv-sandbox:latest"
    env_vars: dict[str, str] = Field(default_factory=dict)
    docker_args: list[str] = Field(default_factory=list)
    startup_timeout: float = 120.0
    keep_alive: bool = False
    memory_limit: str = "8g"
    timeout_minutes: int = 30
```

**Implementation details:**
- Uses `DockerDeployment(image=config.image, docker_args=config.docker_args, startup_timeout=config.startup_timeout)`
- Creates persistent bash session via `CreateBashSessionRequest()`
- `stream_claude` runs: `claude -p "<prompt>" --dangerously-skip-permissions --output-format stream-json --model <model> --max-turns <max_turns>`
- Captures stdout line-by-line, parses each as JSON, yields `StreamEvent` objects
- Environment variables (API keys) passed via `docker_args=["-e", "ANTHROPIC_API_KEY=..."]` or SWE-ReX's env forwarding
- Container named `dkmv-<component>-<short-uuid>` for easy identification
- Docker memory limits: `--memory=8g --memory-swap=8g` added to docker_args by default
- Asyncio timeout wrapper around Claude Code execution (based on `timeout_minutes`)
- Git auth inside container: `echo "$GITHUB_TOKEN" | gh auth login --with-token && gh auth setup-git` — configures git credential helper to use the token for all GitHub HTTPS operations (clone, push, PR creation). No SSH keys needed. For private repos, ensure `GITHUB_TOKEN` has `repo` scope.

**User stories:** US-06, US-22, US-23, US-24

**References:**
- SWE-ReX tutorial: https://swe-rex.com/latest/usage/
- SWE-ReX architecture: https://swe-rex.com/latest/architecture/
- SWE-ReX DockerDeployment API: https://swe-rex.com/latest/api/deployments/docker/
- DockerDeploymentConfig parameters (from SWE-agent source): `image`, `port`, `docker_args`, `startup_timeout`, `pull`, `remove_container`, `container_runtime`
- Claude Code headless mode: https://code.claude.com/docs/en/headless

---

### Feature F4: RunManager & Results (Core Framework)

**Priority:** 3 (parallel with F3 — required before components)

**What it does:** Tracks every component execution with a unique run ID, saves logs, timing, cost, and configuration for later inspection.

**Run directory structure:**
```
outputs/runs/<run-id>/
├── config.json          # Full configuration used for this run
├── result.json          # Structured result (success/fail, cost, duration, branch, etc.)
├── stream.jsonl         # Raw stream-json output from Claude Code
├── prompt.md            # The exact prompt sent to Claude Code
└── logs/
    └── run.log          # Timestamped execution log
```

**Shared result models (`dkmv/core/models.py`, Pydantic BaseModel):**
```python
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime
from pathlib import Path

class BaseComponentConfig(BaseModel):
    repo: str
    branch: str | None = None
    feature_name: str = ""
    model: str | None = None
    max_turns: int | None = None
    keep_alive: bool = False
    verbose: bool = False
    timeout_minutes: int = 30
    sandbox_config: SandboxConfig = Field(default_factory=SandboxConfig)

class BaseResult(BaseModel):
    run_id: str = ""
    component: Literal["dev", "qa", "judge", "docs"]
    status: Literal["success", "failure", "error"]
    repo: str
    branch: str
    feature_name: str = ""
    model: str
    total_cost_usd: float = Field(ge=0, default=0.0)
    duration_seconds: float = Field(ge=0, default=0.0)
    num_turns: int = Field(ge=0, default=0)
    timestamp: datetime = Field(default_factory=datetime.now)
    session_id: str | None = None
    error_message: str | None = None
```

**Component-specific models live in each component's subpackage:**

```python
# dkmv/components/dev/models.py
class DevConfig(BaseComponentConfig):
    prd_path: Path
    feedback_path: Path | None = None
    design_docs_path: Path | None = None

class DevResult(BaseResult):
    component: Literal["dev"] = "dev"
    files_changed: list[str] = Field(default_factory=list)
    tests_passed: int | None = None
    tests_failed: int | None = None

# dkmv/components/qa/models.py
class QAConfig(BaseComponentConfig):
    prd_path: Path

class QAResult(BaseResult):
    component: Literal["qa"] = "qa"
    tests_total: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    warnings: list[str] = Field(default_factory=list)
    qa_report_path: str = ""

# dkmv/components/judge/models.py
class JudgeConfig(BaseComponentConfig):
    prd_path: Path

class JudgeResult(BaseResult):
    component: Literal["judge"] = "judge"
    verdict: Literal["pass", "fail"] = "fail"
    reasoning: str = ""
    issues: list[dict] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)

# dkmv/components/docs/models.py
class DocsConfig(BaseComponentConfig):
    create_pr: bool = False
    pr_base: str = "main"

class DocsResult(BaseResult):
    component: Literal["docs"] = "docs"
    docs_generated: list[str] = Field(default_factory=list)
    pr_url: str | None = None
```

**RunManager interface:**
```python
class RunManager:
    def start_run(self, component: str, config: dict) -> str:
        """Create run directory, return run_id."""

    def save_result(self, run_id: str, result: BaseResult) -> None:
        """Write result.json to run directory. Includes session_id for potential resume."""

    def append_stream(self, run_id: str, event: dict) -> None:
        """Append stream-json event to stream.jsonl."""

    def list_runs(self, component: str = None, feature: str = None, limit: int = 20) -> list[RunSummary]:
        """List recent runs, optionally filtered by component or feature name."""

    def get_run(self, run_id: str) -> RunDetail:
        """Load full run details."""
```

RunManager saves `session_id` from the `type: "result"` stream event into `result.json`. This enables potential `--continue` resume in future versions.

**User stories:** US-20, US-21, US-25

---

### Feature F5: StreamParser (Core Framework)

**Priority:** 3 (parallel with F3, F4)

**What it does:** Parses Claude Code's `stream-json` output line-by-line and renders it to the terminal in real-time.

**Stream-json format (from Claude Code docs):**
- Each line is a JSON object with a `type` field
- `type: "system"` with `subtype: "init"` — session started, includes session_id
- `type: "assistant"` — assistant message (text content, tool_use blocks)
- `type: "user"` — tool results returned to the model
- `type: "result"` — final message with `subtype` ("success", "error_max_turns", etc.), `total_cost_usd`, `duration_ms`, `num_turns`, `session_id`, `is_error`

**Terminal rendering:**
- Assistant text: printed in default color
- Tool use (bash commands): printed in cyan with `$ ` prefix
- Tool results: printed in dim/gray
- Errors: printed in red
- Cost/timing: printed in green at end
- Verbose mode (`--verbose`): shows full JSON events

**User stories:** US-06

**References:**
- Claude Code output formats: https://code.claude.com/docs/en/headless#streaming-json-output

---

### Feature F6: BaseComponent Abstract Class

**Priority:** 4 (required before individual components, after core framework)

**What it does:** Defines the shared interface and execution flow that all components follow. This is the key to the plug-and-play architecture.

**Component Registry (`dkmv/components/__init__.py`):**

A lightweight decorator-based registry for component discovery (no entry_points for v1):

```python
_REGISTRY: dict[str, type[BaseComponent]] = {}

def register_component(name: str):
    """Decorator to register a component class."""
    def decorator(cls):
        _REGISTRY[name] = cls
        return cls
    return decorator

def get_component(name: str) -> type[BaseComponent]:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown component '{name}'. Available: {sorted(_REGISTRY)}")
    return _REGISTRY[name]

def list_components() -> list[str]:
    return sorted(_REGISTRY.keys())
```

Components self-register: `@register_component("dev") class DevComponent(...):`

entry_points plugin discovery is deferred to v2+.

**Generic BaseComponent Interface (`dkmv/components/base.py`):**
```python
from typing import TypeVar, Generic

C = TypeVar("C", bound=BaseComponentConfig)
R = TypeVar("R", bound=BaseResult)

class BaseComponent(ABC, Generic[C, R]):
    """All DKMV components inherit from this with typed config and result."""

    def __init__(self, global_config: DKMVConfig, sandbox: SandboxManager,
                 run_manager: RunManager, stream_parser: StreamParser):
        self.global_config = global_config
        self.sandbox = sandbox
        self.run_manager = run_manager
        self.stream_parser = stream_parser

    @property
    @abstractmethod
    def name(self) -> str:
        """Return component identifier: 'dev', 'qa', 'judge', 'docs'"""

    @abstractmethod
    def build_prompt(self, config: C) -> str:
        """Build the full prompt for Claude Code from templates + context."""

    @abstractmethod
    def parse_result(self, raw_result: dict, config: C) -> R:
        """Parse Claude Code's final result into a typed result object."""

    async def setup_workspace(self, session, config: C) -> None:
        """Hook for component-specific workspace prep. Override if needed."""
        pass

    def _load_prompt_template(self) -> str:
        """Load the co-located prompt.md from the component's subpackage."""
        import importlib.resources as resources
        pkg = f"dkmv.components.{self.name}"
        return resources.files(pkg).joinpath("prompt.md").read_text()

    async def run(self, config: C) -> R:
        """
        Standard execution flow (same for all components):
        1. Validate inputs
        2. Create run via RunManager
        3. Start sandbox container
        4. Set up workspace (clone repo, checkout branch, inject files)
        5. Write CLAUDE.md for agent context (see below)
        6. Build prompt
        7. Run Claude Code in container, stream output
        8. Collect results from git state + stream-json final message
        9. Git commit + push results
        10. Save run result (including session_id)
        11. Tear down container (unless keep_alive)
        12. Return typed result
        """
```

Concrete components: `class DevComponent(BaseComponent[DevConfig, DevResult]):`

**CLAUDE.md Strategy (workspace setup):**

After cloning the repo, the base component writes a `.claude/CLAUDE.md` file into the container workspace:

```markdown
# DKMV Agent Context

You are running as part of the DKMV pipeline ({component_name} stage).
The PRD for this feature is at .dkmv/prd.md.

## Guidelines
- Follow existing code patterns and conventions in this repository
- All work should be committed with meaningful messages
- Tag commits with [dkmv-{component_name}]
```

This gives Claude Code repo-level context without bloating the `-p` prompt. Each component can extend this via the `setup_workspace()` hook.

**Feedback Synthesis:**

When Judge produces a verdict with `verdict: "fail"`, the orchestrator transforms it into a **developer-oriented feedback brief** before passing it to Dev. This is a Python transformation in the orchestrator (no separate LLM call):

1. Extract issues, sorted by severity (critical → major → minor)
2. Convert each issue into an actionable instruction (file, what to change, why)
3. Strip Judge reasoning and confidence scores (prevents Dev from gaming the Judge)
4. Output as `.dkmv/feedback.json` with a clear structure:

```json
{
  "summary": "3 issues found: 1 critical, 2 minor",
  "action_items": [
    {"priority": 1, "file": "src/auth.py", "line": 42, "instruction": "Add input validation for email parameter", "severity": "critical"}
  ]
}
```

Dev receives this synthesized feedback brief, NOT the raw Judge verdict. This follows Amp's "Handoff" pattern — structured summaries packaged for the next phase, rather than raw context passing.

**Why this matters:** When you want to iterate on the Dev component, you only touch its subpackage (`components/dev/`). The run lifecycle, container management, streaming, logging — all handled by the base class. Swap out a component by deleting one directory and one CLI registration line.

**User stories:** All component stories depend on this

---

### Feature F7: Dev Component

**Priority:** 5 (first component to build — validates entire stack)

**What it does:** Takes a PRD and implements the feature in code on a git branch.

**CLI command:**
```
dkmv dev --prd <path> --repo <git-url> [options]

Options:
  --prd PATH              Path to PRD markdown file (required)
  --repo TEXT              Git repo URL (required)
  --branch TEXT            Existing branch to continue on (optional, creates new if omitted)
  --feedback PATH          Path to synthesized feedback JSON for iteration (optional)
  --design-docs PATH       Path to directory or glob of design documents (optional, copied as read-only context)
  --feature-name TEXT      Feature name for branch naming and run grouping (optional, derived from PRD filename if omitted)
  --require-plan           Run two-phase execution: plan first, pause for review, then implement (optional, v1 stretch goal)
  --model TEXT             Claude model to use (default: from config)
  --max-turns INT          Maximum agent turns (default: from config)
  --timeout INT            Wall-clock timeout in minutes (default: 30)
  --keep-alive             Keep container running after completion
  --verbose                Show full stream-json events
```

**Execution flow:**
1. Validate: PRD file exists, repo URL valid, API key present
2. Start container with SandboxManager
3. Clone repo inside container
4. If `--branch` provided: `git checkout <branch>` (iterate mode)
5. If no `--branch`: `git checkout -b feature/<feature-name>-dev` (fresh mode; feature name from `--feature-name` or derived from PRD filename)
6. Add `.dkmv/` to `.gitignore` in the workspace (prevents pipeline artifacts from cluttering the PR diff)
7. Copy PRD file into workspace as `.dkmv/prd.md` — **strip `## Evaluation Criteria` section** before copying (Dev builds to requirements, not evaluation criteria)
8. If `--feedback` provided: copy synthesized feedback as `.dkmv/feedback.json`
9. If `--design-docs` provided: copy design documents to `.dkmv/design_docs/` as **read-only context**
10. Build prompt from component's `prompt.md` template + PRD content + feedback (if any)
11. Agent produces `.dkmv/plan.md` before writing code (captured as run artifact)
12. Run Claude Code with prompt, stream output
13. On completion: `git add -A && git commit -m "feat: implement <feature> [dkmv-dev]"` (`.dkmv/` is gitignored so PRD/feedback are excluded)
14. `git push origin <branch>`
15. Collect: files changed, test results, cost, duration
16. Save DevResult (including session_id)
17. Tear down container

**`--require-plan` mode (v1 stretch goal):** When set, the orchestrator runs **two separate Claude Code invocations**: the first produces `.dkmv/plan.md` and stops, the user reviews the plan, and the second invocation implements it. This matches Devin 2.0's Interactive Planning pattern.

**Prompt template (`components/dev/prompt.md`) — initial version:**
```markdown
You are a senior software engineer implementing a feature based on a PRD.

## Your Task
Read the PRD at `.dkmv/prd.md` and implement ALL requirements in the codebase.

{design_docs_section}

## Phase 1: Explore & Plan
1. Read the PRD at `.dkmv/prd.md` carefully
2. Explore the existing codebase structure to understand conventions
3. Produce a plan at `.dkmv/plan.md` with: files to create/modify, approach, dependencies, test strategy
4. Do NOT write implementation code until the plan is complete

## Phase 2: Implement
5. Execute your plan — write code following existing patterns and conventions
6. Write tests for your implementation
7. Run the test suite to verify nothing is broken
8. Fix any test failures
9. Ensure your code is clean and well-documented

{feedback_section}

## Constraints
- Follow existing code style and patterns
- Do not modify unrelated files
- Write meaningful commit messages
- All tests must pass before you finish
```

The `{design_docs_section}` is injected when `--design-docs` is provided:
```markdown
## Design Documents
Read design documents at `.dkmv/design_docs/` for architectural guidance.
These are reference material — do not modify them.
```

**User stories:** US-05, US-06, US-07, US-08, US-09, US-10, US-11

---

### Feature F8: QA Component

**Priority:** 6 (depends on F6; can be built after Dev is working)

**What it does:** Checks out a branch, runs tests, evaluates code quality against the PRD, produces a structured QA report.

**CLI command:**
```
dkmv qa --branch <branch> --repo <git-url> --prd <path> [options]

Options:
  --branch TEXT            Git branch to evaluate (required)
  --repo TEXT              Git repo URL (required)
  --prd PATH               Path to PRD file (required)
  --model TEXT             Claude model to use
  --max-turns INT          Maximum agent turns
  --timeout INT            Wall-clock timeout in minutes (default: 30)
  --keep-alive             Keep container running
  --verbose                Show full stream events
```

**Execution flow:**
1. Start container, clone repo, checkout branch
2. Copy PRD into workspace — **including** `## Evaluation Criteria` section (QA evaluates against both requirements and criteria)
3. Build QA prompt from component's `prompt.md`
4. Run Claude Code — agent runs tests, reviews code, evaluates PRD coverage and evaluation criteria
5. Agent writes QA report as `.dkmv/qa_report.json` in the workspace
6. Explicitly `git add .dkmv/qa_report.json` then commit to branch, push (QA artifacts are intentionally committed, unlike Dev which gitignores `.dkmv/`)
7. Parse QA report into QAResult, save run

**Prompt template core instructions:**
- Run the full test suite and report results
- Check for regressions against main branch
- Evaluate each PRD requirement: is it implemented? correctly?
- Evaluate each item in the `## Evaluation Criteria` section (if present)
- Review code quality: error handling, edge cases, security
- Produce a structured JSON report at `.dkmv/qa_report.json`

**User stories:** US-12, US-13, US-14

---

### Feature F9: Judge Component

**Priority:** 7 (depends on F6; builds after QA is working)

**What it does:** Independently evaluates the implementation. Reviews code and QA report, produces a pass/fail verdict with actionable feedback.

**CLI command:**
```
dkmv judge --branch <branch> --repo <git-url> --prd <path> [options]

Options:
  --branch TEXT            Git branch to evaluate (required)
  --repo TEXT              Git repo URL (required)
  --prd PATH               Path to PRD file (required)
  --model TEXT             Claude model to use
  --max-turns INT          Maximum agent turns
  --timeout INT            Wall-clock timeout in minutes (default: 30)
  --keep-alive             Keep container running
  --verbose                Show full stream events
```

**Execution flow:**
1. Start container, clone repo, checkout branch
2. Copy PRD into workspace — **including** `## Evaluation Criteria` section (Judge evaluates against both requirements and criteria)
3. Build Judge prompt from component's `prompt.md`
4. Run Claude Code — agent reviews everything against requirements and evaluation criteria, writes verdict
5. Agent writes verdict as `.dkmv/verdict.json`
6. Explicitly `git add .dkmv/verdict.json` then commit to branch, push (Judge artifacts are intentionally committed, unlike Dev which gitignores `.dkmv/`)
7. Parse verdict into JudgeResult, save run
8. Print verdict prominently (PASS in green, FAIL in red, with summary)

**Verdict JSON schema:**
```json
{
  "verdict": "pass|fail",
  "confidence": 0.85,
  "reasoning": "Overall assessment...",
  "prd_requirements": [
    {"requirement": "User login", "status": "implemented", "notes": "..."},
    {"requirement": "Password reset", "status": "missing", "notes": "..."}
  ],
  "issues": [
    {"severity": "critical|major|minor", "file": "src/auth.py", "line": 42, "description": "..."}
  ],
  "suggestions": ["Consider adding rate limiting", "..."]
}
```

**Key design choice:** Judge CANNOT see Dev's reasoning or internal process. It only sees the code, tests, and QA report. This ensures independent evaluation.

**User stories:** US-15, US-16, US-17

---

### Feature F10: Docs Component

**Priority:** 8 (last component; depends on F6)

**What it does:** Generates or updates documentation for the feature, optionally creates a pull request.

**CLI command:**
```
dkmv docs --branch <branch> --repo <git-url> [options]

Options:
  --branch TEXT            Git branch (required)
  --repo TEXT              Git repo URL (required)
  --create-pr              Create a pull request to main
  --pr-base TEXT           Base branch for PR (default: main)
  --model TEXT             Claude model to use
  --max-turns INT          Maximum agent turns
  --timeout INT            Wall-clock timeout in minutes (default: 30)
  --keep-alive             Keep container running
  --verbose                Show full stream events
```

**Execution flow:**
1. Start container, clone repo, checkout branch
2. Build Docs prompt from component's `prompt.md`
3. Run Claude Code — agent reads code, generates docs, updates README
4. Commit docs to branch, push
5. If `--create-pr`: run `gh pr create --base main --head <branch> --title "..." --body "..."`
6. Parse PR URL, save DocsResult

**User stories:** US-18, US-19

---

### Feature F11: Run Management Commands

**Priority:** 9 (utility; can be built after core components work)

**What it does:** `dkmv runs`, `dkmv show`, `dkmv attach`, `dkmv stop` — inspection and management of runs.

**Commands:**

`dkmv runs` — List recent runs
```
$ dkmv runs
ID        COMPONENT  REPO           BRANCH              STATUS   COST    DURATION  WHEN
abc123    dev        myorg/myapp    feature/login-dev    success  $0.12   3m 42s    2h ago
def456    qa         myorg/myapp    feature/login-dev    success  $0.08   2m 15s    1h ago
ghi789    judge      myorg/myapp    feature/login-dev    success  $0.05   1m 03s    45m ago
```
Options: `--component dev|qa|judge|docs`, `--limit N`, `--status success|failure|error|running`

`dkmv show <run-id>` — Show run details
```
$ dkmv show abc123
Run: abc123
Component: dev
Status: success
Repo: git@github.com:myorg/myapp.git
Branch: feature/login-dev
Model: claude-sonnet-4-20250514
Cost: $0.12
Duration: 3m 42s
Turns: 23
Files changed: src/auth/login.py, tests/test_login.py, src/auth/__init__.py
Log: outputs/runs/abc123/run.log
Stream: outputs/runs/abc123/stream.jsonl
```

`dkmv attach <run-id>` — Attach to running container
- Looks up container name from run metadata
- Runs `docker exec -it <container> bash`
- Fails with message if container not running

`dkmv stop <run-id>` — Stop a keep-alive container
- Looks up container from run metadata
- Runs SandboxManager.stop() or `docker stop/rm`
- Updates run status

**User stories:** US-20, US-21, US-22, US-23, US-24

---

## 7. Feature Dependency Order & Build Sequence

```
Phase 1: Foundation
───────────────────
F1: CLI Framework & Config          ← Everything depends on this
F2: Docker Image & Build Command    ← Components need a container to run in

Phase 2: Core Framework
───────────────────
F3: SandboxManager (SWE-ReX wrapper)  ← Components need container lifecycle
F4: RunManager & Results               ← Components need run tracking
F5: StreamParser                       ← Components need output rendering
F6: BaseComponent ABC                  ← Components need shared interface

Phase 3: Components (sequential — each validates the stack further)
───────────────────
F7: Dev Component       ← First component, validates entire stack end-to-end
F8: QA Component        ← Second component, validates component isolation model
F9: Judge Component     ← Third component, validates inter-component data flow via git
F10: Docs Component     ← Fourth component, validates PR creation flow

Phase 4: Utilities
───────────────────
F11: Run Management Commands  ← Nice-to-have tooling, not on critical path
```

---

## 8. Implementation Plan — Task Breakdown

### Phase 0: Testing Infrastructure

**Task 0.1: Unit Test Foundation**
- [ ] Set up `tests/` directory at project root (not inside `dkmv/`)
- [ ] Configure pytest in `pyproject.toml` with `asyncio_mode = "auto"` and `e2e` marker
- [ ] Write unit tests for StreamParser: parse hardcoded stream-json lines, verify event extraction
- [ ] Write unit tests for RunManager: file I/O with pytest `tmp_path`, JSON round-trips
- [ ] Write unit tests for Config: env var loading with `monkeypatch.setenv()`
- [ ] Write unit tests for Result models: Pydantic validation, serialization round-trips

**Task 0.2: Integration Test Fixtures**
- [ ] Create `tests/integration/conftest.py` with SWE-ReX mocks (`DockerDeployment`, `RemoteRuntime`)
- [ ] Create mock sandbox session that records commands
- [ ] Write helper to create temporary test repos with `src/`, `tests/`

### Phase 1: Foundation

**Task 1.1: Project Scaffolding**
- [ ] Create uv-managed project with `pyproject.toml` (hatchling build system)
- [ ] Create subpackage directory structure per Section 3.1
- [ ] Create `dkmv/__init__.py`, `dkmv/__main__.py`, `dkmv/cli.py` with Typer app
- [ ] Create `dkmv/utils/async_support.py` with `async_command` decorator
- [ ] Verify `uv sync && uv run dkmv --help` works
- [ ] Create `.python-version` with `3.12`
- [ ] Add `uv.lock` to git
- [ ] Create `.gitignore`, `README.md`
- [ ] Create `docs/` directory structure per Section 3.4
- [ ] Create `docs/decisions/` directory. Write ADR-0001 (record architecture decisions)
- [ ] Write `docs/getting-started/installation.md` as first doc
- [ ] Configure ruff and mypy in `pyproject.toml`
- [ ] Set up `.pre-commit-config.yaml` with Commitizen commit-msg hook and ruff linting hooks

**Task 1.2: Global Configuration**
- [ ] Create `dkmv/config.py` with `pydantic-settings` `BaseSettings` model (env vars + `.env` file, no YAML)
- [ ] Implement Typer `@app.callback()` for global options (`--verbose`, `--dry-run`)
- [ ] Validate API key at startup with helpful error message
- [ ] Test: config loads from env vars and `.env` file

**Task 1.3: Docker Image**
- [ ] Create `dkmv/images/Dockerfile` per spec in F2 (node:20-bookworm base)
- [ ] Create `dkmv build` CLI command with `--no-cache` and `--claude-version` flags
- [ ] Support `--build-arg CLAUDE_CODE_VERSION=X.Y.Z` for version pinning
- [ ] Implement build with progress output
- [ ] Test: `dkmv build` produces working image
- [ ] Test: container starts, `claude --version` works, runs as user `dkmv`
- [ ] Write `tests/docker/test_image.sh` with image structure assertions (non-root user `dkmv` at UID 1000, tool availability, env vars, working directory)

**Task 1.4: GitHub Actions CI Pipeline**
- [ ] Set up `.github/workflows/ci.yml` with lint, typecheck, unit test, and Docker build stages
- [ ] Lint and typecheck run in parallel (fast, independent)
- [ ] Unit tests depend on lint + typecheck passing
- [ ] Docker build runs in parallel with tests
- [ ] E2E tests only on main merge / nightly (API cost control)
- [ ] Use `astral-sh/setup-uv` action for consistent uv version

### Phase 2: Core Framework

**Task 2.1: SandboxManager**
- [ ] Create `dkmv/core/sandbox.py`
- [ ] Implement `start()` using SWE-ReX DockerDeployment with `--memory=8g --memory-swap=8g` default docker_args
- [ ] Implement `execute()` using SWE-ReX runtime.run_in_session()
- [ ] Implement `stream_claude()` — run claude CLI, capture stdout line-by-line
- [ ] Implement `stop()` with keep_alive logic
- [ ] Implement `write_file()` and `read_file()` via SWE-ReX `WriteFileRequest`/`ReadFileRequest`
- [ ] Handle env var forwarding (ANTHROPIC_API_KEY, GITHUB_TOKEN)
- [ ] Use `gh auth setup-git` for git auth instead of SSH key mounting
- [ ] Implement asyncio timeout wrapper (based on `timeout_minutes`)
- [ ] Test: start container, run command, get output, stop container
- [ ] Test: run claude -p with simple prompt inside container

**Task 2.2: RunManager**
- [ ] Create `dkmv/core/runner.py`
- [ ] Implement run ID generation (short UUID or timestamp-based)
- [ ] Implement run directory creation
- [ ] Implement `save_result()` — serialize Pydantic BaseModel to JSON, includes session_id
- [ ] Implement `append_stream()` — append to JSONL file
- [ ] Implement `list_runs()` — scan output directory
- [ ] Implement `get_run()` — load from directory
- [ ] Create shared Pydantic models in `dkmv/core/models.py` (BaseResult, BaseComponentConfig, SandboxConfig)
- [ ] Save session_id from stream-json `type: "result"` events
- [ ] Test: create run, save result, list runs, get run

**Task 2.3: StreamParser**
- [ ] Create `dkmv/core/stream.py`
- [ ] Implement line-by-line JSON parsing
- [ ] Implement terminal rendering using `rich`
- [ ] Handle: `type: "system"` with `subtype: "init"`, assistant text, tool use, tool results, errors, final result
- [ ] Extract final result (cost, duration, turns, session_id) from `type: "result"` event
- [ ] Test: parse sample stream-json output, verify rendering

**Task 2.4: BaseComponent**
- [ ] Create `dkmv/components/base.py` with `BaseComponent(ABC, Generic[C, R])`
- [ ] Implement standard `run()` method with the 12-step flow
- [ ] Implement `_load_prompt_template()` using `importlib.resources` to read co-located `prompt.md`
- [ ] Implement shared setup logic: clone repo, checkout/create branch, `gh auth setup-git`
- [ ] Implement CLAUDE.md generation in workspace setup
- [ ] Implement `.dkmv/` `.gitignore` addition in workspace setup (for Dev component)
- [ ] Implement shared teardown: git add, commit, push
- [ ] Create component registry in `dkmv/components/__init__.py` (`register_component()`, `get_component()`)
- [ ] Define abstract methods for subclasses
- [ ] Test: create a minimal test component, run it, verify lifecycle

### Phase 3: Components

**Task 3.1: Dev Component**
- [ ] Create `dkmv/components/dev/` subpackage (component.py, models.py, prompt.md, __init__.py)
- [ ] Implement DevConfig and DevResult in `models.py`
- [ ] Implement DevComponent in `component.py` extending `BaseComponent[DevConfig, DevResult]`
- [ ] Register via `@register_component("dev")` decorator
- [ ] Implement `build_prompt()` — inject PRD content (with `## Evaluation Criteria` stripped), feedback if any, design docs reference if any
- [ ] Implement `parse_result()` — extract files changed, test counts
- [ ] Register `dkmv dev` command in cli.py with all options (including `--timeout`, `--design-docs`, `--feature-name`, `--require-plan`)
- [ ] Handle `--design-docs` flag: copy to `.dkmv/design_docs/` in workspace, inject reference in prompt
- [ ] Handle `--feature-name` flag: use for branch naming (`feature/<name>-dev`) and run metadata
- [ ] Handle fresh branch creation vs existing branch checkout
- [ ] Handle feedback injection from synthesized feedback brief (not raw Judge verdict)
- [ ] Update Dev prompt to enforce plan-first approach. Capture `.dkmv/plan.md` as run artifact
- [ ] **End-to-end test:** run against a real (small) repo with a simple PRD
- [ ] Iterate on prompt until quality is acceptable for basic cases

**Task 3.2: QA Component**
- [ ] Create `dkmv/components/qa/` subpackage (component.py, models.py, prompt.md, __init__.py)
- [ ] Implement QAConfig and QAResult in `models.py`
- [ ] Implement QAComponent extending `BaseComponent[QAConfig, QAResult]`
- [ ] Register via `@register_component("qa")` decorator
- [ ] Implement `build_prompt()` — inject PRD, instruct QA report format
- [ ] Implement `parse_result()` — parse QA report JSON from branch
- [ ] Register `dkmv qa` command in cli.py (including `--timeout`)
- [ ] Explicitly `git add .dkmv/qa_report.json` (QA artifacts are committed, not gitignored)
- [ ] **End-to-end test:** run QA on a branch produced by Dev
- [ ] Verify QA report is committed to branch

**Task 3.3: Judge Component**
- [ ] Create `dkmv/components/judge/` subpackage (component.py, models.py, prompt.md, __init__.py)
- [ ] Implement JudgeConfig and JudgeResult in `models.py`
- [ ] Implement JudgeComponent extending `BaseComponent[JudgeConfig, JudgeResult]`
- [ ] Register via `@register_component("judge")` decorator
- [ ] Implement `build_prompt()` — inject PRD, emphasize independence
- [ ] Implement `parse_result()` — parse verdict JSON
- [ ] Register `dkmv judge` command in cli.py (including `--timeout`)
- [ ] Explicitly `git add .dkmv/verdict.json` (Judge artifacts are committed, not gitignored)
- [ ] Implement verdict display (colored PASS/FAIL in terminal)
- [ ] **End-to-end test:** run Judge on a branch with QA report
- [ ] Verify feedback file can be fed back to Dev

**Task 3.4: Docs Component**
- [ ] Create `dkmv/components/docs/` subpackage (component.py, models.py, prompt.md, __init__.py)
- [ ] Implement DocsConfig and DocsResult in `models.py`
- [ ] Implement DocsComponent extending `BaseComponent[DocsConfig, DocsResult]`
- [ ] Register via `@register_component("docs")` decorator
- [ ] Implement `build_prompt()` — instruct doc generation
- [ ] Implement PR creation via `gh pr create` inside container
- [ ] Implement `parse_result()` — extract docs list, PR URL
- [ ] Register `dkmv docs` command in cli.py (including `--timeout`)
- [ ] **End-to-end test:** run Docs, verify PR created

**Task 3.5: Prompt Snapshot Tests**
- [ ] Write syrupy snapshot tests for all prompt templates
- [ ] Verify prompt building with different config combinations (PRD only, PRD + feedback, etc.)

### Phase 4: Utilities

**Task 4.1: Run Management Commands**
- [ ] Implement `dkmv runs` — table output using rich
- [ ] Implement `dkmv show <run-id>` — detailed view
- [ ] Implement `dkmv attach <run-id>` — docker exec passthrough
- [ ] Implement `dkmv stop <run-id>` — container cleanup
- [ ] Test all commands

---

## 9. Technical Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Claude Code `--dangerously-skip-permissions` fails as root in Docker | Agent won't run | Use non-root `dkmv` user in Dockerfile; test during image build |
| SWE-ReX port conflicts when running multiple containers | Parallel runs fail | SWE-ReX handles automatic port allocation; verify in testing |
| Claude Code stream-json format changes between versions | StreamParser breaks | Pin Claude Code version in Dockerfile via `--build-arg CLAUDE_CODE_VERSION`; parse defensively |
| Long-running agent exceeds timeout | Run fails with partial work | Git commits happen inside agent loop (work is preserved); expose `--max-turns` |
| Private repo git auth | Can't clone/push to private repos | `GITHUB_TOKEN` + `gh auth setup-git` handles HTTPS-based clone/push. No SSH keys needed. Fine-grained tokens can scope to specific repos. |
| Agent writes poor code on first attempt | Quality varies | Prompts are iteratable (just edit .md files); Judge provides feedback loop; user can re-run with `--feedback` |
| SWE-ReX version incompatibility | Container startup fails | Pin swe-rex version in both pyproject.toml and Dockerfile |
| Claude Code OOM (JS heap ~2GB, memory leaks) | Container crash, partial work lost | `--memory=8g` on container, `NODE_OPTIONS=--max-old-space-size=4096` in image, save session_id for potential resume |
| Container stuck indefinitely | Blocks developer, wastes money | `--timeout` wall-clock limit (default 30 min), asyncio timeout wrapper |
| Container crash / Claude Code OOM mid-run | Partial work may be lost (but git commits inside the agent loop are preserved) | Save session_id for potential `--continue` resume. Run directory preserves `stream.jsonl` for diagnosis. `--keep-alive` allows manual recovery. |
| Large repos exhaust file descriptors | Claude Code crashes | Add `.claudeignore` to workspace excluding `node_modules`, `.git/objects` etc. |
| Claude Code npm install deprecated | Future build breaks | Monitor Anthropic's official Dockerfile; pin version via build arg; switch to native installer when OOM bug fixed |

---

## 9.5 Testing Strategy

### 9.5.1 Test Levels

1. **Unit tests** (run on every commit, no Docker/API needed):
   - StreamParser: parse hardcoded stream-json lines, verify event extraction
   - RunManager: file I/O with pytest `tmp_path`, JSON round-trips
   - Config: env var loading with `monkeypatch.setenv()`
   - Result models: Pydantic validation, serialization round-trips
   - Prompt building: syrupy snapshot tests for template output

2. **Integration tests** (run on every commit, mocked SWE-ReX):
   - SandboxManager: mock `DockerDeployment` + `RemoteRuntime`, verify lifecycle
   - BaseComponent: mock sandbox, verify 12-step run() flow
   - Component-specific: mock sandbox responses, verify prompt building + result parsing

3. **E2E smoke tests** (nightly/manual, requires Docker + API key):
   - Test repo: dynamically created minimal repo with `src/`, `tests/`
   - Test PRD: trivial feature ("add greet() function")
   - Model: `claude-haiku-4-5-20251001` (cheapest), max-turns: 10
   - Marked with `@pytest.mark.e2e`, excluded from default pytest runs
   - Skip decorators: `skip_no_docker`, `skip_no_api_key`

4. **pytest configuration** in pyproject.toml:
   ```toml
   [tool.pytest.ini_options]
   testpaths = ["tests"]
   asyncio_mode = "auto"
   markers = ["e2e: end-to-end tests requiring Docker and API key"]
   ```

### 9.5.2 Coverage Requirements

- Target: **80% line + branch coverage** overall, enforced in CI via `pytest --cov-fail-under=80`
- Core modules (`core/models.py`, `config.py`, `core/stream.py`, `core/runner.py`): target **90%+**
- Exclude from coverage: `tests/*`, `TYPE_CHECKING` blocks, `__main__.py`

### 9.5.3 Linting & Type Checking

Linting and type checking are quality gates, not just dev conveniences:
- `ruff check .` + `ruff format --check .` — lint and format check
- `mypy dkmv/` — type check all source code
- Both run in CI before tests (fail fast)
- Both should be runnable locally: `uv run ruff check .` and `uv run mypy dkmv/`

### 9.5.4 CI/CD Pipeline

| Stage | Trigger | What runs | Blocks merge? |
|-------|---------|-----------|--------------|
| Lint | Every PR | `ruff check`, `ruff format --check` | Yes |
| Type check | Every PR | `mypy dkmv/` | Yes |
| Unit tests | Every PR | `pytest tests/unit/ --cov --cov-fail-under=80` | Yes |
| Integration tests | Every PR | `pytest tests/integration/` | Yes |
| Docker image tests | Every PR | Build image + shell assertions | Yes |
| E2E tests | Merge to main / nightly | `pytest tests/e2e/ -m e2e` (requires API key) | No (advisory) |

- Lint and type check run in parallel (fast, independent)
- Unit tests depend on lint + typecheck passing
- Docker build runs in parallel with tests
- E2E tests only on main (API cost control)
- Use `astral-sh/setup-uv` action for consistent uv version

### 9.5.5 Docker Image Tests

- Shell script at `tests/docker/test_image.sh`
- Assertions: non-root user `dkmv` at UID 1000, `claude --version`, `gh --version`, `git --version`, `python3 --version`, `swerex-remote` available, `IS_SANDBOX=1` set, `NODE_OPTIONS` set, working directory correct
- Runs in CI after Docker build step
- Alternative for later: Google's container-structure-test (YAML-based, more declarative)

### 9.5.6 Test Fixture Strategy

- `tests/conftest.py`: shared fixtures and factory functions
- `tests/factories.py`: polyfactory-based model factories for all Pydantic models (configs, results, stream events)
- Key fixtures:
  - `git_repo` — temporary git repo with initial commit (via `tmp_path`)
  - `mock_sandbox` — AsyncMock SandboxManager that records commands
  - `mock_anthropic` — mock API responses for stream-json events
  - `make_config` — factory function for DKMVConfig with sensible test defaults
- All async mocks use `unittest.mock.AsyncMock` (stdlib, no extra dependency)

### 9.5.7 Regression Testing Convention

- When a bug is found: write a failing test FIRST, then fix the bug
- Regression tests go in the same test file as related tests (not a separate directory)
- Name pattern: `test_<description>_regression_<issue_number>` (when linked to an issue)
- This is a convention, not tooling — enforced via code review

---

## 10. Configuration Reference

Configuration is purely env vars + optional `.env` file. No YAML config file.

### `.env` (project root, gitignored)
```
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...
DKMV_MODEL=claude-sonnet-4-20250514
DKMV_MAX_TURNS=100
DKMV_IMAGE=dkmv-sandbox:latest
DKMV_OUTPUT_DIR=./outputs
DKMV_TIMEOUT=30
DKMV_MEMORY=8g
```

### Environment Variables
```
ANTHROPIC_API_KEY   — Anthropic API key (required)
GITHUB_TOKEN        — GitHub personal access token (required for private repos and PR creation, ensure `repo` scope)
DKMV_MODEL          — Default Claude model (default: claude-sonnet-4-20250514)
DKMV_MAX_TURNS      — Default max agent turns (default: 100)
DKMV_IMAGE          — Docker image name (default: dkmv-sandbox:latest)
DKMV_OUTPUT_DIR     — Output directory (default: ./outputs)
DKMV_TIMEOUT        — Wall-clock timeout in minutes (default: 30)
DKMV_MEMORY         — Container memory limit (default: 8g)
```

---

## 11. Dependencies

### pyproject.toml
```toml
[project]
name = "dkmv"
version = "0.1.0"
description = "CLI tool that orchestrates AI agents to implement software features end-to-end"
readme = "README.md"
license = "MIT"
requires-python = ">=3.12"
dependencies = [
    "typer>=0.15.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "swe-rex>=1.4",
    "rich>=13.0",
]

[project.scripts]
dkmv = "dkmv.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-cov>=6.0",
    "pytest-timeout>=2.3",
    "syrupy>=4.0",
    "polyfactory>=2.0",
    "ruff>=0.8",
    "mypy>=1.11",
    "commitizen>=4.0",
    "pre-commit>=4.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = ["e2e: end-to-end tests requiring Docker and API key"]

[tool.ruff]
target-version = "py312"
line-length = 100
```

### System requirements
```
Python >= 3.12
Docker >= 24.0 (or Podman with Docker compatibility)
Git >= 2.30
uv >= 0.6              (install: curl -LsSf https://astral.sh/uv/install.sh | sh)
```

### Inside Docker image
```
Node.js 20 (base image: node:20-bookworm)
Claude Code CLI (npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION})
GitHub CLI (gh, from official GitHub repo)
Python 3, pip, venv, pipx
Git
SWE-ReX remote server (pipx install swe-rex)
```

---

## 12. Success Criteria for v1

1. **`dkmv build` works** — builds the Docker image in under 5 minutes
2. **`dkmv dev` produces working code** — given a simple PRD and repo, creates a branch with a reasonable implementation
3. **`dkmv qa` produces a report** — evaluates the branch and commits a structured QA report
4. **`dkmv judge` produces a verdict** — independently evaluates and gives pass/fail with actionable feedback
5. **`dkmv docs` generates docs and optionally creates a PR** — documentation is reasonable and PR is properly formed
6. **Feedback loop works** — Judge verdict can be fed back to Dev, Dev iterates on the same branch
7. **Cost tracking works** — every run reports its cost in USD
8. **Components are truly modular** — changing a prompt file or component .py file requires zero changes to any other file
9. **Real-time streaming works** — user sees what the agent is doing as it works, not just the final result
10. **Runs are inspectable** — `dkmv runs` and `dkmv show` provide useful information about past runs
11. **Key architecture decisions are documented** — ADRs exist in `docs/decisions/` for major choices (CLI framework, Docker base image, sandbox layer, etc.)

---

## 13. v2+ Roadmap (Out of Scope for v1, but Architecture Supports)

- **Claude Code Agent Teams integration** — Anthropic shipped native multi-agent orchestration with Opus 4.6. For v2, the pipeline could use Agent Teams instead of separate containers per stage.
- **Session resume (`--continue`)** — Use saved session_id to resume failed runs without starting over.
- **PRD template/schema** — Define a structured PRD format to improve consistency.
- **`dkmv pipeline` command** — auto-chain Dev → QA → Judge → Docs with configurable retry on failure
- **PRD Refiner component** — `dkmv refine` improves PRDs before Dev
- **Parallel execution** — run multiple features simultaneously (SWE-ReX + asyncio.gather)
- **Multi-branch per stage** — feature/login-dev → feature/login-qa → feature/login-docs
- **Cloud burst** — swap DockerDeployment → ModalDeployment for GPU/high-memory tasks
- **MCP integration** — configure MCP servers in container for additional agent capabilities
- **Web dashboard** — visualize pipeline runs, costs, quality trends
- **Custom component plugins** — third-party components via entry_points
- **Eval framework** — benchmark component quality on known tasks with scoring
- **MCP Memory Server** — cross-feature learning via semantic search across past runs, common patterns, recurring issues
- **Alternative agent runtimes** — Codex CLI, Anthropic Agent SDK custom agents, open-source alternatives. BaseComponent's `stream_claude()` would become `stream_agent()` with a provider parameter
- **PRD dependency graph** — model dependencies between PRDs within a feature, enable parallel execution of independent PRDs
- **PRD Refiner auto-generates `## Evaluation Criteria`** — automatically derive evaluation criteria from requirements
- **Feedback synthesis via lightweight LLM call** — convert raw verdict into developer instructions with context from the codebase (upgrade from v1's Python-only transformation)