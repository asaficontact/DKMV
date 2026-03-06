# PRD: DKMV Init v1 — Project-Scoped Initialization

**Author:** DKMV Team
**Status:** Draft
**Last Updated:** 2026-02-23

---

## Table of Contents

- [1. Executive Summary](#1-executive-summary)
- [2. Problem Statement](#2-problem-statement)
- [3. Goals and Non-Goals](#3-goals-and-non-goals)
- [4. Background: Current Architecture](#4-background-current-architecture)
- [5. Proposed Architecture](#5-proposed-architecture)
  - [5.1 The `.dkmv/` Project Directory](#51-the-dkmv-project-directory)
  - [5.2 Container-Side Rename: `.dkmv/` to `.agent/`](#52-container-side-rename-dkmv-to-agent)
  - [5.3 Config Cascade](#53-config-cascade)
  - [5.4 System Diagram](#54-system-diagram)
- [6. What to Build](#6-what-to-build)
  - [6.1 `dkmv init` Command](#61-dkmv-init-command)
  - [6.2 Project Config Model](#62-project-config-model)
  - [6.3 Config Loading Integration](#63-config-loading-integration)
  - [6.4 Component Registry](#64-component-registry)
  - [6.5 `dkmv components` Command](#65-dkmv-components-command)
  - [6.6 `dkmv register` / `dkmv unregister` Commands](#66-dkmv-register--dkmv-unregister-commands)
  - [6.7 Container-Side `.agent/` Rename](#67-container-side-agent-rename)
  - [6.8 Run Output Relocation](#68-run-output-relocation)
  - [6.9 CLI Changes (--repo Optional)](#69-cli-changes---repo-optional)
  - [6.10 Rich Init Experience](#610-rich-init-experience)
- [7. Implementation Phases](#7-implementation-phases)
  - [Phase 1: Project Config Foundation](#phase-1-project-config-foundation)
  - [Phase 2: Init Command + Rich UX](#phase-2-init-command--rich-ux)
  - [Phase 3: Component Registry](#phase-3-component-registry)
  - [Phase 4: Container-Side Rename](#phase-4-container-side-rename)
  - [Phase 5: CLI Integration + Polish](#phase-5-cli-integration--polish)
- [8. Testing Strategy](#8-testing-strategy)
- [9. User Stories](#9-user-stories)
- [10. Open Questions](#10-open-questions)
- [11. Evaluation Criteria](#11-evaluation-criteria)

---

## 1. Executive Summary

DKMV currently operates as a **stateless CLI tool**: every command requires `--repo`, credentials come from environment variables or a `.env` file the user manually creates, and run outputs accumulate in a generic `./outputs` directory. There is no concept of "this project" — DKMV treats every invocation as independent.

**DKMV Init v1** introduces a **project-scoped model** with a `dkmv init` command that:

1. Creates a `.dkmv/` directory in the project root as the single home for all DKMV state
2. Auto-detects the repository, credentials, and project stack through a guided setup
3. Stores project configuration, component registry, and run outputs in `.dkmv/`
4. Eliminates the need to pass `--repo` on every command
5. Provides a visually engaging, step-by-step initialization experience using Rich

Additionally, this PRD covers:

- **Component registry** — register custom components by name, list all available components
- **Container-side rename** — rename the agent's working directory from `.dkmv/` to `.agent/` inside containers, resolving the name collision between host-side project config and container-side agent workspace
- **Backward compatibility** — all commands continue to work without init by passing explicit flags

---

## 2. Problem Statement

### Current Pain Points

**1. Repetitive `--repo` on every command.**
The most common DKMV workflow is running multiple agents against the same repository. Today, every single command requires the full repo URL:

```bash
dkmv run dev --repo https://github.com/org/my-project --var prd_path=prd.md
dkmv run qa --repo https://github.com/org/my-project --branch feature/auth --var prd_path=prd.md
dkmv run judge --repo https://github.com/org/my-project --branch feature/auth --var prd_path=prd.md
```

This is tedious, error-prone (typos in URLs), and hostile to new users who see a wall of required flags.

**2. Manual credential setup with no guidance.**
New users must:
1. Know to create a `.env` file (not obvious from `--help`)
2. Know the exact variable names (`ANTHROPIC_API_KEY`, `GITHUB_TOKEN`)
3. Obtain and paste API keys manually
4. Hope they didn't make a typo

There is no validation, no discovery of existing credentials (e.g., `gh auth token`), and no interactive setup flow. The `.env.example` file exists but requires manual copying and editing.

**3. No project context or state.**
DKMV doesn't know which project it's operating on. Run history from project A and project B are mixed together in the same `./outputs/` directory. There's no way to see "all runs for this project" because DKMV doesn't know what "this project" is.

**4. Custom components require paths, not names.**
To run a custom component, you must type the full path every time:

```bash
dkmv run /Users/me/components/strict-judge --repo https://github.com/org/repo --var prd_path=prd.md
```

There's no way to give a short name to a frequently-used custom component.

**5. Name collision between host and container `.dkmv/`.**
The `.dkmv/` directory is used inside containers as the agent's workspace for PRDs, plans, reports, and verdicts. If we introduce `.dkmv/` on the host for project config, the same name serves two different purposes — confusing for both users and agents.

**6. No guided first-run experience.**
First-time users face: install dependencies, create `.env` file, build Docker image, learn CLI flags, hope everything works. There's no single "get started" command that validates the environment and guides setup.

---

## 3. Goals and Non-Goals

### Goals

1. **A `dkmv init` command** that creates a `.dkmv/` project directory with auto-detected configuration, discovered credentials, and a clean setup experience
2. **Project-scoped config** stored in `.dkmv/config.json` that provides default values for `--repo`, model, budget, and other settings — eliminating repetitive flags
3. **Component registry** allowing users to register custom components by name, list all available components (built-in + custom), and use short names instead of paths
4. **Container-side rename** from `.dkmv/` to `.agent/` to eliminate the name collision and provide a clear, agent-oriented name for the workspace directory inside containers
5. **Run output relocation** from `./outputs/runs/` to `.dkmv/runs/` so run history is anchored to the project
6. **Backward compatibility** — all commands still work without init when `--repo` and credentials are provided explicitly via flags or environment variables
7. **Visually engaging CLI experience** using Rich panels, spinners, colored output, and clear step-by-step progress

### Non-Goals

- **Global/user-level config** — This PRD covers project-level only. A future PRD may add `~/.config/dkmv/` for user preferences
- **Remote component registries** — No `dkmv install <component>` from a remote registry
- **Docker image customization during init** — Stack detection and image customization are noted as future extensions; init v1 focuses on config, credentials, and component registry
- **Team sharing of `.dkmv/`** — The entire `.dkmv/` directory is gitignored. Sharing project config across teams is a future concern
- **Web UI** — CLI only
- **Token storage in config files** — Tokens are never written to `.dkmv/config.json`. Init discovers and validates credentials but stores only source references (e.g., `"env"`, `"gh_cli"`, `"dotenv"`)

---

## 4. Background: Current Architecture

### Config System (dkmv/config.py)

```python
class DKMVConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    anthropic_api_key: str     # ANTHROPIC_API_KEY (required for agent commands)
    github_token: str          # GITHUB_TOKEN (optional but needed for private repos)
    default_model: str         # DKMV_MODEL (default: "claude-sonnet-4-6")
    default_max_turns: int     # DKMV_MAX_TURNS (default: 100)
    image_name: str            # DKMV_IMAGE (default: "dkmv-sandbox:latest")
    output_dir: Path           # DKMV_OUTPUT_DIR (default: ./outputs)
    timeout_minutes: int       # DKMV_TIMEOUT (default: 30)
    memory_limit: str          # DKMV_MEMORY (default: "8g")
    max_budget_usd: float|None # DKMV_MAX_BUDGET_USD (default: None)
```

All configuration comes from environment variables or `.env` file. There is no project config, no global config, and no interactive setup. `load_config()` is called by every CLI command.

### CLI Command Pattern

Every agent command follows: `load_config()` → validate → construct dependencies → execute. The `--repo` parameter is required on every agent command (positional `Argument` on wrapper commands, required `Option` on `dkmv run`).

### Container-Side `.dkmv/`

Inside Docker containers, `ComponentRunner._setup_workspace()` creates `.dkmv/` at `/home/dkmv/workspace/.dkmv/` for:
- **Inputs:** PRD (`prd.md`), design docs, feedback (`feedback.json`)
- **Outputs:** plan (`plan.md`), QA report (`qa_report.json`), verdict (`verdict.json`)
- **Gitignore:** Added to `.gitignore` so artifacts don't pollute the repo

All 5 built-in YAML task files reference `.dkmv/` paths in their `inputs[].dest`, `outputs[].path`, `instructions`, and `prompt` fields. The 4 legacy Python components also reference `.dkmv/` paths.

### Component Discovery (dkmv/tasks/discovery.py)

```python
BUILTIN_COMPONENTS = {"dev", "qa", "judge", "docs"}

def resolve_component(name_or_path: str) -> Path:
    # 1. Path? (contains / or starts with .) → resolve filesystem path
    # 2. Built-in? → resolve via importlib.resources
    # 3. Error with list of available built-ins
```

No support for user-registered component names. Note: `ComponentName` is already `str` (relaxed from `Literal` during Tasks v1), so arbitrary component names are type-compatible.

### Run Output Structure

```
./outputs/runs/           # DKMV_OUTPUT_DIR/runs/
├── abc12345/             # run_id = uuid4().hex[:8]
│   ├── config.json
│   ├── result.json
│   ├── tasks_result.json
│   ├── stream.jsonl
│   ├── prompt_plan.md
│   ├── container.txt
│   └── logs/
└── def67890/
```

Run history is mixed across all projects. The output directory is configurable via `DKMV_OUTPUT_DIR` but defaults to `./outputs` relative to CWD.

---

## 5. Proposed Architecture

### 5.1 The `.dkmv/` Project Directory

After `dkmv init`, the project root contains:

```
my-project/
├── .dkmv/                          # DKMV project directory (gitignored)
│   ├── config.json                 # Project configuration
│   ├── components.json             # Registered custom components
│   └── runs/                       # Run output (relocated from ./outputs/runs/)
│       ├── abc12345/
│       │   ├── config.json
│       │   ├── result.json
│       │   ├── tasks_result.json
│       │   ├── stream.jsonl
│       │   └── ...
│       └── def67890/
├── .env                            # Credentials (gitignored, may pre-exist)
├── .gitignore                      # Updated to include .dkmv/
├── src/
└── ...
```

**Key design decisions:**

1. **`.dkmv/config.json`** stores project settings (repo, defaults, stack info). **Never stores secrets.** Secrets stay in `.env` or system credential stores.
2. **`.dkmv/components.json`** maps short names to filesystem paths for custom components.
3. **`.dkmv/runs/`** replaces `./outputs/runs/` — run history is now project-scoped.
4. **The entire `.dkmv/` directory is gitignored.** Init adds `.dkmv/` to `.gitignore` if not already present.

### 5.2 Container-Side Rename: `.dkmv/` to `.agent/`

Inside Docker containers, the agent's working directory is renamed from `.dkmv/` to `.agent/`:

```
Container: /home/dkmv/workspace/
├── .agent/                         # Was .dkmv/ — agent workspace
│   ├── prd.md                      # Input: PRD
│   ├── plan.md                     # Output: implementation plan
│   ├── qa_report.json              # Output: QA report
│   ├── verdict.json                # Output: judge verdict
│   ├── design_docs/                # Input: optional design docs
│   └── feedback.json               # Input: optional feedback
├── .claude/
│   └── CLAUDE.md                   # Agent instructions (written by TaskRunner)
├── src/
└── ...
```

**Rationale:**
- `.agent/` is clear and unambiguous: "this is the agent's directory"
- It eliminates confusion between host `.dkmv/` (project config) and container `.dkmv/` (agent workspace)
- The name reads naturally in prompts: "Read the PRD at `.agent/prd.md`"
- It's short, easy to type, and easy to reference in YAML task files

### 5.3 Config Cascade

After init, the configuration resolution order becomes:

```
CLI flags (--model, --max-turns, etc.)
    ↓ (highest priority)
Environment variables (DKMV_MODEL, etc.)
    ↓
.env file (pydantic-settings reads this automatically)
    ↓
.dkmv/config.json (project-level defaults)
    ↓ (lowest priority)
Built-in defaults (hardcoded in DKMVConfig)
```

This means:
- CLI flags always win (existing behavior, unchanged)
- Environment variables override project config (existing behavior, unchanged)
- Project config overrides built-in defaults (new layer)
- If no `.dkmv/config.json` exists, behavior is identical to today

### 5.4 System Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                       USER (Operator)                               │
│  Writes PRDs, runs CLI commands, inspects git branches              │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    DKMV CLI (dkmv)                                   │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │dkmv init │  │dkmv run  │  │ dkmv     │  │  dkmv    │           │
│  │          │  │<comp>    │  │components│  │register  │           │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘           │
│       │              │             │              │                 │
│       ▼              ▼             ▼              ▼                 │
│  ┌──────────────────────────────────────────────────────┐          │
│  │              Config Resolution Layer                   │          │
│  │  CLI flags > env vars > .env > .dkmv/config.json      │          │
│  │              > built-in defaults                       │          │
│  └──────────────────────────────────────────────────────┘          │
│       │                                                             │
│       ▼                                                             │
│  ┌──────────────────────────────────────────────────────┐          │
│  │           Component Resolution Layer                   │          │
│  │  Path? > Built-in? > .dkmv/components.json?           │          │
│  └──────────────────────────────────────────────────────┘          │
│       │                                                             │
│       ▼                                                             │
│  ┌──────────────────────────────────────────────────────┐          │
│  │            Core Framework Layer                        │          │
│  │  SandboxManager  RunManager  StreamParser              │          │
│  └──────────────────────────────────────────────────────┘          │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│           Docker Container (dkmv-sandbox)                            │
│                                                                     │
│  Claude Code (headless, YOLO mode)                                  │
│  ├── Reads PRD from .agent/prd.md         ← was .dkmv/prd.md       │
│  ├── Writes plan to .agent/plan.md        ← was .dkmv/plan.md      │
│  ├── Reads instructions from .claude/CLAUDE.md                      │
│  └── Commits results to git branch                                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 6. What to Build

### 6.1 `dkmv init` Command

**Purpose:** Initialize DKMV for the current project directory. Creates `.dkmv/` with auto-detected configuration and validated credentials.

**CLI Signature:**

```bash
dkmv init [--yes] [--repo <url>] [--name <project-name>]
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--yes` / `-y` | `bool` | `False` | Accept all defaults without prompting (non-interactive mode) |
| `--repo` | `str \| None` | Auto-detected | Override auto-detected repository URL |
| `--name` | `str \| None` | Auto-detected | Override auto-detected project name |

**Behavior:**

Init is a **guided, step-by-step process** with 5 phases. Each phase auto-detects what it can, shows the result, and optionally prompts for confirmation or input.

#### Phase 1: Pre-flight Checks

Before doing anything, verify prerequisites:

1. **Not already initialized?** Check if `.dkmv/config.json` exists. If it does:
   - Print current config summary
   - Ask: "DKMV is already initialized. Reinitialize? (y/N)"
   - If yes, preserve `.dkmv/runs/` and `.dkmv/components.json`, regenerate `config.json`
   - If `--yes`, reinitialize without prompting
2. **Docker available?** Run `shutil.which("docker")`. If not found:
   - Print warning: "Docker not found. You'll need Docker to run agents."
   - Continue (don't block init — user may install Docker later)
3. **Git repository?** Run `git rev-parse --show-toplevel`. If not a git repo:
   - Print warning: "Not a git repository. DKMV works best with git projects."
   - Continue (allow init for non-git use cases)

#### Phase 2: Project Detection

1. **Repository URL:** Run `git remote get-url origin` (or first remote). If found, show it. If not, prompt for it (or use `--repo`).
2. **Project name:** Derive from repo URL (last path segment without `.git`), or from directory name. Show it. Allow override with `--name`.
3. **Default branch:** Run `git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null` or default to `"main"`. Show it.

Display:
```
  Project:     my-project
  Repository:  https://github.com/org/my-project
  Branch:      main
```

#### Phase 3: Credential Discovery

Discover credentials using a priority cascade. For each credential, try sources in order and report what was found.

**Anthropic API Key:**
1. `ANTHROPIC_API_KEY` environment variable
2. `.env` file in project root (parse with `python-dotenv` or simple key=value)
3. Not found → prompt user to enter it

**GitHub Token:**
1. `GITHUB_TOKEN` or `GH_TOKEN` environment variable
2. `.env` file in project root
3. `gh auth token` command (GitHub CLI credential store)
4. Not found → prompt (or skip if user says it's not needed)

For each credential, display the **source** (not the value):
```
  Anthropic API Key:  found (environment variable)
  GitHub Token:       found (gh CLI)
```

**If credentials are missing and user provides them interactively:**
- Write them to `.env` file (create if doesn't exist, append if exists)
- Add `.env` to `.gitignore` if not already present
- Never write credentials to `.dkmv/config.json`

**Validation (optional, with spinner):**
- If Anthropic key found, optionally validate by making a lightweight API call (e.g., list models)
- If GitHub token found and repo is remote, optionally validate with `gh auth status`
- Validation is skippable (don't block init if network is unavailable)

#### Phase 4: Docker Image Check

1. Load config to get `config.image_name` (may be customized via `DKMV_IMAGE` env var)
2. Check if the configured image exists locally: `docker image inspect <config.image_name>`
3. If exists: show image name and size
4. If not exists: inform user they need to run `dkmv build`

Display:
```
  Docker Image:  dkmv-sandbox:latest (found, 2.1GB)
```
or:
```
  Docker Image:  dkmv-sandbox:latest — not found
                 Run 'dkmv build' to create the sandbox image.
```

The image name displayed must come from `config.image_name`, not be hardcoded. If the user has `DKMV_IMAGE=my-custom:v2`, it should check for and display that name.

Do **not** auto-build during init. Building takes minutes and should be a deliberate action.

#### Phase 5: Write Configuration

1. Create `.dkmv/` directory
2. Create `.dkmv/runs/` directory
3. Create `.dkmv/components.json` (empty: `{}`)
4. Write `.dkmv/config.json` with detected values
5. Add `.dkmv/` to `.gitignore` (if not already present)
6. Add `.env` to `.gitignore` (if not already present and if `.env` exists or was created)
7. Display success summary with next steps

**Idempotent behavior:** Running `dkmv init` again is safe. It re-detects, shows current state, and only overwrites `config.json` if the user confirms. It never deletes `runs/` or `components.json`.

### 6.2 Project Config Model

**File:** `.dkmv/config.json`

```json
{
  "version": 1,
  "project_name": "my-project",
  "repo": "https://github.com/org/my-project",
  "default_branch": "main",
  "credentials": {
    "anthropic_api_key_source": "env",
    "github_token_source": "gh_cli"
  },
  "defaults": {
    "model": null,
    "max_turns": null,
    "timeout_minutes": null,
    "max_budget_usd": null,
    "memory": null
  },
  "sandbox": {
    "image": null
  }
}
```

**Design principles:**

1. **`version` field** — enables schema migrations in future versions
2. **`null` means "use the cascade default"** — only non-null values override. This keeps the config minimal and avoids stale values
3. **`credentials` section stores sources, not values** — `"env"`, `"gh_cli"`, `"dotenv"` indicate where to find the credential at runtime, never the credential itself
4. **`defaults` section** maps directly to existing `DKMVConfig` fields — no new concepts
5. **`sandbox` section** is minimal for v1 (just image override), extensible for future stack detection and customization

**Pydantic Model:**

```python
class CredentialSources(BaseModel):
    anthropic_api_key_source: str = "env"  # "env", "dotenv", "manual"
    github_token_source: str = "env"       # "env", "dotenv", "gh_cli", "none"

class ProjectDefaults(BaseModel):
    model: str | None = None
    max_turns: int | None = None
    timeout_minutes: int | None = None
    max_budget_usd: float | None = None
    memory: str | None = None

class SandboxSettings(BaseModel):
    image: str | None = None

class ProjectConfig(BaseModel):
    version: int = 1
    project_name: str
    repo: str
    default_branch: str = "main"
    credentials: CredentialSources = CredentialSources()
    defaults: ProjectDefaults = ProjectDefaults()
    sandbox: SandboxSettings = SandboxSettings()
```

### 6.3 Config Loading Integration

**Modified `load_config()` to incorporate project config:**

The existing `DKMVConfig` pydantic-settings model reads from env vars and `.env`. We add `.dkmv/config.json` as a lower-priority source.

**Approach: Compare-against-defaults**

The challenge: pydantic-settings does not expose *which source* provided each field's value. After `DKMVConfig()` is constructed, there's no API to ask "was `default_model` set by an env var or is it the hardcoded default?"

The solution: **compare each field's resolved value against its known built-in default.** If the value equals the built-in default, apply the project config override. If it differs (meaning an env var or `.env` set it), keep the env-provided value.

```python
# Built-in defaults for comparison (must stay in sync with DKMVConfig field defaults)
_BUILTIN_DEFAULTS = {
    "default_model": "claude-sonnet-4-6",
    "default_max_turns": 100,
    "timeout_minutes": 30,
    "max_budget_usd": None,
    "memory_limit": "8g",
    "image_name": "dkmv-sandbox:latest",
}

def load_config(require_api_key: bool = True) -> DKMVConfig:
    project_root = find_project_root()

    # Pass the project root's .env file so subdirectories work correctly
    env_file = project_root / ".env" if (project_root / ".env").exists() else ".env"
    config = DKMVConfig(_env_file=env_file)

    project = load_project_config(project_root)

    if project:
        # Apply project defaults only where config still has built-in defaults
        # (meaning no env var or .env overrode them)
        if project.defaults.model and config.default_model == _BUILTIN_DEFAULTS["default_model"]:
            config.default_model = project.defaults.model
        if project.defaults.max_turns and config.default_max_turns == _BUILTIN_DEFAULTS["default_max_turns"]:
            config.default_max_turns = project.defaults.max_turns
        # ... same pattern for each field

        # Relocate output_dir to .dkmv/ (unless DKMV_OUTPUT_DIR was explicitly set)
        if config.output_dir == Path("./outputs"):
            config.output_dir = project_root / ".dkmv"

    if require_api_key and not config.anthropic_api_key:
        typer.echo("Error: ANTHROPIC_API_KEY not set...", err=True)
        raise typer.Exit(code=1)
    return config
```

**Known limitation:** If a user explicitly sets `DKMV_MODEL=claude-sonnet-4-6` (the same value as the built-in default), the project config will override it. This is acceptable because the user is explicitly setting the value to the default, and the project config provides a more specific override. In practice, this edge case is harmless — the user would get the project-configured model, which is what they'd likely want.

**Critical constraint:** Environment variables and `.env` ALWAYS win over project config when they differ from built-in defaults. Project config only fills in gaps where the user hasn't set anything. This preserves the existing behavior: if `DKMV_MODEL=claude-opus-4-6` is set in the environment, it overrides both project config and built-in defaults.

**`.env` file resolution from subdirectories:** Note the `_env_file=env_file` parameter above. When the user runs DKMV from a subdirectory (e.g., `my-project/src/`), `find_project_root()` locates `my-project/` and we pass `my-project/.env` to pydantic-settings explicitly. This ensures credentials from `.env` are found regardless of CWD. This fixes a pre-existing limitation where `.env` was only found relative to CWD.

**New helper: `load_project_config()`**

```python
def load_project_config(project_root: Path | None = None) -> ProjectConfig | None:
    """Load .dkmv/config.json if it exists. Returns None if not initialized."""
    root = project_root or find_project_root()
    config_path = root / ".dkmv" / "config.json"
    if not config_path.exists():
        return None
    return ProjectConfig.model_validate_json(config_path.read_text())
```

**New helper: `find_project_root()`**

Walk up from CWD looking for `.dkmv/config.json`. This allows DKMV commands to work from subdirectories of the project:

```python
def find_project_root() -> Path:
    """Walk up from CWD to find .dkmv/config.json. Returns CWD if not found."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / ".dkmv" / "config.json").exists():
            return parent
    return current
```

**Performance note:** `find_project_root()` runs on every `load_config()` call, including read-only commands like `dkmv runs`, `dkmv show`, and `dkmv clean`. The directory walk is negligible (at most ~20 `stat()` calls up the filesystem tree) and is intentional — it provides consistent project context across all commands.

### 6.4 Component Registry

**File:** `.dkmv/components.json`

```json
{
  "strict-judge": "/Users/tawab/components/strict-judge",
  "fast-dev": "./custom/fast-dev"
}
```

**Design:**
- Simple name → path mapping
- Paths can be absolute or relative (resolved relative to project root)
- Names must not collide with built-in component names (`dev`, `qa`, `judge`, `docs`)
- Paths are validated at registration time (must be a directory with YAML files)
- Paths are re-validated at runtime (may become stale)

**Modified `resolve_component()` cascade:**

```
1. Path? (contains / or starts with .)  → resolve as filesystem path
2. Built-in? (dev, qa, judge, docs)     → resolve from dkmv.builtins
3. Registered? (in .dkmv/components.json) → resolve path from registry
4. Error → list all available (built-ins + registered)
```

**Signature change:** The current `resolve_component(name_or_path: str)` is a pure function with no project awareness. Add an optional `project_root` parameter to enable registry lookup without coupling discovery to the project system:

```python
def resolve_component(name_or_path: str, project_root: Path | None = None) -> Path:
    # Step 1: Path check (unchanged)
    # Step 2: Built-in check (unchanged)
    # Step 3: Registry check (new)
    if project_root:
        registry_path = project_root / ".dkmv" / "components.json"
        if registry_path.exists():
            registry = json.loads(registry_path.read_text())
            if name_or_path in registry:
                path = Path(registry[name_or_path])
                if not path.is_absolute():
                    path = (project_root / path).resolve()
                # ... validate path has YAML files
                return path
    # Step 4: Error with full list
```

Callers in `cli.py` pass `project_root=find_project_root()` when calling `resolve_component()`. The default `None` preserves backward compatibility for tests and direct calls.

### 6.5 `dkmv components` Command

**Purpose:** List all available components — built-in and registered custom.

**CLI Signature:**

```bash
dkmv components
```

**Output (Rich table):**

```
Components

  Name           Type       Tasks  Description
  ─────────────  ─────────  ─────  ──────────────────────────────────────
  dev            built-in   2      Plan and implement features from a PRD
  qa             built-in   1      Test and validate implementation
  judge          built-in   1      Evaluate quality with pass/fail verdict
  docs           built-in   1      Generate documentation
  strict-judge   custom     1      /Users/tawab/components/strict-judge
  fast-dev       custom     3      ./custom/fast-dev

  4 built-in, 2 custom
```

**Behavior:**
- Always shows built-in components (no init required)
- Shows registered components only if `.dkmv/components.json` exists
- **Task count:** Scans the component directory and counts `.yaml`/`.yml` files
- **Description:** For built-ins, hardcoded. For custom, shows the registered path
- If a registered component's path is invalid (missing/no YAML files), show it with a warning indicator

### 6.6 `dkmv register` / `dkmv unregister` Commands

**`dkmv register`:**

```bash
dkmv register <name> <path>
```

| Argument | Description |
|----------|-------------|
| `name` | Short name for the component (e.g., `strict-judge`) |
| `path` | Path to the component directory |

**Validation:**
1. `.dkmv/` must exist (init required)
2. `name` must not be a built-in (`dev`, `qa`, `judge`, `docs`)
3. `name` must not already be registered (unless `--force`)
4. `path` must be a directory
5. `path` must contain at least one `.yaml` or `.yml` file (directly or in `tasks/` subdirectory)

**On success:**
```
Registered 'strict-judge' → /Users/tawab/components/strict-judge (1 task)
```

**`dkmv unregister`:**

```bash
dkmv unregister <name>
```

Removes the entry from `.dkmv/components.json`.

**On success:**
```
Unregistered 'strict-judge'
```

### 6.7 Container-Side `.agent/` Rename

**Scope:** Rename all references to `.dkmv/` inside containers to `.agent/`.

**Files to modify:**

| Category | Files | Change |
|----------|-------|--------|
| **Infrastructure** | `dkmv/tasks/component.py` | `mkdir -p .agent` + gitignore `.agent/` |
| **Infrastructure** | `dkmv/components/base.py` | Same (legacy — no CLI command uses this, but update for consistency) |
| **Built-in YAML** | `dkmv/builtins/dev/01-plan.yaml` | All `dest:` and `path:` fields: `.dkmv/` → `.agent/` |
| **Built-in YAML** | `dkmv/builtins/dev/02-implement.yaml` | Same |
| **Built-in YAML** | `dkmv/builtins/qa/01-evaluate.yaml` | Same |
| **Built-in YAML** | `dkmv/builtins/judge/01-verdict.yaml` | Same |
| **Built-in YAML** | `dkmv/builtins/docs/01-generate.yaml` | Same |
| **Prompt templates** | `dkmv/components/dev/prompt.md` | `.dkmv/` → `.agent/` in text |
| **Prompt templates** | `dkmv/components/qa/prompt.md` | Same |
| **Prompt templates** | `dkmv/components/judge/prompt.md` | Same |
| *(Note: `dkmv/components/docs/prompt.md` has no `.dkmv/` references — no change needed)* | | |
| **Legacy Python** | `dkmv/components/dev/component.py` | Path strings |
| **Legacy Python** | `dkmv/components/qa/component.py` | Path strings |
| **Legacy Python** | `dkmv/components/judge/component.py` | Path strings |
| **Tests** | Multiple test files | Path assertions |
| **Snapshots** | `tests/unit/__snapshots__/test_prompts.ambr` | Regenerate all |
| **Documentation** | `README.md`, `CLAUDE.md`, `E2E_TEST_GUIDE.md` | Text references |

**This is a straightforward search-and-replace** across the codebase. The container-side directory name appears as a string constant in all cases — no dynamic construction. Test snapshots will be regenerated automatically with `--snapshot-update`.

**The `.agent/` directory inside the container:**
- Created by `ComponentRunner._setup_workspace()` (and `BaseComponent._setup_workspace()`)
- Added to `.gitignore` in the cloned repo
- Used by YAML task `inputs[].dest` and `outputs[].path` fields
- Referenced in prompt text and instruction text
- Gitignore entry changes from `.dkmv/` to `.agent/`

### 6.8 Run Output Relocation

**Change:** When `.dkmv/` exists (project is initialized), run outputs go to `.dkmv/runs/` instead of `./outputs/runs/`.

**Implementation:** Modify `load_config()` to set `output_dir` to `.dkmv/` when project config exists:

```python
if project:
    config.output_dir = find_project_root() / ".dkmv"
```

Note: `RunManager` already uses `output_dir / "runs"` for the runs directory. Setting `output_dir` to `.dkmv/` means runs go to `.dkmv/runs/`.

**When no init:** Falls back to `DKMV_OUTPUT_DIR` or `./outputs` (existing behavior unchanged).

**The `DKMV_OUTPUT_DIR` env var still overrides project config** — it's higher in the cascade. If someone explicitly sets `DKMV_OUTPUT_DIR`, that wins.

### 6.9 CLI Changes (--repo Optional)

**Change:** `--repo` becomes optional on `dkmv run` and on all wrapper commands when `.dkmv/config.json` provides a default.

**`dkmv run` command:**

Currently, `repo` is a **required** `typer.Option("--repo")` with type `str` (no default). Change to `str | None` with default `None`:

```python
@app.command(name="run")
@async_command
async def run_component(
    component: str,
    repo: Annotated[str | None, typer.Option("--repo", help="Repository URL (default: from project config).")] = None,
    ...
) -> None:
    config = load_config()
    project = load_project_config()

    # Resolve repo: CLI flag > project config > error
    resolved_repo = repo
    if resolved_repo is None and project:
        resolved_repo = project.repo
    if resolved_repo is None:
        typer.echo("Error: --repo is required (or run 'dkmv init' to set a default).", err=True)
        raise typer.Exit(code=1)
```

This changes the error behavior: previously Typer would auto-error with "Missing option '--repo'". Now the error message is custom and suggests `dkmv init`. Existing scripts that pass `--repo` continue to work unchanged.

**Wrapper commands (`dev`, `qa`, `judge`, `docs`):**

These commands currently use `repo` as a required positional `typer.Argument()`. **Convert `repo` from a positional Argument to a named `--repo` Option** for consistency with `dkmv run` and to cleanly support optionality.

**This is a breaking change.** The old syntax was:

```bash
dkmv dev https://github.com/org/repo --prd prd.md      # old: positional
```

The new syntax is:

```bash
dkmv dev --repo https://github.com/org/repo --prd prd.md  # new: named option
dkmv dev --prd prd.md                                      # new: repo from project config
```

**Justification:** Since this is a pre-1.0 tool and `dkmv init` fundamentally changes the UX model, this is an acceptable breaking change. The named `--repo` option is more explicit and consistent across all commands. Without this change, having an optional positional argument creates ambiguous CLI parsing.

Same fallback pattern as `dkmv run`: `--repo` flag > project config > error suggesting `dkmv init`.

**Important:** The `--repo` flag always wins when provided, even if project config has a different value. This allows one-off runs against a different repo without modifying project config.

### 6.10 Rich Init Experience

The init command uses Rich to create a visually engaging, step-by-step experience.

**Visual Design:**

```
┌─────────────────────────────────────────────────────┐
│                                                     │
│   DKMV Init                                         │
│   Initialize your project for AI-powered agents     │
│                                                     │
└─────────────────────────────────────────────────────┘

  [1/4] Detecting project...
        Project:     my-project
        Repository:  https://github.com/org/my-project
        Branch:      main

  [2/4] Checking credentials...
        Anthropic API Key:  found (environment variable)
        GitHub Token:       found (gh CLI)

  [3/4] Checking Docker...
        Image:  dkmv-sandbox:latest (found, 2.1GB)

  [4/4] Writing configuration...
        Created .dkmv/config.json
        Created .dkmv/runs/
        Updated .gitignore

┌─────────────────────────────────────────────────────┐
│                                                     │
│   DKMV initialized for my-project                   │
│                                                     │
│   Next steps:                                       │
│     dkmv build        Build the sandbox image       │
│     dkmv run dev      Run the dev agent             │
│     dkmv components   See available components      │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Implementation with Rich:**

- **Header panel:** `Panel()` with title and subtitle
- **Step numbers:** `[bold cyan][1/4][/bold cyan]` markup
- **Spinners:** `console.status()` context manager for detection/validation steps
- **Status indicators:** `[green]✓[/green]` for found, `[yellow]![/yellow]` for warning, `[red]✗[/red]` for missing
- **Success panel:** Green-bordered `Panel()` with next steps
- **Interactive prompts:** Use `typer.prompt()` and `typer.confirm()` for input (keeps dependency count low — no new libraries needed). Typer's prompt functions work well with Rich's console and are sufficient for the init flow.

**Non-interactive mode (`--yes`):**
- Skip all prompts, accept all defaults
- If a required value can't be auto-detected and `--yes` is set, print error and exit
- Suitable for CI/CD environments and scripted setup

---

## 7. Implementation Phases

### Phase 1: Project Config Foundation

**Goal:** The data layer — Pydantic models for project config, `load_project_config()`, `find_project_root()`, and modified `load_config()` with project config cascade.

**Tasks:**
- T200: Create `dkmv/project.py` with `ProjectConfig`, `CredentialSources`, `ProjectDefaults`, `SandboxSettings` models
- T201: Implement `find_project_root()` — walk up from CWD looking for `.dkmv/config.json`
- T202: Implement `load_project_config()` — load and validate `.dkmv/config.json`
- T203: Modify `load_config()` in `config.py` to merge project config defaults using compare-against-defaults pattern and `_BUILTIN_DEFAULTS` dict
- T204: Fix `.env` resolution from subdirectories — pass `_env_file=project_root / ".env"` to DKMVConfig when project root differs from CWD
- T205: Add `get_repo()` helper — resolves repo from CLI arg, project config, or error
- T206: Write tests for project config loading, cascade, find_project_root, `.env` subdirectory resolution

**Files:**
- New: `dkmv/project.py`
- Modified: `dkmv/config.py`
- New: `tests/unit/test_project.py`

### Phase 2: Init Command + Rich UX

**Goal:** The `dkmv init` command with all 5 phases, Rich output, and interactive/non-interactive modes.

**Tasks:**
- T210: Implement credential discovery functions (env var, dotenv, gh CLI)
- T211: Implement project detection functions (git remote, branch, project name)
- T212: Implement Docker image check
- T213: Implement `.dkmv/` directory creation and config writing
- T214: Implement `.gitignore` update (add `.dkmv/`, `.env`)
- T215: Implement the `dkmv init` CLI command with Rich panels and step output
- T216: Implement `--yes` non-interactive mode
- T217: Implement reinit behavior (detect existing `.dkmv/`, preserve runs/components)
- T218: Handle `.env` creation/update for missing credentials
- T219: Write tests for init command, credential discovery, project detection

**Files:**
- New: `dkmv/init.py` (init logic, separate from CLI)
- Modified: `dkmv/cli.py` (add `init` command)
- New: `tests/unit/test_init.py`

### Phase 3: Component Registry

**Goal:** `dkmv components`, `dkmv register`, `dkmv unregister` commands with modified `resolve_component()`.

**Tasks:**
- T220: Create `ComponentRegistry` class (load/save `.dkmv/components.json`, register/unregister/list)
- T221: Modify `resolve_component()` to add registry lookup as step 3
- T222: Implement `dkmv components` command (Rich table, built-in + custom)
- T223: Implement `dkmv register` command with validation
- T224: Implement `dkmv unregister` command
- T225: Update error messages in `resolve_component()` to include registered components
- T226: Write tests for registry, modified discovery, CLI commands

**Files:**
- New: `dkmv/registry.py`
- Modified: `dkmv/tasks/discovery.py`
- Modified: `dkmv/cli.py`
- New: `tests/unit/test_registry.py`
- Modified: `tests/unit/test_discovery.py`

### Phase 4: Container-Side Rename

**Goal:** Rename all container-side references from `.dkmv/` to `.agent/`.

**Tasks:**
- T230: Update `ComponentRunner._setup_workspace()` — `.dkmv/` → `.agent/`
- T231: Update `BaseComponent._setup_workspace()` — `.dkmv/` → `.agent/` (legacy)
- T232: Update all 5 built-in YAML task files — `dest:` and `path:` fields
- T233: Update all 4 prompt template `.md` files — text references
- T234: Update all legacy Python component files — path strings
- T235: Update and regenerate all test files and snapshots
- T236: Update documentation (`README.md`, `CLAUDE.md`, `E2E_TEST_GUIDE.md`)

**Files:**
- Modified: `dkmv/tasks/component.py`
- Modified: `dkmv/components/base.py`
- Modified: `dkmv/builtins/dev/01-plan.yaml`, `02-implement.yaml`
- Modified: `dkmv/builtins/qa/01-evaluate.yaml`
- Modified: `dkmv/builtins/judge/01-verdict.yaml`
- Modified: `dkmv/builtins/docs/01-generate.yaml`
- Modified: `dkmv/components/dev/prompt.md`, `component.py`
- Modified: `dkmv/components/qa/prompt.md`, `component.py`
- Modified: `dkmv/components/judge/prompt.md`, `component.py`
- Modified: Multiple test files
- Modified: `README.md`, `CLAUDE.md`, `E2E_TEST_GUIDE.md`

### Phase 5: CLI Integration + Polish

**Goal:** Make `--repo` optional, relocate run outputs, update all documentation, final verification.

**Tasks:**
- T240: Make `--repo` optional on `dkmv run` — change type from `str` to `str | None` with default `None`, add project config fallback
- T241: Convert `repo` from positional `Argument` to named `--repo` `Option` on wrapper commands (`dev`, `qa`, `judge`, `docs`) — breaking change, add project config fallback
- T242: Relocate run output dir to `.dkmv/` when project is initialized
- T243: Update `dkmv runs` and `dkmv show` to use project-scoped output dir
- T244: Update README.md — add init documentation, new getting-started flow
- T245: Update CLAUDE.md — add init, project config, component registry
- T246: Final test suite verification — all tests pass, coverage >= 80%
- T247: Update `.env.example` — placeholder values instead of real keys, add comments about `dkmv init`

**Files:**
- Modified: `dkmv/cli.py`
- Modified: `dkmv/config.py`
- Modified: `README.md`, `CLAUDE.md`
- Modified: `.env.example`
- New/modified: test files

---

## 8. Testing Strategy

### Test Categories

| Category | Files | Count (est.) | What's Tested |
|----------|-------|-------------|---------------|
| Project config models | `test_project.py` | ~20 | ProjectConfig validation, defaults, cascade |
| find_project_root | `test_project.py` | ~8 | Walk-up discovery, CWD fallback, nested dirs |
| Config cascade | `test_project.py` | ~10 | Project config overrides, env var priority |
| Credential discovery | `test_init.py` | ~15 | Env var, dotenv, gh CLI, missing credentials |
| Project detection | `test_init.py` | ~8 | Git remote, branch, project name |
| Init command | `test_init.py` | ~12 | Full init flow, reinit, --yes mode, error cases |
| Component registry | `test_registry.py` | ~15 | Register, unregister, list, validation, stale paths |
| Modified discovery | `test_discovery.py` | ~5 | Registry lookup in resolve_component() |
| CLI commands | `test_cli_init.py` | ~10 | init, components, register, unregister via CliRunner |
| Container rename | Existing test files | ~0 new | Snapshot updates, path assertion updates |
| Repo optional | `test_cli_run.py` | ~5 | --repo fallback to project config |
| **Total** | | **~108** | |

### Testing Patterns

```python
# Project config — use tmp_path for .dkmv/ directories
def test_load_project_config(tmp_path):
    dkmv_dir = tmp_path / ".dkmv"
    dkmv_dir.mkdir()
    (dkmv_dir / "config.json").write_text('{"version": 1, "project_name": "test", "repo": "https://..."}')
    # monkeypatch CWD to tmp_path
    config = load_project_config()
    assert config.project_name == "test"

# Credential discovery — mock subprocess and env
def test_discover_github_token_from_gh_cli(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(subprocess, "run", mock_gh_auth_token)
    source, found = discover_github_token()
    assert source == "gh_cli"
    assert found is True

# Init command — CliRunner with mocked filesystem
def test_init_creates_dkmv_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Setup: create .git/config with remote
    result = CliRunner().invoke(app, ["init", "--yes"])
    assert result.exit_code == 0
    assert (tmp_path / ".dkmv" / "config.json").exists()

# Component registry — mock .dkmv/components.json
def test_resolve_registered_component(tmp_path, monkeypatch):
    # Create .dkmv/components.json with entry
    # Create component dir with YAML files
    path = resolve_component("my-component")
    assert path.name == "my-component"
```

### Snapshot Handling

Phase 4 (container-side rename) will require regenerating all prompt snapshots in `tests/unit/__snapshots__/test_prompts.ambr`. This is done by running:

```bash
uv run pytest tests/unit/test_prompts.py --snapshot-update
```

The snapshot changes are expected and should be reviewed to confirm all `.dkmv/` → `.agent/` replacements are correct.

---

## 9. User Stories

### US-01: First-time setup

**As a** developer using DKMV for the first time,
**I want to** run `dkmv init` in my project directory,
**So that** DKMV is configured with my repo, credentials, and defaults without manual file editing.

**Acceptance Criteria:**
- `dkmv init` auto-detects repo URL from `git remote`
- `dkmv init` discovers existing API keys from env vars or `.env`
- `dkmv init` discovers GitHub token from `gh auth token`
- `.dkmv/config.json` is created with detected values
- `.dkmv/` is added to `.gitignore`
- After init, `dkmv run dev --var prd_path=prd.md` works without `--repo`

### US-02: Running without init

**As a** developer who hasn't initialized DKMV,
**I want to** still run commands with explicit flags,
**So that** DKMV works for one-off use without commitment.

**Acceptance Criteria:**
- `dkmv run dev --repo https://... --var prd_path=prd.md` works without `.dkmv/`
- Error message when `--repo` is missing suggests `dkmv init`
- No command crashes when `.dkmv/` doesn't exist

### US-03: Custom component registration

**As a** developer with custom components,
**I want to** register them by name,
**So that** I can use short names instead of paths.

**Acceptance Criteria:**
- `dkmv register strict-judge ./components/strict-judge` adds to registry
- `dkmv run strict-judge --var prd_path=prd.md` resolves from registry
- `dkmv components` shows both built-in and registered components
- `dkmv unregister strict-judge` removes from registry
- Registering a built-in name (`dev`, `qa`, `judge`, `docs`) fails with error

### US-04: Reinitializing

**As a** developer who needs to update their DKMV config,
**I want to** re-run `dkmv init`,
**So that** I can update my repo URL or re-detect credentials without losing run history.

**Acceptance Criteria:**
- `dkmv init` in an already-initialized project shows current config
- Asks for confirmation before reinitializing
- Preserves `.dkmv/runs/` and `.dkmv/components.json`
- Only regenerates `.dkmv/config.json`

### US-05: Project-scoped run history

**As a** developer working on multiple projects,
**I want** run history to be project-scoped,
**So that** `dkmv runs` shows only this project's runs.

**Acceptance Criteria:**
- After init, runs are stored in `.dkmv/runs/`
- `dkmv runs` shows only runs from `.dkmv/runs/`
- Without init, runs go to `./outputs/runs/` (backward compatible)

### US-06: Listing available components

**As a** developer,
**I want to** see all available components,
**So that** I know what I can run.

**Acceptance Criteria:**
- `dkmv components` works without init (shows only built-ins)
- With init, shows built-in + registered components
- Shows task count for each component
- Clearly distinguishes built-in from custom

### US-07: Non-interactive init (CI/CD)

**As a** CI/CD engineer,
**I want to** run `dkmv init --yes --repo https://...`,
**So that** init works in non-interactive environments.

**Acceptance Criteria:**
- `--yes` skips all prompts
- `--repo` provides the repo URL when git remote isn't available
- Exits with error if required values can't be auto-detected
- No TTY required

### US-08: Working from subdirectories

**As a** developer,
**I want to** run DKMV commands from a subdirectory of my project,
**So that** I don't have to be in the project root.

**Acceptance Criteria:**
- `find_project_root()` walks up from CWD to find `.dkmv/config.json`
- `dkmv run dev --var prd_path=prd.md` works from `src/` subdirectory
- `dkmv runs` works from any subdirectory

---

## 10. Open Questions

### OQ-1: Should `dkmv init` auto-run `dkmv build`?

**Current decision:** No. Building the Docker image takes minutes and should be a deliberate action. Init checks if the image exists and suggests running `dkmv build` if it doesn't.

**Future consideration:** Could add `--build` flag to init that triggers image build after config setup.

### OQ-2: Should the component registry support relative paths?

**Current decision:** Yes. Relative paths are resolved relative to the project root at runtime. This allows component directories to be inside the project tree (e.g., `./custom/strict-judge`).

**Risk:** If the user runs DKMV from a subdirectory, relative paths must still resolve from the project root, not from CWD.

### OQ-3: Should `dkmv init` validate credentials by making API calls?

**Current decision:** Optional validation with spinner. If network is unavailable, skip silently. Don't block init on network failures.

**Rationale:** Validation catches typos early but introduces a network dependency. The compromise: try to validate, warn if it fails, but don't error.

### OQ-4: What happens when `.dkmv/config.json` has an unknown `version`?

**Current decision:** Error with message: "This project was initialized with a newer version of DKMV. Please upgrade DKMV or run `dkmv init` to reinitialize."

### OQ-5: Should we add `dkmv status` to show current project state?

**Deferred to future PRD.** Would show: initialized project info, credential status, image status, recent runs, registered components. Nice to have but not essential for v1.

### OQ-6: Docker image customization during init?

**Deferred to future PRD.** Init v1 focuses on config and credentials. Future versions could detect project stack (Go, Rust, Java, etc.) and customize the sandbox image. The `sandbox` section in `config.json` provides the extension point.

---

## 11. Evaluation Criteria

### Phase 1: Project Config Foundation

- [ ] `ProjectConfig` model validates `.dkmv/config.json` correctly
- [ ] `find_project_root()` walks up directory tree and finds `.dkmv/`
- [ ] `load_project_config()` returns `None` when not initialized
- [ ] Modified `load_config()` merges project defaults correctly
- [ ] Config cascade order: CLI > env > .env > project config > built-in defaults
- [ ] Environment variables always override project config
- [ ] All existing tests still pass (no regressions)

### Phase 2: Init Command + Rich UX

- [ ] `dkmv init` creates `.dkmv/config.json` with correct values
- [ ] `dkmv init` auto-detects repo from `git remote get-url origin`
- [ ] `dkmv init` discovers Anthropic key from env var
- [ ] `dkmv init` discovers GitHub token from `gh auth token`
- [ ] `dkmv init` creates `.dkmv/runs/` directory
- [ ] `dkmv init` adds `.dkmv/` to `.gitignore`
- [ ] `dkmv init --yes` works non-interactively
- [ ] `dkmv init` is idempotent (safe to re-run)
- [ ] Rich output with panels, step numbers, and status indicators
- [ ] Missing credentials trigger interactive prompt (or error with `--yes`)
- [ ] All existing tests still pass

### Phase 3: Component Registry

- [ ] `dkmv register <name> <path>` adds to `.dkmv/components.json`
- [ ] `dkmv unregister <name>` removes from `.dkmv/components.json`
- [ ] `dkmv components` lists built-in and registered components
- [ ] `resolve_component()` checks registry after built-ins
- [ ] Built-in names cannot be registered
- [ ] Invalid paths are rejected at registration time
- [ ] Stale paths show warnings in `dkmv components`
- [ ] All existing tests still pass

### Phase 4: Container-Side Rename

- [ ] `.agent/` created instead of `.dkmv/` inside containers
- [ ] All built-in YAML files reference `.agent/` paths
- [ ] All prompt templates reference `.agent/` paths
- [ ] All legacy Python components reference `.agent/` paths
- [ ] `.agent/` added to `.gitignore` (not `.dkmv/`)
- [ ] All test snapshots regenerated and correct
- [ ] All existing tests still pass
- [ ] Documentation updated

### Phase 5: CLI Integration + Polish

- [ ] `--repo` is optional on `dkmv run` when project is initialized
- [ ] `repo` is optional on wrapper commands when initialized
- [ ] Missing `--repo` without init produces helpful error suggesting `dkmv init`
- [ ] Run outputs go to `.dkmv/runs/` when initialized
- [ ] `dkmv runs` reads from `.dkmv/runs/` when initialized
- [ ] `DKMV_OUTPUT_DIR` env var overrides project output dir
- [ ] README.md documents init, components, register
- [ ] CLAUDE.md updated with init system
- [ ] `.env.example` uses placeholder values
- [ ] All tests pass, coverage >= 80%
- [ ] All quality gates clean (ruff, mypy)

### Overall

- [ ] Zero regressions in existing functionality
- [ ] 108+ new tests across all phases
- [ ] Coverage >= 80%
- [ ] `dkmv init → dkmv run dev --var prd_path=prd.md` works end-to-end (no `--repo`)
- [ ] `dkmv run dev --repo https://... --var prd_path=prd.md` still works without init

---

## Appendix A: Full `.dkmv/config.json` Schema

```json
{
  "version": 1,
  "project_name": "string (required)",
  "repo": "string (required, URL or local path)",
  "default_branch": "string (default: 'main')",
  "credentials": {
    "anthropic_api_key_source": "string (default: 'env', values: 'env'|'dotenv'|'manual')",
    "github_token_source": "string (default: 'env', values: 'env'|'dotenv'|'gh_cli'|'none')"
  },
  "defaults": {
    "model": "string|null (default: null → cascade to DKMV_MODEL or built-in)",
    "max_turns": "int|null (default: null → cascade)",
    "timeout_minutes": "int|null (default: null → cascade)",
    "max_budget_usd": "float|null (default: null → cascade)",
    "memory": "string|null (default: null → cascade)"
  },
  "sandbox": {
    "image": "string|null (default: null → cascade to DKMV_IMAGE or built-in)"
  }
}
```

## Appendix B: Credential Discovery Priority Chain

```
Anthropic API Key:
  1. ANTHROPIC_API_KEY env var
  2. .env file (ANTHROPIC_API_KEY=...)
  3. Interactive prompt → write to .env

GitHub Token:
  1. GITHUB_TOKEN or GH_TOKEN env var
  2. .env file (GITHUB_TOKEN=...)
  3. gh auth token (GitHub CLI credential store)
  4. Interactive prompt → write to .env
  5. Skip (optional for public repos)
```

## Appendix C: `.agent/` Directory Layout (Inside Container)

```
/home/dkmv/workspace/
├── .agent/                     # Agent workspace (gitignored)
│   ├── prd.md                  # Input: Product Requirements Document
│   ├── plan.md                 # Output: Implementation plan (dev)
│   ├── qa_report.json          # Output: QA test report (qa)
│   ├── verdict.json            # Output: Judge verdict (judge)
│   ├── feedback.json           # Input: Optional feedback from previous run
│   └── design_docs/            # Input: Optional design documents
│       ├── api_spec.md
│       └── db_schema.md
├── .claude/
│   └── CLAUDE.md               # Agent instructions (written by TaskRunner)
├── .git/
├── src/
└── ...
```

## Appendix D: Migration from Legacy `./outputs/`

When a project is initialized and has existing runs in `./outputs/runs/`:
- Init does **not** migrate existing runs automatically
- A future `dkmv migrate-runs` command could move them
- `dkmv runs` only reads from the active output directory (either `.dkmv/runs/` or `./outputs/runs/`, not both)
- Users can manually move runs: `mv ./outputs/runs/* .dkmv/runs/`
