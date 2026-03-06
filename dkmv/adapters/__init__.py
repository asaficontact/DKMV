from __future__ import annotations

import logging
import re

from dkmv.adapters.base import AgentAdapter, StreamResult
from dkmv.adapters.claude import ClaudeCodeAdapter
from dkmv.adapters.codex import CodexCLIAdapter

logger = logging.getLogger(__name__)

_ADAPTERS: dict[str, type] = {
    "claude": ClaudeCodeAdapter,
    "codex": CodexCLIAdapter,
}


def get_adapter(name: str) -> AgentAdapter:
    cls = _ADAPTERS.get(name)
    if cls is None:
        available = ", ".join(sorted(_ADAPTERS.keys()))
        raise ValueError(f"Unknown agent '{name}'. Available: {available}")
    instance: AgentAdapter = cls()
    return instance


def infer_agent_from_model(model: str) -> str | None:
    """Infer the appropriate agent from a model name. Returns None if unknown."""
    if model.startswith("claude-"):
        return "claude"
    if model.startswith("gpt-"):
        return "codex"
    if re.match(r"^o\d", model):
        return "codex"
    return None


def _model_patterns(agent_name: str) -> str:
    patterns = {"claude": "claude-*", "codex": "gpt-*, o<digit>*"}
    return patterns.get(agent_name, "unknown")


def validate_agent_model(
    agent_name: str,
    model: str,
    agent_explicit: bool = False,
    model_explicit: bool = False,
) -> str:
    """Validate model-agent compatibility. Returns resolved model.

    Raises ValueError if explicit agent+model are incompatible.
    Auto-substitutes default model if conflict is from defaults.
    """
    adapter = get_adapter(agent_name)

    if adapter.validate_model(model):
        return model  # Compatible

    if agent_explicit and model_explicit:
        raise ValueError(
            f"Model '{model}' is not compatible with agent '{agent_name}'. "
            f"Compatible models: {_model_patterns(agent_name)}"
        )

    # Auto-substitute: use agent's default model
    default = adapter.default_model
    logger.info(
        "Model '%s' not compatible with agent '%s'; using default '%s'",
        model,
        agent_name,
        default,
    )
    return default


__all__ = [
    "AgentAdapter",
    "StreamResult",
    "get_adapter",
    "infer_agent_from_model",
    "validate_agent_model",
]
