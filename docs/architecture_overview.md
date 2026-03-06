# DKMV Architecture Overview

DKMV is a Python CLI tool that orchestrates AI agents (Claude Code) inside isolated Docker containers to perform software engineering tasks. Agents are defined as **components** — directories of YAML task definitions governed by a `component.yaml` manifest. Components run sequentially in fresh containers and communicate through git branches.

The system ships four built-in components: **plan** (PRD → implementation docs), **dev** (phase-by-phase implementation), **qa** (evaluate → fix → re-evaluate), and **docs** (documentation + PR creation).

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         YOUR MACHINE (Host)                          │
│                                                                      │
│  ┌─────────┐    ┌──────────────────────────────────────────────────┐ │
│  │  .env   │───>│               DKMV CLI (typer)                  │ │
│  │  file   │    │                                                  │ │
│  └─────────┘    │  ┌──────────────────────────────────────────┐    │ │
│                 │  │        DKMVConfig + ProjectConfig         │    │ │
│  ┌─────────┐   │  │   (pydantic-settings + .dkmv/config.json) │    │ │
│  │ .dkmv/  │──>│  └──────────────┬────────────────────────────┘    │ │
│  │config.  │   │                 │                                  │ │
│  │json     │   │     ┌───────────┴────────────┐                    │ │
│  └─────────┘   │     │                        │                    │ │
│                 │  ┌──▼──────────────┐  ┌─────▼──────────────┐     │ │
│                 │  │ ComponentRunner │  │   RunManager        │     │ │
│                 │  │ (task system    │  │ (persists runs to   │     │ │
│                 │  │  orchestrator)  │  │  .dkmv/runs/)       │     │ │
│                 │  └──┬─────────────┘  └─────────────────────┘     │ │
│                 │     │                                              │ │
│                 │  ┌──▼──────────────────────┐                      │ │
│                 │  │    SandboxManager       │                      │ │
│                 │  │ (Docker container via   │                      │ │
│                 │  │  SWE-ReX)               │                      │ │
│                 │  └──┬──────────────────────┘                      │ │
│                 └─────┼──────────────────────────────────────────────┘ │
│                       │ docker run -e ANTHROPIC_API_KEY=...            │
│                       │ docker run -e GITHUB_TOKEN=...                 │
│                       ▼                                                │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                DOCKER CONTAINER (dkmv-sandbox)                    │  │
│  │                                                                   │  │
│  │  User: dkmv (UID 1000)     Image: node:20-bookworm               │  │
│  │                                                                   │  │
│  │  ┌───────────────────────────────────────────────────────────┐   │  │
│  │  │  SWE-ReX (swerex-remote)                                  │   │  │
│  │  │  Listens on port 8000, receives commands from host        │   │  │
│  │  └──────────────────────┬────────────────────────────────────┘   │  │
│  │                         │                                         │  │
│  │  ┌──────────────────────▼────────────────────────────────────┐   │  │
│  │  │  Bash Sessions                                             │   │  │
│  │  │  ├── "main"  — git clone, setup, launch claude             │   │  │
│  │  │  └── "tail"  — polls /tmp/dkmv_stream.jsonl                │   │  │
│  │  └────────────────────────────────────────────────────────────┘   │  │
│  │                                                                   │  │
│  │  ┌─────────────────────────────────────────────┐                 │  │
│  │  │  /home/dkmv/workspace/                      │                 │  │
│  │  │  ├── (cloned repo)                          │                 │  │
│  │  │  ├── .claude/CLAUDE.md  (layered agent rules)│                │  │
│  │  │  └── .agent/            (inter-task state)   │                │  │
│  │  │      ├── impl_docs/     (injected inputs)    │                │  │
│  │  │      ├── analysis.json  (task outputs)       │                │  │
│  │  │      └── user_decisions.json (pause answers) │                │  │
│  │  └─────────────────────────────────────────────┘                 │  │
│  │                                                                   │  │
│  │  Claude Code (headless) ──> /tmp/dkmv_stream.jsonl               │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                       │                                                │
│                       │ git push origin feature/...                    │
│                       ▼                                                │
│                   ┌────────┐                                           │
│                   │ GitHub │                                           │
│                   └────────┘                                           │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Core Concepts

