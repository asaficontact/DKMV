"""The ``POST /runs`` launch contract — validate → claim-lock → engine start.

This is the load-bearing launch path (PRD §8.4, §8.10, §8.11). It is the single
place a `POST /runs` body becomes a claimed `runs` row and a started engine run,
and it upholds the phase's binding invariants:

* **§8.10 validation (binding).** ``branch`` matches ``^[\\w./-]{1,200}$`` (no
  ``..``, no leading ``-``); ``feature_name`` is slugified (``[a-z0-9-]``, ≤30);
  ``repo`` is the connected project's; ``workflow_id`` resolves via the engine's
  ``validate_component``; ``agent``/``model`` via ``validate_agent_model``;
  ``timeout_minutes``/``memory`` within bounds; ``context`` paths exist inside the
  project. Each failure raises ``400 validation_error`` with field details.
* **Capability-aware rejection (INV-8, binding).** ``max_budget_usd`` /
  ``max_turns`` are **rejected ``400 unsupported_for_agent``** when the *resolved*
  agent's ``supports_budget()`` / ``supports_max_turns()`` is false (Codex) —
  branched on the adapter capability, never silently ignored. The UI hides those
  fields for Codex; the API still enforces.
* **Agent resolution (FR-03-3).** ``resolvedAgent = agent == "auto" ?
  workflow.agent : agent``; the idempotency key is ``issue_num + workflow_id +
  base_branch`` (NOT a hash of the mutable issue body, §8.2) so an issue edit can
  never fork the claim.
* **Claim-lock (INV-5, binding).** The run row is inserted via the Phase-0
  :meth:`Repository.claim_run` helper — ``INSERT … ON CONFLICT(idempotency_key)
  DO NOTHING`` inside ``BEGIN IMMEDIATE`` — and the launch proceeds only if *this*
  call won the row; a duplicate dispatch raises ``409 duplicate_dispatch``. The
  claim is a UNIQUE-key atomic insert (SQLite has no row-locking skip construct).
* **Engine start + platform UUID (§8.4).** Builds ``ExecutionSource(type=remote,
  repo, branch)`` (inside :class:`~app.runtime.RunService`) and calls
  ``EmbeddedRuntime.start(..., on_pause=bridge)``; returns the **platform UUID**.
  The engine ``YYMMDD-HHMM-…`` id is not available synchronously — it back-fills
  as ``engine_run_id`` via the event stream, so all run endpoints address the
  platform UUID.
* **Label transition (INV-11).** On a successful start the issue moves to
  ``agent:in-progress`` via ``set_agent_state`` on the serialized write-queue.

The ``on_pause`` bridge is owned by slice 2.5; in 2.1 it is wired through as a
thin **pass-through placeholder** (:func:`_passthrough_on_pause`) that 2.5
replaces. Nothing here edits ``dkmv/``; the only engine touch is through the
in-process :class:`~app.runtime.RunService` (INV-13).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.api.errors import ApiError, validation_error
from app.api.validation import (
    GuardrailRequest,
    agent_is_known,
    validate_agent_capabilities,
)
from app.api.validation import unsupported_for_agent as _unsupported_for_agent
from app.db.repository import Repository
from app.orchestrator.enforcement import resolve_enforced_caps

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.github.client import GitHubClient
    from app.github.graphql import BoardPage
    from app.github.hash_cache import HashCache
    from app.github.write_queue import WriteQueue
    from app.runtime import RunService

#: ``branch`` validation regex (§8.10): 1–200 chars from ``[\w./-]``. The ``..``
#: traversal and leading-``-`` checks are applied separately (a regex alone can
#: still admit ``..``).
_BRANCH_RE = re.compile(r"^[\w./-]{1,200}$")

#: ``feature_name`` is slugified to ``[a-z0-9-]`` (≤30) before it flows into the
#: run-id / git identity (§8.10).
_FEATURE_RE = re.compile(r"^[a-z0-9-]{1,30}$")

#: Default agent when the workflow declares none and the model implies none
#: (the engine's own default is Claude — §6.1). Used only for the ``auto``
#: resolution fallback so the capability branch always has a concrete agent.
_DEFAULT_AGENT = "claude"

#: Memory-limit bound shape: a positive integer + ``g``/``m`` suffix (e.g. ``8g``).
_MEMORY_RE = re.compile(r"^[1-9][0-9]*[gm]$", re.IGNORECASE)

#: Inclusive ``timeout_minutes`` bounds (§8.10 "within configured bounds").
_TIMEOUT_MIN = 1
_TIMEOUT_MAX = 24 * 60


def unsupported_for_agent(field_name: str, agent: str) -> ApiError:
    """400 — a guardrail field is unsupported by the resolved agent (INV-8).

    Thin re-export of :func:`app.api.validation.unsupported_for_agent` (the §8.10
    ``unsupported_for_agent`` contract now lives in the shared validation module);
    kept here so existing callers/tests that import it from ``app.runs.launch``
    keep working. The single source of the error shape is the validation module.
    """
    return _unsupported_for_agent(field_name, agent)


def duplicate_dispatch(run_id: str) -> ApiError:
    """409 — the idempotency key already has an active run (§8.2 / §8.9).

    Returned when the claim-lock insert lost the race (the row already existed):
    the duplicate dispatch is rejected and the existing run's id is surfaced so
    the client can navigate to the live run rather than launching a second one.
    """
    return ApiError(
        409,
        "duplicate_dispatch",
        "A run for this issue/workflow/branch already exists.",
        details={"run_id": run_id},
    )


@dataclass(slots=True)
class LaunchRequest:
    """The validated, normalized ``POST /runs`` body (§8.4).

    Field names mirror the PRD body. ``context`` is the list of extra-context file
    paths (relative to the project), validated to exist and be project-internal.
    """

    issue_num: int
    repo: str
    workflow_id: str
    agent: str
    branch: str
    feature_name: str
    model: str | None = None
    max_turns: int | None = None
    timeout_minutes: int | None = None
    max_budget_usd: float | None = None
    memory: str | None = None
    context: list[str] = field(default_factory=list)
    keep_alive: bool = False
    start_task: str | None = None


@dataclass(slots=True)
class LaunchResult:
    """Outcome of a successful launch: the platform UUID + resolved identity.

    ``run_id`` is the **platform UUID** (§8.4) the client addresses every run
    endpoint by; ``engine_run_id`` is ``None`` at return time and back-fills via
    the event stream. ``resolved_agent`` / ``resolved_model`` are what the engine
    was actually started with (after ``auto`` resolution + model substitution).
    """

    run_id: str
    resolved_agent: str
    resolved_model: str | None


async def _passthrough_on_pause(request: Any) -> Any:
    """Thin pass-through ``on_pause`` placeholder (slice 2.5 owns the real bridge).

    Slice 2.5 replaces this with the durable HITL bridge (write ``pause_decisions``,
    set ``agent:paused``, release the slot, emit ``pause_requested``, await the
    keyed event). In 2.1 it is a no-op identity so the ``EmbeddedRuntime.start``
    call already carries the ``on_pause=`` wiring 2.5 plugs into — a workflow that
    pauses simply receives an empty response (skip). **TODO(2.5):** swap for the
    real pause bridge. Marked clearly so the wiring is not mistaken for the final
    HITL behavior.
    """
    # Return whatever PauseResponse-shaped no-op the engine accepts; the engine's
    # default (None → skip) is honored when on_pause is absent, so this mirrors it.
    return None


def _resolve_workflow_agent(workflow_id: str, project_root: Path | None = None) -> str:
    """Resolve a workflow's declared agent for the ``auto`` path (FR-03-3).

    Reads the engine's :func:`dkmv.runtime.inspect_component` to learn the
    workflow's declared ``agent`` (or its model's implied agent), falling back to
    the platform default Claude when the workflow pins neither — so ``auto`` always
    resolves to a concrete agent the capability branch can reason about. Engine
    import is in-process (INV-13); never the CLI.

    ``project_root`` is threaded so a registry-NAME ``workflow_id`` (a custom
    component registered on disk, not a built-in or absolute path) resolves to read
    its declared agent — without it ``auto`` on a custom component would silently
    fall back to the default rather than the workflow's pinned agent (FIX-3).
    """
    from dkmv.adapters import infer_agent_from_model
    from dkmv.runtime import inspect_component

    try:
        info = inspect_component(workflow_id, project_root)
    except Exception:  # noqa: BLE001 - resolution failure already surfaced by validate_component
        return _DEFAULT_AGENT
    if info.agent:
        return str(info.agent)
    if info.model:
        inferred = infer_agent_from_model(info.model)
        if inferred:
            return str(inferred)
    return _DEFAULT_AGENT


def resolve_agent(agent: str, workflow_id: str, project_root: Path | None = None) -> str:
    """``resolvedAgent = agent == "auto" ? workflow.agent : agent`` (FR-03-3)."""
    if agent.strip().lower() == "auto":
        return _resolve_workflow_agent(workflow_id, project_root)
    return agent.strip().lower()


def _validate_branch(branch: str) -> str:
    """Validate + return the branch name (§8.10).

    Enforces ``^[\\w./-]{1,200}$`` AND rejects ``..`` traversal and a leading
    ``-`` (which the character class alone would admit). A leading ``-`` is
    rejected because it would be parsed as a git flag downstream.
    """
    value = branch.strip()
    if not _BRANCH_RE.match(value):
        raise validation_error(
            "branch must match ^[\\w./-]{1,200}$",
            details={"field": "branch"},
        )
    if ".." in value:
        raise validation_error("branch must not contain '..'", details={"field": "branch"})
    if value.startswith("-"):
        raise validation_error("branch must not start with '-'", details={"field": "branch"})
    return value


def _validate_feature_name(feature_name: str) -> str:
    """Validate the slugified ``feature_name`` (``[a-z0-9-]``, ≤30) (§8.10)."""
    value = feature_name.strip()
    if not _FEATURE_RE.match(value):
        raise validation_error(
            "feature_name must be slugified ([a-z0-9-], ≤30 chars)",
            details={"field": "feature_name"},
        )
    return value


def _validate_repo(repo: str, *, connected_repo: str) -> str:
    """Reject a ``repo`` that is not the connected project's (§8.10)."""
    value = repo.strip()
    if connected_repo and value.lower() != connected_repo.strip().lower():
        raise validation_error(
            "repo must be the connected project's repository",
            details={"field": "repo", "connected": connected_repo},
        )
    return value


