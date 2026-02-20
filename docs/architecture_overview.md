# DKMV Architecture Overview

DKMV is a Python CLI tool that orchestrates AI agents (Claude Code) inside isolated Docker containers to implement software features end-to-end. Each agent is a specialized **component** — Dev writes code, QA validates it, Judge evaluates quality, and Docs generates documentation. Components run in fresh containers and communicate only through git branches.

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        YOUR MACHINE (Host)                       │
│                                                                  │
│  ┌─────────┐    ┌──────────────────────────────────────────────┐ │
│  │  .env   │───>│              DKMV CLI (typer)                │ │
│  │  file   │    │                                              │ │
│  └─────────┘    │  ┌────────────────────────────────────────┐  │ │
│                 │  │          DKMVConfig                     │  │ │
│                 │  │  (pydantic-settings, reads env + .env)  │  │ │
│                 │  └──────────────┬─────────────────────────┘  │ │
│                 │                 │                             │ │
│                 │     ┌───────────┴───────────┐                │ │
│                 │     │                       │                │ │
│                 │  ┌──▼──────────┐  ┌────────▼─────────┐      │ │
│                 │  │  Component  │  │   RunManager      │      │ │
│                 │  │ (Dev/QA/    │  │ (persists runs    │      │ │
│                 │  │  Judge/Docs)│  │  to outputs/runs/)│      │ │
│                 │  └──┬──────────┘  └──────────────────┘      │ │
│                 │     │                                        │ │
│                 │  ┌──▼──────────────────┐                     │ │
│                 │  │   SandboxManager    │                     │ │
│                 │  │ (manages container  │                     │ │
│                 │  │  via SWE-ReX)       │                     │ │
│                 │  └──┬─────────────────┘                     │ │
│                 └─────┼────────────────────────────────────────┘ │
│                       │ docker run -e ANTHROPIC_API_KEY=...      │
│                       │ docker run -e GITHUB_TOKEN=...           │
│                       ▼                                          │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              DOCKER CONTAINER (dkmv-sandbox)                │  │
│  │                                                             │  │
│  │  User: dkmv (UID 1000)     Image: node:20-bookworm         │  │
│  │                                                             │  │
│  │  ┌─────────────────────────────────────────────────────┐   │  │
│  │  │  SWE-ReX (swerex-remote)                            │   │  │
│  │  │  Listens on port 8000, receives commands from host  │   │  │
│  │  └────────────────────┬────────────────────────────────┘   │  │
│  │                       │                                     │  │
│  │  ┌────────────────────▼────────────────────────────────┐   │  │
│  │  │  Bash Sessions                                      │   │  │
│  │  │  ├── "main"  — git clone, setup, launch claude      │   │  │
│  │  │  └── "tail"  — polls /tmp/dkmv_stream.jsonl         │   │  │
│  │  └─────────────────────────────────────────────────────┘   │  │
│  │                                                             │  │
│  │  ┌────────────────────────────────────────┐                │  │
│  │  │  /home/dkmv/workspace/                 │                │  │
│  │  │  ├── (cloned repo)                     │                │  │
│  │  │  ├── .claude/CLAUDE.md  (agent rules)  │                │  │
│  │  │  └── .dkmv/                            │                │  │
│  │  │      ├── prd.md         (requirements) │                │  │
│  │  │      ├── plan.md        (Dev plan)     │                │  │
│  │  │      ├── qa_report.json (QA output)    │                │  │
│  │  │      └── verdict.json   (Judge output) │                │  │
│  │  └────────────────────────────────────────┘                │  │
│  │                                                             │  │
│  │  Claude Code (headless) ──> /tmp/dkmv_stream.jsonl         │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                       │                                          │
│                       │ git push origin feature/...              │
│                       ▼                                          │
│                   ┌────────┐                                     │
│                   │ GitHub │                                     │
│                   └────────┘                                     │
└──────────────────────────────────────────────────────────────────┘
```

---

## The Component Pipeline

Components are designed to run sequentially on the same git branch. Each component sees the work of the previous ones through the shared branch:

```
                        ┌─────────────┐
                        │     PRD     │  (Product Requirements Document)
                        └──────┬──────┘
                               │
                 ┌─────────────▼──────────────┐
                 │         DEV Agent           │
                 │  - Reads PRD (eval stripped) │
                 │  - Creates plan.md           │
                 │  - Implements code + tests   │
                 │  - Commits to branch         │
                 └─────────────┬──────────────┘
                               │ git push
                 ┌─────────────▼──────────────┐
                 │         QA Agent            │
                 │  - Reads FULL PRD           │
                 │  - Runs tests               │
                 │  - Evaluates requirements   │
                 │  - Writes qa_report.json    │
                 └─────────────┬──────────────┘
                               │ git push
                 ┌─────────────▼──────────────┐
                 │       JUDGE Agent           │
                 │  - Reads FULL PRD           │
                 │  - Independent evaluation   │
                 │  - Writes verdict.json      │
                 │  - Pass/Fail + Score        │
                 └─────────────┬──────────────┘
                               │
                     ┌─────────┴─────────┐
                     │                   │
               ┌─────▼────┐        ┌─────▼─────┐
               │   PASS   │        │   FAIL    │
               └─────┬────┘        └─────┬─────┘
                     │                   │
          ┌──────────▼──────┐    ┌───────▼──────────┐
          │   DOCS Agent    │    │   DEV Agent       │
          │  - Generate docs│    │   (re-run with    │
          │  - Optional PR  │    │    feedback from   │
          └─────────────────┘    │    Judge verdict)  │
                                 └──────────────────┘