### Components

A **component** is a directory containing one or more YAML task definitions and an optional `component.yaml` manifest. The manifest declares shared inputs, default parameters, and the task execution order.

```
my-component/
├── component.yaml      # Manifest (optional): inputs, defaults, task refs
├── 01-analyze.yaml     # Task 1
├── 02-implement.yaml   # Task 2
└── 03-verify.yaml      # Task 3
```

### Tasks

A **task** is a single Claude Code session defined in a YAML file. Each task has:
- A **prompt** sent to Claude Code
- Optional **instructions** layered into CLAUDE.md
- **Inputs** (files, text, env vars) injected into the container
- **Outputs** (files) collected from the container after execution
- **commit/push** flags controlling git behavior

### The Component Pipeline

Components are designed to run on a shared git branch. Each component's tasks operate sequentially within a single Docker container:

```
                          ┌──────────────┐
                          │   PRD File   │
                          └──────┬───────┘
                                 │
                   ┌─────────────▼──────────────┐
                   │       PLAN Component        │
                   │  5 tasks: analyze → features │
                   │  → phases → assembly → eval  │
                   │  Output: impl_docs/          │
                   └─────────────┬──────────────┘
                                 │ impl_docs
                   ┌─────────────▼──────────────┐
                   │       DEV Component         │
                   │  N tasks (one per phase)     │
                   │  Implements code + tests     │
                   └─────────────┬──────────────┘
                                 │ branch with code
                   ┌─────────────▼──────────────┐
                   │        QA Component         │
                   │  3 tasks: evaluate → fix    │
                   │  → re-evaluate              │
                   │  Interactive pause after     │
                   │  evaluate (fix/ship/abort)   │
                   └─────────────┬──────────────┘
                                 │ branch with fixes
                   ┌─────────────▼──────────────┐
                   │       DOCS Component        │
                   │  3 tasks: update-docs →     │
                   │  verify → create-pr         │
                   │  Creates GitHub PR           │
                   └─────────────────────────────┘
```

---

## Architectural Layers

### Layer 1: CLI (`dkmv/cli.py`)

The CLI is built with Typer. It provides wrapper commands for each built-in component plus generic `run` for custom components:

```
dkmv
├── init                          Initialize DKMV project (.dkmv/)
├── components                    List available components
├── register <name> <path>        Register a custom component
├── unregister <name>             Remove a custom component
├── build                         Build the Docker image
│
├── plan --prd ... --branch ...   Run Plan agent (PRD → impl docs)
├── dev --impl-docs ... --branch  Run Dev agent (implement phases)
├── qa --impl-docs ... --branch   Run QA agent (evaluate-fix loop)
├── docs --impl-docs ... --branch Run Docs agent (docs + PR)
├── run <component> --branch ...  Run any component by name/path
│
├── runs                          List past runs (filterable)
├── show <run_id>                 Show full run details
├── attach <run_id>               Shell into running container
├── stop <run_id>                 Stop a running container
└── clean                         Remove all DKMV containers
```

Each run command creates the full runtime stack:

```
CLI command
│
├── load_config() → DKMVConfig (env vars + .env + project config cascade)
├── get_repo() → resolve repo from CLI --repo or project config
├── resolve_component() → find component directory
│
├── Instantiate:
│   ├── SandboxManager()
│   ├── RunManager(output_dir)
│   ├── StreamParser(console, verbose)
│   ├── TaskLoader()
│   └── TaskRunner(sandbox, run_mgr, stream_parser, console)
│
├── ComponentRunner(sandbox, run_mgr, task_loader, task_runner, console)
├── result = await runner.run(component_dir, repo, branch, ...)
│
└── Display result (status, cost, artifacts)
```

**`--repo` is optional** on all run commands when the project is initialized — falls back to `.dkmv/config.json` via `get_repo()`.

### Layer 2: Task System (`dkmv/tasks/`)

The task system handles component loading, task execution, and orchestration.

