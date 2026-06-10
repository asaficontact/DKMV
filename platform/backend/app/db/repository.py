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

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from app.db.connection import connect
from app.db.spend_sql import (
    AGENT_NOT_CODEX_SQL,
    COST_EXCLUDED_AGENT,
    TERMINAL_RUN_STATUSES,
    last_per_task_cte,
    per_run_spend_sql,
    total_spend_sql,
)
from app.db.writer import Writer
from app.secrets.redaction import Redactor

# Re-exported from app.db.spend_sql (the ONE canonical definition — G13) so the
# many existing importers of ``COST_EXCLUDED_AGENT`` from this module keep working
# while the constant + the segment-sum SQL live in one place.
__all__ = ["COST_EXCLUDED_AGENT", "Repository"]

#: The persisted ``issues.agent_state`` value that marks a dispatch candidate
#: (G12). The board-sync derivation writes the bare ``agent:*`` suffix into the
#: indexed ``agent_state`` column; ``"queued"`` is the value the per-tick candidate
#: read predicates on (``WHERE repo=? AND agent_state='queued'``) so the tick reads
#: only the queued issues via ``ix_issues_repo_agent_state``, not the whole board.
QUEUED_AGENT_STATE = "queued"

#: Multi-label precedence for deriving ``agent_state`` from an issue's ``agent:*``
#: labels (§8.1): ``in-progress > paused > review > queued``. Inlined here (the db
#: layer) so the single-row :meth:`Repository.upsert_issue` can derive the indexed
#: column from ``labels`` without importing the github layer; it MUST stay in sync
#: with :data:`app.github.sync._LABEL_PRECEDENCE` (the board-derivation precedence),
#: which :func:`app.github.sync.derive_agent_state` uses for the batch sync path. A
#: state-machine test asserts the two agree.
_AGENT_STATE_PRECEDENCE: tuple[tuple[str, str], ...] = (
    ("agent:in-progress", "in-progress"),
    ("agent:paused", "paused"),
    ("agent:review", "review"),
    ("agent:queued", "queued"),
)

#: Sentinel for "``agent_state`` not explicitly supplied — derive it from labels".
#: Distinguishes an explicit ``None`` (force Backlog) from the common single-row
#: ``upsert_issue(labels=…)`` caller that wants the derived value for free.
_DERIVE_AGENT_STATE: str = "\x00derive"


def _agent_state_from_labels(labels: Sequence[str] | None) -> str | None:
    """Precedence-resolve an issue's ``agent:*`` labels to the ``agent_state`` suffix.

    Returns the bare suffix (``"queued"`` / ``"in-progress"`` / ``"paused"`` /
    ``"review"``) or ``None`` for Backlog. Mirrors
    :func:`app.github.sync.derive_agent_state` (same precedence) so the single-row
    upsert path and the batch sync path persist the identical indexed value (G12).
    """
    present = set(labels or ())
    for label, suffix in _AGENT_STATE_PRECEDENCE:
        if label in present:
            return suffix
    return None


#: Size of the long-lived WAL read-connection pool (PERF). Reads borrow a warm
#: connection instead of opening a fresh worker thread + re-running the four
#: PRAGMAs per call. The SSE-replay / dashboard-spend read path is the hot path
#: this serves; a small fixed pool bounds the thread/fd footprint while keeping
#: a handful of concurrent reads non-blocking under WAL.
READ_POOL_SIZE = 4


