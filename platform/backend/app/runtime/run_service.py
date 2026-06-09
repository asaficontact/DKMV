"""RunService — the platform's thin in-process wrapper over the engine.

The platform consumes the **locked** DKMV engine *in-process* via
``dkmv.runtime.EmbeddedRuntime`` (INV-13) — it never shells the ``dkmv`` CLI.
``RunService`` is the single seam the rest of the backend goes through to reach
the engine: it owns one configured :class:`EmbeddedRuntime` instance, built from
a :class:`RuntimeConfig` whose ``output_dir`` is **platform-owned** and bound to
``settings.OUTPUT_DIR`` (PRD §6.2, §6.5 OQ-4 — the engine writes its
``runs/{run_id}/`` artifact store into a volume the platform controls).

What lives here in Phase 0 (slice 0.2):

* :meth:`get_capabilities` — the standing environment probe powering
  ``GET /api/v1/preflight`` (FR-01-6).
* :meth:`start` — a typed wrapper over ``EmbeddedRuntime.start`` that builds the
  remote :class:`ExecutionSource` and returns the engine ``RunHandle``. This is
  the M0 bridge a run flows through; the full ``POST /runs`` endpoint (claim
  lock, admission, the event pump, SSE) is Phase 2 and is intentionally *not*
  here.

What is **out of scope** for 0.2 and deliberately absent: any DB write, the
observer→queue pump, segment-sum metering, HITL, the orchestrator tick. Those
arrive in later slices/phases. ``RunService`` is constructed once per app and
stored on ``app.state``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dkmv.runtime import EmbeddedRuntime, ExecutionSource, ExecutionSourceType, RuntimeConfig

from app.config import Settings
from app.secrets.github_token import GitHubTokenMinter, TokenScopeError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dkmv.runtime import CapabilityReport
    from dkmv.runtime._handle import RunHandle

    from app.secrets.store import SecretStore
    from app.security.audit import AuditLog

_log = logging.getLogger(__name__)


def build_runtime_config(settings: Settings) -> RuntimeConfig:
    """Translate platform :class:`Settings` into the engine's ``RuntimeConfig``.

    The engine reads credentials and the sandbox image off ``RuntimeConfig``
    (it does **not** read the platform env directly). ``output_dir`` is set to
    the platform-owned :attr:`Settings.OUTPUT_DIR` so the engine's per-run
    artifact store lands in a volume the platform controls (OQ-4).
    """
    return RuntimeConfig(
        anthropic_api_key=settings.ANTHROPIC_API_KEY.get_secret_value(),
        github_token=settings.GITHUB_TOKEN.get_secret_value(),
        codex_api_key=settings.CODEX_API_KEY.get_secret_value(),
        image_name=settings.DKMV_IMAGE,
        output_dir=settings.OUTPUT_DIR,
    )


class RunService:
    """Single in-process seam over a configured :class:`EmbeddedRuntime`.

    Args:
        settings: The platform settings; supplies engine credentials, the
            sandbox image name, and the platform-owned ``OUTPUT_DIR``.
        runtime: Optional pre-built runtime (tests inject a fake/stub); when
            omitted, an :class:`EmbeddedRuntime` is constructed from
            ``settings`` with ``output_dir=settings.OUTPUT_DIR``.
    """

    def __init__(self, settings: Settings, runtime: EmbeddedRuntime | None = None) -> None:
        self._settings = settings
        self._output_dir: Path = settings.OUTPUT_DIR
        # The repo-scoped run-token minting deps (INV-4 / §8.6 / AC-12). Bound by
        # the app-lifespan AFTER it composes the encrypted SecretStore + the audit
        # sink (``bind_run_token_minting``), because ``RunService`` is constructed at
        # app-creation time — before those singletons exist. Absent the binding (a
        # bare test service, or no operator GITHUB_TOKEN), token minting is a
        # graceful no-op and the engine still runs with its existing RuntimeConfig.
        self._minter: GitHubTokenMinter | None = None
        self._audit: AuditLog | None = None
        if runtime is not None:
            self._runtime = runtime
        else:
            # INV-13: construct the engine in-process from RuntimeConfig with a
            # platform-owned output_dir bound to settings.OUTPUT_DIR (OQ-4).
            self._runtime = EmbeddedRuntime(
                config=build_runtime_config(settings),
                output_dir=settings.OUTPUT_DIR,
            )

    def bind_run_token_minting(
        self,
        *,
        secret_store: SecretStore,
        audit: AuditLog | None,
    ) -> None:
        """Wire the repo-scoped run-token minter + audit sink (lifespan injection).

        Called once by ``app.main._lifespan`` after it composes the encrypted
        :class:`SecretStore` and the durable §8.6 audit log, so the launch path's
        :meth:`start` can mint a repo-scoped, ≤1 hr GitHub run token (INV-4) **and
        record the token-mint + token-use evidence lines in production** (AC-12) —
        not just in tests. The minter wraps the operator's fine-grained PAT
        (``settings.GITHUB_TOKEN``); when that PAT is empty (no GitHub configured)
        no minter is built and :meth:`start` skips minting gracefully.
        """
        base_token = self._settings.GITHUB_TOKEN.get_secret_value()
        self._audit = audit
        self._minter = (
            GitHubTokenMinter(secret_store, base_token=base_token) if base_token else None
        )

    @property
    def runtime(self) -> EmbeddedRuntime:
        """The configured engine instance (read-only access for callers)."""
        return self._runtime

    @property
    def output_dir(self) -> Path:
        """The platform-owned engine ``output_dir`` (OQ-4)."""
        return self._output_dir

    def get_capabilities(self) -> CapabilityReport:
        """Probe the standing environment (FR-01-6) — powers preflight.

        Delegates to ``EmbeddedRuntime.get_capabilities()`` (the
        component-agnostic health call). The route layer maps the flat
        capability report into the §8.9 ``{ready, checks, blockers}`` envelope.
        """
        return self._runtime.get_capabilities()

    async def start(
        self,
        *,
        component: str,
        repo: str,
        branch: str | None = None,
        feature_name: str = "",
        agent: str | None = None,
        model: str | None = None,
        max_turns: int | None = None,
        timeout_minutes: int | None = None,
        max_budget_usd: float | None = None,
        memory: str | None = None,
        variables: dict[str, Any] | None = None,
        context_paths: list[Path] | None = None,
        start_task: str | None = None,
        on_pause: Callable[[Any], Awaitable[Any]] | None = None,
        keep_alive: bool = False,
        run_id: str | None = None,
    ) -> RunHandle:
        """Start a component run against a remote ``repo`` and return its handle.

        Builds a remote :class:`ExecutionSource` and delegates to
        ``EmbeddedRuntime.start`` (non-blocking; the engine spawns an
        ``asyncio.Task`` and the ``run_id`` back-fills via the event stream).
        The returned ``RunHandle`` is what later slices register an
        ``EventObserver`` on and ``await``.

        Before the engine starts, the platform mints a **repo-scoped, ≤1 hr** GitHub
        run token (INV-4) when the minter is bound (lifespan, see
        :meth:`bind_run_token_minting`) and authorizes the push to ``repo`` — the
        production call site that records the ``token_mint`` + ``token_use`` §8.6
        evidence lines (AC-12). ``run_id`` is the platform UUID used to correlate
        those audit lines; absent it (an unbound/test service) the mint is skipped.

        This is the M0 bridge; it adds no DB write or admission control — those
        belong to ``POST /runs`` in Phase 2.
        """
        await self._mint_run_token(repo=repo, run_id=run_id)
        source = ExecutionSource(
            type=ExecutionSourceType.REMOTE,
            repo=repo,
            branch=branch,
        )
        return await self._runtime.start(
            component=component,
            source=source,
            feature_name=feature_name,
            variables=variables,
            agent=agent,
            model=model,
            max_turns=max_turns,
            timeout_minutes=timeout_minutes,
            max_budget_usd=max_budget_usd,
            memory=memory,
            on_pause=on_pause,
            context_paths=context_paths,
            start_task=start_task,
            keep_alive=keep_alive,
        )

    async def _mint_run_token(self, *, repo: str, run_id: str | None) -> None:
        """Mint a repo-scoped run token + authorize the push (INV-4 / AC-12 / §8.6).

        The production call site for the ``token_mint`` + ``token_use`` audit kinds:
        mints a repo-scoped, ≤1 hr token for ``repo`` (persisting only ciphertext —
        the plaintext is never logged, INV-4) and immediately authorizes the push to
        the SAME repo, passing the lifespan audit sink so both the mint fact (scope +
        TTL) and the use decision (allowed/denied) land on the durable trail. **No
        raw token value** is ever recorded — the minter/authorizer pass only
        scope/metadata. A no-op when no minter is bound (a bare/test service, or no
        operator GITHUB_TOKEN). Best-effort: a scope error is defensive-only here (we
        just minted a token scoped to ``repo``) and is swallowed-and-logged so it
        never aborts a launch on the evidence path."""
        if self._minter is None:
            return
        correlation = run_id or ""
        token = await self._minter.mint(repo, run_id=correlation, audit=self._audit)
        try:
            token.authorize_push(repo, audit=self._audit, run_id=correlation)
        except TokenScopeError:  # pragma: no cover - defensive: just-minted token is in-scope
            _log.warning("run-token push authorization unexpectedly out of scope for run")