```

**Key design decision:** Dev never sees the Evaluation Criteria section of the PRD. This prevents the Dev agent from gaming the evaluation. QA and Judge both see the full PRD.

---

## Core Infrastructure

Three managers provide the foundation that all components share:

```
┌───────────────────────────────────────────────────────────────┐
│                     BaseComponent.run()                        │
│                                                               │
│  Uses three managers:                                         │
│                                                               │
│  ┌─────────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │ SandboxManager   │  │  RunManager  │  │  StreamParser   │  │
│  │                  │  │              │  │                 │  │
│  │ start()          │  │ start_run()  │  │ parse_line()    │  │
│  │ execute()        │  │ save_result()│  │ render_event()  │  │
│  │ stream_claude()  │  │ append_      │  │                 │  │
│  │ setup_git_auth() │  │   stream()   │  │ Parses Claude   │  │
│  │ read_file()      │  │ save_prompt()│  │ Code stream-json│  │
│  │ write_file()     │  │ list_runs()  │  │ events and      │  │
│  │ stop()           │  │ get_run()    │  │ renders them to │  │
│  │                  │  │              │  │ the terminal    │  │
│  │ Wraps SWE-ReX    │  │ File-based   │  │ via Rich        │  │
│  │ DockerDeployment │  │ persistence  │  │                 │  │
│  └─────────────────┘  └──────────────┘  └─────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

### SandboxManager

Manages the Docker container lifecycle through SWE-ReX. SWE-ReX is a third-party library that provides `DockerDeployment` (starts/stops containers) and `RemoteRuntime` (executes commands inside them via an HTTP API on port 8000).

**Key methods:**
- `start()` — Creates a Docker container, starts SWE-ReX runtime, opens a bash session
- `execute()` — Runs a shell command in the container, returns output + exit code
- `stream_claude()` — Launches Claude Code and streams its output back (see below)
- `setup_git_auth()` — Configures GitHub token: `gh auth login --with-token && gh auth setup-git`
- `stop()` — Closes sessions and removes the container (or keeps it alive)

### RunManager

File-based persistence for all run artifacts. Each run gets a directory:

