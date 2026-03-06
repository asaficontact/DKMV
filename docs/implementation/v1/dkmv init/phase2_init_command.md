# Phase 2: Init Command + Rich UX

## Prerequisites

- Phase 1 complete: `ProjectConfig`, `find_project_root()`, `load_project_config()`, modified `load_config()` all working
- `uv run pytest tests/unit/test_project.py -v` — all pass
- All quality gates passing

## Phase Goal

`dkmv init` creates `.dkmv/` with auto-detected project configuration, discovered credentials, Docker image status, and a visually engaging Rich experience. Both interactive and non-interactive (`--yes`) modes work.

## Phase Evaluation Criteria

- `dkmv init` creates `.dkmv/config.json` with auto-detected repo, project name, branch
- `dkmv init` discovers Anthropic key from environment variable
- `dkmv init` discovers GitHub token from `gh auth token`
- `dkmv init` creates `.dkmv/runs/` directory
- `dkmv init` creates `.dkmv/components.json` (empty `{}`)
- `dkmv init` adds `.dkmv/` to `.gitignore`
- `dkmv init --yes` works non-interactively
- `dkmv init --yes --repo https://...` provides repo in non-git environments
- Re-running `dkmv init` preserves `.dkmv/runs/` and `.dkmv/components.json`
- Rich output with panels, step numbers, and status indicators
- Missing credentials trigger interactive prompt (or error with `--yes`)
- `uv run pytest tests/unit/test_init.py -v` — all pass
- `uv run ruff check . && uv run ruff format --check . && uv run mypy dkmv/` — clean
- All existing tests still pass

---

## Tasks

### T210: Implement Credential Discovery Functions

**PRD Reference:** Section 6.1 Phase 3 (Credential Discovery), Appendix B
**Depends on:** Nothing (standalone functions)
**Blocks:** T215
**User Stories:** US-01

#### Description

Create credential discovery functions that check multiple sources in priority order and return the source name (never the value).

#### Acceptance Criteria

- [x] `discover_anthropic_key()` checks: env var → `.env` file → returns `(source, found)` tuple
- [x] `discover_github_token()` checks: env var → `.env` file → `gh auth token` → returns `(source, found)` tuple
- [x] Environment variable check uses `os.environ.get()`
- [x] `.env` file parsing uses simple key=value reading (no dependency on python-dotenv)
- [x] `gh auth token` executed via `subprocess.run()` with `capture_output=True`
- [x] All functions are pure and testable — no side effects

#### Files to Create/Modify

- `dkmv/init.py` — (create) Credential discovery functions

#### Implementation Notes

```python
import os
import subprocess
from pathlib import Path

def _parse_env_file(env_path: Path) -> dict[str, str]:
    """Parse a .env file into key=value pairs. Ignores comments and blank lines."""
    if not env_path.exists():
        return {}
    result = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result

def discover_anthropic_key(project_root: Path) -> tuple[str, bool]:
    """Discover Anthropic API key. Returns (source, found)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "env", True
    env_vars = _parse_env_file(project_root / ".env")
    if env_vars.get("ANTHROPIC_API_KEY"):
        return "dotenv", True
    return "none", False

def discover_github_token(project_root: Path) -> tuple[str, bool]:
    """Discover GitHub token. Returns (source, found)."""
    if os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"):
        return "env", True
    env_vars = _parse_env_file(project_root / ".env")
    if env_vars.get("GITHUB_TOKEN") or env_vars.get("GH_TOKEN"):
        return "dotenv", True
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return "gh_cli", True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "none", False
```

#### Evaluation Checklist

- [x] Env var discovery works for both credentials
- [x] `.env` file parsing handles comments, blank lines, missing file
- [x] `gh auth token` handles missing `gh` CLI, timeout, non-zero exit
- [x] Functions return source name, never credential values

**Note:** The PRD (Section 6.1 Phase 3) mentions optional credential *validation* — making API calls to verify the key works (e.g., list models, `gh auth status`). This is deliberately deferred from v1 implementation. Credential *discovery* (finding where the key is) is implemented; *validation* (verifying it works) can be added later as an enhancement. The PRD itself notes validation is "skippable" and should not "block init if network is unavailable."

---

### T211: Implement Project Detection Functions

**PRD Reference:** Section 6.1 Phase 2 (Project Detection)
**Depends on:** Nothing (standalone functions)
**Blocks:** T215
**User Stories:** US-01

#### Description

Create project detection functions that auto-detect repository URL, project name, and default branch from git.