```
┌──────────────────────────────────────────────────────────────────┐
│                      ComponentRunner.run()                        │
│                                                                  │
│  1. Scan YAML files in component directory                       │
│  2. Start sandbox (Docker container)                             │
│  3. Setup workspace (clone, branch, git config, .agent/)         │
│  4. Load manifest (if component.yaml exists)                     │
│  5. Expand for_each task refs                                    │
│  6. Inject shared inputs, create dirs, write state files         │
│                                                                  │
│  FOR EACH TASK:                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  7. Build cumulative variables (prior task outputs avail)  │  │
│  │  8. TaskLoader.load() — Jinja2 render + YAML parse         │  │
│  │  9. Apply manifest defaults (task_ref → manifest → task)   │  │
│  │ 10. TaskRunner.run()                                       │  │
│  │     ├── Inject inputs (files/text/env)                     │  │
│  │     ├── Write layered CLAUDE.md                            │  │
│  │     ├── Stream Claude Code (background + tail poll)        │  │
│  │     ├── Collect outputs (with retry on failure)            │  │
│  │     └── Git teardown (commit + push)                       │  │
│  │ 11. Handle pause_after (invoke callback, write decisions)  │  │
│  │ 12. On failure: skip remaining tasks                       │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  13. Stop sandbox, save results                                  │
│  14. Return ComponentResult                                      │
└──────────────────────────────────────────────────────────────────┘
```

### Layer 3: Agent Adapter System (`dkmv/adapters/`)

The adapter layer abstracts agent-specific behavior behind a common `AgentAdapter` Protocol. This enables DKMV to run tasks with either Claude Code or the Codex CLI without changing the task system.

```
┌────────────────────────────────────────────────────────────────┐
│                     AgentAdapter Protocol                       │
│                                                                │
│  name / display_name / instructions_path / gitignore_entries   │
│  default_model / prepend_instructions / supports_*()           │
│                                                                │
│  build_command(prompt_file, model, max_turns, timeout, ...)    │
│  parse_event(data) → StreamEvent | None                        │
│  is_result_event(event) → bool                                 │
│  extract_result(event) → StreamResult                          │
│  get_auth_config(config) → (env_dict, extra_args, creds_file)  │
│  get_env_overrides() → dict[str, str]                          │
└────────────────────────────────────────────────────────────────┘
          ▲                              ▲
          │                              │
┌─────────────────┐            ┌─────────────────┐
│ ClaudeCodeAdapter│            │ CodexCLIAdapter  │
│  (claude.py)    │            │  (codex.py)     │
│                 │            │                 │
│ Runs claude     │            │ Runs codex exec │
│ --output-format │            │ --json          │
│ stream-json     │            │ --dangerously-  │
│                 │            │ bypass-approvals│
│                 │            │ Accumulates     │
│ Supports:       │            │ turn state for  │
│  max_turns ✓    │            │ cost tracking   │
│  max_budget ✓   │            │                 │
│  resume ✓       │            │ Supports:       │
└─────────────────┘            │  resume ✓       │
                               └─────────────────┘
```

**Agent selection cascade (7 levels, highest wins):**
1. Task YAML `agent:` field
2. `ManifestTaskRef.agent` in `component.yaml`
3. `ComponentManifest.agent` in `component.yaml`
4. CLI `--agent` flag
5. `.dkmv/config.json` project defaults
6. `DKMV_AGENT` environment variable / `DKMVConfig.default_agent`
7. Built-in default (`claude`)

**Model-agent inference:** if `--model` is set without `--agent`, the model prefix determines the agent (`claude-*` → claude, `gpt-*` / `o<digit>*` → codex).

### Layer 4: Core Infrastructure (`dkmv/core/`)

Three managers provide the foundation:

```
┌─────────────────┐  ┌──────────────┐  ┌─────────────────┐
│ SandboxManager   │  │  RunManager  │  │  StreamParser   │
│                  │  │              │  │                 │
│ start()          │  │ start_run()  │  │ parse_line()    │
│ execute()        │  │ save_result()│  │ render_event()  │
│ stream_claude()  │  │ append_      │  │                 │
│ setup_git_auth() │  │   stream()   │  │ Parses Claude   │
│ read_file()      │  │ save_prompt()│  │ Code stream-json│
│ write_file()     │  │ save_        │  │ events and      │
│ stop()           │  │   artifact() │  │ renders them to │
│                  │  │ list_runs()  │  │ the terminal    │
│ Wraps SWE-ReX    │  │ get_run()    │  │ via Rich        │
│ DockerDeployment │  │              │  │                 │
│                  │  │ File-based   │  │                 │
└─────────────────┘  └──────────────┘  └─────────────────┘
```

