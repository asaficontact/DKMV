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

import tempfile
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

#: TestClients that ``build_client`` entered (ran startup on). The autouse
#: :func:`_close_entered_clients` fixture runs each one's shutdown after the test
#: so the lifespan-owned Repository writer task / GitHub client are torn down and
#: do not leak across tests (INV-6: exactly one writer per app instance).
_ENTERED_CLIENTS: list[TestClient] = []


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
    if settings is None:
        settings = make_settings()
    if settings.DATABASE_URL == Settings.model_fields["DATABASE_URL"].default:
        # The caller did not pin a DATABASE_URL (it is still the dev default
        # ``./data/dkmv.db``). Entering the lifespan (below) starts a real
        # Repository, so swap in an isolated, migrated temp DB per client — never
        # touch the dev DB, never share one DB across two clients. A caller that
        # pins its own DATABASE_URL (e.g. the issues/board API tests) keeps it.
        settings = settings.model_copy(update={"DATABASE_URL": _temp_migrated_url()})
    run_service = RunService(settings, runtime=runtime or StubRuntime())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed runtime stub/fake
    app = create_app(settings, run_service=run_service)
    client = TestClient(
        app,
        base_url=f"http://{host}",
        raise_server_exceptions=raise_server_exceptions,
    )
    # Enter the lifespan (run startup) so the shared Repository / SecretStore /
    # GitHub client / write-queue are composed on ``app.state`` on the serving
    # portal loop — exercising the real slice-2.0 wiring, not the per-request
    # fallback. The autouse ``_close_entered_clients`` fixture runs shutdown.
    client.__enter__()
    _ENTERED_CLIENTS.append(client)
    return client


def _temp_migrated_url() -> str:
    """Create an isolated, migrated SQLite DB file and return its DATABASE_URL.

    Used by :func:`build_client` when no settings are supplied so a lifespan-entered
    TestClient has a real schema to query. The file lives in a process-temp dir and
    is cleaned up by the OS / test teardown; each call is a fresh DB.
    """
    fd, path = tempfile.mkstemp(prefix="dkmvp-test-", suffix=".db")
    import os

    os.close(fd)
    return _migrate(Path(path))


def auth_headers() -> dict[str, str]:
    """``Authorization: Bearer`` header for :data:`TEST_TOKEN`."""
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture(autouse=True)
def _gvisor_available_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default the whole unit suite to a gVisor-equipped host (G1 determinism).

    The G1 fail-closed gate (``RunService.enforce_sandbox_isolation`` /
    ``isolation_status``) probes ``docker info`` for the ``runsc`` runtime. On a
    docker-less CI box that would make EVERY launch/preflight fail-closed (503 /
    blocker), so the default test posture here is "runsc registered" — the secure,
    properly-provisioned host. Tests that exercise the *blocker* path override this
    with their own ``monkeypatch.setattr(... runtime_available, lambda *a, **k: False)``.
    """
    monkeypatch.setattr("app.executor.runtime_policy.runtime_available", lambda *a, **k: True)


@pytest.fixture(autouse=True)
def _close_entered_clients() -> Iterator[None]:
    """Run lifespan shutdown for every client :func:`build_client` entered.

    ``build_client`` runs startup (``__enter__``) so tests exercise the slice-2.0
    shared-singleton path; this autouse fixture runs the matching shutdown
    (``__exit__``) after each test so the lifespan-owned single writer task and
    GitHub client are released — no writer/loop leaks across tests (INV-6).
    """
    yield
    while _ENTERED_CLIENTS:
        entered = _ENTERED_CLIENTS.pop()
        try:
            entered.__exit__(None, None, None)
        except Exception:  # noqa: BLE001 - best-effort teardown; never fail a test on cleanup
            pass


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