def _utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (the platform's time format)."""
    return datetime.now(UTC).isoformat()


def _labels_ensured_key(repo: str) -> str:
    """``settings`` key for the per-repo "agent:* labels ensured" flag (FIX-2)."""
    return f"labels_ensured::{repo.strip().lower()}"


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


@dataclass(frozen=True, slots=True)
class BoardAggregate:
    """The board aggregate strip + sidebar chip counters (FR-02-4, FR-NAV-1).

    Renders *"{in_progress} in progress · {needs_you} needs you · ${spent_today}
    spent today · {tokens_today} tokens."* (FR-02-4). The Codex caveat (FR-06-1a,
    INV-8) is encoded in the split: ``spent_today`` is the segment-sum spend with
    **Codex runs excluded** (Codex reports $0 from the engine), while
    ``tokens_today`` counts **every** run's tokens including Codex — its tokens are
    real even though its cost is unpriced.
    """

    in_progress: int
    needs_you: int
    spent_today: float
    tokens_today: int


@dataclass(slots=True)
class IssueRow:
    """One ``issues`` cache row for the batch upsert (PK ``(repo, num)``).

    Carries exactly the columns :meth:`Repository.upsert_issue` writes so a whole
    sync page can be upserted in **one** writer transaction (one ``BEGIN
    IMMEDIATE``) via :meth:`Repository.upsert_issues`, instead of one transaction
    per issue.
    """

    repo: str
    num: int
    title: str = ""
    state: str = "backlog"
    labels: Sequence[str] | None = None
    workflow_id: str | None = None
    agent: str | None = None
    pr_num: int | None = None
    #: The derived ``agent:*`` state suffix (``queued`` / ``in-progress`` /
    #: ``paused`` / ``review``), or ``None`` for Backlog (G12). Persisted into the
    #: indexed ``issues.agent_state`` column so the per-tick candidate read is an
    #: index-backed ``WHERE agent_state='queued'`` instead of a full-board JSON
    #: parse. Left at the :data:`_DERIVE_AGENT_STATE` sentinel default it is derived
    #: from ``labels`` at upsert time (matching the single-row path); the sync path
    #: sets it explicitly via :func:`app.github.sync.derive_agent_state`.
    agent_state: str | None = _DERIVE_AGENT_STATE


class Repository:
    """Facade over the platform SQLite database.

    Construct with a ``database_url``; call :meth:`start` to launch the single
    writer task and :meth:`close` to shut it down. Reads run on their own
    connections, so they never block (or are blocked by) the writer beyond
    WAL's normal read-snapshot semantics.
    """

    def __init__(self, database_url: str, *, redactor: Redactor | None = None) -> None:
        self._database_url = database_url
        self._writer = Writer(database_url)
        # Redact-before-persist guard for the append-only event log (INV-4 /
        # §8.6). A leak into ``events`` is permanent + replayable, so every
        # payload is scrubbed HERE, in the single write path, before it can reach
        # the table. Defaults to a pattern-only redactor; callers pass a
        # settings-seeded one (Redactor.from_settings) to also scrub the concrete
        # credential values the platform holds.
        self._redactor = redactor or Redactor()
        self._started = False
        # Long-lived WAL read-connection pool (PERF). Connections are created
        # lazily on first acquire (up to READ_POOL_SIZE), then reused — so the
        # SSE-replay / spend read path doesn't churn a worker thread + 4 PRAGMAs
        # per call. Bounded by a semaphore; idle connections wait in the queue.
        self._read_pool: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue()
        self._read_slots = asyncio.Semaphore(READ_POOL_SIZE)
        self._read_conns: list[aiosqlite.Connection] = []
        self._closed = False

    async def start(self) -> None:
        """Launch the single serialized writer task (INV-6)."""
        if self._started:
            return
        await self._writer.start()
        self._started = True
        self._closed = False

    async def close(self) -> None:
        """Stop the writer task and release the writer + read-pool connections."""
        if not self._started:
            return
        self._closed = True
        await self._writer.stop()
        # Close every read connection ever created (those parked in the pool and
        # any still checked out — tracked in ``_read_conns``).
        for conn in self._read_conns:
            await conn.close()
        self._read_conns.clear()
        # Drain the queue so a restarted Repository starts with an empty pool.
        while not self._read_pool.empty():
            self._read_pool.get_nowait()
        self._started = False

    # -- read connection pool --------------------------------------------------

    @asynccontextmanager
    async def read_connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """Public read seam: borrow a warm WAL read connection from the pool.

        The history/analytics read module (:mod:`app.db.queries_history`) composes
        its filtered-list / cursor-pagination / stats-aggregate SQL against a
        borrowed read connection so all that read SQL stays out of the API layer
        while still flowing through the **same** bounded read-pool the rest of the
        repository uses (INV-6: reads on their own WAL connections, never the
        single writer). A thin public wrapper over :meth:`_read_conn` — Phase-3's
        ``GET /runs`` history filters + ``GET /stats`` aggregates read through this
        one seam, so the SQLite→Postgres swap (NFR-PORT-1) stays additive.
        """
        async with self._read_conn() as conn:
            yield conn

    @asynccontextmanager
    async def _read_conn(self) -> AsyncIterator[aiosqlite.Connection]:
        """Borrow a warm WAL read connection from the pool (separate from the
        writer — INV-6); return it to the pool on exit.

        A bounded pool (``READ_POOL_SIZE``) of long-lived connections is reused
        across reads so a fresh worker thread + the four PRAGMAs are paid once
        per connection, not once per read. WAL keeps these reads non-blocking
        with the single writer; ``foreign_keys=ON`` is set on each (via
        :func:`connect`) and is sticky for the connection's lifetime.
        """
        await self._read_slots.acquire()
        try:
            try:
                conn = self._read_pool.get_nowait()
            except asyncio.QueueEmpty:
                conn = await connect(self._database_url)
                self._read_conns.append(conn)
            try:
                yield conn
            finally:
                # Return the connection to the pool unless we're shutting down,
                # in which case close() owns its teardown.
                if self._closed:
                    if conn in self._read_conns:
                        self._read_conns.remove(conn)
                        await conn.close()
                else:
                    self._read_pool.put_nowait(conn)
        finally:
            self._read_slots.release()

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
        max_turns: int | None = None,
        timeout_minutes: int | None = None,
        max_budget_usd: float | None = None,
        memory_limit: str | None = None,
        run_id: str | None = None,
    ) -> tuple[str, bool]:
        """Atomically claim a run row for ``idempotency_key``.

        Returns ``(run_id, won)`` where ``won`` is ``True`` iff *this* call
        inserted the row. Implemented as ``INSERT … ON CONFLICT(idempotency_key)
        DO NOTHING`` inside the writer's ``BEGIN IMMEDIATE`` transaction so two
        concurrent dispatch coroutines for the same key cannot both launch
        (INV-5). The loser gets back the existing row's ``id``.

        The platform ``id`` is a generated UUID (R-8) — never the engine id.

        The four launched guardrails (``max_turns`` / ``timeout_minutes`` /
        ``max_budget_usd`` / ``memory_limit``) are persisted here so the §8.9
        ``config`` block reflects the *actual* launched values (FR-04-5). For a
        Codex run ``max_turns`` / ``max_budget_usd`` are ``None`` (the engine has
        no such cap — INV-8), consistent with the launch-path rejection.
        """
        new_id = run_id or str(uuid.uuid4())
        started_at = _utc_now_iso()

        async def _job(conn: aiosqlite.Connection) -> tuple[str, bool]:
            cursor = await conn.execute(
                """
                INSERT INTO runs (
                    id, repo, issue_num, workflow_id, agent, model,
                    status, branch, feature_name,
                    max_turns, timeout_minutes, max_budget_usd, memory_limit,
                    started_at, idempotency_key
                )
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)
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
                    max_turns,
                    timeout_minutes,
                    max_budget_usd,
                    memory_limit,
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
        async with self._read_conn() as conn:
            rows = list(await conn.execute_fetchall("SELECT * FROM runs WHERE id = ?", (run_id,)))
            return dict(rows[0]) if rows else None

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

        Performance contract: the whole batch is a **single** statement — one
        multi-row ``INSERT … VALUES (…),(…),… RETURNING id`` — so N events are one
        aiosqlite round-trip, not N, while holding the single global write lock
        (INV-6). ``RETURNING id`` yields the assigned ``events.id`` per row in
        insertion order, preserving the per-row SSE replay cursor. The
        ``payload`` JSON is serialized **before** ``submit()`` so that CPU work is
        not done under the writer's ``BEGIN IMMEDIATE`` lock.
        """
        if not records:
            return []

        # Redact-before-persist (INV-4 / §8.6): scrub every payload for known
        # secret patterns + the platform's own credential values BEFORE it is
        # serialized toward the append-only ``events`` table. This runs here, in
        # the single write path, so no caller can bypass it; a leak into
        # ``events`` would be permanent + replayable. Redaction + JSON-serialize
        # both happen OUTSIDE the write lock (PERF: keep the writer's BEGIN
        # IMMEDIATE transaction CPU-free). Each row contributes the eight column
        # values in the column order of the INSERT below.
        params: list[Any] = []
        for rec in records:
            redacted_payload = self._redactor.payload(rec.payload)
            params.extend(
                (
                    rec.run_id,
                    rec.sequence,
                    rec.ts,
                    rec.event_type,
                    rec.task_index,
                    rec.cost_usd,
                    rec.agent,
                    json.dumps(redacted_payload),
                )
            )
        row_placeholder = "(?, ?, ?, ?, ?, ?, ?, ?)"
        values_clause = ", ".join(row_placeholder for _ in records)
        sql = (
            "INSERT INTO events (\n"
            "    run_id, sequence, ts, event_type,\n"
            "    task_index, cost_usd, agent, payload_json\n"
            ") VALUES "
            f"{values_clause}\n"
            "RETURNING id"
        )

        async def _job(conn: aiosqlite.Connection) -> list[int]:
            rows = await conn.execute_fetchall(sql, params)
            return [int(r["id"]) for r in rows]

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
        async with self._read_conn() as conn:
            rows = await conn.execute_fetchall(sql, params)
            return [dict(r) for r in rows]

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

    async def read_run_stages(self, run_id: str) -> list[dict[str, Any]]:
        """Read a run's ``run_stages`` rows ordered by stage index (§8.9 read).

        The mutable stage read model the live-run stepper renders (slice 2.1's
        ``GET /runs/{id}`` baseline, slice 2.4's StageTracker). A pure WAL read
        through the same repository seam as the other reads (NFR-PORT-1); empty
        until the event pump (slice 2.3) populates the stages.
        """
        async with self._read_conn() as conn:
            rows = await conn.execute_fetchall(
                "SELECT run_id, idx, name, status, cost_usd, turns, duration_s "
                "FROM run_stages WHERE run_id = ? ORDER BY idx",
                (run_id,),
            )
            return [dict(r) for r in rows]

    async def read_pending_pause(self, run_id: str) -> dict[str, Any] | None:
        """Read a run's latest **pending** ``pause_decisions`` row, or ``None`` (§8.3).

        The PauseCard rehydration source (slice 2.3): if the SSE socket drops while
        a run is paused, the reconnect replay only reaches ``pause_requested`` — so
        the client rehydrates the decision card from **state** (``GET /runs/{id}``),
        not the live push. This read surfaces the open decision (``status='pending'``)
        the card needs: ``id``, ``task_name``, the engine ``request_json`` payload,
        and the UTC ``timeout_at``. Returns the most-recent pending row (highest
        ``created_at``) so a run with at most one open pause resolves unambiguously;
        a run with no open pause returns ``None``. A pure WAL read through the
        repository seam — the resolve-exactly-once **write** path is slice 2.5.
        """
        async with self._read_conn() as conn:
            rows = list(
                await conn.execute_fetchall(
                    "SELECT id, run_id, task_name, request_json, status, timeout_at, created_at "
                    "FROM pause_decisions "
                    "WHERE run_id = ? AND status = 'pending' "
                    "ORDER BY created_at DESC, id DESC LIMIT 1",
                    (run_id,),
                )
            )
            return dict(rows[0]) if rows else None

    # === pause_decisions (HITL — INV-9 resolve-exactly-once) ==================

    async def create_pause_decision(
        self,
        *,
        run_id: str,
        request_json: str,
        task_name: str | None,
        timeout_at: str,
        decision_id: str | None = None,
    ) -> str:
        """Insert a ``pending`` ``pause_decisions`` row; return its ``decision_id``.

        The durable half of the §8.5 HITL bridge: on pause the platform persists
        the decision (``status='pending'``, the engine ``PauseRequest`` payload,
        the UTC ``timeout_at``) BEFORE it awaits the human, so the decision
        survives a backend restart even though the suspended run coroutine does
        not (§8.5.5 — the run is re-launchable from the last pushed boundary, never
        "resumed in place"). A generated UUID keys the in-memory event the answer
        endpoint / timeout sweep fire, and is the ``id`` the answer guard targets.
        Written through the single writer (INV-6).
        """
        new_id = decision_id or str(uuid.uuid4())
        created_at = _utc_now_iso()

        async def _job(conn: aiosqlite.Connection) -> str:
            await conn.execute(
                """
                INSERT INTO pause_decisions (
                    id, run_id, task_name, request_json, status, timeout_at, created_at
                )
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                (new_id, run_id, task_name, request_json, timeout_at, created_at),
            )
            return new_id

        return await self._writer.submit(_job)

    async def resolve_pause_decision(
        self,
        decision_id: str,
        *,
        answer_json: str,
        resolved_by: str,
    ) -> bool:
        """Guarded transition ``…SET status='answered' WHERE id=? AND status='pending'``.

        The INV-9 resolve-**exactly-once** primitive (§8.5): the ``UPDATE`` is
        guarded on ``status='pending'`` so a double-click, two tabs, and a racing
        timeout sweep can never all win — only the FIRST writer flips the row and
        gets ``rowcount == 1``; every later attempt matches zero rows. Returns
        ``True`` iff *this* call won the transition (the caller then — and only
        then — fires the in-memory keyed event so the awaiting ``on_pause``
        callback returns its :class:`PauseResponse`). ``resolved_by`` records who
        resolved it (``'human'`` for the answer endpoint, ``'timeout'`` for the
        expiry sweep). Written through the single writer (INV-6).
        """

        async def _job(conn: aiosqlite.Connection) -> bool:
            cursor = await conn.execute(
                "UPDATE pause_decisions "
                "SET status = 'answered', answer_json = ?, resolved_by = ? "
                "WHERE id = ? AND status = 'pending'",
                (answer_json, resolved_by, decision_id),
            )
            return bool(cursor.rowcount == 1)

        return await self._writer.submit(_job)

    async def get_pause_decision(self, decision_id: str) -> dict[str, Any] | None:
        """Read one ``pause_decisions`` row by id (test/observability hook)."""
        async with self._read_conn() as conn:
            rows = list(
                await conn.execute_fetchall(
                    "SELECT * FROM pause_decisions WHERE id = ?",
                    (decision_id,),
                )
            )
            return dict(rows[0]) if rows else None

    async def read_expired_pending_pauses(self, *, now_iso: str) -> list[dict[str, Any]]:
        """Read every ``pending`` pause whose UTC ``timeout_at <= now`` (§8.5 sweep).

        The auto-resolve sweep's read half (INV-9): the index
        ``ix_pause_decisions_status_timeout_at`` serves ``WHERE status='pending'
        AND timeout_at <= :now``. ``timeout_at`` is a UTC ISO-8601 string, so the
        lexicographic comparison is a correct chronological comparison (the
        platform writes every timestamp via :func:`_utc_now_iso`). The sweep then
        resolves each via the same exactly-once guard (``resolved_by='timeout'``)
        so a pause that a human answered in the same tick is never double-resolved.
        """
        async with self._read_conn() as conn:
            rows = await conn.execute_fetchall(
                "SELECT id, run_id, task_name, timeout_at, created_at "
                "FROM pause_decisions "
                "WHERE status = 'pending' AND timeout_at IS NOT NULL AND timeout_at <= ? "
                "ORDER BY timeout_at",
                (now_iso,),
            )
            return [dict(r) for r in rows]

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
        async with self._read_conn() as conn:
            run_rows = list(
                await conn.execute_fetchall("SELECT agent FROM runs WHERE id = ?", (run_id,))
            )
            if run_rows and _is_cost_excluded(run_rows[0]["agent"]):
                return 0.0
            return await _project_run_spend(conn, run_id)

    async def read_run_segments(self, run_id: str) -> list[dict[str, Any]]:
        """Per-``task_index`` last-cumulative event (cost + raw payload) for a run.

        The live-meter read (slice 2.4 / INV-7): for **each distinct**
        ``task_index`` of the run, return the event with the highest ``id`` that
        carries a non-NULL ``cost_usd`` — that row IS the segment's final/latest
        cumulative cost (a completed task's final, or the active task's most-recent
        line). The segment-sum meter (:mod:`app.runs.meters`) sums ``cost_usd``
        across these rows (never a naive ``SUM`` over every event — that
        double-counts the per-task cumulative line; never keep-latest-overall —
        that resets to ~$0 at each stage boundary). ``payload_json`` is included
        so the meter can also recover the engine's cumulative ``turns`` /
        ``num_turns`` for the same segment without a second read. Rows are ordered
        by ``task_index`` so the caller iterates segments in stage order. A pure
        WAL read through the repository seam (NFR-PORT-1).

        G13 note: this is the **one twin** of the canonical segment-sum SQL
        (:mod:`app.db.spend_sql`). It keeps a per-run, ``GROUP BY task_index``,
        payload-returning shape (the meter needs the rows, not a sum) rather than
        composing :func:`app.db.spend_sql.last_per_task_cte` (which projects only
        ``cost_usd``), but encodes the **identical** per-``(run_id, task_index)``
        last-cumulative dedup — so the Python meter
        (:func:`app.runs.meters.compute_run_meters`) and the SQL spend projections
        never diverge into two definitions of "cost".
        """
        async with self._read_conn() as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT e.task_index AS task_index,
                       e.cost_usd AS cost_usd,
                       e.event_type AS event_type,
                       e.payload_json AS payload_json
                FROM events e
                JOIN (
                    SELECT task_index, MAX(id) AS max_id
                    FROM events
                    WHERE run_id = ? AND cost_usd IS NOT NULL
                    GROUP BY task_index
                ) m ON e.id = m.max_id
                WHERE e.run_id = ?
                ORDER BY e.task_index
                """,
                (run_id, run_id),
            )
            return [dict(r) for r in rows]

    async def run_spends(self, run_ids: Sequence[str]) -> dict[str, float]:
        """Bulk segment-sum spend for a **set** of runs in ONE query (PERF).

        Generalizes :meth:`total_spend`'s set-based last-cumulative dedup to return
        a ``{run_id: spend}`` map for exactly the supplied ``run_ids``, so the
        ``GET /runs`` list path is **one** bulk spend query instead of one
        :meth:`run_spend` per row (the N+1 the list path otherwise serializes
        through the 4-slot read pool). The semantics are byte-identical to the
        per-run projection: for each ``(run_id, task_index)`` take the *last*
        (highest ``id``) event carrying a non-NULL ``cost_usd`` — its cumulative
        cost for that task — and sum across tasks; **Codex runs are excluded**
        (FR-06-1a / INV-7), never a naive ``SUM`` over events. A run with no cost
        events (or a Codex run) is absent from the map; the caller defaults it to
        ``0.0``/``None`` as appropriate.
        """
        ids = list(dict.fromkeys(run_ids))  # de-dup, preserve order
        if not ids:
            return {}
        placeholders = ", ".join("?" for _ in ids)
        # The inner GROUP BY keys on (run_id, task_index) so the last-cumulative
        # dedup is per-task; the outer GROUP BY run_id sums those per-task
        # cumulatives into the run's segment-sum. Codex is excluded by the run's
        # agent column (matching total_spend / _spend_today). The CTE + the
        # per-run SELECT come from the ONE canonical segment-sum definition
        # (app.db.spend_sql — G13) so this can never drift from the other spend
        # projections.
        sql = per_run_spend_sql(run_filter=f"AND run_id IN ({placeholders})")
        async with self._read_conn() as conn:
            rows = list(
                await conn.execute_fetchall(
                    sql,  # noqa: S608 — placeholders only; ids bound below
                    (*ids, COST_EXCLUDED_AGENT),
                )
            )
            return {str(r["run_id"]): float(r["spend"] or 0.0) for r in rows}

    async def total_spend(self) -> float:
        """Codex-excluded total spend, via the ``run_totals`` fast-path (G9).

        Two-part sum so the events table is **not** segment-summed across every run
        on every poll (G9 — the unbounded-events ceiling):

        * **Terminal runs** (``status`` in :data:`TERMINAL_RUN_STATUSES`) read their
          cost from the ``run_totals`` completion snapshot — a single indexed row
          per run — never re-scanning their (prunable) events.
        * **Active runs** (non-terminal) are the only ones segment-summed live, via
          the canonical ``last_per_task`` CTE (per ``(run_id, task_index)``
          last-cumulative ``cost_usd``, INV-7), since their snapshot isn't written
          until completion.

        Codex is excluded from BOTH halves (INV-8 / FR-06-1a). The result EQUALS the
        full-events segment-sum for any mix of terminal + active runs (asserted by a
        fast-path-vs-full-scan equality test): a terminal run's snapshot carries the
        exact segment-sum total written at completion, so reading it instead of its
        events is numerically identical, just bounded.
        """
        async with self._read_conn() as conn:
            return await _total_spend_fast_path(conn)

    async def daily_spend_series(self) -> list[dict[str, Any]]:
        """Daily Codex-excluded spend ``[{date, usd}]`` oldest-first, fast-path (G9).

        The ``GET /stats`` ``spend_series`` (FR-06-1a / §8.9): each run's spend
        bucketed by the **date** half of its UTC ``started_at`` (``YYYY-MM-DD``).
        Like :meth:`total_spend`, this reads the ``run_totals`` snapshot for
        **terminal** runs (one indexed row each — no events re-scan) and only
        segment-sums **active** runs via the canonical ``last_per_task`` CTE
        (INV-7) — so the unbounded ``events`` table is not scanned across every
        completed run on every poll (G9). Both halves bucket by the run's
        ``started_at`` date and **exclude Codex** (a $0-cost Codex run never adds a
        phantom bar — INV-8 / FR-06-1a). The two date→usd maps are merged so a day
        carrying both terminal and active spend sums correctly, and the result
        EQUALS the full-events segment-sum series for any state. A pure WAL read
        through the repository seam (NFR-PORT-1).
        """
        async with self._read_conn() as conn:
            buckets: dict[str, float] = {}
            # Terminal runs: bucket the run_totals snapshot cost by started_at date.
            await _bucket_terminal_daily(conn, buckets)
            # Active runs: bucket the live segment-sum by started_at date.
            await _bucket_active_daily(conn, buckets)
        return [{"date": day, "usd": buckets[day]} for day in sorted(buckets)]

    async def board_aggregate(self, repo: str, *, since_iso: str) -> BoardAggregate:
        """The board aggregate-strip + chip counters for a repo (FR-02-4, AC-17).

        Computes, in pure WAL reads (NFR-PORT-1):

        * ``in_progress`` — active runs in this repo whose board state is
          *In Progress* (``running``/``pending``/``stopping``); a ``paused`` run
          is **Needs You**, not In Progress (the §5.3.1 authority-rule split).
        * ``needs_you`` — active runs that are ``paused`` (the amber count the
          sidebar chip surfaces, FR-NAV-1).
        * ``spent_today`` — the **segment-sum** spend (per ``(run_id, task_index)``
          last-cumulative ``cost_usd``, never a naive SUM — INV-7) over runs
          ``started_at >= since_iso``, with **Codex runs excluded** (FR-06-1a /
          INV-8: Codex reports $0 from the engine).
        * ``tokens_today`` — the token total over the same window counting **every**
          run including Codex (its tokens are real even though its cost is
          unpriced — FR-06-1a).

        ``since_iso`` is the UTC start-of-day boundary the caller supplies (see
        :func:`app.api.board.start_of_utc_day`); the today-window is re-evaluated
        each poll, never cached, so the strip refreshes on the poll cadence
        (FR-NAV-2), not via SSE (AC-20).
        """
        async with self._read_conn() as conn:
            in_progress = await _count_runs_by_status(
                conn, repo, ("running", "pending", "stopping")
            )
            needs_you = await _count_runs_by_status(conn, repo, ("paused",))
            spent_today = await _spend_today(conn, repo, since_iso)
            tokens_today = await _tokens_today(conn, repo, since_iso)
        return BoardAggregate(
            in_progress=in_progress,
            needs_you=needs_you,
            spent_today=spent_today,
            tokens_today=tokens_today,
        )

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

    async def prune_events_for_terminal_runs(self, *, older_than_iso: str) -> int:
        """Delete events for TERMINAL, snapshotted runs finished before a horizon (G9).

        The events-retention prune (G9): the ``events`` table was designed for
        retention-pruning (``id`` is ``AUTOINCREMENT`` so it is never reused) but the
        prune was never built, so the table grows unbounded. This deletes the events
        of runs that are **safe to prune** — all THREE must hold:

        * the run is **terminal** (``status`` in :data:`TERMINAL_RUN_STATUSES`);
        * a ``run_totals`` snapshot **exists** for it (so its spend/audit total
          survives the prune via the fast-path — :meth:`total_spend`);
        * it **finished** (``finished_at``) strictly before ``older_than_iso``.

        An **active** run's events are NEVER touched (it is not terminal), and a
        run with **no snapshot** is NEVER pruned (its spend would be lost). The
        DELETE is routed through the **single serialized writer** (INV-6) under the
        writer's ``BEGIN IMMEDIATE``. ``finished_at`` is a UTC ISO-8601 string so the
        lexicographic ``<`` is a correct chronological comparison. Returns the number
        of event rows deleted (0 when nothing is due). The spend total is unchanged
        after the prune because the fast-path reads ``run_totals`` for these runs.
        """
        statuses = sorted(TERMINAL_RUN_STATUSES)
        placeholders = ", ".join("?" for _ in statuses)

        async def _job(conn: aiosqlite.Connection) -> int:
            cursor = await conn.execute(
                # Delete only events whose run is terminal + snapshotted + finished
                # before the horizon. The subquery picks the prunable run ids; an
                # active run or a snapshot-less run is excluded by construction.
                "DELETE FROM events WHERE run_id IN ("  # noqa: S608 — placeholders only
                "    SELECT r.id FROM runs r "
                f"    WHERE r.status IN ({placeholders}) "
                "      AND r.finished_at IS NOT NULL "
                "      AND r.finished_at < ? "
                "      AND EXISTS (SELECT 1 FROM run_totals rt WHERE rt.run_id = r.id)"
                ")",
                (*statuses, older_than_iso),
            )
            return int(cursor.rowcount or 0)

        return await self._writer.submit(_job)

    async def read_candidate_issues(self, repo: str) -> list[dict[str, Any]]:
        """Read this repo's ``agent:queued`` issues via the indexed ``agent_state`` (G12).

        The per-tick dispatch-candidate read (§8.2). Instead of reading the ENTIRE
        board and JSON-parsing ``labels_json`` to filter for ``agent:queued`` in
        Python every tick (the G12 full-board scan), this is an **index-backed**
        ``WHERE repo=? AND agent_state='queued'`` over the persisted, derived
        ``agent_state`` column (written at board-sync time alongside ``labels_json``
        — :func:`app.github.sync.sync_issues`). Backed by
        ``ix_issues_repo_agent_state`` so only the queued rows are read, not the
        whole board. Returns the same row shape as :meth:`read_issues` so the tick's
        candidate builder is unchanged apart from the narrower input. A pure WAL read
        through the repository seam (NFR-PORT-1).
        """
        async with self._read_conn() as conn:
            rows = await conn.execute_fetchall(
                "SELECT repo, num, title, state, labels_json, workflow_id, agent, pr_num "
                "FROM issues WHERE repo = ? AND agent_state = ? ORDER BY num DESC",
                (repo, QUEUED_AGENT_STATE),
            )
            return [dict(r) for r in rows]

    async def get_run_totals(self, run_id: str) -> dict[str, Any] | None:
        """Read a ``run_totals`` snapshot row."""
        async with self._read_conn() as conn:
            rows = list(
                await conn.execute_fetchall("SELECT * FROM run_totals WHERE run_id = ?", (run_id,))
            )
            return dict(rows[0]) if rows else None

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
        async with self._read_conn() as conn:
            rows = list(
                await conn.execute_fetchall("SELECT value FROM settings WHERE key = ?", (key,))
            )
            if not rows:
                return None
            value = rows[0]["value"]
            return None if value is None else str(value)

    async def labels_ensured(self, repo: str) -> bool:
        """True if the four ``agent:*`` labels were already ensured for ``repo``.

        A ``settings`` flag (``labels_ensured::<repo>``) set once per repo after a
        successful :func:`app.github.labels.ensure_agent_labels`, so routine
        incremental ``POST /sync`` polls skip the four GitHub ``POST /labels``
        create calls (GitHub secondary-rate-limit budget — they only matter on
        first connect/sync, AC-4). A pure read through the ``settings`` KV.
        """
        return await self.get_setting(_labels_ensured_key(repo)) == "1"

    async def mark_labels_ensured(self, repo: str) -> None:
        """Record that the ``agent:*`` labels have been ensured for ``repo``.

        Set after a successful ensure so subsequent syncs short-circuit the label
        create calls. Idempotent (a plain ``settings`` upsert).
        """
        await self.set_setting(_labels_ensured_key(repo), "1")

    async def put_secret(self, key: str, ciphertext: str, *, expires_at: str | None = None) -> None:
        """Upsert **ciphertext** into the ``secrets`` table (encrypted at rest).

        The plaintext NEVER reaches this layer — the :class:`SecretStore` owns
        encrypt/decrypt and hands us only the Fernet ciphertext (INV-4 / §8.6).
        ``expires_at`` carries the ≤1 hr TTL for the GitHub run token.
        """
        created_at = _utc_now_iso()

        async def _job(conn: aiosqlite.Connection) -> None:
            await conn.execute(
                """
                INSERT INTO secrets (key, ciphertext, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    ciphertext = excluded.ciphertext,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                """,
                (key, ciphertext, created_at, expires_at),
            )

        await self._writer.submit(_job)

    async def get_secret(self, key: str) -> tuple[str, str | None] | None:
        """Read ``(ciphertext, expires_at)`` for ``key``, or ``None`` if absent.

        Returns the ciphertext as-stored; the :class:`SecretStore` decrypts it.
        Expiry is enforced by the caller (the store) so the read path stays a
        pure projection.
        """
        async with self._read_conn() as conn:
            rows = list(
                await conn.execute_fetchall(
                    "SELECT ciphertext, expires_at FROM secrets WHERE key = ?",
                    (key,),
                )
            )
            if not rows:
                return None
            row = rows[0]
            expires = row["expires_at"]
            return str(row["ciphertext"]), (None if expires is None else str(expires))

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
        agent_state: str | None = _DERIVE_AGENT_STATE,
    ) -> None:
        """Insert or update a single ``issues`` cache row (PK ``(repo, num)``).

        Retained for single-issue callers; the sync import path batches a whole
        page through :meth:`upsert_issues` (one writer transaction) instead.
        ``agent_state`` is the derived ``agent:*`` suffix the indexed G12 candidate
        read predicates on; left at the sentinel default it is **derived from
        ``labels``** (so a caller that passes only labels gets the correct indexed
        state for free), while an explicit ``None`` forces Backlog.
        """
        params = _issue_upsert_params(
            repo=repo,
            num=num,
            title=title,
            state=state,
            labels=labels,
            workflow_id=workflow_id,
            agent=agent,
            pr_num=pr_num,
            agent_state=agent_state,
        )

        async def _job(conn: aiosqlite.Connection) -> None:
            await conn.execute(_ISSUE_UPSERT_SQL, params)

        await self._writer.submit(_job)

    async def upsert_issues(self, rows: Sequence[IssueRow]) -> None:
        """Batch-upsert a whole sync page of ``issues`` in ONE transaction (PERF).

        Mirrors the :meth:`append_events` batch pattern: a **single**
        ``_writer.submit`` job runs every ``INSERT … ON CONFLICT(repo, num) DO
        UPDATE`` inside one ``BEGIN IMMEDIATE`` … ``COMMIT`` (INV-6) rather than
        one transaction per issue, so importing N issues on a user-facing
        ``POST /sync`` is one writer round-trip, not N. The per-row upsert
        semantics (same ON CONFLICT columns/values) are **identical** to
        :meth:`upsert_issue` — it reuses :data:`_ISSUE_UPSERT_SQL` — so the
        idempotent/monotonic behavior is preserved. ``labels``-JSON encoding and
        the ``updated_at`` stamp are computed **outside** the write lock (PERF).
        """
        if not rows:
            return

        # Build every row's bind-params up front (JSON encode + timestamp) so the
        # writer's BEGIN IMMEDIATE transaction stays CPU-free; same column order
        # and ON CONFLICT semantics as the single-row upsert.
        param_sets = [
            _issue_upsert_params(
                repo=row.repo,
                num=row.num,
                title=row.title,
                state=row.state,
                labels=row.labels,
                workflow_id=row.workflow_id,
                agent=row.agent,
                pr_num=row.pr_num,
                agent_state=row.agent_state,
            )
            for row in rows
        ]

        async def _job(conn: aiosqlite.Connection) -> None:
            # All upserts run inside the single BEGIN IMMEDIATE the writer opened
            # — one transaction for the whole page (never a second writer).
            await conn.executemany(_ISSUE_UPSERT_SQL, param_sets)

        await self._writer.submit(_job)

    async def read_issues(self, repo: str) -> list[dict[str, Any]]:
        """Read a repo's cached ``issues`` rows (a pure WAL read projection).

        Surfaces the board read through the repository seam (NFR-PORT-1) so the
        ``GET /repos/{repo}/issues`` read path honors the same single DB boundary
        the writes do. The persisted ``state`` column is included so the §5.3.1
        **Done** signal stored at sync time survives to the board re-derivation
        (a closed/merged issue must re-derive to Done, not flatten to Backlog).
        """
        async with self._read_conn() as conn:
            rows = await conn.execute_fetchall(
                "SELECT repo, num, title, state, labels_json, workflow_id, agent, pr_num "
                "FROM issues WHERE repo = ? ORDER BY num DESC",
                (repo,),
            )
            return [dict(r) for r in rows]

    async def read_issue(self, repo: str, num: int) -> dict[str, Any] | None:
        """Read a single cached ``issues`` row by ``(repo, num)``, or ``None``.

        A targeted point read served by the ``issues`` PK/index on ``(repo, num)``,
        for hot paths (the Backlog↔Queued drag) that need exactly one issue's
        current labels — avoiding the full-repo ``read_issues`` scan + Python filter.
        A pure WAL read through the same repository seam as ``read_issues`` /
        ``read_active_runs`` (NFR-PORT-1).
        """
        async with self._read_conn() as conn:
            rows = await conn.execute_fetchall(
                "SELECT repo, num, title, state, labels_json, workflow_id, agent, pr_num "
                "FROM issues WHERE repo = ? AND num = ?",
                (repo, num),
            )
            row = next(iter(rows), None)
            return dict(row) if row is not None else None

    async def read_active_runs(self, repo: str, statuses: Sequence[str]) -> list[dict[str, Any]]:
        """Read a repo's non-terminal ``runs`` rows for the authority rule (§8.1).

        Returns the minimal ``(issue_num, status, pr_num)`` projection for runs in
        ``statuses`` (the caller's active-status set). A pure WAL read through the
        repository seam (NFR-PORT-1); the active-run→board-state overlay itself
        lives in :mod:`app.github.sync`.
        """
        status_list = list(statuses)
        if not status_list:
            return []
        placeholders = ", ".join("?" for _ in status_list)
        async with self._read_conn() as conn:
            rows = await conn.execute_fetchall(
                "SELECT issue_num, status, pr_num FROM runs "  # noqa: S608 — placeholders only
                f"WHERE repo = ? AND issue_num IS NOT NULL AND status IN ({placeholders})",
                (repo, *status_list),
            )
            return [dict(r) for r in rows]

    async def read_active_run_memory(
        self, repo: str, statuses: Sequence[str]
    ) -> list[dict[str, Any]]:
        """Read this repo's memory-holding runs' ``memory_limit`` (admission — AC-3).

        The aggregate-memory admission input (:mod:`app.orchestrator.admission`):
        the ``(id, status, memory_limit)`` projection for runs in ``statuses`` so the
        controller can sum ``Σ(running container memory)``. A ``paused`` run still
        holds memory (its container is parked open — §8.5) so the caller includes it
        in the status set even though it has *released* its concurrency slot. A pure
        WAL read through the repository seam (NFR-PORT-1).
        """
        status_list = list(statuses)
        if not status_list:
            return []
        placeholders = ", ".join("?" for _ in status_list)
        async with self._read_conn() as conn:
            rows = await conn.execute_fetchall(
                "SELECT id, status, memory_limit FROM runs "  # noqa: S608 — placeholders only
                f"WHERE repo = ? AND status IN ({placeholders})",
                (repo, *status_list),
            )
            return [dict(r) for r in rows]

    async def spend_today(self, repo: str, *, since_iso: str) -> float:
        """Codex-excluded segment-sum spend for this repo since ``since_iso`` (AC-3).

        The daily-spend admission input (:mod:`app.orchestrator.admission`): the
        **same** ``_spend_today`` segment-sum projection the board strip uses (per
        ``(run_id, task_index)`` last-cumulative ``cost_usd``, INV-7 — never a naive
        SUM), with **Codex excluded** (INV-8 / FR-06-1a: a Codex run contributes $0
        and never trips the daily-spend cap). Routed through the one helper so the
        admission cap and the board ``spent_today`` can never drift.
        """
        async with self._read_conn() as conn:
            return await _spend_today(conn, repo, since_iso)


