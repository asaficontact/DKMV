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
``total_spend_usd`` and the daily ``spend_series``** (via the run's ``agent``
column, matching :meth:`Repository.total_spend`), while its **tokens and
agent-hours count normally**. The spend numbers are the **segment-sum**
projection (per ``(run_id, task_index)`` last-cumulative ``cost_usd``, never a
naive ``SUM`` over events — INV-7), read from the same event log the live meter
and the board strip read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiosqlite

from app.db.repository import COST_EXCLUDED_AGENT, Repository

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
        where.append("repo = ?")
        params.append(repo)
    for column, value in filters.items():
        where.append(f"{column} = ?")
        params.append(value)
    sql = "SELECT * FROM runs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?"
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
    * ``total_spend_usd`` — the **segment-sum** spend (per ``(run_id, task_index)``
      last-cumulative ``cost_usd``, INV-7) over **non-Codex** runs (FR-06-1a).
    * ``tokens`` — ``Σ(tokens_in + tokens_out)`` over **every** run (Codex
      included — its tokens are real, FR-06-1a).
    * ``agent_hours`` — ``Σ duration_s / 3600`` over every run (Codex included).
    * ``spend_series`` — daily Codex-excluded segment-sum spend keyed by the
      ``started_at`` date, oldest-first.
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
        total_spend = await _total_spend_excluding_codex(conn)
        spend_series = await _spend_series_excluding_codex(conn)
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


async def _total_spend_excluding_codex(conn: aiosqlite.Connection) -> float:
    """Σ segment-sum spend across all non-Codex runs (INV-7 / FR-06-1a).

    Per ``(run_id, task_index)`` last-cumulative ``cost_usd`` summed per run, then
    summed across runs, with **Codex excluded** by the run's ``agent`` column —
    identical to :meth:`Repository.total_spend`, recomputed here so the stats
    read shares one event-log source with the live meter (never a naive ``SUM``
    over events).
    """
    rows = await conn.execute_fetchall(
        """
        WITH last_per_task AS (
            SELECT e.run_id AS run_id, e.cost_usd AS cost_usd
            FROM events e
            JOIN (
                SELECT run_id, task_index, MAX(id) AS max_id
                FROM events
                WHERE cost_usd IS NOT NULL
                GROUP BY run_id, task_index
            ) m ON e.run_id = m.run_id AND e.id = m.max_id
        )
        SELECT COALESCE(SUM(lpt.cost_usd), 0.0) AS total
        FROM last_per_task lpt
        JOIN runs r ON r.id = lpt.run_id
        WHERE COALESCE(LOWER(r.agent), '') != ?
        """,
        (COST_EXCLUDED_AGENT,),
    )
    return float(next(iter(rows))["total"] or 0.0) if rows else 0.0


async def _spend_series_excluding_codex(conn: aiosqlite.Connection) -> list[dict[str, Any]]:
    """Daily Codex-excluded segment-sum spend ``[{date, usd}]`` oldest-first.

    Buckets each run's segment-sum spend by the **date** half of its UTC
    ``started_at`` (``YYYY-MM-DD``); **Codex runs are excluded** (FR-06-1a) so a
    $0-cost Codex run never adds a phantom bar. The per-run segment sum is the
    same last-cumulative-per-task projection used everywhere (INV-7).
    """
    rows = await conn.execute_fetchall(
        """
        WITH last_per_task AS (
            SELECT e.run_id AS run_id, e.cost_usd AS cost_usd
            FROM events e
            JOIN (
                SELECT run_id, task_index, MAX(id) AS max_id
                FROM events
                WHERE cost_usd IS NOT NULL
                GROUP BY run_id, task_index
            ) m ON e.run_id = m.run_id AND e.id = m.max_id
        ),
        per_run AS (
            SELECT lpt.run_id AS run_id, SUM(lpt.cost_usd) AS spend
            FROM last_per_task lpt
            JOIN runs r ON r.id = lpt.run_id
            WHERE COALESCE(LOWER(r.agent), '') != ?
              AND r.started_at IS NOT NULL
            GROUP BY lpt.run_id
        )
        SELECT substr(r.started_at, 1, 10) AS day,
               COALESCE(SUM(pr.spend), 0.0) AS usd
        FROM per_run pr
        JOIN runs r ON r.id = pr.run_id
        GROUP BY day
        ORDER BY day
        """,
        (COST_EXCLUDED_AGENT,),
    )
    return [{"date": str(r["day"]), "usd": float(r["usd"] or 0.0)} for r in rows]