---

## Task System Details

### Task Definition Model (`tasks/models.py`)

```python
class TaskDefinition(BaseModel):
    name: str
    description: str = ""
    commit: bool = True           # Git commit after task
    push: bool = True             # Git push after commit

    # Parameters (cascade from manifest → config if None)
    agent: str | None = None
    model: str | None = None
    max_turns: int | None = None
    timeout_minutes: int | None = None
    max_budget_usd: float | None = None

    inputs: list[TaskInput] = []   # Files/text/env vars to inject
    outputs: list[TaskOutput] = [] # Files to collect after execution

    instructions: str | None = None    # Layered into CLAUDE.md
    instructions_file: str | None = None
    prompt: str | None = None          # Sent as -p argument
    prompt_file: str | None = None
```

### Component Manifest Model (`tasks/manifest.py`)

```python
class ComponentManifest(BaseModel):
    name: str
    description: str = ""

    inputs: list[ManifestInput] = []      # Shared inputs for all tasks
    workspace_dirs: list[str] = []         # Directories to create in workspace
    state_files: list[ManifestStateFile] = []  # Pre-written files

    agent_md: str | None = None           # Inline CLAUDE.md content
    agent_md_file: str | None = None      # Path to CLAUDE.md file

    # Component-level defaults (task_ref overrides these, task YAML overrides both)
    agent: str | None = None
    model: str | None = None
    max_turns: int | None = None
    timeout_minutes: int | None = None
    max_budget_usd: float | None = None

    tasks: list[ManifestTaskRef] = []     # Ordered task references
    deliverables: list[ManifestDeliverable] = []
```

### ManifestTaskRef — Per-Task Overrides

```python
class ManifestTaskRef(BaseModel):
    file: str                              # YAML filename
    agent: str | None = None               # Override agent for this task
    model: str | None = None               # Override manifest default
    max_turns: int | None = None
    timeout_minutes: int | None = None
    max_budget_usd: float | None = None
    pause_after: bool = False              # Pause for user input after task
    for_each: str | None = None            # Iterate over a variable list
```

### Parameter Resolution Cascade

Parameters (model, max_turns, timeout, budget) resolve through a 4-level cascade:

```
Priority (highest → lowest):
1. Task YAML        — value set directly in the task definition file
2. ManifestTaskRef  — per-task override in component.yaml
3. ComponentManifest — component-level default in component.yaml
4. CLI / Config     — _resolve_param: task → CLI override → DKMVConfig default
```

Levels 1-3 are applied by `ComponentRunner._apply_manifest_defaults()` (static method, mutates the TaskDefinition before execution). Level 4 is applied at runtime by `TaskRunner._resolve_param()`.

### Jinja2 Templating with Cumulative Variables

Task YAML files are Jinja2 templates rendered with `StrictUndefined` (undefined variables raise errors). Variables are built cumulatively by `ComponentRunner._build_variables()`:

```python
variables = {
    # Static
    "repo": "https://github.com/org/repo",
    "branch": "feat/my-feature",
    "feature_name": "my-feature",
    "component": "dev",
    "model": "claude-sonnet-4-6",
    "run_id": "a1b2c3d4",

    # User-provided (from CLI --var or command-specific args)
    "impl_docs_path": "/path/to/impl-docs",
    "phases": [{"phase_number": 1, "phase_name": "core", "phase_file": "phase1_core.md"}],

    # Cumulative: outputs from prior completed tasks (JSON auto-parsed)
    "tasks": {
        "analyze": {
            "outputs": {
                "analysis": {"output_dir": "docs/impl/v1", "features": [...]}
            }
        }
    }
}
```

This enables powerful inter-task data flow: Task 2 can reference `{{ tasks.analyze.outputs.analysis.output_dir }}`.

### For-Each Task Expansion

