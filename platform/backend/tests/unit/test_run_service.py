"""AC-0.2-1 / AC-0.2-2: RunService over EmbeddedRuntime, platform-owned output_dir.

Asserts ``build_runtime_config`` maps platform settings onto the engine
``RuntimeConfig`` and that ``RunService`` constructs a real ``EmbeddedRuntime``
whose ``output_dir`` is bound to ``settings.OUTPUT_DIR`` (OQ-4), and that it
delegates ``get_capabilities``/``start`` to the engine in-process.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from app.config import Settings
from app.runtime import RunService, build_runtime_config
from dkmv.runtime import EmbeddedRuntime, ExecutionSourceType

from tests.conftest import make_settings


def _settings(tmp_path: Path) -> Settings:
    return make_settings(
        OUTPUT_DIR=tmp_path / "outputs",
        ANTHROPIC_API_KEY="sk-ant-fixture",
        GITHUB_TOKEN="gh-fixture",
        CODEX_API_KEY="codex-fixture",
        DKMV_IMAGE="dkmv-sandbox:pinned",
    )


def test_build_runtime_config_maps_settings(tmp_path: Path) -> None:
    cfg = build_runtime_config(_settings(tmp_path))
    assert cfg.anthropic_api_key == "sk-ant-fixture"
    assert cfg.github_token == "gh-fixture"
    assert cfg.codex_api_key == "codex-fixture"
    assert cfg.image_name == "dkmv-sandbox:pinned"
    assert cfg.output_dir == tmp_path / "outputs"


def test_build_runtime_config_threads_isolation_passthrough(tmp_path: Path) -> None:
    """G1/G2: SANDBOX_RUNTIME / EGRESS_NETWORK / SANDBOX_DNS / SECRET_FILE_MOUNT
    reach the engine RuntimeConfig so EVERY run is pinned to gVisor + the egress
    network + file-mounted creds (not relying on the daemon default)."""
    settings = make_settings(
        OUTPUT_DIR=tmp_path / "outputs",
        SANDBOX_RUNTIME="runsc",
        EGRESS_NETWORK="dkmv-egress",
        SANDBOX_DNS="172.20.0.2",
        SECRET_FILE_MOUNT=True,
    )
    cfg = build_runtime_config(settings)
    assert cfg.sandbox_runtime == "runsc"
    assert cfg.egress_network == "dkmv-egress"
    assert cfg.sandbox_dns == "172.20.0.2"
    assert cfg.github_token_file_mount is True


def test_build_runtime_config_empty_network_is_none(tmp_path: Path) -> None:
    """An empty EGRESS_NETWORK disables the --network passthrough (None, not '')."""
    settings = make_settings(OUTPUT_DIR=tmp_path / "outputs", EGRESS_NETWORK="")
    cfg = build_runtime_config(settings)
    assert cfg.egress_network is None


def test_enforce_sandbox_isolation_fails_closed_when_runsc_missing(tmp_path: Path) -> None:
    """G1: runsc required but unavailable + no opt-in → 503 sandbox_isolation_unavailable."""
    from app.api.errors import ApiError

    settings = make_settings(
        OUTPUT_DIR=tmp_path / "outputs",
        SANDBOX_RUNTIME="runsc",
        ALLOW_WEAKER_ISOLATION=False,
    )
    service = RunService(settings, runtime=_Fake())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed fake
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.executor.runtime_policy.runtime_available", lambda *a, **k: False)
        with pytest.raises(ApiError) as exc:
            service.enforce_sandbox_isolation()
    assert exc.value.status_code == 503
    assert exc.value.code == "sandbox_isolation_unavailable"


def test_enforce_sandbox_isolation_passes_when_runsc_available(tmp_path: Path) -> None:
    """G1: runsc available → no error (the secure default path)."""
    settings = make_settings(OUTPUT_DIR=tmp_path / "outputs", SANDBOX_RUNTIME="runsc")
    service = RunService(settings, runtime=_Fake())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed fake
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.executor.runtime_policy.runtime_available", lambda *a, **k: True)
        service.enforce_sandbox_isolation()  # no raise


def test_enforce_sandbox_isolation_opt_in_proceeds(tmp_path: Path) -> None:
    """G1: runsc unavailable but ALLOW_WEAKER_ISOLATION → proceeds (no raise)."""
    settings = make_settings(
        OUTPUT_DIR=tmp_path / "outputs",
        SANDBOX_RUNTIME="runsc",
        ALLOW_WEAKER_ISOLATION=True,
    )
    service = RunService(settings, runtime=_Fake())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed fake
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.executor.runtime_policy.runtime_available", lambda *a, **k: False)
        service.enforce_sandbox_isolation()  # no raise


class _Fake:
    """Minimal duck-typed runtime so RunService skips real EmbeddedRuntime build."""

    def get_capabilities(self) -> str:
        return "delegated"


def test_run_service_constructs_engine_with_platform_output_dir(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    service = RunService(settings)
    assert isinstance(service.runtime, EmbeddedRuntime)
    # OQ-4: the engine's output_dir is the platform-owned OUTPUT_DIR.
    assert service.output_dir == settings.OUTPUT_DIR
    assert service.runtime._output_dir == settings.OUTPUT_DIR


def test_get_capabilities_delegates_to_engine(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    class _Fake:
        def get_capabilities(self) -> str:
            return "delegated"

    service = RunService(settings, runtime=_Fake())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed fake
    assert service.get_capabilities() == "delegated"  # type: ignore[comparison-overlap]  # DKMVP-ESCAPE: fake returns sentinel


@pytest.mark.asyncio
async def test_start_builds_remote_execution_source(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    captured: dict[str, Any] = {}

    class _CapturingRuntime:
        async def start(self, *, component: str, source: Any, **kwargs: Any) -> str:
            captured["component"] = component
            captured["source"] = source
            captured["kwargs"] = kwargs
            return "handle"

    service = RunService(settings, runtime=_CapturingRuntime())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed fake
    handle = await service.start(
        component="dev",
        repo="https://github.com/acme/widget",
        branch="dkmv/issue-1",
        feature_name="widget",
    )
    assert handle == "handle"  # type: ignore[comparison-overlap]  # DKMVP-ESCAPE: fake returns sentinel
    assert captured["component"] == "dev"
    assert captured["source"].type == ExecutionSourceType.REMOTE
    assert captured["source"].repo == "https://github.com/acme/widget"
    assert captured["source"].branch == "dkmv/issue-1"
    assert captured["kwargs"]["feature_name"] == "widget"