#### Acceptance Criteria

- [x] `detect_repo()` runs `git remote get-url origin` and returns URL or None
- [x] `detect_project_name(repo_url)` derives name from URL (last path segment without `.git`) or falls back to directory name
- [x] `detect_default_branch()` runs `git symbolic-ref refs/remotes/origin/HEAD` and returns branch name or "main"
- [x] All functions handle subprocess errors gracefully (return defaults)

#### Files to Create/Modify

- `dkmv/init.py` — (modify) Add project detection functions

#### Implementation Notes

```python
def detect_repo(project_root: Path) -> str | None:
    """Detect repository URL from git remote."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, cwd=project_root, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None

def detect_project_name(repo_url: str | None, project_root: Path) -> str:
    """Derive project name from repo URL or directory name."""
    if repo_url:
        name = repo_url.rstrip("/").rsplit("/", 1)[-1]
        return name.removesuffix(".git")
    return project_root.name

def detect_default_branch(project_root: Path) -> str:
    """Detect default branch from git. Falls back to 'main'."""
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True, text=True, cwd=project_root, timeout=10,
        )
        if result.returncode == 0:
            ref = result.stdout.strip()  # e.g., "refs/remotes/origin/main"
            return ref.rsplit("/", 1)[-1]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "main"
```

#### Evaluation Checklist

- [x] Repo detected from git remote
- [x] Project name derived from URL or directory
- [x] Default branch detected or falls back to "main"
- [x] Graceful handling of non-git directories

---

### T212: Implement Docker Image Check

**PRD Reference:** Section 6.1 Phase 4 (Docker Image Check)
**Depends on:** Nothing
**Blocks:** T215
**User Stories:** US-01

#### Description

Create a function to check if the configured Docker image exists locally and report its size.

#### Acceptance Criteria

- [x] Checks `docker image inspect <image_name>` — returns found status + size
- [x] Uses image name from `DKMVConfig.image_name` (not hardcoded)
- [x] Graceful when Docker is not installed (`shutil.which("docker")` check)
- [x] Graceful when image doesn't exist (suggests `dkmv build`)

#### Files to Create/Modify

- `dkmv/init.py` — (modify) Add Docker check function

#### Implementation Notes

```python
import shutil
from dataclasses import dataclass

@dataclass
class DockerStatus:
    docker_available: bool
    image_found: bool
    image_name: str
    image_size: str | None = None

def check_docker_image(image_name: str) -> DockerStatus:
    """Check if Docker is available and image exists."""
    if not shutil.which("docker"):
        return DockerStatus(docker_available=False, image_found=False, image_name=image_name)
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image_name, "--format", "{{.Size}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            size_bytes = int(result.stdout.strip())
            size_gb = f"{size_bytes / (1024**3):.1f}GB"
            return DockerStatus(
                docker_available=True, image_found=True,
                image_name=image_name, image_size=size_gb,
            )
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return DockerStatus(docker_available=True, image_found=False, image_name=image_name)
```

#### Evaluation Checklist

- [x] Returns found=True when image exists
- [x] Returns found=False when image missing
- [x] Returns docker_available=False when Docker not installed
- [x] Uses configured image name, not hardcoded

---

### T213: Implement `.dkmv/` Directory Creation

**PRD Reference:** Section 6.1 Phase 5 (Write Configuration)
**Depends on:** T200
**Blocks:** T215
**User Stories:** US-01

#### Description

Create functions to write `.dkmv/config.json`, create `.dkmv/runs/`, and create `.dkmv/components.json`.

#### Acceptance Criteria

