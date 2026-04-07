"""Capability and readiness checks for the embedded runtime."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel

from dkmv.runtime._types import ExecutionSource, ExecutionSourceType, RuntimeConfig


class CapabilityReport(BaseModel):
    """Reports what the runtime can do and what infrastructure is available."""

    version: str = ""
    embedded_runtime: bool = True
    event_observer: bool = True
    pause_callback: bool = True
    stop_cancel: bool = True
    introspection: bool = True
    replay_history: bool = True
    retention: bool = True
    telemetry: bool = True
    docker_available: bool = False
    docker_version: str = ""
    image_exists: bool = False
    image_name: str = ""
    available_agents: list[str] = []
    has_anthropic_key: bool = False
    has_github_token: bool = False
    has_codex_key: bool = False
    project_initialized: bool = False
    project_root: Path | None = None


class PreflightResult(BaseModel):
    """Result of a pre-execution readiness check."""

    ready: bool
    blockers: list[str] = []
    warnings: list[str] = []


def _check_docker_version() -> tuple[bool, str]:
    """Check if Docker is available and return its version."""
    if not shutil.which("docker"):
        return False, ""
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return False, ""


def _check_image_exists(image_name: str) -> bool:
    """Check if a Docker image exists locally."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image_name],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def get_capabilities(config: RuntimeConfig | None = None) -> CapabilityReport:
    """Probe the runtime environment and return a capability report."""
    import dkmv

    from dkmv.adapters import _ADAPTERS
    from dkmv.project import find_project_root, load_project_config

    cfg = config or RuntimeConfig()
    image_name = cfg.image_name
    docker_available, docker_version = _check_docker_version()
    image_exists = _check_image_exists(image_name) if docker_available else False

    project_root = find_project_root()
    project_config = load_project_config(project_root)

    return CapabilityReport(
        version=dkmv.__version__,
        docker_available=docker_available,
        docker_version=docker_version,
        image_exists=image_exists,
        image_name=image_name,
        available_agents=sorted(_ADAPTERS.keys()),
        has_anthropic_key=bool(cfg.anthropic_api_key),
        has_github_token=bool(cfg.github_token),
        has_codex_key=bool(cfg.codex_api_key),
        project_initialized=project_config is not None,
        project_root=project_root if project_config else None,
    )


def preflight_check(
    config: RuntimeConfig,
    component: str,
    source: ExecutionSource,
) -> PreflightResult:
    """Validate that a run can be started with the given parameters."""
    from dkmv.adapters import get_adapter
    from dkmv.tasks.discovery import ComponentNotFoundError, resolve_component

    blockers: list[str] = []
    warnings: list[str] = []

    # Check source
    if source.type == ExecutionSourceType.REMOTE:
        if not source.repo:
            blockers.append("Remote source requires 'repo' URL")
    elif source.type == ExecutionSourceType.LOCAL_SNAPSHOT:
        if source.local_path and not source.local_path.exists():
            blockers.append(f"Local path does not exist: {source.local_path}")

    # Check component resolves
    try:
        resolve_component(component)
    except ComponentNotFoundError as e:
        blockers.append(str(e))

    # Check agent credentials
    agent_name = config.default_agent
    try:
        adapter = get_adapter(agent_name)
        if adapter.name == "claude":
            if not config.anthropic_api_key and not config.claude_oauth_token:
                blockers.append("Claude agent requires ANTHROPIC_API_KEY or OAuth token")
        elif adapter.name == "codex":
            if not config.codex_api_key:
                blockers.append("Codex agent requires CODEX_API_KEY")
    except ValueError as e:
        blockers.append(str(e))

    # Check Docker
    docker_available, _ = _check_docker_version()
    if not docker_available:
        blockers.append("Docker is not available")
    elif not _check_image_exists(config.image_name):
        warnings.append(
            f"Docker image '{config.image_name}' not found locally (will need to build)"
        )

    # Check GitHub token
    if not config.github_token:
        if source.type == ExecutionSourceType.REMOTE:
            warnings.append("No GitHub token — private repos will fail to clone")

    return PreflightResult(
        ready=len(blockers) == 0,
        blockers=blockers,
        warnings=warnings,
    )
