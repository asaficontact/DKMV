from __future__ import annotations

from dkmv.adapters.base import AgentAdapter, StreamResult
from dkmv.adapters.claude import ClaudeCodeAdapter

_ADAPTERS: dict[str, type] = {
    "claude": ClaudeCodeAdapter,
}


def get_adapter(name: str) -> AgentAdapter:
    cls = _ADAPTERS.get(name)
    if cls is None:
        available = ", ".join(sorted(_ADAPTERS.keys()))
        raise ValueError(f"Unknown agent '{name}'. Available: {available}")
    instance: AgentAdapter = cls()
    return instance


__all__ = ["AgentAdapter", "StreamResult", "get_adapter"]
