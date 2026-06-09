"""History & analytics read queries (slice 3.1 — F10 / §8.9, §6.5).

The read-only SQL behind the Phase-3 history/analytics API. Everything here is a
**pure WAL read** borrowed from the :class:`~app.db.repository.Repository` read
pool (``Repository.read_connection`` — INV-6: reads on their own connections,
never the single writer), kept out of the API layer so the SQLite→Postgres swap
(NFR-PORT-1) stays additive and the evaluator's spend/exclusion greps find the
behavior in one place.

What this module computes:

* :func:`list_runs_filtered` — the ``GET /runs`` history page: ``workflow`` /
  ``agent`` / ``status`` filters + ``limit``-bounded **cursor pagination** over
  the ``runs`` read model (NOT the engine ``list_runs`` directory scan — §6.5).
* :func:`compute_stats` — the ``GET /stats`` aggregates from ``run_totals`` +
  active runs (NOT the engine ``get_stats`` directory scan — §6.5): total runs,
  ``completed/(completed+failed)`` success rate, **Codex-excluded** total spend +
  daily ``spend_series``, all-agent tokens, and agent-hours.

**Codex exclusion (FR-06-1a / INV-8 — binding).** Codex reports ``$0`` from the
engine and supports no budget cap, so its runs are **excluded from
``total_spend_usd`` and the daily ``spend_series``**, while its **tokens and
agent-hours count normally**.

**One canonical segment-sum (INV-7).** The spend numbers are the segment-sum
projection (per ``(run_id, task_index)`` last-cumulative ``cost_usd``, never a
naive ``SUM`` over events). This module does **not** re-implement that CTE: the
daily Codex-excluded series comes from :meth:`Repository.daily_spend_series`
(a sibling of :meth:`Repository.total_spend` / :meth:`Repository.run_spends`,
sharing the **same** ``last_per_task`` CTE shape), and ``total_spend_usd`` is the
sum of that series — so the one segment-sum definition lives in the repository
spend methods and ``/stats`` reads through it, reconciling exactly with the live
meter and the board strip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiosqlite

from app.db.repository import Repository

#: The two run statuses (§6.3) that move the success ratio. The PRD pins success
#: rate to ``completed/(completed+failed)`` (FR-06-1), so the denominator is
#: exactly these two states — other states (running/paused/cancelled/timed_out/
#: interrupted) are neither numerator nor denominator for the ratio.
_COMPLETED = "completed"
_FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StatsResult:
    """The ``GET /stats`` aggregate result (FR-06-1 / §8.9), pre-serialization.

    ``total_spend_usd`` + ``spend_series`` are **Codex-excluded** (FR-06-1a);
    ``tokens`` + ``agent_hours`` count every agent including Codex.
    """

    total_runs: int
    completed: int
    failed: int
    total_spend_usd: float
    tokens: int
    agent_hours: float
    spend_series: list[dict[str, Any]]

    @property
    def success_rate(self) -> float:
        """``completed/(completed+failed)`` (FR-06-1); ``0.0`` with no outcomes."""
        denom = self.completed + self.failed
        return (self.completed / denom) if denom else 0.0


def _normalize_filters(
    *, workflow: str | None, agent: str | None, status: str | None
) -> dict[str, str]:
    """Drop empty/whitespace filter values so ``?workflow=`` is a no-op filter.

    A bare ``?workflow=`` (empty string) must NOT narrow to "rows whose
    workflow_id is the empty string" — it means "no workflow filter". Only a
    non-blank value becomes a SQL predicate.
    """
    out: dict[str, str] = {}
    if workflow and workflow.strip():
        out["workflow_id"] = workflow.strip()
    if agent and agent.strip():
        out["agent"] = agent.strip()
    if status and status.strip():
        out["status"] = status.strip()
    return out


async def list_runs_filtered(
    repository: Repository,
    *,
    repo: str | None = None,
    workflow: str | None = None,
    agent: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Read a filtered, paginated ``runs`` page newest-first (§8.9 / FR-06-4).

    The history table's read: optional ``repo`` scope + the FR-06-4 ``workflow`` /
    ``agent`` / ``status`` filters, ordered ``started_at DESC, id DESC`` (stable
    newest-first), ``LIMIT``/``OFFSET`` for cursor pagination. Reads the platform
    ``runs`` read model through the repository read pool — **never** the engine
    ``list_runs`` directory scan (§6.5). The caller over-fetches one row to detect
    a next page; cost projection is layered on by :func:`app.runs.service` so the
    Codex-``null`` + segment-sum semantics are shared with the live spine.
    """
    filters = _normalize_filters(workflow=workflow, agent=agent, status=status)
    where: list[str] = []
    params: list[Any] = []
    if repo is not None:
        where.append("r.repo = ?")
        params.append(repo)
    for column, value in filters.items():
        where.append(f"r.{column} = ?")
        params.append(value)
    # Fold the issue-title lookup into the page query as a single LEFT JOIN on the
    # ``issues`` cache (keyed on (repo, num) — the issues PK) so the FR-06-4
    # "Issue (#num title)" column has its title in the **same** read as the page —
    # NO per-row ``read_issue`` (no N+1). ``r.*`` keeps every existing run column
    # (cost projection / config / pr_num) so the summary projection is unchanged
    # apart from the added ``issue_title``. The join is title-only and LEFT (a run
    # whose issue is not yet cached still returns, with a NULL title that degrades
    # to "" in the projection).
    sql = (
        "SELECT r.*, i.title AS issue_title "
        "FROM runs r "
        "LEFT JOIN issues i ON i.repo = r.repo AND i.num = r.issue_num"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.started_at DESC, r.id DESC LIMIT ? OFFSET ?"
    params.extend((limit, offset))
    async with repository.read_connection() as conn:
        rows = await conn.execute_fetchall(sql, params)  # noqa: S608 — columns are literals; values bound
        return [dict(r) for r in rows]


async def compute_stats(repository: Repository) -> StatsResult:
    """Compute the ``GET /stats`` aggregates from ``run_totals`` + active runs (§6.5).

    Reads the platform projections — **never** the engine ``get_stats`` directory
    scan (§6.5). All in pure WAL reads through the repository read pool:

    * ``total_runs`` — every ``runs`` row.
    * ``completed`` / ``failed`` — the success-rate halves (``completed +
      failed`` denominator, FR-06-1).
    * ``tokens`` — ``Σ(tokens_in + tokens_out)`` over **every** run (Codex
      included — its tokens are real, FR-06-1a).
    * ``agent_hours`` — ``Σ duration_s / 3600`` over every run (Codex included).
    * ``spend_series`` — daily Codex-excluded **segment-sum** spend (per
      ``(run_id, task_index)`` last-cumulative ``cost_usd``, INV-7) keyed by the
      ``started_at`` date, oldest-first, via :meth:`Repository.daily_spend_series`
      (the **one** canonical segment-sum definition — never a CTE re-implemented
      here).
    * ``total_spend_usd`` — the same Codex-excluded segment-sum spend, **derived
      as the sum of ``spend_series``** so the events table is scanned once for the
      spend total + series, not twice (FIX-4 / PERF), and the run total always
      reconciles exactly with the bars it summarizes.
    """
    async with repository.read_connection() as conn:
        total_runs = await _scalar_int(conn, "SELECT COUNT(*) AS n FROM runs")
        completed = await _count_status(conn, _COMPLETED)
        failed = await _count_status(conn, _FAILED)
        tokens = await _scalar_int(
            conn, "SELECT COALESCE(SUM(tokens_in + tokens_out), 0) AS n FROM runs"
        )
        agent_seconds = await _scalar_float(
            conn, "SELECT COALESCE(SUM(duration_s), 0.0) AS n FROM runs"
        )
    # The Codex-excluded segment-sum series IS the one canonical projection
    # (Repository.daily_spend_series — same last_per_task CTE as total_spend /
    # run_spends). The /stats total is the sum of those daily buckets, so the
    # events segment-sum is read exactly once for both the total and the series.
    spend_series = await repository.daily_spend_series()
    total_spend = sum(float(point["usd"]) for point in spend_series)
    return StatsResult(
        total_runs=total_runs,
        completed=completed,
        failed=failed,
        total_spend_usd=total_spend,
        tokens=tokens,
        agent_hours=agent_seconds / 3600.0,
        spend_series=spend_series,
    )


async def _scalar_int(conn: aiosqlite.Connection, sql: str) -> int:
    rows = await conn.execute_fetchall(sql)
    return int(next(iter(rows))["n"]) if rows else 0


async def _scalar_float(conn: aiosqlite.Connection, sql: str) -> float:
    rows = await conn.execute_fetchall(sql)
    return float(next(iter(rows))["n"] or 0.0) if rows else 0.0


async def _count_status(conn: aiosqlite.Connection, status: str) -> int:
    rows = await conn.execute_fetchall("SELECT COUNT(*) AS n FROM runs WHERE status = ?", (status,))
    return int(next(iter(rows))["n"]) if rows else 0