```
outputs/runs/{run_id}/
├── config.json      Component config snapshot
├── prompt.md        The prompt sent to Claude Code
├── stream.jsonl     Every Claude Code event (one JSON per line, append-only)
├── result.json      Final result (atomic write via .tmp + os.replace)
├── container.txt    Docker container name (for attach/stop commands)
└── logs/
```

Run IDs are 8-character hex strings from `uuid4`. Results are written atomically (write to `.tmp`, then `os.replace`) to prevent partial reads.

### StreamParser

Parses Claude Code's `stream-json` output format into normalized `StreamEvent` objects and renders them to the terminal via Rich.

**Event types from Claude Code:**
| Type | What it represents |
|---|---|
| `system` | Session initialization (cwd, tools, model) |
| `assistant` | Claude's response — text or tool_use blocks |
| `user` | Tool execution results |
| `result` | Final summary — cost, duration, turns, success/error |

---

## File-Based Streaming (The Dual-Session Workaround)

This is the most important implementation detail to understand. SWE-ReX's `run_in_session()` is **blocking** — it waits for a command to finish before returning. But Claude Code can run for 30+ minutes. We need real-time output, not blocking.

**Solution:** Run Claude Code in the background, write output to a file, tail that file from a second session.

```
Container
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  Session "main":                                         │
│  ┌────────────────────────────────────────────────────┐  │
│  │  1. claude -p "..." --output-format stream-json    │  │
│  │       < /dev/null                                  │  │
│  │       > /tmp/dkmv_stream.jsonl                     │  │
│  │       2>/tmp/dkmv_stream.err                       │  │
│  │       & echo $!                                    │  │
│  │                                                    │  │
│  │  2. Periodically: kill -0 $PID   (is it alive?)   │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  Session "tail":                                         │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Periodically: tail -n +{N} /tmp/dkmv_stream.jsonl │  │
│  │  (reads new lines since last poll)                 │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  /tmp/dkmv_stream.jsonl  <── Claude writes here          │
│  /tmp/dkmv_stream.err    <── stderr captured here        │
│  /tmp/dkmv_prompt.md     <── prompt written here         │
│                                                          │
└──────────────────────────────────────────────────────────┘

Host (polling loop, 0.5s interval):
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  while True:                                             │
│    1. Check if PID alive  (via "main" session)           │
│    2. Read new lines      (via "tail" session)           │
│    3. Parse JSON, yield events to caller                 │
│    4. If "result" event seen + process dead → exit       │
│    5. If process dead, no result → read stderr, exit     │
│    6. If result seen + alive > 10s → kill (cost savings) │
│    7. Sleep 0.5s                                         │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

The `finally` block always kills the Claude Code process and closes the tail session — even on timeout — to prevent runaway API costs.

**Why `< /dev/null`?** SWE-ReX's pexpect sessions are **interactive bash** (job control enabled). Background processes get their own process group. If a background process tries to read from the terminal, the kernel sends **SIGTTIN** which freezes the process immediately — 0 bytes written, no error message. Redirecting stdin from `/dev/null` prevents this. Non-interactive shells (e.g., `docker exec bash -c`) don't have this issue because job control is disabled.

---

## The 12-Step Component Lifecycle

Every component (Dev, QA, Judge, Docs) executes the same lifecycle defined in `BaseComponent.run()`. Components customize behavior by overriding hooks.

```
BaseComponent.run(config)
│
├── 1. VALIDATE          config.repo required, timeout > 0
│
├── 2. CREATE RUN        RunManager.start_run() → run_id
│                        Writes config.json to outputs/runs/{run_id}/
│
├── 3. START SANDBOX     SandboxManager.start() → SandboxSession
│   │                    Launches Docker container via SWE-ReX
│   │                    Injects ANTHROPIC_API_KEY + GITHUB_TOKEN as -e flags
│   │
│   └── 3.5 SAVE         RunManager.save_container_name()
│          CONTAINER      (enables `dkmv attach` and `dkmv stop`)
│
├── 4. SETUP WORKSPACE
│   ├── Git auth          gh auth login --with-token
│   ├── Clone repo        git clone {repo} /home/dkmv/workspace
│   ├── Hook ●            pre_workspace_setup()  [can derive branch name]
│   ├── Checkout branch   git checkout {branch} || git checkout -b {branch}
│   ├── Create .dkmv/     mkdir .dkmv, add to .gitignore
│   └── Hook ●            setup_workspace()  [writes PRD, feedback, etc.]
│
├── 5. WRITE CLAUDE.MD   Agent instructions → .claude/CLAUDE.md
│
├── 6. BUILD PROMPT      Hook ●  build_prompt()  [loads template, injects config]
│                        RunManager.save_prompt()
│
├── 7. STREAM CLAUDE     SandboxManager.stream_claude()
│      CODE              For each event:
│                          RunManager.append_stream()     (persist)
│                          StreamParser.parse_line()       (normalize)
│                          StreamParser.render_event()     (display)
│                          Capture "result" event
│
├── 8. COLLECT RESULTS   Extract cost, duration, turns from result event
│   └── 8.5 ARTIFACTS    Hook ●  collect_artifacts()  [reads JSON from container]
│                        parse_result() + merge into result
│
├── 9. GIT TEARDOWN      git add -A → git commit → git push origin {branch}
│   └── 9.5 POST HOOK    Hook ●  post_teardown()  [PR creation, plan capture]
│
├── 10. MARK COMPLETE    result.status = "completed"
│
├── [ON ERROR]           TimeoutError → status = "timed_out"
│                        Exception    → status = "failed"
│
├── FINALLY: SAVE        RunManager.save_result()  (always, even on failure)
├── FINALLY: STOP        SandboxManager.stop()     (remove container or keep alive)
│
└── 12. RETURN           Typed result (DevResult, QAResult, etc.)
```

Steps marked with ● are hooks that components override to customize behavior.

---

## The Four Components

### Dev Component

**Purpose:** Implement a feature from a PRD. Plans first, then codes and tests.

**Hook overrides:**
| Hook | What Dev does |
|---|---|
| `pre_workspace_setup` | Auto-derives branch name: `feature/{feature_name}-dev` |
| `setup_workspace` | Writes PRD to `.dkmv/prd.md` **with evaluation criteria stripped** via regex. Optionally copies feedback and design docs |
| `build_prompt` | Loads `prompt.md`, conditionally adds design docs and feedback sections |
| `post_teardown` | Captures `.dkmv/plan.md` from container (saves to run artifacts) |

**Config (`DevConfig`):**
```
BaseComponentConfig +
  prd_path: Path              # PRD file (host path, required)
  feedback_path: Path | None  # Feedback from previous Judge run
  design_docs_path: Path | None  # Directory of design documents