- [x] Creates `.dkmv/` directory if it doesn't exist
- [x] Creates `.dkmv/runs/` directory
- [x] Writes `.dkmv/config.json` from `ProjectConfig` model
- [x] Writes `.dkmv/components.json` as empty `{}` (only if it doesn't exist — preserve during reinit)
- [x] Reinit preserves existing `runs/` and `components.json`
- [x] Config JSON is pretty-printed with indent=2

#### Files to Create/Modify

- `dkmv/init.py` — (modify) Add directory creation functions

#### Implementation Notes

```python
from dkmv.project import ProjectConfig

def write_project_config(project_root: Path, config: ProjectConfig) -> None:
    """Write .dkmv/config.json and create supporting directories."""
    dkmv_dir = project_root / ".dkmv"
    dkmv_dir.mkdir(exist_ok=True)
    (dkmv_dir / "runs").mkdir(exist_ok=True)

    # Write config.json (always overwrite — reinit behavior)
    config_path = dkmv_dir / "config.json"
    config_path.write_text(config.model_dump_json(indent=2) + "\n")

    # Create components.json only if it doesn't exist (preserve during reinit)
    components_path = dkmv_dir / "components.json"
    if not components_path.exists():
        components_path.write_text("{}\n")
```

#### Evaluation Checklist

- [x] `.dkmv/config.json` written with correct content
- [x] `.dkmv/runs/` created
- [x] `.dkmv/components.json` created (only if missing)
- [x] Reinit preserves existing data

---

### T214: Implement `.gitignore` Update

**PRD Reference:** Section 6.1 Phase 5 (Write Configuration)
**Depends on:** Nothing
**Blocks:** T215
**User Stories:** US-01

#### Description

Create a function to add `.dkmv/` and `.env` to `.gitignore` if not already present.

#### Acceptance Criteria

- [x] Adds `.dkmv/` to `.gitignore` if not present
- [x] Adds `.env` to `.gitignore` if not present and `.env` exists (or was created)
- [x] Creates `.gitignore` if it doesn't exist
- [x] Does not duplicate entries
- [x] Adds a newline before entries if file doesn't end with one

#### Files to Create/Modify

- `dkmv/init.py` — (modify) Add `.gitignore` update function

#### Implementation Notes

```python
def update_gitignore(project_root: Path, entries: list[str]) -> list[str]:
    """Add entries to .gitignore if not already present. Returns list of entries added."""
    gitignore = project_root / ".gitignore"
    existing_lines: set[str] = set()
    if gitignore.exists():
        existing_lines = {line.strip() for line in gitignore.read_text().splitlines()}

    added: list[str] = []
    to_append: list[str] = []
    for entry in entries:
        if entry not in existing_lines:
            to_append.append(entry)
            added.append(entry)

    if to_append:
        content = gitignore.read_text() if gitignore.exists() else ""
        if content and not content.endswith("\n"):
            content += "\n"
        content += "\n".join(to_append) + "\n"
        gitignore.write_text(content)

    return added
```

#### Evaluation Checklist

- [x] `.dkmv/` added when not present
- [x] `.env` added when not present
- [x] No duplicates created
- [x] File created if missing

---

### T215: Implement `dkmv init` CLI Command

**PRD Reference:** Section 6.1 (`dkmv init` Command), Section 6.10 (Rich Init Experience)
**Depends on:** T210, T211, T212, T213, T214
**Blocks:** T216, T217
**User Stories:** US-01

#### Description

Implement the `dkmv init` command in `cli.py` that orchestrates the 5-phase init flow with Rich output.

#### Acceptance Criteria

- [x] `dkmv init` registered as a Typer command
- [x] Accepts `--yes`, `--repo`, `--name` flags
- [x] Phase 1: Pre-flight checks (existing init, Docker, git)
- [x] Phase 2: Project detection (repo, name, branch)
- [x] Phase 3: Credential discovery (Anthropic key, GitHub token)
- [x] Phase 4: Docker image check
- [x] Phase 5: Write configuration (`.dkmv/`, `.gitignore`)
- [x] Rich panels for header and success summary
- [x] Step numbers `[1/4]` through `[4/4]` with colored status indicators
- [x] Success panel with next steps
- [x] Exit code 0 on success

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) Add `init` command
- `dkmv/init.py` — (modify) Add `run_init()` orchestration function

#### Implementation Notes

Keep the init logic in `dkmv/init.py` and the CLI registration in `dkmv/cli.py`. The CLI command calls `run_init()`:

```python
# In dkmv/cli.py
@app.command()
def init(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Accept all defaults.")] = False,
    repo: Annotated[str | None, typer.Option("--repo", help="Repository URL.")] = None,
    name: Annotated[str | None, typer.Option("--name", help="Project name.")] = None,
) -> None:
    """Initialize DKMV for the current project."""
    from dkmv.init import run_init
    run_init(yes=yes, repo_override=repo, name_override=name)
```

The `run_init()` function orchestrates the phases and handles Rich output:

