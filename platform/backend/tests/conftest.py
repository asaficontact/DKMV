"""Shared test fixtures for the platform backend (slice 0.2).

These consolidate the small helpers that several unit tests need so the same
settings factory / authed TestClient builder / fake runtime are not re-declared
in every module:

* :func:`make_settings` — a throwaway :class:`~app.config.Settings` with
  ``_env_file=None`` (so the dev ``.env`` never bleeds into a test) and a known
  token; extra keyword overrides pass straight through.
* :data:`TEST_TOKEN` — the token :func:`make_settings` installs.
* :func:`build_client` — a loopback-pinned :class:`TestClient` over the real
  app wired to a caller-supplied runtime stub/fake; loopback base URL satisfies
  the anti-DNS-rebinding ``Host`` check (INV-1).
* :func:`auth_headers` — the ``Authorization: Bearer`` header for the test token.
* :class:`StubRuntime` / :class:`FakeRuntime` — duck-typed engine stand-ins so
  the app never constructs a real Docker-bound ``EmbeddedRuntime``.

Nothing here reaches into ``dkmv/`` or shells the CLI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.config import Settings
from app.main import create_app
from app.runtime import RunService
from fastapi.testclient import TestClient

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dkmv.runtime import CapabilityReport

# Shared test token (not a real secret).
TEST_TOKEN = "test-token-xyz"  # noqa: S105 - fixture token, not a real secret


def make_settings(**overrides: Any) -> Settings:
    """Build throwaway settings with ``_env_file=None`` + the test token.

    ``_env_file=None`` keeps a developer's local ``.env`` from leaking into the
    test. Any keyword override (``OUTPUT_DIR=…``, ``ANTHROPIC_API_KEY=…``,
    ``DKMV_EXPOSE_DOCS_UNAUTHENTICATED=…`` …) passes straight through.
    """
    kwargs: dict[str, Any] = {"DKMV_PLATFORM_TOKEN": TEST_TOKEN, **overrides}
    return Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]  # DKMVP-ESCAPE: pydantic-settings injected kwargs


class StubRuntime:
    """Engine stand-in whose ``get_capabilities`` is intentionally never called.

    Used by access-control tests: reaching it (and tripping the assertion → 500
    envelope) *proves* the request cleared access control rather than being
    rejected at 401/403.
    """

    def get_capabilities(self) -> Any:  # pragma: no cover - tripped only if reached
        raise AssertionError("preflight not under test here")


class FakeRuntime:
    """Engine stand-in returning a fixed :class:`CapabilityReport`."""

    def __init__(self, report: CapabilityReport) -> None:
        self._report = report

    def get_capabilities(self) -> CapabilityReport:
        return self._report


def build_client(
    *,
    settings: Settings | None = None,
    runtime: Any | None = None,
    host: str = "127.0.0.1",
    raise_server_exceptions: bool = False,
) -> TestClient:
    """Build a loopback-pinned ``TestClient`` over the real app.

    ``host`` defaults to ``127.0.0.1`` so the anti-DNS-rebinding ``Host`` check
    passes; pass a foreign host to exercise the 403 path.
    ``raise_server_exceptions=False`` (the default) lets the installed exception
    handlers turn an uncaught error into the §8.9 500 envelope so a test can
    assert a request reached the inner app (vs. being rejected at 401/403).
    """
    settings = settings or make_settings()
    run_service = RunService(settings, runtime=runtime or StubRuntime())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed runtime stub/fake
    app = create_app(settings, run_service=run_service)
    return TestClient(
        app,
        base_url=f"http://{host}",
        raise_server_exceptions=raise_server_exceptions,
    )


def auth_headers() -> dict[str, str]:
    """``Authorization: Bearer`` header for :data:`TEST_TOKEN`."""
    return {"Authorization": f"Bearer {TEST_TOKEN}"}
