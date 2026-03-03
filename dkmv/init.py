"""dkmv init — project initialization with credential discovery and Rich UX."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import typer
from dotenv import dotenv_values
from rich.console import Console
from rich.panel import Panel

from dkmv.project import (
    AuthMethod,
    CredentialSources,
    ProjectConfig,
    find_project_root,
    load_project_config,
)

console = Console()


# ── Credential Discovery (T210) ─────────────────────────────────────


def discover_anthropic_key(project_root: Path) -> tuple[str, bool]:
    """Discover Anthropic API key source. Returns (source_name, found)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ("env", True)

    env_file = project_root / ".env"
    if env_file.exists():
        values = dotenv_values(env_file)
        if values.get("ANTHROPIC_API_KEY"):
            return (".env", True)

    return ("none", False)


def discover_oauth_token(project_root: Path) -> tuple[str, bool]:
    """Discover Claude Code OAuth token source. Returns (source_name, found)."""
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return ("env", True)

    env_file = project_root / ".env"
    if env_file.exists():
        values = dotenv_values(env_file)
        if values.get("CLAUDE_CODE_OAUTH_TOKEN"):
            return (".env", True)

    return ("none", False)


def discover_github_token(project_root: Path) -> tuple[str, bool]:
    """Discover GitHub token source. Returns (source_name, found)."""
    if os.environ.get("GITHUB_TOKEN"):
        return ("env:GITHUB_TOKEN", True)

    if os.environ.get("GH_TOKEN"):
        return ("env:GH_TOKEN", True)

    env_file = project_root / ".env"
    if env_file.exists():
        values = dotenv_values(env_file)
        if values.get("GITHUB_TOKEN"):
            return (".env", True)
        if values.get("GH_TOKEN"):
            return (".env", True)

    # Try gh CLI
    if shutil.which("gh"):
        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return ("gh auth token", True)
        except subprocess.TimeoutExpired:
            pass
        except FileNotFoundError:
            pass

    return ("none", False)


# ── Project Detection (T211) ────────────────────────────────────────


