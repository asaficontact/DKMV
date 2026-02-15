"""Model factories for testing.

Uses polyfactory to generate valid Pydantic model instances with sensible
defaults. Factories are added as models are created in each phase.

TODO(T030): Add factories for SandboxConfig, BaseComponentConfig, BaseResult
TODO(T061): Add DevConfigFactory, DevResultFactory
TODO(T074): Add QAConfigFactory, QAResultFactory
TODO(T079): Add JudgeConfigFactory, JudgeResultFactory
TODO(T084): Add DocsConfigFactory, DocsResultFactory
"""

# from polyfactory.factories.pydantic_factory import ModelFactory
