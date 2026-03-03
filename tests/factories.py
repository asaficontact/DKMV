"""Model factories for testing.

Uses polyfactory to generate valid Pydantic model instances with sensible
defaults. Factories are added as models are created in each phase.
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
    model = "claude-sonnet-4-6"
    max_turns = 10
    timeout_minutes = 5
    keep_alive = False
    verbose = False


class BaseResultFactory(ModelFactory):
    __model__ = BaseResult
    run_id = "260101-1200-dev-test-feature-a1b2"
    component = "dev"
    status = "completed"
    repo = "https://github.com/test/repo.git"
    branch = "feature/test"
    feature_name = "test-feature"
    model = "claude-sonnet-4-6"
    total_cost_usd = 0.05
    duration_seconds = 120.0
    num_turns = 5


class RunSummaryFactory(ModelFactory):
    __model__ = RunSummary
    run_id = "260101-1200-dev-test-feature-a1b2"
    component = "dev"
    status = "completed"
    feature_name = "test-feature"
    total_cost_usd = 0.05
    duration_seconds = 120.0


class RunDetailFactory(ModelFactory):
    __model__ = RunDetail
    run_id = "260101-1200-dev-test-feature-a1b2"
    component = "dev"
    status = "completed"
    repo = "https://github.com/test/repo.git"
    branch = "feature/test"
    stream_events_count = 10
    prompt = "Test prompt"
    log_path = "outputs/runs/260101-1200-dev-test-feature-a1b2/logs/run.log"