def detect_repo(project_root: Path) -> str | None:
    """Detect repository URL from git remote. Returns URL or None."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_root,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def detect_project_name(repo_url: str | None, project_root: Path) -> str:
    """Derive project name from repo URL or directory name."""
    if repo_url:
        # Extract last path segment, strip .git suffix
        name = repo_url.rstrip("/").rsplit("/", 1)[-1]
        if name.endswith(".git"):
            name = name[:-4]
        if name:
            return name
    return project_root.name


def detect_default_branch(project_root: Path) -> str:
    """Detect default branch. Two-step: symbolic-ref → remote show → 'main'."""
    # Step 1: Fast local check
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_root,
        )
        if result.returncode == 0 and result.stdout.strip():
            # refs/remotes/origin/main → main
            return result.stdout.strip().rsplit("/", 1)[-1]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Step 2: Network call (reliable)
    try:
        result = subprocess.run(
            ["git", "remote", "show", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_root,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "HEAD branch:" in line:
                    branch = line.split("HEAD branch:")[-1].strip()
                    if branch:
                        return branch
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return "main"


# ── Docker Image Check (T212) ───────────────────────────────────────


@dataclass
class DockerStatus:
    docker_available: bool
    image_found: bool
    image_name: str
    image_size: str | None = field(default=None)


def check_docker_image(image_name: str) -> DockerStatus:
    """Check if Docker is available and the sandbox image exists."""
    if not shutil.which("docker"):
        return DockerStatus(
            docker_available=False,
            image_found=False,
            image_name=image_name,
        )

    try:
        result = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Size}}", image_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            size_bytes = int(result.stdout.strip())
            size_gb = size_bytes / (1024**3)
            return DockerStatus(
                docker_available=True,
                image_found=True,
                image_name=image_name,
                image_size=f"{size_gb:.1f}GB",
            )
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass

    return DockerStatus(
        docker_available=True,
        image_found=False,
        image_name=image_name,
    )


# ── Filesystem Operations (T213, T214) ──────────────────────────────


def write_project_config(project_root: Path, config: ProjectConfig) -> None:
    """Create .dkmv/ directory structure and write config.json."""
    dkmv_dir = project_root / ".dkmv"
    dkmv_dir.mkdir(exist_ok=True)
    (dkmv_dir / "runs").mkdir(exist_ok=True)

    # Always overwrite config.json (supports reinit)
    config_path = dkmv_dir / "config.json"
    config_path.write_text(config.model_dump_json(indent=2) + "\n")

    # Only create components.json if it doesn't exist (preserve on reinit)
    components_path = dkmv_dir / "components.json"
    if not components_path.exists():
        components_path.write_text("{}\n")


def update_gitignore(project_root: Path, entries: list[str]) -> list[str]:
    """Add entries to .gitignore if not present. Returns list of entries added."""
    gitignore_path = project_root / ".gitignore"

    existing_lines: list[str] = []
    if gitignore_path.exists():
        existing_lines = gitignore_path.read_text().splitlines()

    existing_set = {line.strip() for line in existing_lines}
    added: list[str] = []

    for entry in entries:
        if entry not in existing_set:
            added.append(entry)

    if added:
        content = gitignore_path.read_text() if gitignore_path.exists() else ""
        if content and not content.endswith("\n"):
            content += "\n"
        content += "\n".join(added) + "\n"
        gitignore_path.write_text(content)

    return added


# ── Credential Prompting (T218) ─────────────────────────────────────


def _prompt_and_write_credential(project_root: Path, key_name: str, prompt_text: str) -> str:
    """Prompt for a credential value and append it to .env."""
    value: str = typer.prompt(prompt_text)
    env_file = project_root / ".env"
    content = env_file.read_text() if env_file.exists() else ""
    if content and not content.endswith("\n"):
        content += "\n"
    content += f"{key_name}={value}\n"
    env_file.write_text(content)
    return value


# ── Orchestration (T215 + T216 + T217) ──────────────────────────────


def run_init(
    *,
    yes: bool = False,
    repo_override: str | None = None,
    name_override: str | None = None,
) -> None:
    """Run the dkmv init flow."""
    project_root = Path.cwd()

    # ── Header ──
    console.print(
        Panel(
            "[bold]DKMV Project Initialization[/bold]\n"
            "This will create a .dkmv/ directory with project configuration.",
            title="dkmv init",
            border_style="blue",
        )
    )

    # ── Reinit check (T217) ──
    existing_config = load_project_config(project_root)
    if existing_config:
        console.print(
            f"\n[yellow]This project is already initialized:[/yellow] "
            f"{existing_config.project_name} ({existing_config.repo})"
        )
        if not yes:
            if not typer.confirm("Reinitialize?", default=False):
                console.print("Aborted.")
                raise typer.Exit(code=0)
        else:
            console.print("  --yes: reinitializing")

    # ── Nested init check (T217) ──
    if not existing_config:
        parent_root = find_project_root()
        if parent_root != project_root and (parent_root / ".dkmv" / "config.json").is_file():
            console.print(
                f"\n[yellow]Warning:[/yellow] Parent directory is already initialized: "
                f"{parent_root}"
            )
            if not yes:
                if not typer.confirm("Initialize here anyway?", default=False):
                    console.print("Aborted.")
                    raise typer.Exit(code=0)
            else:
                console.print("  --yes: proceeding with nested init")

    # ── [1/4] Detect project ──
    console.print("\n[bold][1/4] Detecting project...[/bold]")

    repo = repo_override or detect_repo(project_root)
    if repo is None:
        if yes:
            console.print("[red]Error:[/red] Could not detect repo. Use --repo to specify.")
            raise typer.Exit(code=1)
        repo = typer.prompt("Repository URL")

    project_name = name_override or detect_project_name(repo, project_root)
    default_branch = detect_default_branch(project_root)

    console.print(f"  Project: {project_name}")
    console.print(f"  Repo:    {repo}")
    console.print(f"  Branch:  {default_branch}")

    # ── [2/4] Check credentials ──
    console.print("\n[bold][2/4] Checking credentials...[/bold]")

    api_key_source, api_key_found = discover_anthropic_key(project_root)
    oauth_source, oauth_found = discover_oauth_token(project_root)
    gh_token_source, gh_token_found = discover_github_token(project_root)

    # Determine auth method
    auth_method: AuthMethod
    if yes:
        # Auto-detect: prefer API key if available, then OAuth
        if api_key_found:
            auth_method = "api_key"
        elif oauth_found:
            auth_method = "oauth"
        else:
            console.print(
                "[red]Error:[/red] No authentication found. "
                "Set ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN."
            )
            raise typer.Exit(code=1)
    else:
        # Interactive: let user choose
        console.print("  Authentication methods:")
        console.print("    [bold]1.[/bold] API Key (ANTHROPIC_API_KEY) — pay-per-token")
        console.print(
            "    [bold]2.[/bold] Claude Code subscription (OAuth) — flat rate, requires setup-token"
        )
        auth_choice = typer.prompt("  Choose auth method", default="1")
        auth_method = "oauth" if auth_choice.strip() == "2" else "api_key"

    # Validate and discover credentials for chosen method
    if auth_method == "api_key":
        if api_key_found:
            console.print(f"  Anthropic API key: [green]found[/green] ({api_key_source})")
        else:
            if yes:
                # Unreachable in current flow but defensive
                console.print(
                    "[red]Error:[/red] ANTHROPIC_API_KEY not found. "
                    "Set it via environment variable or .env file."
                )
                raise typer.Exit(code=1)
            console.print("  Anthropic API key: [yellow]not found[/yellow]")
            _prompt_and_write_credential(
                project_root, "ANTHROPIC_API_KEY", "Enter your Anthropic API key"
            )
            api_key_source = ".env"
            console.print("  Anthropic API key: [green]saved to .env[/green]")
    else:
        # OAuth flow
        if oauth_found:
            console.print(f"  OAuth token:       [green]found[/green] ({oauth_source})")
        else:
            if yes:
                # Unreachable in current flow but defensive
                console.print("[red]Error:[/red] CLAUDE_CODE_OAUTH_TOKEN not found.")
                raise typer.Exit(code=1)
            console.print("  OAuth token:       [yellow]not found[/yellow]")
            console.print(
                "\n  [dim]Run [bold]claude setup-token[/bold] in your terminal to "
                "generate a long-lived token,[/dim]"
            )
            console.print("  [dim]then paste it below.[/dim]\n")
            _prompt_and_write_credential(
                project_root,
                "CLAUDE_CODE_OAUTH_TOKEN",
                "Enter your OAuth token (sk-ant-oat01-...)",
            )
            oauth_source = ".env"
            console.print("  OAuth token:       [green]saved to .env[/green]")

    console.print(f"  Auth method:       [bold]{auth_method}[/bold]")

    if gh_token_found:
        console.print(f"  GitHub token:      [green]found[/green] ({gh_token_source})")
    else:
        console.print("  GitHub token:      [dim]not found (optional)[/dim]")

    # ── [3/4] Check Docker ──
    console.print("\n[bold][3/4] Checking Docker...[/bold]")

    image_name = os.environ.get("DKMV_IMAGE", "dkmv-sandbox:latest")
    docker_status = check_docker_image(image_name)

    if not docker_status.docker_available:
        console.print("  Docker: [yellow]not found[/yellow] — install Docker to run agents")
    elif docker_status.image_found:
        console.print(
            f"  Docker image: [green]found[/green] ({docker_status.image_name}"
            + (f", {docker_status.image_size}" if docker_status.image_size else "")
            + ")"
        )
    else:
        console.print(f"  Docker image: [yellow]not found[/yellow] ({docker_status.image_name})")
        console.print("  Run [bold]dkmv build[/bold] to build the sandbox image.")

    # ── [4/4] Write configuration ──
    console.print("\n[bold][4/4] Writing configuration...[/bold]")

    project_config = ProjectConfig(
        project_name=project_name,
        repo=repo,
        default_branch=default_branch,
        credentials=CredentialSources(
            auth_method=auth_method,
            anthropic_api_key_source=api_key_source if auth_method == "api_key" else "none",
            oauth_token_source=oauth_source if auth_method == "oauth" else "none",
            github_token_source=gh_token_source,
        ),
    )

    write_project_config(project_root, project_config)
    console.print("  Created .dkmv/config.json")
    console.print("  Created .dkmv/runs/")
    console.print("  Created .dkmv/components.json")

    gitignore_entries = [".dkmv/"]
    if (project_root / ".env").exists():
        gitignore_entries.append(".env")
    added = update_gitignore(project_root, gitignore_entries)
    if added:
        console.print(f"  Updated .gitignore: added {', '.join(added)}")

    # ── Success ──
    console.print(
        Panel(
            f"[green bold]Project initialized successfully![/green bold]\n\n"
            f"  Project: {project_name}\n"
            f"  Config:  .dkmv/config.json\n\n"
            f"Next steps:\n"
            f"  1. Run [bold]dkmv build[/bold] to build the sandbox image\n"
            f"  2. Run [bold]dkmv plan --prd <file>[/bold] to start planning",
            title="Done",
            border_style="green",
        )
    )
