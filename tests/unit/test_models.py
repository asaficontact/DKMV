from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from dkmv.core.models import (
    BaseComponentConfig,
    BaseResult,
    RunDetail,
    RunSummary,
    SandboxConfig,
)
from tests.factories import (
    BaseComponentConfigFactory,
    BaseResultFactory,
    RunDetailFactory,
    RunSummaryFactory,
    SandboxConfigFactory,
)


class TestSandboxConfig:
    def test_defaults(self) -> None:
        cfg = SandboxConfig()
        assert cfg.image == "dkmv-sandbox:latest"
        assert cfg.env_vars == {}
        assert cfg.docker_args == []
        assert cfg.startup_timeout == 180.0
        assert cfg.keep_alive is False
        assert cfg.memory_limit == "8g"
        assert cfg.timeout_minutes == 30

    def test_json_round_trip(self) -> None:
        cfg = SandboxConfig(image="custom:v1", memory_limit="16g")
        data = json.loads(cfg.model_dump_json())
        restored = SandboxConfig.model_validate(data)
        assert restored == cfg

    def test_mutable_defaults_not_shared(self) -> None:
        a = SandboxConfig()
        b = SandboxConfig()
        a.env_vars["FOO"] = "bar"
        assert "FOO" not in b.env_vars

    def test_factory_generates_valid(self) -> None:
        cfg = SandboxConfigFactory.build()
        assert cfg.image
        assert cfg.timeout_minutes > 0


class TestBaseComponentConfig:
    def test_defaults(self) -> None:
        cfg = BaseComponentConfig(repo="https://github.com/test/repo.git")
        assert cfg.repo == "https://github.com/test/repo.git"
        assert cfg.branch is None
        assert cfg.feature_name == ""
        assert cfg.model == "claude-sonnet-4-6"
        assert cfg.max_turns == 100
        assert cfg.keep_alive is False
        assert cfg.verbose is False
        assert cfg.timeout_minutes == 30
        assert isinstance(cfg.sandbox_config, SandboxConfig)
        assert cfg.max_budget_usd is None

    def test_json_round_trip(self) -> None:
        cfg = BaseComponentConfig(
            repo="https://github.com/test/repo.git",
            branch="main",
            feature_name="auth",
            max_budget_usd=5.0,
        )
        data = json.loads(cfg.model_dump_json())
        restored = BaseComponentConfig.model_validate(data)
        assert restored == cfg

    def test_factory_generates_valid(self) -> None:
        cfg = BaseComponentConfigFactory.build()
        assert cfg.repo
        assert cfg.max_turns > 0


class TestBaseResult:
    def test_defaults(self) -> None:
        result = BaseResult(run_id="abc", component="dev")
        assert result.status == "pending"
        assert result.total_cost_usd == 0.0
        assert result.duration_seconds == 0.0
        assert result.num_turns == 0
        assert result.session_id == ""
        assert result.error_message == ""
        assert result.timestamp is not None

    def test_json_round_trip(self) -> None:
        result = BaseResultFactory.build()
        data = json.loads(result.model_dump_json())
        restored = BaseResult.model_validate(data)
        assert restored.run_id == result.run_id
        assert restored.component == result.component
        assert restored.status == result.status

    def test_accepts_custom_component_name(self) -> None:
        result = BaseResult(run_id="abc", component="my-custom-component")
        assert result.component == "my-custom-component"

    def test_rejects_invalid_status(self) -> None:
        with pytest.raises(ValidationError):
            BaseResult(run_id="abc", component="dev", status="bogus")  # type: ignore[arg-type]

    def test_factory_generates_valid(self) -> None:
        result = BaseResultFactory.build()
        assert result.run_id
        assert result.component in ("dev", "qa", "docs", "plan")


class TestBaseResultConstraints:
    def test_rejects_negative_cost(self) -> None:
        with pytest.raises(ValidationError):
            BaseResult(run_id="abc", component="dev", total_cost_usd=-1.0)

    def test_rejects_negative_duration(self) -> None:
        with pytest.raises(ValidationError):
            BaseResult(run_id="abc", component="dev", duration_seconds=-1.0)

    def test_rejects_negative_turns(self) -> None:
        with pytest.raises(ValidationError):
            BaseResult(run_id="abc", component="dev", num_turns=-1)

    def test_zero_values_accepted(self) -> None:
        result = BaseResult(
            run_id="abc", component="dev", total_cost_usd=0.0, duration_seconds=0.0, num_turns=0
        )
        assert result.total_cost_usd == 0.0
        assert result.duration_seconds == 0.0
        assert result.num_turns == 0


class TestRunSummaryConstraints:
    def test_rejects_negative_cost(self) -> None:
        with pytest.raises(ValidationError):
            RunSummary(run_id="abc", component="dev", status="completed", total_cost_usd=-1.0)

    def test_rejects_negative_duration(self) -> None:
        with pytest.raises(ValidationError):
            RunSummary(run_id="abc", component="dev", status="completed", duration_seconds=-1.0)


class TestRunSummary:
    def test_json_round_trip(self) -> None:
        summary = RunSummaryFactory.build()
        data = json.loads(summary.model_dump_json())
        restored = RunSummary.model_validate(data)
        assert restored.run_id == summary.run_id

    def test_factory_generates_valid(self) -> None:
        summary = RunSummaryFactory.build()
        assert summary.run_id
        assert summary.component in ("dev", "qa", "docs", "plan")


class TestRunDetail:
    def test_extends_base_result(self) -> None:
        detail = RunDetail(run_id="x", component="qa")
        assert detail.config == {}
        assert detail.stream_events_count == 0
        assert detail.prompt == ""
        assert detail.log_path == ""
        # Inherited fields
        assert detail.status == "pending"
        assert detail.total_cost_usd == 0.0

    def test_json_round_trip(self) -> None:
        detail = RunDetailFactory.build()
        data = json.loads(detail.model_dump_json())
        restored = RunDetail.model_validate(data)
        assert restored.run_id == detail.run_id
        assert restored.stream_events_count == detail.stream_events_count

    def test_factory_generates_valid(self) -> None:
        detail = RunDetailFactory.build()
        assert detail.run_id
        assert detail.prompt