```

**Result (`DevResult`):**
```
BaseResult +
  files_changed: list[str]     # Files modified/created
  tests_passed: int | None     # Test results
  tests_failed: int | None
```

**What Claude Code does inside the container:**
1. Reads `.dkmv/prd.md` (evaluation criteria already removed)
2. Explores codebase
3. Writes plan to `.dkmv/plan.md`
4. Implements the feature
5. Writes tests, runs them, fixes failures

### QA Component

**Purpose:** Validate the implementation against the full PRD, including evaluation criteria.

**Hook overrides:**
| Hook | What QA does |
|---|---|
| `setup_workspace` | Writes **full PRD** (with evaluation criteria) to `.dkmv/prd.md` |
| `build_prompt` | Loads `prompt.md` as-is |
| `collect_artifacts` | Reads `.dkmv/qa_report.json` from container |
| `_teardown_git` | Force-commits `.dkmv/qa_report.json` (even if .dkmv/ is gitignored) |

**Config (`QAConfig`):**
```
BaseComponentConfig +
  prd_path: Path  # Full PRD file (required)
```

**Result (`QAResult`):**
```
BaseResult +
  tests_total: int       # Total test count
  tests_passed: int
  tests_failed: int
  warnings: list[str]    # Quality warnings
```

**What Claude Code does inside the container:**
1. Reads the full PRD (sees evaluation criteria)
2. Runs the test suite
3. Evaluates each requirement and evaluation criterion
4. Reviews code quality
5. Writes structured report to `.dkmv/qa_report.json`

### Judge Component

**Purpose:** Independent pass/fail evaluation. Explicitly instructed to ignore QA reports and form its own assessment.

**Hook overrides:**
| Hook | What Judge does |
|---|---|
| `setup_workspace` | Writes **full PRD** to `.dkmv/prd.md` |
| `build_prompt` | Loads `prompt.md` as-is |
| `collect_artifacts` | Reads `.dkmv/verdict.json` from container |
| `_teardown_git` | Force-commits `.dkmv/verdict.json` |

**Config (`JudgeConfig`):**
```
BaseComponentConfig +
  prd_path: Path  # Full PRD file (required)