ManifestTaskRefs can declare `for_each: "variable_name"` to iterate over a list variable. Each iteration receives `item` (the list element) and `item_index` injected into its template context. The dev component uses this to instantiate `implement-phase.yaml` once per phase.

### CLAUDE.md Layering

Each agent's CLAUDE.md is assembled from multiple layers:

```
┌────────────────────────────────────────────────────┐
│ 1. DKMV_SYSTEM_CONTEXT (system_context.py)         │
│    - Agent identity, workspace rules, environment   │
├────────────────────────────────────────────────────┤
│ 2. Component agent_md (from component.yaml)         │
│    - Component-specific rules and conventions       │
├────────────────────────────────────────────────────┤
│ 3. Task instructions (from task YAML)               │
│    - Task-specific rules and constraints            │
├────────────────────────────────────────────────────┤
│ 4. Git commit rules (auto-appended when commit=true)│
│    - Conventional commit format requirements        │
└────────────────────────────────────────────────────┘
```

### Pause-After (Human-in-the-Loop)

ManifestTaskRefs can set `pause_after: true`. After a task succeeds, the ComponentRunner:
1. Extracts questions from the task's JSON output (looking for a `questions` array with `id`, `question`, `options` fields)
2. Builds a `PauseRequest` and invokes the `on_pause` callback
3. Writes user answers to `.agent/user_decisions.json`
4. If the callback sets `skip_remaining=True`, remaining tasks are skipped

Used by: QA component (pause after evaluate — user chooses fix/ship/abort) and Plan component (pause after analyze — user reviews analysis).

### Retry on Output Failure

If `_collect_outputs` fails (missing required output or failed field validation), the TaskRunner resumes the Claude session with `--resume` and a corrective prompt asking it to produce the missing output. Max turns capped at 10 for the retry.

---

## File-Based Streaming (Dual-Session Workaround)

SWE-ReX's `run_in_session()` is **blocking** — it waits for a command to finish. But Claude Code can run for 30+ minutes. The solution: run Claude in the background, tail its output from a second session.

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
│  /tmp/dkmv_stream.jsonl  ←── Claude writes here          │
│  /tmp/dkmv_stream.err    ←── stderr captured here        │
│  /tmp/dkmv_prompt.md     ←── prompt written here         │
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

The `finally` block always kills the Claude Code process and closes the tail session to prevent runaway API costs.

**Why `< /dev/null`?** SWE-ReX's pexpect sessions use **interactive bash** (job control enabled). Background processes get their own process group. If a background process reads from the terminal, the kernel sends **SIGTTIN** which freezes it silently — 0 bytes, no error. Redirecting stdin from `/dev/null` prevents this.

---

## Inter-Component Communication

Components share zero in-memory state. All communication flows through git:

```
┌─────────┐   git push    ┌────────┐   git clone    ┌─────────┐
│  PLAN   │ ────────────> │ GitHub │ <──────────── │   DEV   │
│Container│               │ Branch │               │Container│
└─────────┘               └────────┘               └─────────┘
                               ▲
                               │ git clone
                          ┌────┴────┐
                          │   QA   │
                          │Container│
                          └─────────┘
```

Within a single component, tasks share state via the `.agent/` directory inside the container. Outputs from completed tasks are automatically available as Jinja2 variables for later tasks.

---

## Configuration System

### Config Cascade

```
Precedence (highest to lowest):
1. CLI flags (--model, --max-turns, etc.)
2. Shell environment variables
3. .env file in current directory
4. Project config (.dkmv/config.json defaults)
5. Hardcoded defaults in DKMVConfig
```

### Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Claude API authentication |
| `CLAUDE_CODE_OAUTH_TOKEN` | `""` | OAuth token (alternative to API key) |
| `GITHUB_TOKEN` | `""` | Git operations + PR creation |
| `CODEX_API_KEY` | `""` | OpenAI API key for Codex agent (`OPENAI_API_KEY` also accepted) |
| `DKMV_AGENT` | `claude` | Default agent backend (`claude` or `codex`) |
| `DKMV_MODEL` | `claude-sonnet-4-6` | Default Claude model |
| `DKMV_MAX_TURNS` | `100` | Max Claude Code turns |
| `DKMV_IMAGE` | `dkmv-sandbox:latest` | Docker image name |
| `DKMV_OUTPUT_DIR` | `./outputs` | Run artifact directory |
| `DKMV_TIMEOUT` | `30` | Timeout in minutes |
| `DKMV_MEMORY` | `8g` | Docker memory limit |
| `DKMV_MAX_BUDGET_USD` | `None` | Optional cost cap per run |

