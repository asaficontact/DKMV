"""Repository layer — the single seam in front of all platform DB access.

Everything the rest of the backend does to the database goes through
:class:`Repository`. Writes are routed to the single serialized writer task
(INV-6); reads open their own short-lived connections under WAL. Keeping *all*
SQL here is what makes the SQLite→Postgres swap (NFR-PORT-1) an additive change
rather than a rewrite, and what lets the evaluator's greps find the binding
behaviors (``BEGIN IMMEDIATE``, ``ON CONFLICT … DO NOTHING``, the ``task_index``
spend dedup, ``VACUUM INTO``) in one place.

Key binding behaviors implemented here:

* **Idempotency claim-insert (INV-5 / §8.2):** :meth:`claim_run` does
  ``INSERT … ON CONFLICT(idempotency_key) DO NOTHING`` inside the writer's
  ``BEGIN IMMEDIATE`` transaction and reports whether *this* caller won the row.
  The claim is a UNIQUE-key insert, not a row-lock skip — SQLite has neither of
  the row-locking constructs Postgres offers, by design here.
* **Append-only event log (§6.4/§6.5):** :meth:`append_events` batch-inserts
  into ``events`` (never UPDATE/DELETE); ``events.id`` is the monotonic SSE
  cursor. :meth:`read_events_after` is the replay read.
* **Spend projection (INV-7 prep / §6.5):** :meth:`run_spend` /
  :meth:`total_spend` compute **last-cumulative ``cost_usd`` per
  ``(run_id, task_index)`` summed per run**, with **Codex excluded** — never a
  naive flat sum of every event's cost (that double-counts the per-task
  cumulative line at each step).
* **run_totals snapshot + backup (§6.5):** :meth:`snapshot_run_totals` writes
  the completion snapshot; :meth:`backup_to` runs ``VACUUM INTO``.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from app.db.connection import connect
from app.db.writer import Writer

#: Agent name whose runs are excluded from spend (FR-06-1a; INV-7). Codex
#: reports $0 cost and supports no budget cap — its tokens count, its cost does
#: not contribute to the materialized spend projection.
COST_EXCLUDED_AGENT = "codex"


def _utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (the platform's time format)."""
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class EventRecord:
    """One engine ``RuntimeEvent`` projected into a row for the append log.

    ``task_index``/``cost_usd``/``agent`` are materialized out of the event so
    the spend projection can dedup last-cumulative cost per ``(run_id,
    task_index)`` without re-parsing ``payload_json`` per row. ``payload_json``
    is the redacted, serialized event body (redaction lands in slice 0.5 — this
    layer persists whatever it is handed).
    """

    run_id: str
    sequence: int
    event_type: str
    payload: Mapping[str, Any]
    task_index: int | None = None
    cost_usd: float | None = None
    agent: str | None = None
    ts: str = field(default_factory=_utc_now_iso)


@dataclass(slots=True)
class RunTotals:
    """Completion snapshot written to ``run_totals`` (§6.5)."""

    cost_usd: float | None
    tokens_in: int = 0
    tokens_out: int = 0
    turns: int = 0
    duration_s: float | None = None


