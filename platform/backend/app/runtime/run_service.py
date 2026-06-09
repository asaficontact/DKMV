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

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dkmv.runtime import EmbeddedRuntime, ExecutionSource, ExecutionSourceType, RuntimeConfig

from app.config import Settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dkmv.runtime import CapabilityReport
    from dkmv.runtime._handle import RunHandle

    from app.secrets.store import SecretStore
    from app.security.audit import AuditLog

#: The operator PAT's repo scope label recorded on the ``token_grant`` audit line
#: (the credential threaded into ``RuntimeConfig`` is repo-scopeable; the scope
#: metadata is honest about what the grant authorizes — never the token value).
_OPERATOR_PAT_SCOPE = "repo"


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
        # The §8.6 credential-grant audit deps (INV-4 / AC-12). Bound by the app
        # lifespan AFTER it composes the durable audit sink (``bind_run_token_minting``),
        # because ``RunService`` is constructed at app-creation time — before that
        # singleton exists. Absent the binding (a bare test service), or when no
        # operator GITHUB_TOKEN is configured, the grant audit is a graceful no-op and
        # the engine still runs with its existing RuntimeConfig.
        self._audit: AuditLog | None = None
        self._github_configured: bool = False
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
        """Wire the durable §8.6 audit sink for the credential-grant trail (lifespan).

        Called once by ``app.main._lifespan`` after it composes the durable §8.6 audit
        log, so the launch path's :meth:`start` records the **real** ``token_grant``
        evidence line in production (AC-12) — the honest "platform granted run X access
        to repo Y" decision — not just in tests.

        **Honest v1 credential model (ADR-P004).** v1 threads the operator's
        fine-grained PAT into the engine's ``RuntimeConfig`` (see
        :func:`build_runtime_config`); the engine clones/pushes **inside the gVisor
        container** with that PAT, so a true per-run *mint* and the in-container *use*
        are not observable in platform Python. Fine-grained per-run token *minting* (the
        GitHub-App installation-token model) + in-container push-*use* telemetry are
        **deferred post-v1**; v1 audits the operator-PAT provisioning grant. The
        :class:`~app.secrets.github_token.GitHubTokenMinter` / ``authorize_push``
        machinery is retained as the seam the App model will plug into — it is **not**
        invoked to fabricate a mint-for-audit here.

        ``secret_store`` is accepted for binding-signature stability (the lifespan +
        the deferred App seam supply it); v1's grant audit does not mint into it. When
        the operator PAT is empty (no GitHub configured) the grant audit is skipped.
        """
        del secret_store  # v1 grant audit does not mint a per-run secret (ADR-P004).
        self._audit = audit
        self._github_configured = bool(self._settings.GITHUB_TOKEN.get_secret_value())

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

        Before the engine starts, the platform records the **real** ``token_grant``
        §8.6 evidence line (AC-12) when the audit sink is bound (lifespan, see
        :meth:`bind_run_token_minting`) and an operator GitHub PAT is configured: the
        honest "platform granted run ``run_id`` access to ``repo``" decision — the run's
        credential is provisioned into the engine ``RuntimeConfig``
        (:func:`build_runtime_config`). ``run_id`` is the platform UUID used to
        correlate that grant line; absent it (an unbound/test service, or a ``None``
        run_id) the grant is skipped and the engine still starts normally. **No raw
        token value** is ever recorded (INV-4). Fine-grained per-run *minting* + the
        in-container push *use* are the deferred GitHub-App model (ADR-P004, post-v1).

        This is the M0 bridge; it adds no DB write or admission control — those
        belong to ``POST /runs`` in Phase 2.
        """
        self._audit_token_grant(repo=repo, run_id=run_id)
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

    def _audit_token_grant(self, *, repo: str, run_id: str | None) -> None:
        """Record the **real** ``token_grant`` §8.6 evidence line (INV-4 / AC-12).

        The honest, platform-observable GitHub-credential security decision in v1: the
        platform granted run ``run_id`` access to ``repo`` by provisioning the operator
        PAT into the engine ``RuntimeConfig`` (:func:`build_runtime_config`). Records
        the run, the repo, and the credential's repo ``scope`` — **never the token
        value** (INV-4; the audit redactor is a backstop over the whole record). A
        graceful no-op when no audit sink is bound (a bare/test service), no operator
        GITHUB_TOKEN is configured (nothing was granted), or ``run_id`` is absent (so
        the grant line is always correlated to a real run UUID).

        **Deferral (ADR-P004, post-v1).** Fine-grained per-run token *minting* (the
        GitHub-App installation-token model) and in-container push-*use* telemetry are
        not platform-observable in v1 (the engine pushes inside the gVisor container
        with the threaded PAT), so they are deferred — like the egress-denial proxy
        hook. v1 audits this provisioning grant; the
        :class:`~app.secrets.github_token.GitHubTokenMinter` machinery is the retained
        seam for the App model and is NOT invoked here to fabricate a mint.
        """
        if self._audit is None or not self._github_configured or not run_id:
            return
        self._audit.record_token_grant(repo=repo, run_id=run_id, scope=_OPERATOR_PAT_SCOPE)