def _validate_workflow(workflow_id: str, project_root: Path | None = None) -> str:
    """Reject a ``workflow_id`` that does not resolve via ``validate_component`` (§8.10).

    ``project_root`` is threaded so a registry-NAME ``workflow_id`` (a custom
    component registered on disk via the engine's ``ComponentRegistry``) resolves
    and validates — the engine's ``resolve_component(name, project_root)`` consults
    the project's ``.dkmv/components.json`` registry. Without it only built-ins and
    absolute-path ids resolve, so a registry-name run would 400 (FIX-3). Built-in /
    absolute-path resolution is unchanged when ``project_root`` is ``None``.
    """
    from dkmv.runtime import validate_component

    value = workflow_id.strip()
    if not value:
        raise validation_error("workflow_id is required", details={"field": "workflow_id"})
    result = validate_component(value, project_root)
    if not result.valid:
        raise validation_error(
            f"workflow_id '{value}' is not a valid workflow",
            details={"field": "workflow_id", "errors": list(result.errors)},
        )
    return value


def _validate_agent_model(agent: str, model: str | None) -> str | None:
    """Resolve/validate ``(agent, model)`` via the engine's ``validate_agent_model``.

    Returns the resolved model (auto-substituted to the agent default when the
    given model is incompatible-from-defaults; raised as a 400 when an *explicit*
    incompatible pair is supplied — §8.10). ``model=None`` means "use the agent
    default", so no validation is forced.
    """
    from dkmv.adapters import get_adapter, validate_agent_model

    if model is None:
        return None
    try:
        resolved = validate_agent_model(
            agent,
            model,
            agent_explicit=True,
            model_explicit=True,
        )
        return str(resolved)
    except ValueError as exc:
        compatible = get_adapter(agent).default_model if _agent_known(agent) else None
        raise validation_error(
            str(exc),
            details={"field": "model", "agent": agent, "suggested": compatible},
        ) from exc


