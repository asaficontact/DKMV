"""Model factories for testing.

Uses polyfactory to generate valid Pydantic model instances with sensible
defaults. Factories are added as models are created in each phase.
"""

from pathlib import Path

from polyfactory.factories.pydantic_factory import ModelFactory

from dkmv.components.dev.models import DevConfig, DevResult
from dkmv.components.docs.models import DocsConfig, DocsResult
from dkmv.components.judge.models import JudgeConfig, JudgeResult
from dkmv.components.qa.models import QAConfig, QAResult
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


class DevConfigFactory(ModelFactory):
    __model__ = DevConfig
    repo = "https://github.com/test/repo.git"
    branch = "feature/test-dev"
    feature_name = "test-feature"
    prd_path = Path("/tmp/test-prd.md")
    model = "claude-sonnet-4-20250514"
    max_turns = 10
    timeout_minutes = 5
    keep_alive = False
    verbose = False


class DevResultFactory(ModelFactory):
    __model__ = DevResult
    run_id = "abc12345"
    component = "dev"
    status = "completed"
    repo = "https://github.com/test/repo.git"
    branch = "feature/test-dev"
    feature_name = "test-feature"
    total_cost_usd = 0.05
    duration_seconds = 120.0
    num_turns = 5


class QAConfigFactory(ModelFactory):
    __model__ = QAConfig
    repo = "https://github.com/test/repo.git"
    branch = "feature/test"
    prd_path = Path("/tmp/test-prd.md")
    model = "claude-sonnet-4-20250514"
    max_turns = 10
    timeout_minutes = 5
    keep_alive = False
    verbose = False


class QAResultFactory(ModelFactory):
    __model__ = QAResult
    run_id = "abc12345"
    component = "qa"
    status = "completed"
    repo = "https://github.com/test/repo.git"
    branch = "feature/test"
    tests_total = 10
    tests_passed = 8
    tests_failed = 2


class JudgeConfigFactory(ModelFactory):
    __model__ = JudgeConfig
    repo = "https://github.com/test/repo.git"
    branch = "feature/test"
    prd_path = Path("/tmp/test-prd.md")
    model = "claude-sonnet-4-20250514"
    max_turns = 10
    timeout_minutes = 5
    keep_alive = False
    verbose = False


class JudgeResultFactory(ModelFactory):
    __model__ = JudgeResult
    run_id = "abc12345"
    component = "judge"
    status = "completed"
    repo = "https://github.com/test/repo.git"
    branch = "feature/test"
    verdict = "pass"
    confidence = 0.9
    reasoning = "All requirements met"
    score = 85


class DocsConfigFactory(ModelFactory):
    __model__ = DocsConfig
    repo = "https://github.com/test/repo.git"
    branch = "feature/test-docs"
    model = "claude-sonnet-4-20250514"
    max_turns = 10
    timeout_minutes = 5
    keep_alive = False
    verbose = False
    create_pr = False
    pr_base = "main"


class DocsResultFactory(ModelFactory):
    __model__ = DocsResult
    run_id = "abc12345"
    component = "docs"
    status = "completed"
    repo = "https://github.com/test/repo.git"
    branch = "feature/test-docs"
