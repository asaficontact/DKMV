"""Model factories for testing.

Uses polyfactory to generate valid Pydantic model instances with sensible
defaults. Factories are added as models are created in each phase.

TODO(T061): Add DevConfigFactory, DevResultFactory
TODO(T074): Add QAConfigFactory, QAResultFactory
TODO(T079): Add JudgeConfigFactory, JudgeResultFactory
TODO(T084): Add DocsConfigFactory, DocsResultFactory
"""

from polyfactory.factories.pydantic_factory import ModelFactory

from dkmv.core.models import (
    BaseComponentConfig,
    BaseResult,
    RunDetail,
    RunSummary,
    SandboxConfig,
)


class SandboxConfigFactory(ModelFactory):
    __model__ = SandboxConfig
    image = "dkmv-sandbox:latest"
    memory_limit = "4g"
    timeout_minutes = 5
    startup_timeout = 30.0
    keep_alive = False


class BaseComponentConfigFactory(ModelFactory):
    __model__ = BaseComponentConfig
    repo = "https://github.com/test/repo.git"
    branch = "feature/test"
    feature_name = "test-feature"
    model = "claude-sonnet-4-20250514"
    max_turns = 10
    timeout_minutes = 5
    keep_alive = False
    verbose = False


class BaseResultFactory(ModelFactory):
    __model__ = BaseResult
    run_id = "abc12345"
    component = "dev"
    status = "completed"
    repo = "https://github.com/test/repo.git"
    branch = "feature/test"
    feature_name = "test-feature"
    model = "claude-sonnet-4-20250514"
    total_cost_usd = 0.05
    duration_seconds = 120.0
    num_turns = 5


class RunSummaryFactory(ModelFactory):
    __model__ = RunSummary
    run_id = "abc12345"
    component = "dev"
    status = "completed"
    feature_name = "test-feature"
    total_cost_usd = 0.05
    duration_seconds = 120.0


class RunDetailFactory(ModelFactory):
    __model__ = RunDetail
    run_id = "abc12345"
    component = "dev"
    status = "completed"
    repo = "https://github.com/test/repo.git"
    branch = "feature/test"
    stream_events_count = 10
    prompt = "Test prompt"
    log_path = "outputs/runs/abc12345/logs/run.log"
