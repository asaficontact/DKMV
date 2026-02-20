import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from dkmv.config import load_config
from dkmv.utils import async_command

app = typer.Typer(
    help="DKMV — AI agent orchestrator for software development.", no_args_is_help=True
)

_verbose: bool = False
_dry_run: bool = False

console = Console()


def _format_relative_time(dt: datetime) -> str:
    delta = datetime.now(UTC) - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    remaining = int(seconds % 60)
    return f"{minutes}m {remaining}s"


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
@async_command
async def dev(
    repo: Annotated[str, typer.Argument(help="GitHub repository URL or local path.")],
    prd: Annotated[Path, typer.Option("--prd", help="Path to the PRD file.")],
    branch: Annotated[str | None, typer.Option("--branch", help="Branch name to use.")] = None,
    feedback: Annotated[
        Path | None, typer.Option("--feedback", help="Path to feedback JSON from previous run.")
    ] = None,
    design_docs: Annotated[
        Path | None, typer.Option("--design-docs", help="Path to design documents directory.")
    ] = None,
    feature_name: Annotated[
        str | None, typer.Option("--feature-name", help="Feature name for tracking.")
    ] = None,
    model: Annotated[str | None, typer.Option("--model", help="Model to use for this run.")] = None,
    max_turns: Annotated[
        int | None, typer.Option("--max-turns", help="Maximum agent turns.")
    ] = None,
    max_budget_usd: Annotated[
        float | None, typer.Option("--max-budget-usd", help="Maximum budget in USD.")
    ] = None,
    timeout: Annotated[int | None, typer.Option("--timeout", help="Timeout in minutes.")] = None,
    keep_alive: Annotated[
        bool, typer.Option("--keep-alive", help="Keep container running after completion.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Verbose output.")] = False,
) -> None:
    """Run the Dev agent to implement a feature."""
    from dkmv.components.dev import DevComponent, DevConfig
    from dkmv.core.runner import RunManager
    from dkmv.core.sandbox import SandboxManager
    from dkmv.core.stream import StreamParser

    config_obj = load_config()
    dev_config = DevConfig(
        repo=repo,
        prd_path=prd,
        branch=branch,
        feedback_path=feedback,
        design_docs_path=design_docs,
        feature_name=feature_name or "",
        model=model or config_obj.default_model,
        max_turns=max_turns if max_turns is not None else config_obj.default_max_turns,
        timeout_minutes=timeout if timeout is not None else config_obj.timeout_minutes,
        keep_alive=keep_alive,
        verbose=verbose or _verbose,
        max_budget_usd=max_budget_usd if max_budget_usd is not None else config_obj.max_budget_usd,
    )
    sandbox = SandboxManager()
    run_mgr = RunManager(output_dir=config_obj.output_dir)
    parser = StreamParser(verbose=verbose or _verbose)
    component = DevComponent(
        global_config=config_obj,
        sandbox=sandbox,
        run_manager=run_mgr,
        stream_parser=parser,
    )
    result = await component.run(dev_config)
    console.print(f"Run {result.run_id} completed with status: {result.status}")
    if result.error_message:
        console.print(f"Error: {result.error_message}", style="bold red")