```python
# In dkmv/init.py
from rich.console import Console
from rich.panel import Panel

def run_init(
    yes: bool = False,
    repo_override: str | None = None,
    name_override: str | None = None,
) -> None:
    console = Console()
    project_root = Path.cwd()

    # Header panel
    console.print(Panel(
        "[bold]DKMV Init[/bold]\nInitialize your project for AI-powered agents",
        expand=False,
    ))

    # Step [1/4]: Detect project
    console.print("\n  [bold cyan][1/4][/bold cyan] Detecting project...")
    # ... detection logic ...

    # Step [2/4]: Check credentials
    console.print("\n  [bold cyan][2/4][/bold cyan] Checking credentials...")
    # ... credential discovery ...

    # Step [3/4]: Check Docker
    console.print("\n  [bold cyan][3/4][/bold cyan] Checking Docker...")
    # ... docker check ...

    # Step [4/4]: Write configuration
    console.print("\n  [bold cyan][4/4][/bold cyan] Writing configuration...")
    # ... write config, gitignore ...

    # Success panel
    console.print(Panel(
        f"[bold green]DKMV initialized for {project_name}[/bold green]\n\n"
        "Next steps:\n"
        "  dkmv build        Build the sandbox image\n"
        "  dkmv run dev      Run the dev agent\n"
        "  dkmv components   See available components",
        expand=False,
    ))
```

Note: The PRD shows 5 phases in the init flow, but the UX groups pre-flight checks into detection, so the displayed steps are `[1/4]` through `[4/4]`.

#### Evaluation Checklist

- [x] `dkmv init --help` shows command and all flags
- [x] `dkmv init --yes` creates `.dkmv/` in a git project with env vars set
- [x] Rich output displays panels and step indicators
- [x] Exit code 0 on success

---

### T216: Implement `--yes` Non-interactive Mode

**PRD Reference:** Section 6.1 (--yes flag), Section 6.10 (Non-interactive mode)
**Depends on:** T215
**Blocks:** Nothing
**User Stories:** US-07

#### Description

Ensure `--yes` mode skips all prompts and works in non-TTY environments.

#### Acceptance Criteria