Secrets (`ANTHROPIC_API_KEY`, `GITHUB_TOKEN`) are passed into Docker containers as `-e` flags at runtime — never baked into the image.

### Project Config (`.dkmv/config.json`)

Created by `dkmv init`. Provides project-scoped defaults:

```json
{
  "version": 1,
  "project_name": "my-project",
  "repo": "https://github.com/org/repo",
  "default_branch": "main",
  "credentials": {
    "anthropic_api_key_source": "env",
    "github_token_source": "gh_cli"
  },
  "defaults": {
    "model": "claude-sonnet-4-6",
    "max_turns": 100,
    "timeout_minutes": 30
  },
  "sandbox": {
    "image": "dkmv-sandbox:latest"
  }
}
```

Project config is the **lowest-priority** config source — env vars and CLI flags always win.

---

## Project Initialization (`dkmv init`)

`dkmv init` creates the `.dkmv/` directory structure with auto-detection:

```
.dkmv/
├── config.json        # ProjectConfig (version, repo, credentials, defaults)
├── components.json    # Custom component registry (initially empty)
└── runs/              # Run artifacts directory
```

The init process runs 4 steps with Rich UX:
1. **Project detection** — repo URL (from git remote), project name, default branch
2. **Credential discovery** — checks env vars, `.env` file, `gh auth token`
3. **Docker check** — verifies Docker is available and image exists
4. **Write config** — creates `.dkmv/` structure, updates `.gitignore`

Supports `--yes` for non-interactive mode, `--repo` and `--name` overrides, reinit detection, and nested project warnings.

---

## Component Registry

Custom components can be registered with `dkmv register <name> <path>`:

```bash
dkmv register my-linter ./components/linter
dkmv components          # Lists built-in + custom
dkmv run my-linter ...   # Uses the registered component
dkmv unregister my-linter
```

Registry entries are stored in `.dkmv/components.json`. Component resolution order:
1. **Path** (contains `/` or starts with `.`) — resolve to absolute path
2. **Built-in** — lookup in `dkmv.builtins` package
3. **Registry** — lookup in `.dkmv/components.json`

---

## Built-in Components

### Plan Component

**Purpose:** Convert a PRD into a full set of implementation documents (phases, tasks, user stories, features).

**Inputs:** PRD file (required), design docs directory (optional).

**Tasks (5 sequential):**

| # | Task | Purpose | Pause | Budget |
|---|------|---------|-------|--------|
| 1 | analyze | Deep PRD analysis, research, constraints. Output: `analysis.json` | Yes | $2.00 |
| 2 | features-stories | Extract feature registry + user stories | No | $2.00 |
| 3 | phases | Decompose into phases with task-level detail | No | $5.00 |
| 4 | assembly | Assemble README, GUIDE.md, tasks.md, progress.md | No | $2.00 |
| 5 | evaluate-fix | 3-pass verification loop. Output: `plan_report.json` | No | $3.00 |

**Key pattern:** Task 1 sets `output_dir` in `analysis.json`. All subsequent tasks reference it via `{{ tasks.analyze.outputs.analysis.output_dir }}`.

### Dev Component

**Purpose:** Phase-by-phase implementation from implementation docs produced by Plan.

**Inputs:** Implementation docs directory (file input).

**Agent MD:** Loaded from `{impl_docs_path}/CLAUDE.md` (the CLAUDE.md generated by the plan component).

**Tasks:** Single template `implement-phase.yaml` iterated via `for_each: "phases"`. Each iteration implements one phase, reading its phase document and producing a `phase_N_result.json`.

### QA Component

**Purpose:** Evaluate-fix-re-evaluate loop for quality assurance.

**Inputs:** Implementation docs directory (file input).

**Tasks (3 sequential with interactive pause):**