@app.command()
@async_command
async def qa(
    repo: Annotated[str, typer.Argument(help="GitHub repository URL or local path.")],
    branch: Annotated[str, typer.Option("--branch", help="Branch to QA.")],
    prd: Annotated[Path, typer.Option("--prd", help="Path to the PRD file.")],
    model: Annotated[str | None, typer.Option("--model", help="Model to use.")] = None,
    max_turns: Annotated[
        int | None, typer.Option("--max-turns", help="Maximum agent turns.")
    ] = None,
    max_budget_usd: Annotated[
        float | None, typer.Option("--max-budget-usd", help="Maximum budget in USD.")
    ] = None,
    timeout: Annotated[int | None, typer.Option("--timeout", help="Timeout in minutes.")] = None,
    keep_alive: Annotated[
        bool, typer.Option("--keep-alive", help="Keep container running after completion.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Verbose output.")] = False,
) -> None:
    """Run the QA agent to review and test a branch."""
    from dkmv.components.qa import QAComponent, QAConfig
    from dkmv.core.runner import RunManager
    from dkmv.core.sandbox import SandboxManager
    from dkmv.core.stream import StreamParser

    config_obj = load_config()
    qa_config = QAConfig(
        repo=repo,
        branch=branch,
        prd_path=prd,
        model=model or config_obj.default_model,
        max_turns=max_turns if max_turns is not None else config_obj.default_max_turns,
        timeout_minutes=timeout if timeout is not None else config_obj.timeout_minutes,
        keep_alive=keep_alive,
        verbose=verbose or _verbose,
        max_budget_usd=max_budget_usd if max_budget_usd is not None else config_obj.max_budget_usd,
    )
    sandbox = SandboxManager()
    run_mgr = RunManager(output_dir=config_obj.output_dir)
    parser = StreamParser(verbose=verbose or _verbose)
    component = QAComponent(
        global_config=config_obj,
        sandbox=sandbox,
        run_manager=run_mgr,
        stream_parser=parser,
    )
    result = await component.run(qa_config)
    console.print(f"Run {result.run_id} completed with status: {result.status}")
    if result.error_message:
        console.print(f"Error: {result.error_message}", style="bold red")


@app.command()
@async_command
async def judge(
    repo: Annotated[str, typer.Argument(help="GitHub repository URL or local path.")],
    branch: Annotated[str, typer.Option("--branch", help="Branch to judge.")],
    prd: Annotated[Path, typer.Option("--prd", help="Path to the PRD file.")],
    model: Annotated[str | None, typer.Option("--model", help="Model to use.")] = None,
    max_turns: Annotated[
        int | None, typer.Option("--max-turns", help="Maximum agent turns.")
    ] = None,
    max_budget_usd: Annotated[
        float | None, typer.Option("--max-budget-usd", help="Maximum budget in USD.")
    ] = None,
    timeout: Annotated[int | None, typer.Option("--timeout", help="Timeout in minutes.")] = None,
    keep_alive: Annotated[
        bool, typer.Option("--keep-alive", help="Keep container running after completion.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Verbose output.")] = False,
) -> None:
    """Run the Judge agent to evaluate implementation quality."""
    from dkmv.components.judge import JudgeComponent, JudgeConfig
    from dkmv.core.runner import RunManager
    from dkmv.core.sandbox import SandboxManager
    from dkmv.core.stream import StreamParser

    config_obj = load_config()
    judge_config = JudgeConfig(
        repo=repo,
        branch=branch,
        prd_path=prd,
        model=model or config_obj.default_model,
        max_turns=max_turns if max_turns is not None else config_obj.default_max_turns,
        timeout_minutes=timeout if timeout is not None else config_obj.timeout_minutes,
        keep_alive=keep_alive,
        verbose=verbose or _verbose,
        max_budget_usd=max_budget_usd if max_budget_usd is not None else config_obj.max_budget_usd,
    )
    sandbox = SandboxManager()
    run_mgr = RunManager(output_dir=config_obj.output_dir)
    parser = StreamParser(verbose=verbose or _verbose)
    component = JudgeComponent(
        global_config=config_obj,
        sandbox=sandbox,
        run_manager=run_mgr,
        stream_parser=parser,
    )
    result = await component.run(judge_config)

    # Verdict display
    if result.verdict == "pass":
        console.print("VERDICT: PASS", style="bold green")
    else:
        console.print("VERDICT: FAIL", style="bold red")
    console.print(f"Reasoning: {result.reasoning}")
    if result.score:
        console.print(f"Score: {result.score}/100")
    if result.confidence:
        console.print(f"Confidence: {result.confidence:.0%}")
    for issue in result.issues:
        severity = issue.severity.upper()
        console.print(f"  [{severity}] {issue.description}")

    if result.error_message:
        console.print(f"Error: {result.error_message}", style="bold red")