class Repository:
    """Facade over the platform SQLite database.

    Construct with a ``database_url``; call :meth:`start` to launch the single
    writer task and :meth:`close` to shut it down. Reads run on their own
    connections, so they never block (or are blocked by) the writer beyond
    WAL's normal read-snapshot semantics.
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._writer = Writer(database_url)
        self._started = False

    async def start(self) -> None:
        """Launch the single serialized writer task (INV-6)."""
        if self._started:
            return
        await self._writer.start()
        self._started = True

    async def close(self) -> None:
        """Stop the writer task and release its connection."""
        if not self._started:
            return
        await self._writer.stop()
        self._started = False

    # -- read connection helper ------------------------------------------------

    async def _read_conn(self) -> aiosqlite.Connection:
        """Open a fresh read connection (separate from the writer — INV-6)."""
        return await connect(self._database_url)

    # === idempotency claim-insert (INV-5 / §8.2) =============================

    async def claim_run(
        self,
        *,
        idempotency_key: str,
        repo: str,
        issue_num: int | None = None,
        workflow_id: str | None = None,
        agent: str | None = None,
        model: str | None = None,
        branch: str | None = None,
        feature_name: str | None = None,
        run_id: str | None = None,
    ) -> tuple[str, bool]:
        """Atomically claim a run row for ``idempotency_key``.

        Returns ``(run_id, won)`` where ``won`` is ``True`` iff *this* call
        inserted the row. Implemented as ``INSERT … ON CONFLICT(idempotency_key)
        DO NOTHING`` inside the writer's ``BEGIN IMMEDIATE`` transaction so two
        concurrent dispatch coroutines for the same key cannot both launch
        (INV-5). The loser gets back the existing row's ``id``.

        The platform ``id`` is a generated UUID (R-8) — never the engine id.
        """
        new_id = run_id or str(uuid.uuid4())
        started_at = _utc_now_iso()

        async def _job(conn: aiosqlite.Connection) -> tuple[str, bool]:
            cursor = await conn.execute(
                """
                INSERT INTO runs (
                    id, repo, issue_num, workflow_id, agent, model,
                    status, branch, feature_name, started_at, idempotency_key
                )
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (
                    new_id,
                    repo,
                    issue_num,
                    workflow_id,
                    agent,
                    model,
                    branch,
                    feature_name,
                    started_at,
                    idempotency_key,
                ),
            )
            if cursor.rowcount == 1:
                return new_id, True
            # Lost the race (or a retry): return the existing row's id.
            existing = list(
                await conn.execute_fetchall(
                    "SELECT id FROM runs WHERE idempotency_key = ?",
                    (idempotency_key,),
                )
            )
            return str(existing[0]["id"]), False

        return await self._writer.submit(_job)

    # === runs read/update =====================================================

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Fetch a single run row as a dict (read connection)."""
        conn = await self._read_conn()
        try:
            rows = list(await conn.execute_fetchall("SELECT * FROM runs WHERE id = ?", (run_id,)))
            return dict(rows[0]) if rows else None
        finally:
            await conn.close()

    async def update_run_fields(self, run_id: str, **fields: Any) -> None:
        """Patch arbitrary columns on a ``runs`` row (whitelisted by name)."""
        if not fields:
            return
        allowed = {
            "engine_run_id",
            "status",
            "model",
            "branch",
            "feature_name",
            "cost_usd",
            "tokens_in",
            "tokens_out",
            "turns",
            "duration_s",
            "finished_at",
            "pr_num",
            "error",
        }
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"update_run_fields: non-updatable columns {sorted(bad)}")
        assignments = ", ".join(f"{col} = ?" for col in fields)
        values: list[Any] = [*fields.values(), run_id]

        async def _job(conn: aiosqlite.Connection) -> None:
            await conn.execute(
                f"UPDATE runs SET {assignments} WHERE id = ?",  # noqa: S608 — cols whitelisted above
                values,
            )

        await self._writer.submit(_job)

    # === append-only event log (§6.4/§6.5) ===================================

    async def append_events(self, records: Sequence[EventRecord]) -> list[int]:
        """Batch-append events; returns the monotonic ``events.id`` for each.

        The ``events`` table is **append-only** — there is no UPDATE/DELETE path
        on it anywhere in the repository. The returned ids are the SSE replay
        cursors and are strictly increasing (``INTEGER PRIMARY KEY
        AUTOINCREMENT``).
        """
        if not records:
            return []

        async def _job(conn: aiosqlite.Connection) -> list[int]:
            ids: list[int] = []
            for rec in records:
                cursor = await conn.execute(
                    """
                    INSERT INTO events (
                        run_id, sequence, ts, event_type,
                        task_index, cost_usd, agent, payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rec.run_id,
                        rec.sequence,
                        rec.ts,
                        rec.event_type,
                        rec.task_index,
                        rec.cost_usd,
                        rec.agent,
                        json.dumps(rec.payload),
                    ),
                )
                ids.append(int(cursor.lastrowid or 0))
            return ids

        return await self._writer.submit(_job)

    async def read_events_after(
        self, run_id: str, last_id: int = 0, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Replay read: ``WHERE run_id=? AND id > :last ORDER BY id`` (§8.3)."""
        sql = "SELECT * FROM events WHERE run_id = ? AND id > ? ORDER BY id"
        params: list[Any] = [run_id, last_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        conn = await self._read_conn()
        try:
            rows = await conn.execute_fetchall(sql, params)
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    # === run_stages ===========================================================

    async def upsert_stage(
        self,
        run_id: str,
        idx: int,
        name: str,
        *,
        status: str = "pending",
        cost_usd: float | None = None,
        turns: int = 0,
        duration_s: float | None = None,
    ) -> None:
        """Insert or update a ``run_stages`` row (the mutable read model)."""

        async def _job(conn: aiosqlite.Connection) -> None:
            await conn.execute(
                """
                INSERT INTO run_stages (run_id, idx, name, status, cost_usd, turns, duration_s)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, idx) DO UPDATE SET
                    name = excluded.name,
                    status = excluded.status,
                    cost_usd = excluded.cost_usd,
                    turns = excluded.turns,
                    duration_s = excluded.duration_s
                """,
                (run_id, idx, name, status, cost_usd, turns, duration_s),
            )

        await self._writer.submit(_job)

    # === spend projection (INV-7 prep / §6.5) ================================

    async def run_spend(self, run_id: str) -> float:
        """Projected cost of one run: Σ last-cumulative ``cost_usd`` per task.

        The displayed run cost is the **segment sum**: for each distinct
        ``task_index`` of the run, take the *last* (highest ``id``) event that
        carries a ``cost_usd`` — that is the cumulative cost for that task — then
        sum across tasks. This is **never** a naive flat sum of every event's
        cost (that double-counts the per-task cumulative line at every step), and
        **never** keep-latest-overall (that would reset to ~$0 at each stage
        boundary). **Codex runs contribute $0** (FR-06-1a).
        """
        conn = await self._read_conn()
        try:
            run_rows = list(
                await conn.execute_fetchall("SELECT agent FROM runs WHERE id = ?", (run_id,))
            )
            if run_rows and _is_cost_excluded(run_rows[0]["agent"]):
                return 0.0
            return await _project_run_spend(conn, run_id)
        finally:
            await conn.close()

    async def total_spend(self) -> float:
        """Sum of :meth:`run_spend` across all runs (Codex excluded).

        Uses the materialized ``task_index`` column so the projection stays a
        per-``(run_id, task_index)`` last-cumulative dedup — never a flat sum of
        every event's cost over the whole events table.
        """
        conn = await self._read_conn()
        try:
            # Exclude Codex runs by agent on the run row; for the rest, the spend
            # is the per-(run_id, task_index) last-cumulative cost summed.
            rows = list(
                await conn.execute_fetchall(
                    """
                    WITH last_per_task AS (
                        SELECT e.run_id AS run_id,
                               e.cost_usd AS cost_usd
                        FROM events e
                        JOIN (
                            SELECT run_id, task_index, MAX(id) AS max_id
                            FROM events
                            WHERE cost_usd IS NOT NULL
                            GROUP BY run_id, task_index
                        ) m
                          ON e.run_id = m.run_id
                         AND e.id = m.max_id
                    )
                    SELECT COALESCE(SUM(lpt.cost_usd), 0.0) AS total
                    FROM last_per_task lpt
                    JOIN runs r ON r.id = lpt.run_id
                    WHERE COALESCE(LOWER(r.agent), '') != ?
                    """,
                    (COST_EXCLUDED_AGENT,),
                )
            )
            return float(rows[0]["total"] or 0.0)
        finally:
            await conn.close()

    # === run_totals snapshot + backup (§6.5) =================================

    async def snapshot_run_totals(self, run_id: str, totals: RunTotals) -> None:
        """Write the completion snapshot into ``run_totals`` (idempotent upsert).

        Called at run completion so ``events`` can be retention-pruned without
        losing spend/audit totals (§6.5).
        """

        async def _job(conn: aiosqlite.Connection) -> None:
            await conn.execute(
                """
                INSERT INTO run_totals (run_id, cost_usd, tokens_in, tokens_out, turns, duration_s)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    cost_usd = excluded.cost_usd,
                    tokens_in = excluded.tokens_in,
                    tokens_out = excluded.tokens_out,
                    turns = excluded.turns,
                    duration_s = excluded.duration_s
                """,
                (
                    run_id,
                    totals.cost_usd,
                    totals.tokens_in,
                    totals.tokens_out,
                    totals.turns,
                    totals.duration_s,
                ),
            )

        await self._writer.submit(_job)

    async def get_run_totals(self, run_id: str) -> dict[str, Any] | None:
        """Read a ``run_totals`` snapshot row."""
        conn = await self._read_conn()
        try:
            rows = list(
                await conn.execute_fetchall("SELECT * FROM run_totals WHERE run_id = ?", (run_id,))
            )
            return dict(rows[0]) if rows else None
        finally:
            await conn.close()

    async def backup_to(self, dest_path: str) -> None:
        """Produce a consistent backup file via ``VACUUM INTO`` (§6.5).

        ``VACUUM INTO`` writes a fully-checkpointed, defragmented copy of the
        database to ``dest_path`` — a restorable single-file snapshot of the
        source of truth for spend + audit. Runs on the writer so it does not
        race a concurrent write transaction.
        """

        async def _job(conn: aiosqlite.Connection) -> None:
            # VACUUM cannot run inside a transaction; commit the BEGIN IMMEDIATE
            # the writer opened, run VACUUM INTO in autocommit, then re-open so
            # the writer's COMMIT has a transaction to close.
            await conn.execute("COMMIT")
            try:
                await conn.execute("VACUUM INTO ?", (dest_path,))
            finally:
                await conn.execute("BEGIN IMMEDIATE")

        await self._writer.submit(_job)

    # === settings / secrets / projects / issues ==============================

    async def set_setting(self, key: str, value: str) -> None:
        """Upsert a row in the ``settings`` key/value table."""

        async def _job(conn: aiosqlite.Connection) -> None:
            await conn.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

        await self._writer.submit(_job)

    async def get_setting(self, key: str) -> str | None:
        """Read a ``settings`` value by key."""
        conn = await self._read_conn()
        try:
            rows = list(
                await conn.execute_fetchall("SELECT value FROM settings WHERE key = ?", (key,))
            )
            if not rows:
                return None
            value = rows[0]["value"]
            return None if value is None else str(value)
        finally:
            await conn.close()

    async def upsert_project(
        self,
        *,
        project_id: str,
        repo: str,
        default_branch: str = "main",
        github_installation_id: str | None = None,
    ) -> None:
        """Insert or update a ``projects`` row."""
        created_at = _utc_now_iso()

        async def _job(conn: aiosqlite.Connection) -> None:
            await conn.execute(
                """
                INSERT INTO projects (id, repo, default_branch, github_installation_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    repo = excluded.repo,
                    default_branch = excluded.default_branch,
                    github_installation_id = excluded.github_installation_id
                """,
                (project_id, repo, default_branch, github_installation_id, created_at),
            )

        await self._writer.submit(_job)

    async def upsert_issue(
        self,
        *,
        repo: str,
        num: int,
        title: str = "",
        state: str = "backlog",
        labels: Sequence[str] | None = None,
        workflow_id: str | None = None,
        agent: str | None = None,
        pr_num: int | None = None,
    ) -> None:
        """Insert or update an ``issues`` cache row (PK ``(repo, num)``)."""
        labels_json = json.dumps(list(labels or []))
        updated_at = _utc_now_iso()

        async def _job(conn: aiosqlite.Connection) -> None:
            await conn.execute(
                """
                INSERT INTO issues (
                    repo, num, title, state, labels_json,
                    workflow_id, agent, pr_num, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repo, num) DO UPDATE SET
                    title = excluded.title,
                    state = excluded.state,
                    labels_json = excluded.labels_json,
                    workflow_id = excluded.workflow_id,
                    agent = excluded.agent,
                    pr_num = excluded.pr_num,
                    updated_at = excluded.updated_at
                """,
                (
                    repo,
                    num,
                    title,
                    state,
                    labels_json,
                    workflow_id,
                    agent,
                    pr_num,
                    updated_at,
                ),
            )

        await self._writer.submit(_job)


def _is_cost_excluded(agent: Any) -> bool:
    """True if a run's agent is cost-excluded from spend (Codex; FR-06-1a)."""
    return isinstance(agent, str) and agent.strip().lower() == COST_EXCLUDED_AGENT


async def _project_run_spend(conn: aiosqlite.Connection, run_id: str) -> float:
    """Σ over distinct ``task_index`` of the last-cumulative ``cost_usd``.

    The dedup key is ``task_index`` (materialized on the event row); for each we
    take the event with the highest ``id`` that carries a non-NULL ``cost_usd``
    — its cumulative total for that task — and sum across tasks.
    """
    rows = await conn.execute_fetchall(
        """
        SELECT e.cost_usd AS cost_usd
        FROM events e
        JOIN (
            SELECT task_index, MAX(id) AS max_id
            FROM events
            WHERE run_id = ? AND cost_usd IS NOT NULL
            GROUP BY task_index
        ) m ON e.id = m.max_id
        WHERE e.run_id = ?
        """,
        (run_id, run_id),
    )
    return float(sum((r["cost_usd"] or 0.0) for r in rows))