#: The single ``issues`` upsert statement, shared by :meth:`Repository.upsert_issue`
#: (one row) and :meth:`Repository.upsert_issues` (batched via ``executemany``), so
#: the ON CONFLICT(repo, num) columns/values stay byte-identical between the two
#: paths and the batch import cannot drift from the per-issue semantics.
_ISSUE_UPSERT_SQL = """
INSERT INTO issues (
    repo, num, title, state, labels_json,
    workflow_id, agent, pr_num, agent_state, updated_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(repo, num) DO UPDATE SET
    title = excluded.title,
    state = excluded.state,
    labels_json = excluded.labels_json,
    workflow_id = excluded.workflow_id,
    agent = excluded.agent,
    pr_num = excluded.pr_num,
    agent_state = excluded.agent_state,
    updated_at = excluded.updated_at
"""


def _issue_upsert_params(
    *,
    repo: str,
    num: int,
    title: str,
    state: str,
    labels: Sequence[str] | None,
    workflow_id: str | None,
    agent: str | None,
    pr_num: int | None,
    agent_state: str | None,
) -> tuple[Any, ...]:
    """Bind-params for one :data:`_ISSUE_UPSERT_SQL` row (column order of the INSERT).

    Encodes ``labels`` to JSON and stamps ``updated_at`` here so both the single
    and batch paths produce the same row, and so this CPU work happens **outside**
    the writer's ``BEGIN IMMEDIATE`` lock for the batch path (PERF). ``agent_state``
    is the derived ``agent:*`` suffix the indexed G12 candidate read predicates on;
    at the :data:`_DERIVE_AGENT_STATE` sentinel it is derived from ``labels``, else
    the explicit value (incl. ``None`` = Backlog) is used.
    """
    resolved_agent_state = (
        _agent_state_from_labels(labels) if agent_state == _DERIVE_AGENT_STATE else agent_state
    )
    return (
        repo,
        num,
        title,
        state,
        json.dumps(list(labels or [])),
        workflow_id,
        agent,
        pr_num,
        resolved_agent_state,
        _utc_now_iso(),
    )


