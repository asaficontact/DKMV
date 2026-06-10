"""Canonical segment-sum spend SQL (INV-7 / INV-8) — the ONE last-per-task CTE.

G13 (ship-gap): the ``last_per_task`` segment-sum CTE was materialized **verbatim
~6×** across the codebase (``repository.run_spends`` / ``total_spend`` /
``daily_spend_series`` / ``_spend_today`` / ``_project_run_spend`` and
``backup._total_spend``). Six byte-for-byte copies of a load-bearing,
correctness-critical projection is a maintenance trap: a fix to one (or a drift in
the Codex exclusion) silently forks the meter from the dashboard from the backup
checksum. This module is the **single source** every SQL spend site composes.

The binding semantics (INV-7, §6.4, §8.3, R-17) the fragment encodes::

    run_cost = Σ over distinct (run_id, task_index) of the LAST-cumulative cost_usd

i.e. for each ``(run_id, task_index)`` take the event with the highest ``id`` that
carries a non-NULL ``cost_usd`` — that row IS that task's final/latest cumulative
cost — then sum across tasks. This is **never** a naive ``SUM(cost_usd)`` over
every event (the per-task ``cost_usd`` is cumulative, so a flat sum double-counts
every intermediate line) and **never** keep-latest-overall (which resets toward
``$0`` at every stage boundary).

**Codex exclusion (INV-8 / FR-06-1a).** A Codex run reports ``$0`` and supports no
budget cap, so its runs are excluded from spend by the run's ``agent`` column
(:data:`COST_EXCLUDED_AGENT`). Its tokens still count elsewhere; only its *cost* is
dropped here. The exclusion predicate is exported as :data:`AGENT_NOT_CODEX_SQL`
so every site applies the identical filter.

This module holds **SQL fragments only** (no DB access). The Python twin of this
projection (the live meter) is :func:`app.runs.meters.compute_run_meters`, which
sums :meth:`app.db.repository.Repository.read_run_segments` — itself built on the
same per-``task_index`` last-cumulative definition documented here.
"""

from __future__ import annotations

#: ``runs.status`` values that are **terminal** — the run is finished, its
#: ``run_totals`` completion snapshot is (or will be) written, and its events are
#: prunable (G9). The complement of the §8.1 active set. The fast-path spend
#: projections read the snapshot for these instead of re-scanning their events; the
#: retention prune only touches events of runs in this set (never an active run).
#: Single-sourced here (the db layer) so the spend fast-path, the prune, and the
#: reconcile pass all agree on "is this run finished?" without a circular import.
TERMINAL_RUN_STATUSES: frozenset[str] = frozenset(
    {"completed", "failed", "cancelled", "timed_out", "interrupted"}
)

#: Agent name whose runs are excluded from spend (FR-06-1a; INV-7/INV-8). Codex
#: reports $0 cost and supports no budget cap — its tokens count, its cost does
#: not contribute to the materialized spend projection. Re-exported from here so
#: the spend SQL and the exclusion constant live together; ``repository`` and
#: ``backup`` import it from this module (one definition).
COST_EXCLUDED_AGENT = "codex"

#: The Codex-exclusion WHERE predicate, against a ``runs`` alias ``r``. Bound with
#: a single ``?`` = :data:`COST_EXCLUDED_AGENT`. Every spend site applies the
#: identical filter so the exclusion can never drift between projections.
AGENT_NOT_CODEX_SQL = "COALESCE(LOWER(r.agent), '') != ?"


def last_per_task_cte(*, run_filter: str = "") -> str:
    """Return the canonical ``last_per_task`` CTE body (INV-7 — the ONE definition).

    Produces the ``WITH last_per_task AS (…)`` clause that yields, per
    ``(run_id, task_index)``, the last-cumulative ``cost_usd`` row of the run's
    cost-bearing events — the segment the outer query sums. Every spend SQL site
    composes this so the per-task last-cumulative dedup is byte-identical
    everywhere (no forked copy can drift).

    ``run_filter`` is an optional extra predicate spliced into the inner
    ``events`` scan's ``WHERE`` (after ``cost_usd IS NOT NULL``) to scope the CTE
    to a run set — e.g. ``"AND run_id IN (?, ?)"`` for the bulk
    :meth:`Repository.run_spends` read. It MUST contain only a parameterized
    predicate (``?`` placeholders), never interpolated values — callers bind the
    values positionally. Empty (the default) scans all cost-bearing events (the
    whole-table projections: ``total_spend`` / ``daily_spend_series`` /
    ``backup._total_spend``).
    """
    extra = f" {run_filter}" if run_filter else ""
    return (
        "WITH last_per_task AS (\n"
        "    SELECT e.run_id AS run_id,\n"
        "           e.cost_usd AS cost_usd\n"
        "    FROM events e\n"
        "    JOIN (\n"
        "        SELECT run_id, task_index, MAX(id) AS max_id\n"
        "        FROM events\n"
        f"        WHERE cost_usd IS NOT NULL{extra}\n"
        "        GROUP BY run_id, task_index\n"
        "    ) m\n"
        "      ON e.run_id = m.run_id\n"
        "     AND e.id = m.max_id\n"
        ")"
    )


def per_run_spend_sql(*, run_filter: str = "") -> str:
    """``{cte} SELECT run_id, SUM(cost_usd) AS spend … GROUP BY run_id`` (Codex-excluded).

    The per-run segment-sum: the canonical CTE joined to ``runs`` with the
    Codex-exclusion predicate, grouped per run. Bound params order: any
    ``run_filter`` placeholders FIRST (they sit inside the CTE), then the single
    :data:`COST_EXCLUDED_AGENT` for :data:`AGENT_NOT_CODEX_SQL`. Used by the bulk
    :meth:`Repository.run_spends` read.
    """
    return (
        f"{last_per_task_cte(run_filter=run_filter)}\n"
        "SELECT lpt.run_id AS run_id,\n"
        "       COALESCE(SUM(lpt.cost_usd), 0.0) AS spend\n"
        "FROM last_per_task lpt\n"
        "JOIN runs r ON r.id = lpt.run_id\n"
        f"WHERE {AGENT_NOT_CODEX_SQL}\n"
        "GROUP BY lpt.run_id"
    )


def total_spend_sql(*, run_filter: str = "") -> str:
    """``{cte} SELECT SUM(cost_usd) AS total …`` over all (Codex-excluded) runs.

    The flat total segment-sum: every distinct ``(run_id, task_index)``
    last-cumulative cost over Codex-excluded runs, summed. Bound params order: any
    ``run_filter`` placeholders FIRST, then the single :data:`COST_EXCLUDED_AGENT`.
    Used by :meth:`Repository.total_spend`'s active-run branch and
    :func:`app.db.backup._total_spend`'s whole-DB checksum.
    """
    return (
        f"{last_per_task_cte(run_filter=run_filter)}\n"
        "SELECT COALESCE(SUM(lpt.cost_usd), 0.0) AS total\n"
        "FROM last_per_task lpt\n"
        "JOIN runs r ON r.id = lpt.run_id\n"
        f"WHERE {AGENT_NOT_CODEX_SQL}"
    )


__all__ = [
    "AGENT_NOT_CODEX_SQL",
    "COST_EXCLUDED_AGENT",
    "TERMINAL_RUN_STATUSES",
    "last_per_task_cte",
    "per_run_spend_sql",
    "total_spend_sql",
]