| # | Task | Purpose | Pause | Commit |
|---|------|---------|-------|--------|
| 1 | evaluate | Read-only evaluation. Output: `qa_evaluation.json` | Yes | No |
| 2 | fix | Fix issues based on user decision. Reads `user_decisions.json` | No | Yes |
| 3 | re-evaluate | Fresh re-evaluation. Output: `qa_report.json` | No | No |

**Key pattern:** After evaluate, pause presents the user with Fix/Ship/Abort options. If "ship" is chosen, `skip_remaining=True` skips fix and re-evaluate.

### Docs Component

**Purpose:** Update documentation and create a pull request.

**Inputs:** Implementation docs directory (file input).

**Tasks (3 sequential):**

| # | Task | Purpose | Commit |
|---|------|---------|--------|
| 1 | update-docs | Review impl, update docs. Output: `docs_manifest.json` | Yes |
| 2 | verify | Second-pass verification. Output: `docs_verification.json` | Yes |
| 3 | create-pr | Clean up `.agent/`, create PR. Output: `pr_result.json` | Yes |

---

## Container-Side Directory Rename

Host-side `.dkmv/` becomes container-side `.agent/` (per ADR-0010). This is implemented by `_normalize_dest()` in `manifest.py`, which prepends `/home/dkmv/workspace/.agent/` to relative destination paths in manifest inputs and task outputs. The workspace setup creates `.agent/` in the container workspace.

---

## Git Teardown (Per-Task)

After each task completes, `TaskRunner._git_teardown()` performs a 3-layer commit strategy:

```
1. Force-add declared outputs    git add -f {output_path}
   (may be in .gitignore)        (for each output in task.outputs)

2. Safety-net add               git add -A -- . ':!.agent/' ':!.claude/'
   (catch code changes the       (excludes framework directories)
    agent made but didn't stage)

3. Commit if dirty              git commit -m "chore: uncommitted changes from {task_name}"

4. Push if configured           git push origin HEAD
```

The commit message uses a deterministic git identity: `DKMV/{ComponentName} <dkmv-agent@noreply.dkmv.dev>`.

---

## Run Artifacts

Each run gets a directory with all artifacts:

```
.dkmv/runs/{run_id}/
├── config.json               # Component config snapshot
├── result.json               # Final ComponentResult (atomic write)
├── tasks_result.json         # Per-task results array
├── stream.jsonl              # Raw Claude Code events (append-only)
├── container.txt             # Docker container name
├── prompts_log.md            # Unified prompts log (all tasks)
├── prompt_{task_name}.md     # Per-task prompt
├── claude_md_{task_name}.md  # Per-task CLAUDE.md
├── {task_output_artifacts}   # Collected output files
└── logs/
```

Run IDs are 8-character hex strings from `uuid4`. Results are written atomically (write to `.tmp`, then `os.replace`) to prevent corrupt reads.

---

## The Docker Sandbox

The `dkmv-sandbox` image is purpose-built for running Claude Code headless:

```
Image Layers
───────────────────────────────────────────────────────
  node:20-bookworm              Base (Debian + Node.js 20)
  ───────────────────────────────────────────────────────
  apt-get install               System packages:
    git, curl, wget, jq,          Core tools
    build-essential,               Build tools (native modules)
    python3, pip, pipx,            Python stack (for SWE-ReX)
    gh                             GitHub CLI (official repo)
  ───────────────────────────────────────────────────────
  npm install -g                Claude Code (pinned version)
    @anthropic-ai/claude-code
  ───────────────────────────────────────────────────────
  User: dkmv (UID 1000)        Non-root with passwordless sudo
  ───────────────────────────────────────────────────────
  pipx install swe-rex          SWE-ReX (remote execution server)
  ───────────────────────────────────────────────────────

Key Environment Variables:
  IS_SANDBOX=1                  Enables --dangerously-skip-permissions
  CLAUDE_CODE_DISABLE_          Allows headless (no TTY) operation
    NONINTERACTIVE_CHECK=1
  NODE_OPTIONS                  --max-old-space-size=4096 (4GB heap)
```