def _agent_known(agent: str) -> bool:
    """True iff ``agent`` is a registered adapter name (else a 400 is raised).

    Delegates to :func:`app.api.validation.agent_is_known` (shared §8.10 source).
    """
    return agent_is_known(agent)


def _validate_capabilities(agent: str, req: LaunchRequest) -> None:
    """Reject budget/turn guardrails the **resolved** agent cannot honor (INV-8).

    Delegates to the shared :func:`app.api.validation.validate_agent_capabilities`
    — the single §8.10 capability gate that branches on the adapter's
    ``supports_budget()`` / ``supports_max_turns()``: for Codex (both false) a
    supplied ``max_budget_usd`` / ``max_turns`` is a ``400 unsupported_for_agent``
    (never silently ignored), because the engine has no such cap and a false
    hard-cap promise would let a Codex run run away. An unknown agent is a 400.
    """
    validate_agent_capabilities(
        agent,
        GuardrailRequest(max_budget_usd=req.max_budget_usd, max_turns=req.max_turns),
    )


def _validate_numeric_guardrails(req: LaunchRequest) -> None:
    """Validate positivity + bounds for budget/turns/timeout/memory (§8.10)."""
    if req.max_budget_usd is not None and req.max_budget_usd <= 0:
        raise validation_error(
            "max_budget_usd must be positive", details={"field": "max_budget_usd"}
        )
    if req.max_turns is not None and req.max_turns <= 0:
        raise validation_error("max_turns must be positive", details={"field": "max_turns"})
    if req.timeout_minutes is not None and not (
        _TIMEOUT_MIN <= req.timeout_minutes <= _TIMEOUT_MAX
    ):
        raise validation_error(
            f"timeout_minutes must be within [{_TIMEOUT_MIN}, {_TIMEOUT_MAX}]",
            details={"field": "timeout_minutes"},
        )
    if req.memory is not None and not _MEMORY_RE.match(req.memory.strip()):
        raise validation_error(
            "memory must look like '8g' or '512m'",
            details={"field": "memory"},
        )


