import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from dkmv.config import load_config
from dkmv.tasks.pause import PauseRequest, PauseResponse
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
def init(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Accept all defaults.")] = False,
    repo: Annotated[str | None, typer.Option("--repo", help="Repository URL.")] = None,
    name: Annotated[str | None, typer.Option("--name", help="Project name.")] = None,
) -> None:
    """Initialize DKMV for the current project."""
    from dkmv.init import run_init

    run_init(yes=yes, repo_override=repo, name_override=name)


@app.command()
def components() -> None:
    """List all available components (built-in and registered)."""
    from dkmv.project import find_project_root
    from dkmv.registry import ComponentRegistry

    project_root = find_project_root()
    has_init = (project_root / ".dkmv" / "components.json").exists()

    infos = ComponentRegistry.list_all(project_root if has_init else None)

    table = Table(title="Components")
    table.add_column("Name", style="cyan")
    table.add_column("Type")
    table.add_column("Tasks", justify="right")
    table.add_column("Agent")
    table.add_column("Description")

    builtin_count = 0
    custom_count = 0

    for info in infos:
        agent_display = info.agent or ""
        if info.component_type == "built-in":
            builtin_count += 1
            table.add_row(
                info.name,
                "built-in",
                str(info.task_count),
                agent_display,
                info.description,
            )
        else:
            custom_count += 1
            if info.valid:
                table.add_row(
                    info.name,
                    "custom",
                    str(info.task_count),
                    agent_display,
                    info.description,
                )
            else:
                table.add_row(
                    info.name,
                    "custom",
                    "[yellow]?[/yellow]",
                    agent_display,
                    f"[yellow]path not found: {info.description}[/yellow]",
                )

    console.print(table)
    console.print(f"\n{builtin_count} built-in, {custom_count} custom")


@app.command()
def register(
    name: Annotated[str, typer.Argument(help="Short name for the component.")],
    path: Annotated[str, typer.Argument(help="Path to component directory.")],
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite existing registration.")
    ] = False,
) -> None:
    """Register a custom component by name."""
    from dkmv.project import find_project_root
    from dkmv.registry import ComponentRegistry

    project_root = find_project_root()
    if not (project_root / ".dkmv").exists():
        console.print("Error: DKMV not initialized. Run 'dkmv init' first.", style="bold red")
        raise typer.Exit(code=1)

    try:
        resolved_path = ComponentRegistry.register(project_root, name, path, force=force)
    except ValueError as e:
        console.print(f"Error: {e}", style="bold red")
        raise typer.Exit(code=1)

    yaml_files = list(resolved_path.glob("*.yaml")) + list(resolved_path.glob("*.yml"))
    tasks_subdir = resolved_path / "tasks"
    if tasks_subdir.is_dir():
        yaml_files.extend(tasks_subdir.glob("*.yaml"))
        yaml_files.extend(tasks_subdir.glob("*.yml"))
    yaml_count = len(yaml_files)
    console.print(
        f"Registered '{name}' → {resolved_path} ({yaml_count} task{'s' if yaml_count != 1 else ''})"
    )


@app.command()
def unregister(
    name: Annotated[str, typer.Argument(help="Component name to unregister.")],
) -> None:
    """Unregister a custom component."""
    from dkmv.project import find_project_root
    from dkmv.registry import ComponentRegistry

    project_root = find_project_root()
    if not (project_root / ".dkmv").exists():
        console.print("Error: DKMV not initialized. Run 'dkmv init' first.", style="bold red")
        raise typer.Exit(code=1)

    try:
        ComponentRegistry.unregister(project_root, name)
    except ValueError as e:
        console.print(f"Error: {e}", style="bold red")
        raise typer.Exit(code=1)

    console.print(f"Unregistered '{name}'")


