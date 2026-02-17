from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from dkmv.components.base import BaseComponent

_REGISTRY: dict[str, type[BaseComponent]] = {}
_DISCOVERED = False

_COMPONENT_MODULES = [
    "dkmv.components.dev",
    "dkmv.components.qa",
    "dkmv.components.judge",
    "dkmv.components.docs",
]


def _discover() -> None:
    global _DISCOVERED  # noqa: PLW0603
    if _DISCOVERED:
        return
    for mod in _COMPONENT_MODULES:
        try:
            importlib.import_module(mod)
        except ImportError:
            pass
    _DISCOVERED = True


def register_component(name: str) -> Callable[[type[BaseComponent]], type[BaseComponent]]:
    """Decorator to register a component class."""

    def decorator(cls: type[BaseComponent]) -> type[BaseComponent]:
        _REGISTRY[name] = cls
        return cls

    return decorator


def get_component(name: str) -> type[BaseComponent]:
    _discover()
    try:
        return _REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        msg = f"Unknown component {name!r}. Available: {available}"
        raise KeyError(msg) from None


def list_components() -> list[str]:
    _discover()
    return sorted(_REGISTRY)