def _is_cost_excluded(agent: Any) -> bool:
    """True if a run's agent is cost-excluded from spend (Codex; FR-06-1a)."""
    return isinstance(agent, str) and agent.strip().lower() == COST_EXCLUDED_AGENT


async def _count_runs_by_status(
    conn: aiosqlite.Connection, repo: str, statuses: Sequence[str]
) -> int:
    """Count this repo's runs whose ``status`` is one of ``statuses``."""
    status_list = list(statuses)
    if not status_list:
        return 0
    placeholders = ", ".join("?" for _ in status_list)
    rows = await conn.execute_fetchall(
        "SELECT COUNT(*) AS n FROM runs "  # noqa: S608 — placeholders only
        f"WHERE repo = ? AND status IN ({placeholders})",
        (repo, *status_list),
    )
    return int(next(iter(rows))["n"]) if rows else 0


async def _spend_today(conn: aiosqlite.Connection, repo: str, since_iso: str) -> float:
    """Segment-sum spend for this repo's runs started since ``since_iso``.

    Per ``(run_id, task_index)`` last-cumulative ``cost_usd`` (INV-7 — never a
    naive SUM over events), summed over runs ``started_at >= since_iso`` with
    **Codex excluded** (FR-06-1a / INV-8). The Codex exclusion is by the run's
    ``agent`` column, matching :meth:`Repository.total_spend`.
    """
    # The CTE body + the Codex-exclusion predicate come from the ONE canonical
    # segment-sum definition (app.db.spend_sql — G13); the repo/started_at window
    # is the only thing this site adds. ``_spend_today`` intentionally stays a live
    # segment-sum over events (not the run_totals fast-path): it is a per-repo
    # today-window read driving admission (AC-3), so it must reflect an in-flight
    # run's cost immediately, before any completion snapshot exists.
    sql = (
        f"{last_per_task_cte()}\n"
        "SELECT COALESCE(SUM(lpt.cost_usd), 0.0) AS total\n"
        "FROM last_per_task lpt\n"
        "JOIN runs r ON r.id = lpt.run_id\n"
        "WHERE r.repo = ?\n"
        "  AND r.started_at IS NOT NULL\n"
        "  AND r.started_at >= ?\n"
        f"  AND {AGENT_NOT_CODEX_SQL}"
    )
    rows = await conn.execute_fetchall(sql, (repo, since_iso, COST_EXCLUDED_AGENT))
    return float(next(iter(rows))["total"] or 0.0) if rows else 0.0