def _validate_context_paths(context: list[str], *, project_root: Path | None) -> list[Path]:
    """Validate that each context path is **inside** the project (§8.10).

    A traversal-resistant check: each path is resolved against the project root and
    must stay within it (no ``..``/absolute escape) — an attacker-influenced
    context path must never read outside the project tree. When ``project_root`` is
    provided (a local checkout) the path is also **existence-checked**; for a remote
    run (no host checkout) the path is repo-relative, so only the traversal guard
    applies. An empty entry / escaping path / missing local path is a
    ``400 validation_error``.
    """
    resolved: list[Path] = []
    root = project_root.resolve() if project_root is not None else None
    for raw in context:
        if not raw or not raw.strip():
            raise validation_error("context path must not be empty", details={"field": "context"})
        # Reject absolute paths and ``..`` traversal regardless of a local root.
        candidate_rel = Path(raw)
        if candidate_rel.is_absolute() or ".." in candidate_rel.parts:
            raise validation_error(
                f"context path '{raw}' escapes the project",
                details={"field": "context", "path": raw},
            )
        if root is None:
            resolved.append(candidate_rel)
            continue
        candidate = (root / raw).resolve()
        if not candidate.is_relative_to(root):
            raise validation_error(
                f"context path '{raw}' escapes the project",
                details={"field": "context", "path": raw},
            )
        if not candidate.exists():
            raise validation_error(
                f"context path '{raw}' does not exist",
                details={"field": "context", "path": raw},
            )
        resolved.append(candidate)
    return resolved