@app.command()
@async_command
async def docs(
    repo: Annotated[str, typer.Argument(help="GitHub repository URL or local path.")],
    branch: Annotated[str, typer.Option("--branch", help="Branch to document.")],
    create_pr: Annotated[
        bool, typer.Option("--create-pr", help="Create a PR with documentation changes.")
    ] = False,
    pr_base: Annotated[str, typer.Option("--pr-base", help="Base branch for PR.")] = "main",
    model: Annotated[str | None, typer.Option("--model", help="Model to use.")] = None,
    max_turns: Annotated[
        int | None, typer.Option("--max-turns", help="Maximum agent turns.")
    ] = None,
    max_budget_usd: Annotated[
        float | None, typer.Option("--max-budget-usd", help="Maximum budget in USD.")
    ] = None,
    timeout: Annotated[int | None, typer.Option("--timeout", help="Timeout in minutes.")] = None,
    keep_alive: Annotated[
        bool, typer.Option("--keep-alive", help="Keep container running after completion.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Verbose output.")] = False,
) -> None:
    """Run the Docs agent to generate documentation."""
    from dkmv.components.docs import DocsComponent, DocsConfig
    from dkmv.core.runner import RunManager
    from dkmv.core.sandbox import SandboxManager
    from dkmv.core.stream import StreamParser

    config_obj = load_config()
    docs_config = DocsConfig(
        repo=repo,
        branch=branch,
        create_pr=create_pr,
        pr_base=pr_base,
        model=model or config_obj.default_model,
        max_turns=max_turns if max_turns is not None else config_obj.default_max_turns,
        timeout_minutes=timeout if timeout is not None else config_obj.timeout_minutes,
        keep_alive=keep_alive,
        verbose=verbose or _verbose,
        max_budget_usd=max_budget_usd if max_budget_usd is not None else config_obj.max_budget_usd,
    )
    sandbox = SandboxManager()
    run_mgr = RunManager(output_dir=config_obj.output_dir)
    parser = StreamParser(verbose=verbose or _verbose)
    component = DocsComponent(
        global_config=config_obj,
        sandbox=sandbox,
        run_manager=run_mgr,
        stream_parser=parser,
    )
    result = await component.run(docs_config)
    console.print(f"Run {result.run_id} completed with status: {result.status}")
    if result.pr_url:
        console.print(f"PR created: {result.pr_url}", style="bold green")
    if result.error_message:
        console.print(f"Error: {result.error_message}", style="bold red")