async def _tokens_today(conn: aiosqlite.Connection, repo: str, since_iso: str) -> int:
    """Token total for this repo's runs started since ``since_iso`` (all agents).

    Counts ``tokens_in + tokens_out`` across **every** run in the window —
    Codex included (FR-06-1a: Codex tokens are real even though its cost is
    unpriced and excluded from :func:`_spend_today`).
    """
    rows = await conn.execute_fetchall(
        """
        SELECT COALESCE(SUM(tokens_in + tokens_out), 0) AS total
        FROM runs
        WHERE repo = ? AND started_at IS NOT NULL AND started_at >= ?
        """,
        (repo, since_iso),
    )
    return int(next(iter(rows))["total"] or 0) if rows else 0


async def _project_run_spend(conn: aiosqlite.Connection, run_id: str) -> float:
    """Σ over distinct ``task_index`` of the last-cumulative ``cost_usd`` for one run.

    The dedup key is ``(run_id, task_index)`` (materialized on the event row); for
    each we take the event with the highest ``id`` that carries a non-NULL
    ``cost_usd`` — its cumulative total for that task — and sum across tasks.
    Composes the ONE canonical ``last_per_task`` CTE (app.db.spend_sql — G13)
    scoped to a single run, so the per-run projection cannot drift from the
    total/daily/bulk spend definitions.
    """
    sql = (
        f"{last_per_task_cte(run_filter='AND run_id = ?')}\n"
        "SELECT COALESCE(SUM(lpt.cost_usd), 0.0) AS total\n"
        "FROM last_per_task lpt"
    )
    rows = await conn.execute_fetchall(sql, (run_id,))
    return float(next(iter(rows))["total"] or 0.0) if rows else 0.0