```

**Result (`JudgeResult`):**
```
BaseResult +
  verdict: "pass" | "fail"
  confidence: float (0.0–1.0)
  reasoning: str
  prd_requirements: list[PrdRequirement]  # Per-requirement status
  issues: list[JudgeIssue]               # Severity + description + file/line
  suggestions: list[str]
  score: int (0–100)
```

**Nested models:**
- `PrdRequirement`: `{requirement, status: implemented|missing|partial, notes}`
- `JudgeIssue`: `{severity: critical|high|medium|low, description, file, line, suggestion}`

**What Claude Code does inside the container:**
1. Reads the full PRD
2. Reviews implementation independently (ignores QA reports)
3. Runs the test suite
4. Evaluates each requirement
5. Writes verdict to `.dkmv/verdict.json` with pass/fail, score, and issues

### Docs Component

**Purpose:** Generate or update documentation. Optionally creates a GitHub PR.

**Hook overrides:**
| Hook | What Docs does |
|---|---|
| `build_prompt` | Loads `prompt.md` as-is |
| `post_teardown` | If `create_pr=True`: runs `gh pr create` in container |

**Config (`DocsConfig`):**
```
BaseComponentConfig +
  create_pr: bool = False   # Whether to create a PR
  pr_base: str = "main"     # Base branch for PR
```

**Result (`DocsResult`):**
```
BaseResult +
  docs_generated: list[str]   # Files created/updated
  pr_url: str | None          # PR URL if created
```

**What Claude Code does inside the container:**
1. Explores the codebase
2. Identifies APIs, config, and key concepts
3. Creates/updates documentation files
4. Commits changes

---

## Component Comparison

```
                    DEV           QA            JUDGE         DOCS
                    ─────────     ─────────     ─────────     ─────────
PRD Treatment       Stripped      Full          Full          None
                    (no eval      (sees eval    (sees eval
                    criteria)     criteria)     criteria)

Branch Naming       Auto-derived  From input    From input    From input
                    feature/X-dev

Artifact Written    .dkmv/        .dkmv/        .dkmv/        (docs files)
                    plan.md       qa_report     verdict
                                  .json         .json

Force-Commit        No            qa_report     verdict       No
                                  .json         .json

Post-Teardown       Capture       —             —             gh pr create
                    plan.md                                   (optional)

Modifies Code?      YES           No            No            No
                                  (read-only)   (read-only)   (docs only)
