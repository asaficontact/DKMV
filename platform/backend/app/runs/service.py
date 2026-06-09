"""Run read model — the §8.9 ``GET /runs`` / ``GET /runs/{id}`` baseline shapes.

This module projects the platform's persisted run state into the wire shapes the
live-run view (slice 2.4) and the run-list spine read. It is a **pure read
projection** over the :class:`~app.db.repository.Repository` seam (NFR-PORT-1):
no GitHub call, no engine call, no ``dkmv/`` import.

What it returns (PRD §8.9):

* :func:`build_run_detail` → the ``GET /runs/{id}`` body::

      { id, engine_run_id, repo, issue:{num,title}, workflow_id, agent, model,
        status, branch, cost_usd|null, tokens_in, tokens_out, turns,
        duration_s|null, started_at, finished_at|null, pr|null, error|null,
        stages:[RunStage], config:{...FR-04-5 keys}, sandbox:{...},
        artifacts:[...] }

* :func:`build_run_summary` → one ``GET /runs`` list row (the live-view spine;
  history filters/sort are Phase 3).

**Codex cost handling (INV-8 / FR-06-1a).** A Codex run reports ``$0`` from the
engine, so its ``cost_usd`` is rendered ``null`` (the UI shows "—") and it is
excluded from spend; **tokens still count**. The cost shown is the segment-sum
``Repository.run_spend`` projection (per ``(run_id, task_index)`` last-cumulative,
Codex-excluded — INV-7), not a raw ``cost_usd`` column read, so the live cost is
correct across stage boundaries. The full meter computation lives in slice 2.4;
this read surfaces the same projection for the baseline shape.
"""

from __future__ import annotations

from typing import Any

from app.db.repository import COST_EXCLUDED_AGENT, Repository

#: The verbatim FR-04-5 run-config snapshot keys the right-rail renders (slice
#: 2.4). Pinned here so the ``GET /runs/{id}`` ``config`` block carries exactly
#: these keys (AC-5 asserts their presence).
RUN_CONFIG_KEYS: tuple[str, ...] = (
    "repo",
    "branch",
    "feature_name",
    "model",
    "max_turns",
    "timeout_minutes",
    "max_budget_usd",
    "memory_limit",
)


def _is_codex(agent: Any) -> bool:
    """True iff the run's agent is the cost-excluded Codex agent (FR-06-1a)."""
    return isinstance(agent, str) and agent.strip().lower() == COST_EXCLUDED_AGENT


def _issue_block(row: dict[str, Any], title: str | None) -> dict[str, Any] | None:
    """The ``issue:{num,title}`` block, or ``None`` for a repo-only run.

    ``title`` is resolved from the ``issues`` cache by the caller (the run row
    only carries ``issue_num``); a missing cache row degrades to an empty title
    rather than a failed read.
    """
    num = row.get("issue_num")
    if num is None:
        return None
    return {"num": int(num), "title": title or ""}


def _pr_block(row: dict[str, Any]) -> dict[str, Any] | None:
    """The ``pr:{num,...}|null`` block from ``runs.pr_num`` (§8.9).

    Phase 2 surfaces the linked PR number when one exists (set by the completion
    path / Phase 3 reconcile); ``title``/``checks`` back-fill later. ``None`` when
    no PR is linked yet.
    """
    pr_num = row.get("pr_num")
    if pr_num is None:
        return None
    return {"num": int(pr_num), "title": None, "checks": None}


