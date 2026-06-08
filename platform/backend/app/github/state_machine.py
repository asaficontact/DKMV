"""The ``agent:*`` label state machine: ``set_agent_state`` + completeness (§8.1).

This is the **write** half of the GitHub control plane (the read/derivation half
is :mod:`app.github.sync`, slice 1.2 — reused here, never forked). It owns:

* :func:`set_agent_state` — the single primitive **all** ``agent:*`` transitions
  go through (INV-11). It computes the issue's **full desired label set**
  (non-agent labels preserved + **at most one** ``agent:*`` label) and performs the
  write via GitHub's **``PUT /repos/{o}/{r}/issues/{num}/labels``** replace-all
  (``client.replace_labels``), **routed through the serialized write-queue**
  (§8.1). The replace-all ``PUT`` is idempotent and guarantees the
  **single-occupancy** invariant — there is no add/remove race and **the fictional
  single-label PATCH endpoint is never constructed** (INV-11). After a successful write the
  GraphQL hash-cache is **invalidated** so the next board read reflects the change.

* **State-machine completeness** (§8.1, binding) as pure decision functions over a
  cached issue + its active run, each independently unit-tested:
  - :func:`merged_pr_transition` — In Review → Done on a linked **merged** PR
    (linkage via ``runs.pr_num`` / "Closes #N"): strip ``agent:review``.
  - :func:`closed_transition` — ``issues.closed`` → Done (and a **cancel-live-run**
    hook that is a **no-op stub in Phase 1** — runs don't exist yet — but the
    demotion/label logic is built + tested).
  - :func:`reopened_transition` — ``issues.reopened`` → out of Done (restore the
    prior ``agent:*`` label, else Backlog).
  - :func:`failed_run_demotion` — demote off ``agent:in-progress`` on a failed run
    (→ ``agent:queued`` if it will auto-retry, else strip to Backlog) so the board
    never strands a failed issue in **In Progress**.

The **authority rule** (active-run DB row > label) lives in
:func:`app.github.sync.derive_state` and is *reused* here for completeness
decisions — this module extends, never forks, the 1.2 derivation/precedence
tables. Nothing here edits ``dkmv/``; the only GitHub mutation is the replace-all
``PUT`` behind the write-queue.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.github.labels import AGENT_LABEL_NAMES
from app.github.sync import _LABEL_PRECEDENCE, ActiveRun

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.github.client import GitHubClient
    from app.github.graphql import BoardPage
    from app.github.hash_cache import HashCache
    from app.github.write_queue import WriteQueue

#: The valid ``set_agent_state`` targets: the four control-plane states, by their
#: bare suffix, plus ``None`` (meaning "clear the ``agent:*`` label" → Backlog).
#: The ``POST /issues/{num}/agent-state`` body uses the suffix form ``queued`` /
#: ``none`` for the Backlog↔Queued drag (§8.1 endpoints).
AGENT_STATE_TARGETS: frozenset[str] = frozenset({"queued", "in-progress", "paused", "review"})

#: Map a target suffix (``"queued"``) to its full label name (``"agent:queued"``).
_TARGET_TO_LABEL: dict[str, str] = {suffix: f"agent:{suffix}" for suffix in AGENT_STATE_TARGETS}


def _agent_label_for(target: str | None) -> str | None:
    """Resolve a ``set_agent_state`` target to its ``agent:*`` label, or ``None``.

    ``None`` / ``"none"`` clears the label (Backlog). A bare suffix
    (``"queued"``) or a full label (``"agent:queued"``) both resolve to the full
    label name. An unknown target raises :class:`ValueError` so a typo never
    silently writes an empty/garbage state.
    """
    if target is None:
        return None
    normalized = target.strip().lower()
    if normalized in {"", "none", "backlog"}:
        return None
    if normalized.startswith("agent:"):
        suffix = normalized.split(":", 1)[1]
    else:
        suffix = normalized
    if suffix not in AGENT_STATE_TARGETS:
        raise ValueError(f"unknown agent state target {target!r}")
    return _TARGET_TO_LABEL[suffix]


def compute_desired_labels(current: Sequence[str], target: str | None) -> list[str]:
    """Compute the full replace-all label set for a transition (single-occupancy).

    Strips **every** ``agent:*`` label from ``current`` (preserving order of the
    non-agent labels), then appends the single ``agent:*`` label for ``target``
    (none for Backlog). The result is the *complete* desired label set handed to
    GitHub's replace-all ``PUT`` — so the write is idempotent and **at most one**
    ``agent:*`` label can ever remain (INV-11). Non-agent labels are preserved.
    """
    desired = [label for label in current if label not in AGENT_LABEL_NAMES]
    wanted = _agent_label_for(target)
    if wanted is not None:
        desired.append(wanted)
    return desired


@dataclass(frozen=True, slots=True)
class SetAgentStateResult:
    """Outcome of one :func:`set_agent_state` write.

    ``labels`` is the issue's label set after the replace-all ``PUT`` (echoed from
    GitHub). ``agent_label`` is the single surviving ``agent:*`` label (or ``None``
    for Backlog) — the single-occupancy assertion the board relies on.
    """

    repo: str
    num: int
    labels: tuple[str, ...]
    agent_label: str | None

    @property
    def agent_labels(self) -> tuple[str, ...]:
        """All ``agent:*`` labels remaining (must be 0 or 1 — single-occupancy)."""
        return tuple(name for name in self.labels if name in AGENT_LABEL_NAMES)


async def set_agent_state(
    client: GitHubClient,
    repo: str,
    num: int,
    target: str | None,
    *,
    current_labels: Sequence[str],
    write_queue: WriteQueue,
    cache: HashCache[BoardPage] | None = None,
) -> SetAgentStateResult:
    """Transition an issue's ``agent:*`` state via replace-all ``PUT`` (§8.1, INV-11).

    The single primitive **all** ``agent:*`` transitions go through. It:

    1. Computes the **full desired label set** (:func:`compute_desired_labels`):
       non-agent labels preserved + at most one ``agent:*`` label for ``target``
       (``None`` → Backlog).
    2. Performs the write via ``client.replace_labels`` (GitHub's
       **``PUT .../labels``** replace-all), **submitted to the serialized
       write-queue** so it is paced + serialized with every other mutating call
       (§8.1) — and a 403-secondary ``Retry-After`` is honored, not hammered.
    3. **Invalidates** the GraphQL hash-cache for the repo (if supplied) so the
       next board read reflects the change rather than serving a pre-write page.

    The replace-all ``PUT`` makes this idempotent and guarantees single-occupancy
    (INV-11); **no single-label PATCH endpoint is constructed**. Returns the post-write
    label set + the surviving ``agent:*`` label.
    """
    desired = compute_desired_labels(current_labels, target)

    async def _do_write() -> list[str]:
        return await client.replace_labels(repo, num, desired)

    written = await write_queue.submit(_do_write, label=f"set_agent_state:{repo}#{num}")

    if cache is not None:
        _invalidate_board_cache(cache, repo)

    agent_label = _agent_label_for(target)
    return SetAgentStateResult(
        repo=repo,
        num=num,
        labels=tuple(written),
        agent_label=agent_label,
    )


def _invalidate_board_cache(cache: HashCache[BoardPage], repo: str) -> None:
    """Drop the cached board read for ``repo`` after a mutation (§8.1).

    The board read (:func:`app.github.graphql.read_board`) keys the hash-cache by
    the GraphQL ``(query, variables)`` for the repo (``owner``/``name`` plus
    cursors). A label write must not be hidden behind a stale cached page, so we
    clear the cache here; the next read re-fetches the fresh board. Clearing the
    whole cache is conservative but correct (one event loop, small working set) and
    avoids having to reconstruct every cursor-keyed variant the read may have put.
    """
    cache.clear()


# ── State-machine completeness (§8.1, binding) — pure decision functions ───────


@dataclass(frozen=True, slots=True)
class TransitionPlan:
    """A planned ``agent:*`` transition: the target + whether a write is needed.

    ``target`` is the ``set_agent_state`` target (a suffix like ``"queued"``,
    ``"review"``, or ``None`` for Backlog). ``should_write`` is ``False`` when the
    issue is already in the desired state (a no-op — the replace-all ``PUT`` would
    be idempotent anyway, but skipping it spends no write-queue/secondary-limit
    budget). ``cancel_live_run`` flags the closed→Done case where any live run on
    the issue must be cancelled (a **no-op stub in Phase 1** — runs don't exist
    yet — surfaced so the caller/Phase-3 reconcile can act on it).
    """

    target: str | None
    should_write: bool
    cancel_live_run: bool = False
    reason: str = ""


def _current_agent_target(labels: Sequence[str]) -> str | None:
    """The issue's current ``agent:*`` target suffix (precedence-resolved), or None.

    Reuses 1.2's precedence (``in-progress > paused > review > queued``) via the
    imported :data:`app.github.sync._LABEL_PRECEDENCE` ordering so completeness
    decisions and board derivation never disagree. Returns the bare suffix
    (``"queued"``) or ``None`` when no ``agent:*`` label is present (Backlog).
    """
    present = [name for name in labels if name in AGENT_LABEL_NAMES]
    if not present:
        return None
    # Single-source the precedence ordering from sync (extend, don't fork) so a
    # future edit to one table can't silently diverge board derivation (sync) from
    # completeness decisions (state_machine) — INV-11 / §8.1.
    for label in _LABEL_PRECEDENCE:
        if label in present:
            return label.split(":", 1)[1]
    return None  # pragma: no cover - present ⊆ the precedence set


def merged_pr_transition(
    *, current_labels: Sequence[str], merged_pr_num: int | None
) -> TransitionPlan:
    """In Review → Done on a linked **merged** PR: strip ``agent:review`` (§8.1).

    Linkage is the merged-PR number surfaced by the board read (``runs.pr_num`` /
    "Closes #N" — :attr:`BoardIssue.merged_pr_num`). When a merged PR references the
    issue the work shipped → Done, which on the label plane means **clearing**
    ``agent:review`` (Done is the absence of an active ``agent:*`` label + the
    closed/merged signal). A no-op when there is no merged PR or no ``agent:review``
    to strip.
    """
    if merged_pr_num is None:
        return TransitionPlan(target=_current_agent_target(current_labels), should_write=False)
    has_review = "agent:review" in current_labels
    return TransitionPlan(
        target=None,
        should_write=has_review,
        reason="merged_pr" if has_review else "",
    )


def closed_transition(*, current_labels: Sequence[str], has_active_run: bool) -> TransitionPlan:
    """``issues.closed`` → Done; cancel any live run (§8.1).

    A closed issue is **Done** regardless of any stale ``agent:*`` label (§5.3.1
    row 6), so the label plane clears to no ``agent:*`` label. ``cancel_live_run``
    is set when an active run exists on the issue — the **cancel call is a no-op
    stub in Phase 1** (runs are Phase 2/3), but the demotion/label decision is
    built and unit-tested here so Phase 3's reconcile only has to wire the cancel.
    A no-op write when there is already no ``agent:*`` label to clear.
    """
    has_agent_label = any(name in AGENT_LABEL_NAMES for name in current_labels)
    return TransitionPlan(
        target=None,
        should_write=has_agent_label,
        cancel_live_run=has_active_run,
        reason="closed",
    )


def reopened_transition(
    *, current_labels: Sequence[str], restore_target: str | None = None
) -> TransitionPlan:
    """``issues.reopened`` → out of Done: restore an ``agent:*`` label or Backlog (§8.1).

    A reopened issue leaves Done. The PRD says "restore the appropriate ``agent:*``
    label or Backlog": ``restore_target`` (e.g. the state the issue carried before
    it was closed, if known) is restored; otherwise the issue drops to **Backlog**
    (no ``agent:*`` label). ``should_write`` is ``True`` only when the restored
    target differs from the current label state (idempotent skip otherwise).
    """
    target = restore_target
    if target is not None:
        # Normalize/validate the restore target through the same resolver.
        label = _agent_label_for(target)
        target = None if label is None else label.split(":", 1)[1]
    current_target = _current_agent_target(current_labels)
    return TransitionPlan(
        target=target,
        should_write=target != current_target,
        reason="reopened",
    )


def failed_run_demotion(*, current_labels: Sequence[str], will_retry: bool) -> TransitionPlan:
    """Demote a **failed** run off ``agent:in-progress`` (§8.1) — no stranded issue.

    On a run failure the board must not strand the issue in **In Progress**: the
    label is demoted off ``agent:in-progress`` to **``agent:queued``** if the run
    will auto-retry (it goes back into the queue), else **stripped to Backlog**
    (target ``None``). A no-op when the issue is not currently ``agent:in-progress``
    (nothing to demote). This is the failed-run completeness rule (§8.1, third
    bullet); the reconcile loop that *calls* it on a real failure is Phase 3, but
    the demotion decision is built + unit-tested here.
    """
    if "agent:in-progress" not in current_labels:
        return TransitionPlan(
            target=_current_agent_target(current_labels),
            should_write=False,
        )
    target = "queued" if will_retry else None
    return TransitionPlan(
        target=target,
        should_write=True,
        reason="failed_retry" if will_retry else "failed_strip",
    )


async def apply_transition(
    client: GitHubClient,
    repo: str,
    num: int,
    plan: TransitionPlan,
    *,
    current_labels: Sequence[str],
    write_queue: WriteQueue,
    cache: HashCache[BoardPage] | None = None,
    cancel_run: Callable[[], Awaitable[None]] | None = None,
) -> SetAgentStateResult | None:
    """Execute a :class:`TransitionPlan` (completeness rule) via ``set_agent_state``.

    Skips the GitHub write when ``plan.should_write`` is ``False`` (idempotent
    no-op). When ``plan.cancel_live_run`` is set, invokes ``cancel_run`` if one is
    supplied — in Phase 1 this is the **no-op stub** (runs don't exist yet), so the
    default ``None`` simply records the intent; Phase 3 passes a real canceller.
    Returns the write result, or ``None`` when nothing was written.
    """
    if plan.cancel_live_run and cancel_run is not None:
        await cancel_run()
    if not plan.should_write:
        return None
    return await set_agent_state(
        client,
        repo,
        num,
        plan.target,
        current_labels=current_labels,
        write_queue=write_queue,
        cache=cache,
    )


__all__ = [
    "AGENT_STATE_TARGETS",
    "ActiveRun",
    "SetAgentStateResult",
    "TransitionPlan",
    "apply_transition",
    "closed_transition",
    "compute_desired_labels",
    "failed_run_demotion",
    "merged_pr_transition",
    "reopened_transition",
    "set_agent_state",
]