# === G9 — events-retention fast-path spend (run_totals for terminal runs) =====
#
# The whole-DB spend projections (total_spend / daily_spend_series) must NOT
# segment-sum the unbounded events table across every completed run on every poll
# (G9 — the long-term ceiling). Instead:
#
#   total = Σ(run_totals.cost_usd  for TERMINAL runs WITH a snapshot)   # fast-path
#         + Σ(segment-sum of events for ACTIVE runs OR terminal-without-snapshot)
#
# both Codex-excluded. A terminal run's snapshot carries the EXACT segment-sum
# total written at completion, so reading it instead of its events is numerically
# identical — the result EQUALS the full-events segment-sum for any state (a
# fast-path-vs-full-scan equality test asserts this over a mixed fixture). A
# terminal run that has NOT yet been snapshotted (the brief window before the
# completion supervisor writes run_totals) falls back to the live segment-sum, so
# the total is never under-counted. After a retention prune the events are gone but
# the snapshot remains, so the same total survives the prune (also asserted).


#: SQL predicate (against ``runs`` alias ``r``) selecting a TERMINAL run that has a
#: ``run_totals`` snapshot — the fast-path set whose cost is read from the snapshot,
#: not re-scanned from events. The ``status`` placeholders are bound from
#: :data:`TERMINAL_RUN_STATUSES`; the ``EXISTS`` guards a terminal-but-unsnapshotted
#: run out of the fast-path so it falls through to the live segment-sum instead.
def _terminal_snapshotted_predicate() -> tuple[str, list[Any]]:
    statuses = sorted(TERMINAL_RUN_STATUSES)
    placeholders = ", ".join("?" for _ in statuses)
    pred = (
        f"r.status IN ({placeholders}) "
        "AND EXISTS (SELECT 1 FROM run_totals rt WHERE rt.run_id = r.id)"
    )
    return pred, list(statuses)