def build_run_config(
    row: dict[str, Any], *, sandbox_image: str, memory_limit: str
) -> dict[str, Any]:
    """Build the FR-04-5 ``config`` snapshot with exactly :data:`RUN_CONFIG_KEYS`.

    The verbatim run-config keys the right rail renders (slice 2.4). The
    guardrail values (``max_turns`` / ``timeout_minutes`` / ``max_budget_usd`` /
    ``memory_limit``) are read from the ``runs`` row — the **actual launched
    values** persisted at ``claim_run`` time — so the block is truthful (FR-04-5).
    ``max_turns`` / ``max_budget_usd`` are ``None`` for a Codex run (the engine
    has no such cap — INV-8) and surface as ``null``. ``memory_limit`` falls back
    to the configured default for a legacy row that did not pin one.
    """
    return {
        "repo": row.get("repo"),
        "branch": row.get("branch"),
        "feature_name": row.get("feature_name"),
        "model": row.get("model"),
        "max_turns": row.get("max_turns"),
        "timeout_minutes": row.get("timeout_minutes"),
        "max_budget_usd": row.get("max_budget_usd"),
        "memory_limit": memory_limit,
    }


def _sandbox_block(*, image: str, memory_limit: str) -> dict[str, Any]:
    """The ``sandbox:{image,mem,vcpu,health}`` block (§8.9 / FR-04-5).

    Health is a static ``healthy`` in the baseline shape; the live sandbox probe
    (slice 2.4) refines it. ``mem``/``vcpu`` echo the run's memory limit and the
    fixed 2-vCPU sandbox profile (§8.6/FR-04-5).
    """
    return {
        "image": image,
        "mem": memory_limit,
        "vcpu": 2,
        "health": "healthy",
    }


async def _stages(repository: Repository, run_id: str) -> list[dict[str, Any]]:
    """Read the ``run_stages`` rows for a run, ordered by stage index (§8.9).

    A pure read of the mutable stage read model (the stepper the live view
    renders). Empty until the event pump (slice 2.3) populates it.
    """
    rows = await repository.read_run_stages(run_id)
    return [
        {
            "idx": int(r["idx"]),
            "name": r["name"],
            "status": r["status"],
            "cost_usd": r.get("cost_usd"),
            "turns": int(r.get("turns") or 0),
            "duration_s": r.get("duration_s"),
        }
        for r in rows
    ]


