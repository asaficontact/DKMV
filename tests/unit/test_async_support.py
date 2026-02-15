import pytest

from dkmv.utils.async_support import async_command


class TestAsyncCommand:
    def test_converts_async_to_sync(self) -> None:
        @async_command
        async def greet() -> str:
            return "hello"

        assert greet() == "hello"

    def test_preserves_function_name(self) -> None:
        @async_command
        async def my_func() -> None:
            pass

        assert my_func.__name__ == "my_func"

    def test_preserves_docstring(self) -> None:
        @async_command
        async def documented() -> None:
            """Some docstring."""

        assert documented.__doc__ == "Some docstring."

    def test_passes_kwargs(self) -> None:
        @async_command
        async def add(a: int, b: int = 0) -> int:
            return a + b

        assert add(2, b=3) == 5

    def test_propagates_exceptions(self) -> None:
        @async_command
        async def fail() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            fail()

    def test_importable_from_utils_package(self) -> None:
        from dkmv.utils import async_command as ac

        assert ac is async_command
