"""Shared test fixtures for the platform backend (slices 0.2 + 0.3).

This conftest unions two independent fixture sets so the whole backend suite
(api-layer *and* db-layer) shares one source of truth:

**App / API fixtures (slice 0.2)** — consolidate the helpers the access-control,
preflight and error-envelope tests need so the same settings factory / authed
TestClient builder / fake runtime are not re-declared in every module:

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

**DB fixtures (slice 0.3)** — build a real, migrated SQLite file via Alembic
``upgrade head`` so tests exercise the *migration-produced* schema (AC-0.3-4),
not an ad-hoc ``create_all``. Each test gets an isolated temp DB file and a
started :class:`Repository` whose single writer task is torn down afterward.

Nothing here reaches into ``dkmv/`` or shells the CLI.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app.config import Settings
from app.db import Repository
from app.main import create_app
from app.runtime import RunService
from fastapi.testclient import TestClient

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dkmv.runtime import CapabilityReport


# ── App / API fixtures (slice 0.2) ───────────────────────────────────────────

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


# ── DB fixtures (slice 0.3) ──────────────────────────────────────────────────

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _migrate(db_path: Path) -> str:
    """Run ``alembic upgrade head`` against ``db_path``; return its DATABASE_URL."""
    url = f"sqlite:///{db_path}"
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


@pytest.fixture
def database_url(tmp_path: Path) -> Iterator[str]:
    """An isolated, migrated SQLite DB file; yields its DATABASE_URL."""
    db_path = tmp_path / "test.db"
    yield _migrate(db_path)


@pytest_asyncio.fixture
async def repo(database_url: str) -> AsyncIterator[Repository]:
    """A started :class:`Repository` over a migrated temp DB."""
    repository = Repository(database_url)
    await repository.start()
    try:
        yield repository
    finally:
        await repository.close()