- [x] `--yes` skips confirmation prompts
- [x] `--yes` accepts auto-detected values without asking
- [x] If repo can't be detected and `--repo` not provided, exit with error
- [x] If Anthropic key not found and `--yes`, exit with error (can't prompt)
- [x] No TTY required when `--yes` is set

#### Files to Create/Modify

- `dkmv/init.py` — (modify) Add `--yes` handling to `run_init()`

#### Implementation Notes

In the init flow, each prompt point has a `--yes` guard:

```python
if not yes:
    if not typer.confirm("Use detected repo?", default=True):
        repo_url = typer.prompt("Enter repository URL")
```

When `--yes` is set and a required value is missing (no auto-detection possible):
```python
if repo_url is None and not repo_override:
    if yes:
        console.print("Error: Cannot detect repo. Provide --repo.", style="bold red")
        raise typer.Exit(code=1)
    repo_url = typer.prompt("Enter repository URL")
```

#### Evaluation Checklist

- [x] `dkmv init --yes` succeeds in git repo with env vars
- [x] `dkmv init --yes` fails with clear error when repo can't be detected
- [x] No interactive prompts in `--yes` mode

---

### T217: Implement Reinit Behavior

**PRD Reference:** Section 6.1 Phase 1 (Pre-flight Checks — reinit)
**Depends on:** T215
**Blocks:** Nothing
**User Stories:** US-04

#### Description

Handle the case where `dkmv init` is run in an already-initialized project, and detect nested initialization when run from a subdirectory of an already-initialized project.

#### Acceptance Criteria

- [x] Detects existing `.dkmv/config.json` in CWD (reinit case)
- [x] Shows current configuration summary
- [x] Asks "Reinitialize? (y/N)" (unless `--yes`)
- [x] If yes: regenerates `config.json`, preserves `runs/` and `components.json`
- [x] If no: exits without changes
- [x] Detects existing `.dkmv/config.json` in a **parent** directory (nested init case)
- [x] Warns about nested initialization and asks for confirmation
- [x] `--yes` skips nested init warning and initializes in CWD

#### Files to Create/Modify

- `dkmv/init.py` — (modify) Add reinit and nested init handling to `run_init()`

#### Implementation Notes

At the start of `run_init()`, check two scenarios:

```python
from dkmv.project import find_project_root, load_project_config

project_root = Path.cwd()

# Check 1: CWD already initialized (reinit)
existing_config = load_project_config(project_root)
if existing_config:
    console.print(f"  DKMV is already initialized for [bold]{existing_config.project_name}[/bold]")
    console.print(f"  Repo: {existing_config.repo}")
    if not yes:
        if not typer.confirm("Reinitialize?", default=False):
            raise typer.Exit(code=0)
    # Continue with init flow — write_project_config() overwrites config.json
    # but mkdir(exist_ok=True) preserves runs/ and components.json

# Check 2: Parent directory already initialized (nested init prevention)
else:
    parent_root = find_project_root()
    if parent_root != project_root and (parent_root / ".dkmv" / "config.json").exists():
        parent_config = load_project_config(parent_root)
        if parent_config:
            console.print(
                f"  [yellow]Warning:[/yellow] Parent directory already initialized "
                f"at [bold]{parent_root}[/bold] ({parent_config.project_name})"
            )
            console.print(
                "  Creating a nested .dkmv/ in the current directory is usually unintended."
            )
            if not yes:
                if not typer.confirm("Initialize in current directory anyway?", default=False):
                    raise typer.Exit(code=0)
```

**Rationale:** Tools like DVC require `--subdir` to create nested configs. npm creates disconnected configs silently. DKMV warns and asks — a safe middle ground. With `--yes`, the nested init proceeds (useful for monorepo setups where subdirectories are independent projects).

#### Evaluation Checklist

- [x] Detects existing init in CWD
- [x] Prompts before reinit (interactive mode)
- [x] `--yes` reinits without prompting
- [x] `runs/` and `components.json` preserved
- [x] Warns when parent directory has `.dkmv/`
- [x] `--yes` skips nested warning and proceeds

---

### T218: Handle `.env` Creation for Missing Credentials

**PRD Reference:** Section 6.1 Phase 3 (Credential Discovery — interactive prompt)
**Depends on:** T210, T215
**Blocks:** Nothing
**User Stories:** US-01

#### Description

When credentials are missing and user provides them interactively, write them to `.env`.

#### Acceptance Criteria

- [x] Missing Anthropic key → prompt user for it
- [x] Missing GitHub token → prompt or allow skip
- [x] New credentials appended to `.env` (create if needed)
- [x] `.env` added to `.gitignore`
- [x] Never writes credentials to `.dkmv/config.json`

#### Files to Create/Modify

- `dkmv/init.py` — (modify) Add credential prompting in init flow

#### Implementation Notes

```python
def _prompt_and_write_credential(
    project_root: Path, key_name: str, prompt_text: str
) -> str:
    """Prompt for a credential and append it to .env."""
    value = typer.prompt(prompt_text)
    env_path = project_root / ".env"
    content = env_path.read_text() if env_path.exists() else ""
    if content and not content.endswith("\n"):
        content += "\n"
    content += f"{key_name}={value}\n"
    env_path.write_text(content)
    return value
```

When `--yes` is set and Anthropic key is missing, exit with error. GitHub token can be skipped.

#### Evaluation Checklist

- [x] Interactive prompt works for missing key
- [x] Value written to `.env` correctly
- [x] `.env` created if missing
- [x] `--yes` mode exits with error for missing required credentials

---

### T219: Write Init Command Tests

**PRD Reference:** Section 8 (Testing Strategy)
**Depends on:** T210-T218
**Blocks:** Nothing
**User Stories:** N/A (testing)
**Estimated scope:** 1.5 hours

#### Description

Write comprehensive tests for init command, credential discovery, and project detection.

#### Acceptance Criteria

- [x] ~35 tests covering all init functionality
- [x] Credential discovery: env var, dotenv, gh CLI, missing (for both keys)
- [x] Project detection: git remote, non-git, project name derivation, default branch
- [x] Docker check: available + found, available + missing, not available
- [x] Init flow: fresh init, reinit, nested init warning, `--yes` mode, `--repo` override, `--name` override
- [x] `.gitignore` update: new file, existing file, no duplicates
- [x] `.env` creation: new file, append to existing
- [x] Error cases: missing required credentials in `--yes` mode

#### Files to Create/Modify

- `tests/unit/test_init.py` — (create) ~35 tests

#### Implementation Notes

Mock `subprocess.run` for git and docker commands. Mock `os.environ` for credential discovery. Use `tmp_path` and `monkeypatch.chdir()` for file system isolation.

```python
def test_discover_anthropic_key_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    source, found = discover_anthropic_key(Path("/tmp"))
    assert source == "env"
    assert found is True

def test_init_creates_dkmv_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    # Mock git remote
    ...
    result = CliRunner().invoke(app, ["init", "--yes", "--repo", "https://github.com/org/repo"])
    assert result.exit_code == 0
    assert (tmp_path / ".dkmv" / "config.json").exists()
```

#### Evaluation Checklist

- [x] `uv run pytest tests/unit/test_init.py -v` — all pass
- [x] All discovery, detection, and init functions covered
- [x] No existing test regressions
