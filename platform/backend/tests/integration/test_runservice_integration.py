"""AC-0.2-6: a component runs end-to-end through RunService (M0 exit).

This drives the *real* ``RunService`` → ``EmbeddedRuntime.start`` →
``RunHandle`` path against a throwaway git repo and asserts the M0 exit
contract: the run reaches a terminal status and artifacts are indexed in the
platform-owned ``output_dir``.

A genuine Docker-backed agent run requires the ``dkmv-sandbox`` image + a
gVisor-capable Docker host, which is not available in unit CI. So we keep the
*entire facade path real* (source resolution, run-id back-fill, the
``source_provenance.json`` artifact the facade itself writes, handle/task
lifecycle, ``wait()``, ``list_artifacts``) and replace only the engine's
innermost Docker-bound collaborator — ``ComponentRunner.run`` — with a fast
in-process fake that uses the engine's *own* ``RunManager`` to create the run
directory, persist an artifact, and return a real ``ComponentResult`` with a
terminal status. The test therefore exercises the platform↔engine bridge
in-process (INV-13) without shelling the CLI or needing Docker.

The Docker-backed variant is marked ``integration`` and skipped unless the
``dkmv-sandbox`` image is present.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from app.config import Settings
from app.runtime import RunService
from dkmv.tasks.models import ComponentResult

from tests.conftest import make_settings


def _make_throwaway_repo(root: Path) -> str:
    """Init a throwaway git repo and return its ``file://`` URL."""
    repo = root / "throwaway-repo"
    repo.mkdir()
    (repo / "README.md").write_text("# throwaway\n")
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, env={**env})
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env={**env})
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "init"],
        check=True,
        env={**env},
    )
    return f"file://{repo}"


def _settings(tmp_path: Path) -> Settings:
    return make_settings(
        OUTPUT_DIR=tmp_path / "outputs",
        ANTHROPIC_API_KEY="sk-ant-fixture",
        DKMV_IMAGE="dkmv-sandbox:latest",
    )


@pytest.mark.asyncio
async def test_runservice_integration_completes_run_with_artifacts(
    tmp_path: Path,
) -> None:
    """RunService drives a run to a terminal status with indexed artifacts."""
    settings = _settings(tmp_path)
    service = RunService(settings)
    runtime = service.runtime

    repo_url = _make_throwaway_repo(tmp_path)

    # Replace the innermost Docker-bound collaborator with a fast fake that
    # still uses the engine's real RunManager (run dir + artifact persistence).
    run_manager = runtime._run_manager

    async def _fake_run(
        *,
        component_dir: Path,
        repo: str,
        branch: str | None,
        feature_name: str,
        on_event: Any = None,
        on_run_id: Any = None,
        **_kwargs: Any,
    ) -> ComponentResult:
        from dkmv.core.models import BaseComponentConfig

        base_config = BaseComponentConfig(
            repo=repo,
            branch=branch,
            feature_name=feature_name,
            model="claude-sonnet-4-6",
            max_turns=10,
            timeout_minutes=5,
            keep_alive=False,
            verbose=False,
        )
        run_id = run_manager.start_run(component_dir.name, base_config)
        if on_run_id is not None:
            on_run_id(run_id)
        if on_event is not None:
            on_event(
                {
                    "type": "system",
                    "event_type": "task_completed",
                    "task_index": 0,
                    "cost_usd": 0.0,
                }
            )
        run_manager.save_artifact(run_id, "GUIDE.md", "# Plan\nDone.\n")
        return ComponentResult(
            run_id=run_id,
            component=component_dir.name,
            status="completed",
            repo=repo,
            branch=branch or "",
            feature_name=feature_name,
            total_cost_usd=0.0,
            duration_seconds=0.01,
            task_results=[],
        )

    # Bind onto the instance; the facade calls ``self._component_runner.run(...)``
    # with keyword args, which our fake accepts.
    runtime._component_runner.run = _fake_run  # type: ignore[method-assign,assignment]  # DKMVP-ESCAPE: in-process test seam for the Docker-bound collaborator

    handle = await service.start(
        component="dev",
        repo=repo_url,
        branch="dkmv/issue-1-throwaway",
        feature_name="throwaway",
    )
    result = await handle.wait(timeout=10)

    # M0 exit: terminal status + artifacts indexed.
    assert result.status == "completed"
    assert handle.status == "completed"
    run_id = handle.run_id
    assert run_id

    artifacts = runtime.list_artifacts(run_id)
    names = {a.filename for a in artifacts}
    # The facade writes source_provenance.json; our run wrote GUIDE.md.
    assert "GUIDE.md" in names
    assert "source_provenance.json" in names

    # Artifacts live under the platform-owned OUTPUT_DIR (OQ-4).
    guide = runtime.get_artifact(run_id, "GUIDE.md")
    assert "Plan" in guide
    assert (settings.OUTPUT_DIR / "runs").exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_runservice_integration_docker_backed(tmp_path: Path) -> None:
    """Full Docker-backed M0 run; skipped unless the sandbox image is present."""
    image = "dkmv-sandbox:latest"
    probe = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
    )
    if probe.returncode != 0:
        pytest.skip(f"sandbox image {image} not available")

    settings = _settings(tmp_path)
    service = RunService(settings)
    repo_url = _make_throwaway_repo(tmp_path)

    handle = await service.start(
        component="dev",
        repo=repo_url,
        branch="dkmv/issue-1-throwaway",
        feature_name="throwaway",
    )
    result = await handle.wait(timeout=900)
    assert result.status in {"completed", "failed", "timed_out", "cancelled"}
    assert handle.run_id