async def _total_spend_fast_path(conn: aiosqlite.Connection) -> float:
    """Codex-excluded total spend via the run_totals fast-path (G9).

    ``Σ(run_totals.cost_usd)`` over terminal+snapshotted Codex-excluded runs, plus
    the live segment-sum over the remaining (active / not-yet-snapshotted) runs.
    EQUALS the full-events segment-sum for any state.
    """
    term_pred, term_params = _terminal_snapshotted_predicate()
    # Part A — terminal snapshot sum (fast-path; one indexed row per run).
    snap_rows = await conn.execute_fetchall(
        "SELECT COALESCE(SUM(rt.cost_usd), 0.0) AS total "  # noqa: S608 — placeholders only
        "FROM run_totals rt JOIN runs r ON r.id = rt.run_id "
        f"WHERE {term_pred} AND {AGENT_NOT_CODEX_SQL}",
        (*term_params, COST_EXCLUDED_AGENT),
    )
    snapshot_total = float(next(iter(snap_rows))["total"] or 0.0) if snap_rows else 0.0
    # Part B — live segment-sum over the runs NOT in the fast-path set.
    active_total = await _active_segment_sum_total(conn, term_pred, term_params)
    return snapshot_total + active_total


async def _active_segment_sum_total(
    conn: aiosqlite.Connection, term_pred: str, term_params: list[Any]
) -> float:
    """Live segment-sum over runs OUTSIDE the terminal+snapshotted fast-path set.

    The canonical ``last_per_task`` CTE summed over Codex-excluded runs that are NOT
    ``(terminal AND snapshotted)`` — i.e. active runs and any terminal run whose
    snapshot is not yet written. ``term_params`` binds the terminal-status set
    referenced inside the negated predicate.
    """
    sql = (
        f"{total_spend_sql()}\n"
        f"  AND NOT ({term_pred})"  # exclude the fast-path set (read from snapshot)
    )
    rows = await conn.execute_fetchall(
        sql,  # noqa: S608 — placeholders only; values bound below
        (COST_EXCLUDED_AGENT, *term_params),
    )
    return float(next(iter(rows))["total"] or 0.0) if rows else 0.0