```

---

## The CLI Layer

The CLI is built with Typer. Each component has a corresponding command, plus utility commands for run management:

```
dkmv
├── build                     Build the Docker image
├── dev <repo> --prd ...      Run Dev agent
├── qa <repo> --branch ...    Run QA agent
├── judge <repo> --branch ... Run Judge agent
├── docs <repo> --branch ...  Run Docs agent
├── runs                      List past runs (filterable)
├── show <run_id>             Show full run details
├── attach <run_id>           Shell into a running container
└── stop <run_id>             Stop a running container
```

**How a CLI command wires things together (example: `dkmv dev`):**

```
CLI command
│
├── load_config() → DKMVConfig (from .env + env vars)
│
├── Create DevConfig from CLI flags + global defaults
│
├── Instantiate managers:
│   ├── SandboxManager()
│   ├── RunManager(output_dir)
│   └── StreamParser(console, verbose)
│
├── DevComponent(global_config, sandbox, run_manager, stream_parser)
│
├── result = await component.run(dev_config)
│
└── Display result (status, error if any)
```

All component commands follow this same pattern. The `@async_command` decorator wraps the async function with `asyncio.run()` so Typer can call it synchronously.

---

## Configuration System

Configuration uses pydantic-settings: environment variables and `.env` files, no YAML.

```
Precedence (highest to lowest):
1. CLI flags (--model, --max-turns, etc.)
2. Shell environment variables
3. .env file in current directory
4. Hardcoded defaults in DKMVConfig
```

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Claude API authentication |
| `GITHUB_TOKEN` | `""` | Git operations + PR creation |
| `DKMV_MODEL` | `claude-sonnet-4-6` | Default Claude model |
| `DKMV_MAX_TURNS` | `100` | Max Claude Code turns |
| `DKMV_IMAGE` | `dkmv-sandbox:latest` | Docker image name |
| `DKMV_OUTPUT_DIR` | `./outputs` | Run artifact directory |
| `DKMV_TIMEOUT` | `30` | Timeout in minutes |
| `DKMV_MEMORY` | `8g` | Docker memory limit |
| `DKMV_MAX_BUDGET_USD` | `None` | Optional cost cap per run |

Secrets (`ANTHROPIC_API_KEY`, `GITHUB_TOKEN`) are passed into Docker containers as `-e` flags at runtime — never baked into the image.

---

## The Docker Sandbox

The `dkmv-sandbox` image is purpose-built for running Claude Code headless in Docker:

```
Image Layers
─────────────────────────────────────────────────────────
  node:20-bookworm              Base (Debian + Node.js 20)
  ─────────────────────────────────────────────────────────
  apt-get install               System packages:
    git, curl, wget, jq,          Core tools
    build-essential,               Build tools (native modules)
    python3, pip, pipx,            Python stack (for SWE-ReX)
    gh                             GitHub CLI (official repo)
  ─────────────────────────────────────────────────────────
  npm install -g                Claude Code (pinned version)
    @anthropic-ai/claude-code
  ─────────────────────────────────────────────────────────
  User: dkmv (UID 1000)        Non-root with passwordless sudo
  ─────────────────────────────────────────────────────────
  pipx install swe-rex          SWE-ReX (remote execution server)
  ─────────────────────────────────────────────────────────

Environment Variables in Container:
  PATH                          Includes ~/.local/bin (pipx binaries)
  NODE_OPTIONS                  --max-old-space-size=4096 (4GB heap)
  IS_SANDBOX=1                  Enables --dangerously-skip-permissions
  CLAUDE_CODE_DISABLE_          Allows headless (no TTY) operation
    NONINTERACTIVE_CHECK=1
```

Claude Code refuses `--dangerously-skip-permissions` as root, so the `dkmv` user (UID 1000) is created with passwordless sudo.

When the container starts, SWE-ReX (`swerex-remote`) runs on port 8000. The host communicates with it via HTTP to execute commands, read/write files, and manage bash sessions.

---

## Inter-Component Communication

Components share zero in-memory state. All communication flows through git:

```
┌─────────┐   git push    ┌────────┐   git clone    ┌─────────┐
│   DEV   │ ────────────> │ GitHub │ <──────────── │   QA    │
│Container│               │ Branch │               │Container│
└─────────┘               └────────┘               └─────────┘
                              ▲
                              │ git clone
                          ┌───┴─────┐
                          │  JUDGE  │
                          │Container│
                          └─────────┘
