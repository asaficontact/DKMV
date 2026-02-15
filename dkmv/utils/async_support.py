import asyncio
import functools
from typing import Any, Callable, Coroutine


def async_command(func: Callable[..., Coroutine[Any, Any, Any]]) -> Callable[..., Any]:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(func(*args, **kwargs))

    return wrapper