@app.command()
def runs(
    component: Annotated[
        str | None, typer.Option("--component", help="Filter by component (dev|qa|judge|docs).")
    ] = None,
    status: Annotated[str | None, typer.Option("--status", help="Filter by status.")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max number of runs to show.")] = 20,
) -> None:
    """List all DKMV runs."""
    from dkmv.core.runner import RunManager

    config = load_config(require_api_key=False)
    run_mgr = RunManager(output_dir=config.output_dir)

    summaries = run_mgr.list_runs(
        component=component,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        limit=limit,
    )

    if not summaries:
        console.print("No runs found.", style="dim")
        return

    table = Table(title="DKMV Runs")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Component", style="magenta")
    table.add_column("Status")
    table.add_column("Feature")
    table.add_column("Cost", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("When", justify="right")

    for run in summaries:
        status_style = {
            "completed": "green",
            "running": "yellow",
            "failed": "red",
            "timed_out": "red",
            "pending": "dim",
        }.get(run.status, "")

        table.add_row(
            run.run_id,
            run.component,
            f"[{status_style}]{run.status}[/{status_style}]" if status_style else run.status,
            run.feature_name or "-",
            f"${run.total_cost_usd:.2f}",
            _format_duration(run.duration_seconds),
            _format_relative_time(run.timestamp),
        )

    console.print(table)


@app.command()
def show(
    run_id: Annotated[str, typer.Argument(help="Run ID to display.")],
) -> None:
    """Show details of a specific run."""
    from dkmv.core.runner import RunManager

    config = load_config(require_api_key=False)
    run_mgr = RunManager(output_dir=config.output_dir)

    try:
        detail = run_mgr.get_run(run_id)
    except FileNotFoundError:
        console.print(f"Error: Run '{run_id}' not found.", style="bold red")
        raise typer.Exit(code=1)

    status_style = {
        "completed": "green",
        "running": "yellow",
        "failed": "red",
        "timed_out": "red",
    }.get(detail.status, "")

    console.print(f"[bold]Run {detail.run_id}[/bold]")
    console.print(f"  Component:  {detail.component}")
    console.print(
        f"  Status:     [{status_style}]{detail.status}[/{status_style}]"
        if status_style
        else f"  Status:     {detail.status}"
    )
    console.print(f"  Repo:       {detail.repo or '-'}")
    console.print(f"  Branch:     {detail.branch or '-'}")
    console.print(f"  Model:      {detail.model or '-'}")
    console.print(f"  Feature:    {detail.feature_name or '-'}")
    console.print(f"  Cost:       ${detail.total_cost_usd:.2f}")
    console.print(f"  Duration:   {_format_duration(detail.duration_seconds)}")
    console.print(f"  Turns:      {detail.num_turns}")
    if detail.session_id:
        console.print(f"  Session ID: {detail.session_id}")
    console.print(f"  Events:     {detail.stream_events_count}")
    if detail.log_path:
        console.print(f"  Log:        {detail.log_path}")

    if detail.error_message:
        console.print(f"\n  [bold red]Error:[/bold red] {detail.error_message}")


@app.command()
def attach(
    run_id: Annotated[str, typer.Argument(help="Run ID to attach to.")],
) -> None:
    """Attach to a running container."""
    from dkmv.core.runner import RunManager

    config = load_config(require_api_key=False)
    run_mgr = RunManager(output_dir=config.output_dir)

    try:
        run_mgr.get_run(run_id)
    except FileNotFoundError:
        console.print(f"Error: Run '{run_id}' not found.", style="bold red")
        raise typer.Exit(code=1)

    container_name = run_mgr.get_container_name(run_id)
    if not container_name:
        console.print("Error: No container name found for this run.", style="bold red")
        console.print("The container may have been started without --keep-alive.")
        raise typer.Exit(code=1)

    inspect_result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", container_name],
        capture_output=True,
        text=True,
    )
    if inspect_result.returncode != 0 or inspect_result.stdout.strip() != "true":
        console.print(f"Error: Container '{container_name}' is not running.", style="bold red")
        raise typer.Exit(code=1)

    console.print(f"Attaching to container {container_name}...")
    result = subprocess.run(["docker", "exec", "-it", container_name, "bash"])
    raise typer.Exit(code=result.returncode)


@app.command()
def stop(
    run_id: Annotated[str, typer.Argument(help="Run ID to stop.")],
) -> None:
    """Stop a running container."""
    from dkmv.core.runner import RunManager

    config = load_config(require_api_key=False)
    run_mgr = RunManager(output_dir=config.output_dir)

    try:
        run_mgr.get_run(run_id)
    except FileNotFoundError:
        console.print(f"Error: Run '{run_id}' not found.", style="bold red")
        raise typer.Exit(code=1)

    container_name = run_mgr.get_container_name(run_id)
    if not container_name:
        console.print("Error: No container name found for this run.", style="bold red")
        raise typer.Exit(code=1)

    inspect_result = subprocess.run(
        ["docker", "inspect", container_name],
        capture_output=True,
        text=True,
    )
    if inspect_result.returncode != 0:
        console.print(f"Container '{container_name}' is already removed.", style="dim")
        return

    stop_result = subprocess.run(["docker", "stop", container_name], capture_output=True, text=True)
    if stop_result.returncode != 0:
        console.print(f"Container '{container_name}' is already stopped.", style="dim")

    subprocess.run(["docker", "rm", container_name], capture_output=True, text=True)

    console.print(f"Container '{container_name}' stopped and removed.", style="green")


@app.command()
def clean() -> None:
    """Remove all DKMV sandbox containers (running and stopped)."""
    result = subprocess.run(
        ["docker", "ps", "-a", "--filter", "name=dkmv-sandbox", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print("Error: Failed to list Docker containers.", style="bold red")
        raise typer.Exit(code=1)

    containers = [name.strip() for name in result.stdout.strip().splitlines() if name.strip()]
    if not containers:
        console.print("No DKMV containers found.", style="dim")
        return

    removed = 0
    for name in containers:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True)
        console.print(f"  Removed {name}")
        removed += 1

    console.print(f"Cleaned up {removed} container(s).", style="green")
