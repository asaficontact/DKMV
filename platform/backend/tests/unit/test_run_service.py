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