Claude Code refuses `--dangerously-skip-permissions` as root, hence the `dkmv` user (UID 1000) with passwordless sudo.

---

## Project Structure

```
dkmv/
├── __init__.py                  # __version__ = "0.1.0"
├── __main__.py                  # Entry: from dkmv.cli import app; app()
├── cli.py                       # All Typer commands
├── config.py                    # DKMVConfig (pydantic-settings) + load_config()
├── project.py                   # ProjectConfig, find_project_root(), get_repo()
├── init.py                      # dkmv init logic (credential discovery, Rich UX)
├── registry.py                  # ComponentRegistry (.dkmv/components.json)
│
├── utils/
│   └── async_support.py         # @async_command decorator
│
├── core/
│   ├── models.py                # SandboxConfig, BaseComponentConfig, BaseResult, RunSummary
│   ├── sandbox.py               # SandboxManager (Docker + SWE-ReX)
│   ├── runner.py                # RunManager (file-based persistence)
│   └── stream.py                # StreamParser + StreamEvent
│
├── tasks/
│   ├── models.py                # TaskDefinition, TaskResult, ComponentResult, CLIOverrides
│   ├── manifest.py              # ComponentManifest, ManifestTaskRef, ManifestInput
│   ├── loader.py                # TaskLoader (YAML + Jinja2 + Pydantic)
│   ├── runner.py                # TaskRunner (single-task execution)
│   ├── component.py             # ComponentRunner (multi-task orchestration)
│   ├── discovery.py             # resolve_component(), BUILTIN_COMPONENTS
│   ├── pause.py                 # PauseRequest, PauseResponse models
│   └── system_context.py        # DKMV_SYSTEM_CONTEXT constant
│
├── builtins/
│   ├── plan/                    # 5 tasks: analyze → features → phases → assembly → eval
│   │   ├── component.yaml
│   │   ├── 01-analyze.yaml
│   │   ├── 02-features-stories.yaml
│   │   ├── 03-phases.yaml
│   │   ├── 04-assembly.yaml
│   │   └── 05-evaluate-fix.yaml
│   │
│   ├── dev/                     # 1 template task, iterated via for_each
│   │   ├── component.yaml
│   │   └── implement-phase.yaml
│   │
│   ├── qa/                      # 3 tasks: evaluate → fix → re-evaluate
│   │   ├── component.yaml
│   │   ├── 01-evaluate.yaml
│   │   ├── 02-fix.yaml
│   │   └── 03-re-evaluate.yaml
│   │
│   └── docs/                    # 3 tasks: update-docs → verify → create-pr
│       ├── component.yaml
│       ├── 01-update-docs.yaml
│       ├── 02-verify.yaml
│       └── 03-create-pr.yaml
│
└── images/
    └── Dockerfile               # dkmv-sandbox image definition
```

**Isolation rules:**
- Core infrastructure (`core/`) has no knowledge of the task system
- The task system (`tasks/`) depends on core but not on CLI
- CLI (`cli.py`) wires everything together
- Built-in components are pure YAML — no Python code

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **YAML manifests, not Python classes** | Components are declarative YAML, not code. Easier to create, version, share, and understand |
| **One container per component** | Clean state, no cross-contamination between agents |
| **Git branches for inter-component communication** | Durable, auditable, no shared memory |
| **`.agent/` for intra-component communication** | Tasks within a component share files via the `.agent/` directory |
| **Jinja2 with StrictUndefined** | Template errors are caught at load time, not silently swallowed |
| **Cumulative task variables** | Later tasks can reference outputs from earlier tasks |
| **File-based streaming** | Works around SWE-ReX blocking I/O; provides real-time output |
| **Layered CLAUDE.md** | System + component + task instructions compose cleanly |
| **Parameter cascade** | Sensible defaults with precise override control at every level |
| **Atomic result writes** | Write to `.tmp` then `os.replace()` prevents corrupt reads |
| **For-each expansion** | One YAML template, N instances — enables the dev phase-per-task pattern |
| **Pause-after mechanism** | Human-in-the-loop decisions between tasks without breaking automation |
| **Project-scoped config** | `dkmv init` removes the need for `--repo` on every command |
| **Component registry** | Custom components can be named and used like built-ins |