async def build_run_detail(
    repository: Repository,
    row: dict[str, Any],
    *,
    sandbox_image: str,
    default_memory: str,
) -> dict[str, Any]:
    """Project a ``runs`` row into the §8.9 ``GET /runs/{id}`` baseline body.

    Assembles the live-view detail: identity, status, the segment-sum
    ``cost_usd`` (``null`` for Codex — INV-8/FR-06-1a), token/turn meters, the
    ``stages`` stepper, the FR-04-5 ``config`` snapshot, the ``sandbox`` block,
    ``artifacts`` (empty in the baseline; the live artifact list is slice 2.4),
    and the linked ``pr``/``error``. Cost is the **segment-sum projection**
    (:meth:`Repository.run_spend`), never the raw ``cost_usd`` column, so the
    displayed cost is correct across stage boundaries (INV-7).
    """
    run_id = str(row["id"])
    agent = row.get("agent")
    memory_limit = _row_memory(row, default_memory)

    # Issue title from the cache (the run row carries only issue_num).
    issue_title: str | None = None
    issue_num = row.get("issue_num")
    if issue_num is not None:
        issue_row = await repository.read_issue(str(row["repo"]), int(issue_num))
        issue_title = (issue_row or {}).get("title") if issue_row else None

    # Codex contributes $0 / "—": cost_usd is null (FR-06-1a). Otherwise the
    # segment-sum projection (per (run_id, task_index) last-cumulative — INV-7).
    cost_usd: float | None
    if _is_codex(agent):
        cost_usd = None
    else:
        cost_usd = await repository.run_spend(run_id)

    return {
        "id": run_id,
        "engine_run_id": row.get("engine_run_id"),
        "repo": row.get("repo"),
        "issue": _issue_block(row, issue_title),
        "workflow_id": row.get("workflow_id"),
        "agent": agent,
        "model": row.get("model"),
        "status": row.get("status"),
        "branch": row.get("branch"),
        "cost_usd": cost_usd,
        "tokens_in": int(row.get("tokens_in") or 0),
        "tokens_out": int(row.get("tokens_out") or 0),
        "turns": int(row.get("turns") or 0),
        "duration_s": row.get("duration_s"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "pr": _pr_block(row),
        "error": row.get("error"),
        "stages": await _stages(repository, run_id),
        "config": build_run_config(row, sandbox_image=sandbox_image, memory_limit=memory_limit),
        "sandbox": _sandbox_block(image=sandbox_image, memory_limit=memory_limit),
        "artifacts": [],
    }


def _row_memory(row: dict[str, Any], default_memory: str) -> str:
    """Resolve a run's memory limit from the persisted ``memory_limit`` column.

    The launch path persists the resolved ``memory_limit`` (``req.memory`` or the
    configured default) at ``claim_run`` time, so this returns the *actual*
    launched value (FR-04-5). Falls back to the configured default only for a
    legacy row that predates the column.
    """
    mem = row.get("memory_limit")
    return str(mem) if mem else default_memory


def _summary_row(row: dict[str, Any], cost_usd: float | None) -> dict[str, Any]:
    """Assemble one ``GET /runs`` list row from a run row + its resolved cost.

    Shared by the single- and bulk-cost paths so the wire shape is identical
    regardless of how ``cost_usd`` was projected.
    """
    return {
        "id": str(row["id"]),
        "engine_run_id": row.get("engine_run_id"),
        "repo": row.get("repo"),
        "issue_num": row.get("issue_num"),
        "workflow_id": row.get("workflow_id"),
        "agent": row.get("agent"),
        "model": row.get("model"),
        "status": row.get("status"),
        "branch": row.get("branch"),
        "cost_usd": cost_usd,
        "tokens_in": int(row.get("tokens_in") or 0),
        "tokens_out": int(row.get("tokens_out") or 0),
        "turns": int(row.get("turns") or 0),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
    }


async def build_run_summary(
    repository: Repository,
    row: dict[str, Any],
) -> dict[str, Any]:
    """Project a ``runs`` row into one ``GET /runs`` list row (the live spine).

    The minimal summary the run list renders (id, identity, status, the
    segment-sum cost — Codex ``null``, tokens/turns). History filters/sort/columns
    are Phase 3 (FR-06-4); Phase 2 ships the baseline list spine. Single-row
    helper retained for callers that already hold one row; the list path uses the
    bulk :func:`build_run_summaries` (one spend query, not N).
    """
    run_id = str(row["id"])
    agent = row.get("agent")
    cost_usd = None if _is_codex(agent) else await repository.run_spend(run_id)
    return _summary_row(row, cost_usd)


async def build_run_summaries(
    repository: Repository,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project a whole ``GET /runs`` page in **one** bulk spend query (PERF).

    Replaces the per-row :meth:`Repository.run_spend` (a 100-run page = 1 list
    query + 100 serialized per-run spend queries through the 4-slot read pool)
    with a single :meth:`Repository.run_spends` call over all the page's
    non-Codex run ids, so the page costs **one** list query + **one** bulk spend
    query (O(1), not O(N)). The segment-sum semantics are preserved exactly
    (per ``(run_id, task_index)`` last-cumulative, Codex excluded — INV-7). A
    Codex row's ``cost_usd`` stays ``null``; a non-Codex run with no cost events
    defaults to ``0.0``.
    """
    if not rows:
        return []
    # Only non-Codex runs contribute to the bulk spend query (Codex → null).
    spend_ids = [str(r["id"]) for r in rows if not _is_codex(r.get("agent"))]
    spends = await repository.run_spends(spend_ids)
    items: list[dict[str, Any]] = []
    for row in rows:
        if _is_codex(row.get("agent")):
            cost_usd: float | None = None
        else:
            cost_usd = spends.get(str(row["id"]), 0.0)
        items.append(_summary_row(row, cost_usd))
    return items
