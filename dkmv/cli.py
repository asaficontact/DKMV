import shutil
import subprocess
from pathlib import Path
from typing import Annotated

import typer

from dkmv.config import load_config

app = typer.Typer(
    help="DKMV — AI agent orchestrator for software development.", no_args_is_help=True
)

_verbose: bool = False
_dry_run: bool = False


@app.callback()
def main(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose output.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would be done without executing.")
    ] = False,
) -> None:
    global _verbose, _dry_run  # noqa: PLW0603
    _verbose = verbose
    _dry_run = dry_run


@app.command()
def build(
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="Build Docker image without cache.")
    ] = False,
    claude_version: Annotated[
        str, typer.Option("--claude-version", help="Claude Code version to install.")
    ] = "latest",
) -> None:
    """Build the DKMV sandbox Docker image."""
    if _dry_run:
        typer.echo("Dry run: would build Docker image.")
        return

    if not shutil.which("docker"):
        typer.echo("Error: Docker is not installed or not in PATH.", err=True)
        raise typer.Exit(code=1)

    config = load_config(require_api_key=False)
    dockerfile_dir = Path(__file__).parent / "images"
    dockerfile = dockerfile_dir / "Dockerfile"

    if not dockerfile.exists():
        typer.echo(f"Error: Dockerfile not found at {dockerfile}", err=True)
        raise typer.Exit(code=1)

    cmd: list[str] = [
        "docker",
        "build",
        "-t",
        config.image_name,
        "--build-arg",
        f"CLAUDE_CODE_VERSION={claude_version}",
    ]
    if no_cache:
        cmd.append("--no-cache")
    cmd.append(str(dockerfile_dir))

    typer.echo(f"Building image {config.image_name}...")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        typer.echo("Error: Docker build failed.", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Image {config.image_name} built successfully.")


@app.command()
def dev(
    repo: Annotated[str, typer.Argument(help="GitHub repository URL or local path.")],
    prd: Annotated[str, typer.Option("--prd", help="Path to the PRD file.")],
    branch: Annotated[str | None, typer.Option("--branch", help="Branch name to use.")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Model to use for this run.")] = None,
    max_turns: Annotated[
        int | None, typer.Option("--max-turns", help="Maximum agent turns.")
    ] = None,
    design_docs: Annotated[
        list[str] | None, typer.Option("--design-doc", help="Design document paths.")
    ] = None,
) -> None:
    """Run the Dev agent to implement a feature."""
    typer.echo("Not yet implemented.")


@app.command()
def qa(
    repo: Annotated[str, typer.Argument(help="GitHub repository URL or local path.")],
    branch: Annotated[str, typer.Option("--branch", help="Branch to QA.")],
    prd: Annotated[str, typer.Option("--prd", help="Path to the PRD file.")],
    model: Annotated[str | None, typer.Option("--model", help="Model to use for this run.")] = None,
) -> None:
    """Run the QA agent to review and test a branch."""
    typer.echo("Not yet implemented.")


@app.command()
def judge(
    repo: Annotated[str, typer.Argument(help="GitHub repository URL or local path.")],
    branch: Annotated[str, typer.Option("--branch", help="Branch to judge.")],
    prd: Annotated[str, typer.Option("--prd", help="Path to the PRD file.")],
    model: Annotated[str | None, typer.Option("--model", help="Model to use for this run.")] = None,
) -> None:
    """Run the Judge agent to evaluate implementation quality."""
    typer.echo("Not yet implemented.")


@app.command()
def docs(
    repo: Annotated[str, typer.Argument(help="GitHub repository URL or local path.")],
    branch: Annotated[str, typer.Option("--branch", help="Branch to document.")],
    model: Annotated[str | None, typer.Option("--model", help="Model to use for this run.")] = None,
) -> None:
    """Run the Docs agent to generate documentation."""
    typer.echo("Not yet implemented.")


@app.command()
def runs() -> None:
    """List all DKMV runs."""
    typer.echo("Not yet implemented.")


@app.command()
def show(
    run_id: Annotated[str, typer.Argument(help="Run ID to display.")],
) -> None:
    """Show details of a specific run."""
    typer.echo("Not yet implemented.")


@app.command()
def attach(
    run_id: Annotated[str, typer.Argument(help="Run ID to attach to.")],
) -> None:
    """Attach to a running container."""
    typer.echo("Not yet implemented.")


@app.command()
def stop(
    run_id: Annotated[str, typer.Argument(help="Run ID to stop.")],
) -> None:
    """Stop a running container."""
    typer.echo("Not yet implemented.")