```

**Shared artifacts on the branch:**

| File | Written by | Read by |
|---|---|---|
| Source code + tests | Dev | QA, Judge, Docs |
| `.dkmv/prd.md` | Each component (own copy) | Claude Code in that container |
| `.dkmv/plan.md` | Dev (Claude writes it) | — |
| `.dkmv/qa_report.json` | QA | (available on branch) |
| `.dkmv/verdict.json` | Judge | CLI (displays verdict) |

**Feedback loop:** When Judge returns `fail`, you can extract feedback from the verdict and pass it to Dev's next run:
```
judge verdict.json → BaseComponent.synthesize_feedback() → feedback.md → Dev --feedback
```

---

## Project Structure

```
dkmv/
├── __init__.py                  # __version__ = "0.1.0"
├── __main__.py                  # Entry: from dkmv.cli import app; app()
├── cli.py                       # All Typer commands (build, dev, qa, judge, docs, runs, show, attach, stop)
├── config.py                    # DKMVConfig (pydantic-settings)
│
├── utils/
│   └── async_support.py         # @async_command decorator (wraps asyncio.run)
│
├── core/
│   ├── __init__.py              # Public exports
│   ├── models.py                # SandboxConfig, BaseComponentConfig, BaseResult, RunSummary, RunDetail
│   ├── sandbox.py               # SandboxManager (Docker + SWE-ReX)
│   ├── runner.py                # RunManager (file-based persistence)
│   └── stream.py                # StreamParser + StreamEvent
│
├── components/
│   ├── __init__.py              # Component registry (register_component, get_component)
│   ├── base.py                  # BaseComponent ABC (12-step lifecycle + hooks)
│   │
│   ├── dev/
│   │   ├── __init__.py          # Exports DevComponent, DevConfig, DevResult
│   │   ├── component.py         # DevComponent (strips eval criteria, derives branch)
│   │   ├── models.py            # DevConfig, DevResult
│   │   └── prompt.md            # Dev agent prompt template
│   │
│   ├── qa/
│   │   ├── __init__.py
│   │   ├── component.py         # QAComponent (full PRD, force-commits report)
│   │   ├── models.py            # QAConfig, QAResult
│   │   └── prompt.md
│   │
│   ├── judge/
│   │   ├── __init__.py
│   │   ├── component.py         # JudgeComponent (independent eval, force-commits verdict)
│   │   ├── models.py            # JudgeConfig, JudgeResult, PrdRequirement, JudgeIssue
│   │   └── prompt.md
│   │
│   └── docs/
│       ├── __init__.py
│       ├── component.py         # DocsComponent (optional PR creation)
│       ├── models.py            # DocsConfig, DocsResult
│       └── prompt.md
│
└── images/
    └── Dockerfile               # dkmv-sandbox image definition
```

**Isolation rules:**
- Components import from `core/` — never from each other
- Shared types live in `core/models.py`
- Component-specific types live in their own `models.py`
- Prompt templates are co-located as `prompt.md` inside each component package

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **One container per component** | Clean state, no cross-contamination between agents |
| **Git branches for communication** | Components share zero in-memory state; branches are durable and auditable |
| **File-based streaming** | Works around SWE-ReX blocking I/O; provides real-time output |
| **Eval criteria stripped from Dev** | Prevents Dev from gaming the evaluation |
| **Judge is independent** | Prompt explicitly tells Judge to ignore QA reports |
| **No YAML config** | Env vars + `.env` only — simpler, 12-factor app style |
| **Atomic result writes** | Write to `.tmp` then `os.replace()` prevents corrupt reads |
| **npm for Claude Code install** | Native installer has OOM bug in Docker; npm allows version pinning |
| **node:20-bookworm base** | Anthropic-recommended; Alpine breaks native Node modules |
| **Non-root dkmv user** | Claude Code requires non-root for `--dangerously-skip-permissions` |