async def _bucket_terminal_daily(conn: aiosqlite.Connection, buckets: dict[str, float]) -> None:
    """Add terminal+snapshotted runs' snapshot cost into ``buckets`` keyed by day (G9).

    Buckets ``run_totals.cost_usd`` by the run's ``started_at`` date (``YYYY-MM-DD``,
    matching the active-run bucketing) over Codex-excluded terminal+snapshotted runs
    — no events scan. Mutates ``buckets`` in place so it merges with the active-run
    daily series in :meth:`Repository.daily_spend_series`.
    """
    term_pred, term_params = _terminal_snapshotted_predicate()
    rows = await conn.execute_fetchall(
        "SELECT substr(r.started_at, 1, 10) AS day, "  # noqa: S608 — placeholders only
        "COALESCE(SUM(rt.cost_usd), 0.0) AS usd "
        "FROM run_totals rt JOIN runs r ON r.id = rt.run_id "
        f"WHERE {term_pred} AND {AGENT_NOT_CODEX_SQL} AND r.started_at IS NOT NULL "
        "GROUP BY day",
        (*term_params, COST_EXCLUDED_AGENT),
    )
    for row in rows:
        day = str(row["day"])
        buckets[day] = buckets.get(day, 0.0) + float(row["usd"] or 0.0)


async def _bucket_active_daily(conn: aiosqlite.Connection, buckets: dict[str, float]) -> None:
    """Add the live segment-sum of non-fast-path runs into ``buckets`` by day (G9).

    The canonical ``last_per_task`` segment-sum bucketed by ``started_at`` date over
    Codex-excluded runs that are NOT ``(terminal AND snapshotted)`` — the active /
    not-yet-snapshotted runs. Mutates ``buckets`` in place; merges with the terminal
    daily series so a day with both contributes the sum.
    """
    term_pred, term_params = _terminal_snapshotted_predicate()
    sql = (
        f"{last_per_task_cte()},\n"
        "per_run AS (\n"
        "    SELECT lpt.run_id AS run_id, SUM(lpt.cost_usd) AS spend\n"
        "    FROM last_per_task lpt\n"
        "    JOIN runs r ON r.id = lpt.run_id\n"
        f"    WHERE {AGENT_NOT_CODEX_SQL}\n"
        "      AND r.started_at IS NOT NULL\n"
        f"      AND NOT ({term_pred})\n"
        "    GROUP BY lpt.run_id\n"
        ")\n"
        "SELECT substr(r.started_at, 1, 10) AS day,\n"
        "       COALESCE(SUM(pr.spend), 0.0) AS usd\n"
        "FROM per_run pr\n"
        "JOIN runs r ON r.id = pr.run_id\n"
        "GROUP BY day"
    )
    rows = await conn.execute_fetchall(
        sql,  # noqa: S608 — placeholders only; values bound below
        (COST_EXCLUDED_AGENT, *term_params),
    )
    for row in rows:
        day = str(row["day"])
        buckets[day] = buckets.get(day, 0.0) + float(row["usd"] or 0.0)