def idempotency_key(issue_num: int, workflow_id: str, base_branch: str) -> str:
    """``idempotency_key = issue_num + workflow_id + base_branch`` (§8.2).

    NOT a hash of the mutable issue body (an edit must not fork the claim); a
    deterministic composite so a retry reuses the same run row rather than
    colliding.
    """
    return f"{issue_num}::{workflow_id}::{base_branch}"


async def launch_run(
    req: LaunchRequest,
    *,
    repository: Repository,
    run_service: RunService,
    github_client: GitHubClient,
    write_queue: WriteQueue,
    cache: HashCache[BoardPage] | None,
    connected_repo: str,
    project_root: Path | None = None,
    default_memory: str,
    current_labels: list[str],
    on_pause: Callable[[Any], Awaitable[Any]] | None = None,
    build_on_pause: Callable[[str], Callable[[Any], Awaitable[Any]]] | None = None,
    attach_stream: Callable[[str, Any], None] | None = None,
) -> LaunchResult:
    """Validate → resolve → claim-lock → start → move-label (the §8.11 launch flow).

    The single launch path (PRD §8.4, §8.10, §8.11). It validates the body
    (§8.10), resolves the agent (``auto → workflow.agent``), **rejects** Codex
    budget/turn guardrails (INV-8), claims the run row via the INV-5
    ``ON CONFLICT DO NOTHING`` helper (``409 duplicate_dispatch`` on a lost race),
    starts the engine through :class:`~app.runtime.RunService` (with the slice-2.5
    ``on_pause`` bridge, built per-run via ``build_on_pause(run_id)`` once the
    claimed UUID exists), **wires the run into the live SSE stream** via the
    ``attach_stream`` hook (registers the
    platform observer on the ``RunHandle`` + spawns the per-run pump/supervisor —
    F8/§8.3), and moves the issue to ``agent:in-progress`` via ``set_agent_state``
    on the write-queue (INV-11). Returns the **platform UUID**.
    """
    from app.github.state_machine import set_agent_state

    # ── §8.10 validation (order: cheap structural → engine resolution) ─────────
    repo = _validate_repo(req.repo, connected_repo=connected_repo)
    branch = _validate_branch(req.branch)
    feature_name = _validate_feature_name(req.feature_name)
    workflow_id = _validate_workflow(req.workflow_id, project_root)
    context_paths = _validate_context_paths(req.context, project_root=project_root)

    # ── agent resolution (auto → workflow.agent) + capability + model validation ─
    resolved_agent = resolve_agent(req.agent, workflow_id, project_root)
    _validate_numeric_guardrails(req)
    _validate_capabilities(resolved_agent, req)  # INV-8: Codex budget/turns → 400
    resolved_model = _validate_agent_model(resolved_agent, req.model)

    # ── capability-aware cap resolution (INV-8 / ADR-P009, 5.2) ────────────────
    # Branch on the resolved agent's adapter capability to decide which caps are
    # actually enforced + the effective timeout. For Codex (timeout-only) the
    # budget/turn caps resolve to None (already rejected above by INV-8) and the
    # timeout defaults to the *strictly tighter* Codex default — timeout is its
    # sole runtime guardrail (§7.2 fn3). For Claude they are hard caps and the
    # timeout defaults to the Claude default when unset. The persisted +
    # engine-started values are these resolved caps so GET /runs/{id}'s §8.9
    # config block is truthful (FR-04-5) and the engine is bounded correctly.
    caps = resolve_enforced_caps(
        agent=resolved_agent,
        max_budget_usd=req.max_budget_usd,
        max_turns=req.max_turns,
        timeout_minutes=req.timeout_minutes,
    )

    # ── G1 fail-closed isolation gate (INV-3) ──────────────────────────────────
    # The single chokepoint for EVERY launch (route + orchestrator/retry redispatch
    # both reach here): if SANDBOX_RUNTIME=runsc but gVisor is not registered with
    # the daemon and the operator hasn't opted into the weaker fallback, refuse to
    # dispatch (503 sandbox_isolation_unavailable) BEFORE claiming the run row — a run
    # must never start under bare runc when gVisor was required. Placed after the
    # cheap §8.10 validation so a malformed body still gets its 400, but before the
    # claim-lock so a blocked run never claims a row it cannot start.
    run_service.enforce_sandbox_isolation()

    # ── claim-lock (INV-5): INSERT … ON CONFLICT DO NOTHING under BEGIN IMMEDIATE ─
    # memory_limit is the resolved value the engine is started with (req.memory or
    # the configured default).
    resolved_memory = req.memory or default_memory
    key = idempotency_key(req.issue_num, workflow_id, branch)
    run_id, won = await repository.claim_run(
        idempotency_key=key,
        repo=repo,
        issue_num=req.issue_num,
        workflow_id=workflow_id,
        agent=resolved_agent,
        model=resolved_model,
        branch=branch,
        feature_name=feature_name,
        max_turns=caps.max_turns,
        timeout_minutes=caps.timeout_minutes,
        max_budget_usd=caps.max_budget_usd,
        memory_limit=resolved_memory,
    )
    if not won:
        # Lost the race / a duplicate dispatch — the row already exists. Reject
        # with 409 and surface the existing run's id (do NOT launch a second run).
        raise duplicate_dispatch(run_id)

    # ── engine start (returns a RunHandle; the platform UUID is the address) ────
    # The real HITL ``on_pause`` bridge (slice 2.5) is built per-run via
    # ``build_on_pause(run_id)`` now that the claimed platform UUID exists — it
    # writes ``pause_decisions``, sets ``agent:paused``, releases the slot, emits
    # ``pause_requested``, and awaits the keyed event (INV-9 / §8.5). A direct
    # ``on_pause`` (a test injecting a callback) takes precedence; absent both, the
    # engine-default no-op pass-through is wired so ``start`` always carries the
    # ``on_pause=`` seam.
    if on_pause is not None:
        pause_bridge: Callable[[Any], Awaitable[Any]] = on_pause
    elif build_on_pause is not None:
        pause_bridge = build_on_pause(run_id)
    else:
        pause_bridge = _passthrough_on_pause
    # ``run_id`` is the claimed platform UUID — thread it into ``start`` so the §8.6
    # ``token_grant`` audit line (the real "platform granted run X access to repo Y"
    # decision, recorded as the credential is provisioned into RuntimeConfig) is
    # correlated to this run (AC-12 / INV-4; never the raw PAT). ADR-P004: fine-grained
    # per-run mint + in-container push-use telemetry are the deferred GitHub-App model.
    handle = await run_service.start(
        component=workflow_id,
        repo=repo,
        branch=branch,
        feature_name=feature_name,
        agent=resolved_agent,
        model=resolved_model,
        max_turns=caps.max_turns,
        timeout_minutes=caps.timeout_minutes,
        max_budget_usd=caps.max_budget_usd,
        memory=resolved_memory,
        context_paths=context_paths or None,
        start_task=req.start_task,
        on_pause=pause_bridge,
        keep_alive=req.keep_alive,
        run_id=run_id,
    )

    # ── wire the run into the live stream (F8 — the SSE backbone, §8.3) ─────────
    # The engine returned the RunHandle BEFORE its run coroutine had a chance to
    # emit (it was just create_task-d), so registering the platform observer +
    # pump here — synchronously, before any await below — never races the first
    # event (INV-12). ``attach_stream`` (provided by the route, bound to
    # app.state.stream_registry) registers ``hub.observer()`` on the handle and
    # spawns the per-run pump + completion supervisor; without it a launched run
    # would never persist events or fan out (the dead-code gap this closes).
    if attach_stream is not None:
        attach_stream(run_id, handle)

    # ── move the issue to agent:in-progress (INV-11, write-queue) ──────────────
    await set_agent_state(
        github_client,
        repo,
        req.issue_num,
        "in-progress",
        current_labels=current_labels,
        write_queue=write_queue,
        cache=cache,
    )

    return LaunchResult(
        run_id=run_id,
        resolved_agent=resolved_agent,
        resolved_model=resolved_model,
    )
