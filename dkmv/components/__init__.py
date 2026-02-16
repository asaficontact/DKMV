from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from dkmv.components.base import BaseComponent

_REGISTRY: dict[str, type[BaseComponent]] = {}


def register_component(name: str) -> Callable[[type[BaseComponent]], type[BaseComponent]]:
    """Decorator to register a component class."""

    def decorator(cls: type[BaseComponent]) -> type[BaseComponent]:
        _REGISTRY[name] = cls
        return cls

    return decorator


def get_component(name: str) -> type[BaseComponent]:
    try:
        return _REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        msg = f"Unknown component {name!r}. Available: {available}"
        raise KeyError(msg) from None


def list_components() -> list[str]:
    return sorted(_REGISTRY)