@app.command()
def build(
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="Build Docker image without cache.")
    ] = False,
    claude_version: Annotated[
        str, typer.Option("--claude-version", help="Claude Code version to install.")
    ] = "latest",
    codex_version: Annotated[
        str, typer.Option("--codex-version", help="Codex CLI version to install.")
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
        "--build-arg",
        f"CODEX_VERSION={codex_version}",
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


def _discover_phases(impl_docs_dir: Path) -> list[dict[str, Any]]:
    """Scan implementation docs directory for phase files."""
    phase_files = sorted(impl_docs_dir.glob("phase*_*.md"))
    if not phase_files:
        raise typer.BadParameter(f"No phase files (phase*_*.md) found in {impl_docs_dir}")
    phases: list[dict[str, Any]] = []
    for pf in phase_files:
        stem = pf.stem  # "phase1_foundation"
        parts = stem.split("_", 1)
        phase_num = int(parts[0].replace("phase", ""))
        phase_name = parts[1].replace("_", " ") if len(parts) > 1 else f"phase{phase_num}"
        phases.append(
            {
                "phase_number": phase_num,
                "phase_name": phase_name,
                "phase_file": pf.name,
            }
        )
    return phases


@app.command()
@async_command
async def dev(
    impl_docs: Annotated[
        Path, typer.Option("--impl-docs", help="Path to implementation docs directory.")
    ],
    repo: Annotated[
        str | None,
        typer.Option("--repo", help="Repository URL (default: from project config)."),
    ] = None,
    branch: Annotated[str | None, typer.Option("--branch", help="Branch name to use.")] = None,
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
    start_phase: Annotated[
        int | None,
        typer.Option("--start-phase", help="Phase number to start from (skip earlier phases)."),
    ] = None,
    context: Annotated[
        list[Path] | None,
        typer.Option("--context", help="Local file or directory to include as extra context."),
    ] = None,
    agent: Annotated[
        str | None, typer.Option("--agent", help="Agent to use (claude, codex).")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Verbose output.")] = False,
) -> None:
    """Run the Dev agent to implement phases from implementation docs.

    Takes the output of 'dkmv plan' and implements each phase sequentially.
    Use --start-phase to resume from a specific phase after a failure.
    """
    from dkmv.project import find_project_root, get_repo
    from dkmv.tasks import ComponentRunner, TaskLoader, TaskRunner, resolve_component
    from dkmv.tasks.models import CLIOverrides
    from dkmv.core.runner import RunManager
    from dkmv.core.sandbox import SandboxManager
    from dkmv.core.stream import StreamParser

    config_obj = load_config()
    project_root = find_project_root()
    resolved_repo = get_repo(repo)

    impl_docs_dir = Path(impl_docs).resolve()
    if not impl_docs_dir.is_dir():
        console.print(f"Error: {impl_docs_dir} is not a directory.", style="bold red")
        raise typer.Exit(code=1)

    phases = _discover_phases(impl_docs_dir)

    if start_phase is not None:
        total = len(phases)
        phases = [p for p in phases if p["phase_number"] >= start_phase]
        if not phases:
            console.print(
                f"Error: No phases with number >= {start_phase}. "
                f"Available: {', '.join(str(p['phase_number']) for p in _discover_phases(impl_docs_dir))}",
                style="bold red",
            )
            raise typer.Exit(code=1)
        skipped = total - len(phases)
        if skipped:
            console.print(
                f"Resuming from phase {start_phase} (skipping {skipped} earlier phase{'s' if skipped != 1 else ''})",
                style="cyan",
            )

    resolved_feature = feature_name or impl_docs_dir.name
    resolved_branch = branch or f"feature/{resolved_feature}-dev"

    variables: dict[str, Any] = {
        "impl_docs_path": str(impl_docs_dir),
        "phases": phases,
    }

    cli_overrides = CLIOverrides(
        model=model,
        max_turns=max_turns,
        timeout_minutes=timeout,
        max_budget_usd=max_budget_usd,
        agent=agent,
    )

    component_dir = resolve_component("dev", project_root=project_root)
    sandbox = SandboxManager()
    run_mgr = RunManager(output_dir=config_obj.output_dir)
    parser = StreamParser(verbose=verbose or _verbose)
    loader = TaskLoader()
    task_runner = TaskRunner(sandbox, run_mgr, parser, Console())
    runner = ComponentRunner(sandbox, run_mgr, loader, task_runner, Console())

    result = await runner.run(
        component_dir=component_dir,
        repo=resolved_repo,
        branch=resolved_branch,
        feature_name=resolved_feature,
        variables=variables,
        config=config_obj,
        cli_overrides=cli_overrides,
        keep_alive=keep_alive,
        verbose=verbose or _verbose,
        context_paths=context,
    )
    console.print(f"Run {result.run_id} completed with status: {result.status}")
    if result.error_message:
        console.print(f"Error: {result.error_message}", style="bold red")


async def _rich_pause_callback(request: PauseRequest) -> PauseResponse:
    """Render pause questions with Rich and collect user answers via typer.prompt."""
    if not request.questions:
        return PauseResponse(answers={})

    console.print(
        f"\n[bold cyan]Task '{request.task_name}' has questions about architectural decisions:[/bold cyan]\n"
    )
    answers: dict[str, str] = {}
    for q in request.questions:
        console.print(f"[bold]{q.question}[/bold]")
        if q.options:
            for i, opt in enumerate(q.options, 1):
                label = opt.get("label", opt.get("value", ""))
                desc = opt.get("description", "")
                default_marker = " (default)" if q.default and opt.get("value") == q.default else ""
                console.print(f"  {i}. {label}{default_marker}")
                if desc:
                    console.print(f"     {desc}", style="dim")

            default_idx = None
            if q.default:
                for i, opt in enumerate(q.options, 1):
                    if opt.get("value") == q.default:
                        default_idx = str(i)
                        break

            choice = typer.prompt("Choose", default=default_idx or "1")
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(q.options):
                    answers[q.id] = q.options[idx].get("value", choice)
                else:
                    answers[q.id] = choice
            except ValueError:
                answers[q.id] = choice
        else:
            answer = typer.prompt("Answer", default=q.default or "")
            answers[q.id] = answer
        console.print()

    return PauseResponse(answers=answers)


@app.command()
@async_command
async def plan(
    prd: Annotated[Path, typer.Option("--prd", help="Path to the PRD file.")],
    repo: Annotated[
        str | None,
        typer.Option("--repo", help="Repository URL (default: from project config)."),
    ] = None,
    branch: Annotated[str | None, typer.Option("--branch", help="Branch name to use.")] = None,
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
    context: Annotated[
        list[Path] | None,
        typer.Option("--context", help="Local file or directory to include as extra context."),
    ] = None,
    auto: Annotated[bool, typer.Option("--auto", help="Skip interactive pauses.")] = False,
    agent: Annotated[
        str | None, typer.Option("--agent", help="Agent to use (claude, codex).")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Verbose output.")] = False,
) -> None:
    """Run the Plan agent to convert a PRD into implementation documents.

    Produces features.md, user_stories.md, phaseN_*.md, tasks.md, progress.md,
    README.md, and CLAUDE.md in docs/implementation/{feature_name}/.
    """
    import json as json_mod

    from dkmv.project import find_project_root, get_repo
    from dkmv.tasks import ComponentRunner, TaskLoader, TaskRunner, resolve_component
    from dkmv.tasks.models import CLIOverrides
    from dkmv.core.runner import RunManager
    from dkmv.core.sandbox import SandboxManager
    from dkmv.core.stream import StreamParser

    config_obj = load_config()
    project_root = find_project_root()
    resolved_repo = get_repo(repo)

    resolved_feature = feature_name or Path(prd).stem
    resolved_branch = branch or f"feature/{resolved_feature}-plan"

    variables: dict[str, str] = {
        "prd_path": str(prd),
    }
    if design_docs:
        variables["design_docs_path"] = str(design_docs)

    cli_overrides = CLIOverrides(
        model=model,
        max_turns=max_turns,
        timeout_minutes=timeout,
        max_budget_usd=max_budget_usd,
        agent=agent,
    )

    component_dir = resolve_component("plan", project_root=project_root)
    sandbox = SandboxManager()
    run_mgr = RunManager(output_dir=config_obj.output_dir)
    parser = StreamParser(verbose=verbose or _verbose)
    loader = TaskLoader()
    task_runner = TaskRunner(sandbox, run_mgr, parser, Console())
    runner = ComponentRunner(sandbox, run_mgr, loader, task_runner, Console())

    result = await runner.run(
        component_dir=component_dir,
        repo=resolved_repo,
        branch=resolved_branch,
        feature_name=resolved_feature,
        variables=variables,
        config=config_obj,
        cli_overrides=cli_overrides,
        keep_alive=keep_alive,
        verbose=verbose or _verbose,
        on_pause=None if auto else _rich_pause_callback,
        context_paths=context,
    )

    # Plan report display from saved artifact
    report_file = config_obj.output_dir / "runs" / result.run_id / "plan_report.json"
    if result.status == "completed" and report_file.exists():
        report_data = json_mod.loads(report_file.read_text())
        status = report_data.get("status", "unknown")
        if status == "pass":
            console.print("PLAN: PASS", style="bold green")
        else:
            console.print("PLAN: FAIL", style="bold red")
        found = report_data.get("issues_found", 0)
        fixed = report_data.get("issues_fixed", 0)
        console.print(f"Issues found: {found}, fixed: {fixed}")
        docs = report_data.get("documents_produced", [])
        if docs:
            console.print(f"Documents: {', '.join(docs)}")
        if report_data.get("summary"):
            console.print(f"Summary: {report_data['summary']}")
    else:
        console.print(f"Run {result.run_id} completed with status: {result.status}")

    if result.error_message:
        console.print(f"Error: {result.error_message}", style="bold red")


async def _qa_pause_callback(request: PauseRequest) -> PauseResponse:
    """Present QA evaluation results and let the user choose: fix, ship, or abort."""
    import json as json_mod

    # Parse evaluation data from context
    eval_data: dict[str, Any] = {}
    for _path, content in request.context.items():
        try:
            data = json_mod.loads(content)
            if isinstance(data, dict) and "status" in data:
                eval_data = data
                break
        except (json_mod.JSONDecodeError, TypeError):
            continue

    status = eval_data.get("status", "unknown")
    issues = eval_data.get("issues", [])
    tests_total = eval_data.get("tests_total", 0)
    tests_passed = eval_data.get("tests_passed", 0)
    tests_failed = eval_data.get("tests_failed", 0)
    summary = eval_data.get("summary", "")

    # Display evaluation summary
    if status == "pass":
        console.print("\n[bold green]QA Evaluation: PASS[/bold green]")
    else:
        console.print("\n[bold red]QA Evaluation: FAIL[/bold red]")

    if tests_total:
        console.print(f"Tests: {tests_total} total, {tests_passed} passed, {tests_failed} failed")

    if issues:
        severity_counts: dict[str, int] = {}
        for issue in issues:
            sev = issue.get("severity", "unknown")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
        parts = [f"{count} {sev}" for sev, count in sorted(severity_counts.items())]
        console.print(f"Issues: {', '.join(parts)}")

    if summary:
        console.print(f"Summary: {summary}")

    console.print("\n[bold]What would you like to do?[/bold]")
    console.print("  1. Fix issues and re-evaluate (Recommended)")
    console.print("  2. Ship as-is (skip fixes)")
    console.print("  3. Abort")

    choice = typer.prompt("Choose", default="1")

    if choice == "3":
        raise typer.Exit(code=1)
    elif choice == "2":
        return PauseResponse(answers={"action": "ship"}, skip_remaining=True)
    else:
        return PauseResponse(answers={"action": "fix"})


@app.command()
@async_command
async def qa(
    impl_docs: Annotated[
        Path, typer.Option("--impl-docs", help="Path to implementation docs directory.")
    ],
    branch: Annotated[str, typer.Option("--branch", help="Branch to QA.")],
    repo: Annotated[
        str | None,
        typer.Option("--repo", help="Repository URL (default: from project config)."),
    ] = None,
    feature_name: Annotated[
        str | None, typer.Option("--feature-name", help="Feature name for tracking.")
    ] = None,
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
    context: Annotated[
        list[Path] | None,
        typer.Option("--context", help="Local file or directory to include as extra context."),
    ] = None,
    auto: Annotated[bool, typer.Option("--auto", help="Skip interactive pauses.")] = False,
    agent: Annotated[
        str | None, typer.Option("--agent", help="Agent to use (claude, codex).")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Verbose output.")] = False,
) -> None:
    """Run the QA agent to evaluate, fix, and re-evaluate a branch.

    Uses an evaluate-fix-re-evaluate loop: the agent first evaluates the
    implementation, then you choose to fix issues or ship as-is.
    """
    import json as json_mod

    from dkmv.project import find_project_root, get_repo
    from dkmv.tasks import ComponentRunner, TaskLoader, TaskRunner, resolve_component
    from dkmv.tasks.models import CLIOverrides
    from dkmv.core.runner import RunManager
    from dkmv.core.sandbox import SandboxManager
    from dkmv.core.stream import StreamParser

    config_obj = load_config()
    project_root = find_project_root()
    resolved_repo = get_repo(repo)

    impl_docs_dir = Path(impl_docs).resolve()
    if not impl_docs_dir.is_dir():
        console.print(f"Error: {impl_docs_dir} is not a directory.", style="bold red")
        raise typer.Exit(code=1)

    resolved_feature = feature_name or impl_docs_dir.name

    variables: dict[str, str] = {"impl_docs_path": str(impl_docs_dir)}
    cli_overrides = CLIOverrides(
        model=model,
        max_turns=max_turns,
        timeout_minutes=timeout,
        max_budget_usd=max_budget_usd,
        agent=agent,
    )

    component_dir = resolve_component("qa", project_root=project_root)
    sandbox = SandboxManager()
    run_mgr = RunManager(output_dir=config_obj.output_dir)
    parser = StreamParser(verbose=verbose or _verbose)
    loader = TaskLoader()
    task_runner = TaskRunner(sandbox, run_mgr, parser, Console())
    runner = ComponentRunner(sandbox, run_mgr, loader, task_runner, Console())

    result = await runner.run(
        component_dir=component_dir,
        repo=resolved_repo,
        branch=branch,
        feature_name=resolved_feature,
        variables=variables,
        config=config_obj,
        cli_overrides=cli_overrides,
        keep_alive=keep_alive,
        verbose=verbose or _verbose,
        on_pause=None if auto else _qa_pause_callback,
        context_paths=context,
    )

    # QA report display from saved artifact
    report_file = config_obj.output_dir / "runs" / result.run_id / "qa_report.json"
    if result.status == "completed" and report_file.exists():
        report_data = json_mod.loads(report_file.read_text())
        qa_status = report_data.get("status", "unknown")
        if qa_status == "pass":
            console.print("QA: PASS", style="bold green")
        else:
            console.print("QA: FAIL", style="bold red")
        total = report_data.get("tests_total", 0)
        passed = report_data.get("tests_passed", 0)
        failed = report_data.get("tests_failed", 0)
        console.print(f"Tests: {total} total, {passed} passed, {failed} failed")
        if report_data.get("summary"):
            console.print(f"Summary: {report_data['summary']}")
    else:
        console.print(f"Run {result.run_id} completed with status: {result.status}")

    if result.error_message:
        console.print(f"Error: {result.error_message}", style="bold red")


@app.command()
@async_command
async def docs(
    impl_docs: Annotated[
        Path, typer.Option("--impl-docs", help="Path to implementation docs directory.")
    ],
    branch: Annotated[str, typer.Option("--branch", help="Branch to document and create PR for.")],
    repo: Annotated[
        str | None,
        typer.Option("--repo", help="Repository URL (default: from project config)."),
    ] = None,
    pr_base: Annotated[
        str | None,
        typer.Option("--pr-base", help="Base branch for PR (default: repo default branch)."),
    ] = None,
    feature_name: Annotated[
        str | None, typer.Option("--feature-name", help="Feature name for tracking.")
    ] = None,
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
    context: Annotated[
        list[Path] | None,
        typer.Option("--context", help="Local file or directory to include as extra context."),
    ] = None,
    agent: Annotated[
        str | None, typer.Option("--agent", help="Agent to use (claude, codex).")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Verbose output.")] = False,
) -> None:
    """Run the Docs agent to update documentation and create a PR.

    Reviews the implementation against plan docs, updates all relevant
    documentation, verifies accuracy, and creates a comprehensive pull
    request covering all branch changes.
    """
    import json as json_mod

    from dkmv.project import find_project_root, get_repo
    from dkmv.tasks import ComponentRunner, TaskLoader, TaskRunner, resolve_component
    from dkmv.tasks.models import CLIOverrides
    from dkmv.core.runner import RunManager
    from dkmv.core.sandbox import SandboxManager
    from dkmv.core.stream import StreamParser

    config_obj = load_config()
    project_root = find_project_root()
    resolved_repo = get_repo(repo)

    impl_docs_dir = Path(impl_docs).resolve()
    if not impl_docs_dir.is_dir():
        console.print(f"Error: {impl_docs_dir} is not a directory.", style="bold red")
        raise typer.Exit(code=1)

    resolved_feature = feature_name or impl_docs_dir.name

    variables: dict[str, str] = {"impl_docs_path": str(impl_docs_dir)}
    if pr_base:
        variables["pr_base"] = pr_base

    cli_overrides = CLIOverrides(
        model=model,
        max_turns=max_turns,
        timeout_minutes=timeout,
        max_budget_usd=max_budget_usd,
        agent=agent,
    )

    component_dir = resolve_component("docs", project_root=project_root)
    sandbox = SandboxManager()
    run_mgr = RunManager(output_dir=config_obj.output_dir)
    parser = StreamParser(verbose=verbose or _verbose)
    loader = TaskLoader()
    task_runner = TaskRunner(sandbox, run_mgr, parser, Console())
    runner = ComponentRunner(sandbox, run_mgr, loader, task_runner, Console())

    result = await runner.run(
        component_dir=component_dir,
        repo=resolved_repo,
        branch=branch,
        feature_name=resolved_feature,
        variables=variables,
        config=config_obj,
        cli_overrides=cli_overrides,
        keep_alive=keep_alive,
        verbose=verbose or _verbose,
        context_paths=context,
    )
    console.print(f"Run {result.run_id} completed with status: {result.status}")

    # Verification status display
    verify_file = config_obj.output_dir / "runs" / result.run_id / "docs_verification.json"
    if result.status == "completed" and verify_file.exists():
        verify_data = json_mod.loads(verify_file.read_text())
        v_status = verify_data.get("status", "unknown")
        if v_status == "pass":
            console.print("Docs verification: PASS", style="bold green")
        else:
            console.print("Docs verification: FAIL", style="bold red")

    # PR result display
    pr_file = config_obj.output_dir / "runs" / result.run_id / "pr_result.json"
    if result.status == "completed" and pr_file.exists():
        pr_data = json_mod.loads(pr_file.read_text())
        pr_url = pr_data.get("pr_url", "")
        if pr_url:
            console.print(f"PR: {pr_url}", style="bold green")
        pr_status = pr_data.get("status", "unknown")
        console.print(f"PR status: {pr_status}")

    if result.error_message:
        console.print(f"Error: {result.error_message}", style="bold red")


def _parse_vars(var_list: list[str] | None) -> dict[str, str]:
    if not var_list:
        return {}
    variables: dict[str, str] = {}
    for item in var_list:
        if "=" not in item:
            raise typer.BadParameter(f"Invalid --var format: '{item}'. Expected KEY=VALUE")
        key, _, value = item.partition("=")
        variables[key.strip()] = value.strip()
    return variables


@app.command(name="run")
@async_command
async def run_component(
    component: Annotated[
        str, typer.Argument(help="Component name or path to component directory.")
    ],
    repo: Annotated[
        str | None,
        typer.Option("--repo", help="Repository URL (default: from project config)."),
    ] = None,
    branch: Annotated[str | None, typer.Option("--branch", help="Branch name.")] = None,
    feature_name: Annotated[
        str | None, typer.Option("--feature-name", help="Feature name for tracking.")
    ] = None,
    var: Annotated[
        list[str] | None, typer.Option("--var", help="Template variable as KEY=VALUE.")
    ] = None,
    model: Annotated[str | None, typer.Option("--model", help="Default model for tasks.")] = None,
    max_turns: Annotated[int | None, typer.Option("--max-turns", help="Default max turns.")] = None,
    timeout: Annotated[
        int | None, typer.Option("--timeout", help="Default timeout in minutes.")
    ] = None,
    max_budget_usd: Annotated[
        float | None, typer.Option("--max-budget-usd", help="Default budget in USD.")
    ] = None,
    keep_alive: Annotated[
        bool, typer.Option("--keep-alive", help="Keep container running.")
    ] = False,
    context: Annotated[
        list[Path] | None,
        typer.Option("--context", help="Local file or directory to include as extra context."),
    ] = None,
    agent: Annotated[
        str | None, typer.Option("--agent", help="Agent to use (claude, codex).")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Verbose output.")] = False,
) -> None:
    """Run a component (directory of task YAML files)."""
    from dkmv.project import find_project_root, get_repo
    from dkmv.tasks import ComponentRunner, TaskLoader, TaskRunner, resolve_component
    from dkmv.tasks.models import CLIOverrides
    from dkmv.core.runner import RunManager
    from dkmv.core.sandbox import SandboxManager
    from dkmv.core.stream import StreamParser

    config = load_config()
    project_root = find_project_root()
    resolved_repo = get_repo(repo)

    component_dir = resolve_component(component, project_root=project_root)
    variables = _parse_vars(var)

    cli_overrides = CLIOverrides(
        model=model,
        max_turns=max_turns,
        timeout_minutes=timeout,
        max_budget_usd=max_budget_usd,
        agent=agent,
    )

    sandbox = SandboxManager()
    run_mgr = RunManager(output_dir=config.output_dir)
    parser = StreamParser(verbose=verbose or _verbose)
    loader = TaskLoader()
    task_runner = TaskRunner(sandbox, run_mgr, parser, Console())
    runner = ComponentRunner(sandbox, run_mgr, loader, task_runner, Console())

    result = await runner.run(
        component_dir=component_dir,
        repo=resolved_repo,
        branch=branch,
        feature_name=feature_name or component_dir.name,
        variables=variables,
        config=config,
        cli_overrides=cli_overrides,
        keep_alive=keep_alive,
        verbose=verbose or _verbose,
        context_paths=context,
    )
    console.print(f"Run {result.run_id} completed with status: {result.status}")
    if result.error_message:
        console.print(f"Error: {result.error_message}", style="bold red")


@app.command()
def runs(
    component: Annotated[
        str | None, typer.Option("--component", help="Filter by component (dev|qa|docs).")
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
    except ValueError as e:
        console.print(f"Error: {e}", style="bold red")
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
        detail = run_mgr.get_run(run_id)
    except FileNotFoundError:
        console.print(f"Error: Run '{run_id}' not found.", style="bold red")
        raise typer.Exit(code=1)
    except ValueError as e:
        console.print(f"Error: {e}", style="bold red")
        raise typer.Exit(code=1)

    container_name = run_mgr.get_container_name(detail.run_id)
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
        detail = run_mgr.get_run(run_id)
    except FileNotFoundError:
        console.print(f"Error: Run '{run_id}' not found.", style="bold red")
        raise typer.Exit(code=1)
    except ValueError as e:
        console.print(f"Error: {e}", style="bold red")
        raise typer.Exit(code=1)

    container_name = run_mgr.get_container_name(detail.run_id)
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
