"""Platform database schema (SQLAlchemy Core ``MetaData``) — PRD §6.5.

This module is the *single* declarative source of the nine platform tables
(`projects, issues, runs, run_stages, events, pause_decisions, run_totals,
settings, secrets`), their binding indexes, and the FK ``ON DELETE CASCADE``
relationships from the child tables to ``runs(id)``.

It is consumed two ways:

* **Alembic** wires ``target_metadata = metadata`` in ``alembic/env.py`` so the
  initial migration is generated/verified against this exact shape.
* **Runtime** uses raw ``aiosqlite`` for writes (through the single serialized
  writer task with ``BEGIN IMMEDIATE`` — INV-6) and reads; the table/column
  *names* below are the contract the repository layer binds to. We do **not**
  open a SQLAlchemy engine at runtime — the engine here is purely a schema
  description / migration aid (keeps the SQLite→Postgres seam dialect-portable,
  NFR-PORT-1, without coupling the hot write path to the ORM).

Binding rules encoded here (PRD §6.5):

* ``runs.id`` is the platform-generated **UUID** PK (text); ``engine_run_id`` is
  a separate **non-unique** human-readable column; ``idempotency_key`` is
  **UNIQUE** (the claim-insert key, INV-5/§8.2).
* ``events.id`` is ``INTEGER PRIMARY KEY AUTOINCREMENT`` — the monotonic SSE
  replay cursor; the table is append-only.
* FK ``ON DELETE CASCADE`` on ``run_stages / events / pause_decisions /
  run_totals`` → ``runs(id)``.
* The five binding indexes: ``UNIQUE(events.run_id, sequence)``,
  ``events(run_id, id)``, ``runs(status, started_at)``, ``runs(issue_num)``,
  ``pause_decisions(status, timeout_at)``.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
)

# A stable naming convention so Alembic-generated index/constraint names are
# deterministic across the SQLite→Postgres seam.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

# --- projects -----------------------------------------------------------------
projects = Table(
    "projects",
    metadata,
    Column("id", Text, primary_key=True),
    Column("repo", Text, nullable=False),
    Column("default_branch", Text, nullable=False, server_default="main"),
    Column("github_installation_id", Text, nullable=True),
    Column("created_at", Text, nullable=False),
    Column("tenant_id", Text, nullable=True),
)

# --- issues (cache/index of GitHub issues; PK (repo, num)) ---------------------
issues = Table(
    "issues",
    metadata,
    Column("repo", Text, nullable=False),
    Column("num", Integer, nullable=False),
    Column("title", Text, nullable=False, server_default=""),
    Column("state", Text, nullable=False, server_default="backlog"),
    Column("labels_json", Text, nullable=False, server_default="[]"),
    Column("workflow_id", Text, nullable=True),
    Column("agent", Text, nullable=True),
    Column("pr_num", Integer, nullable=True),
    Column("updated_at", Text, nullable=True),
    Column("sync_cursor", Text, nullable=True),
    # Derived ``agent:*`` state suffix (queued / in-progress / paused / review) or
    # NULL for Backlog (G12). Written at board-sync time alongside labels_json so
    # the per-tick dispatch candidate read is an index-backed
    # ``WHERE repo=? AND agent_state='queued'`` instead of reading the whole board
    # and JSON-parsing labels in Python every tick. Added in migration b1c2d3e4f5a6.
    Column("agent_state", Text, nullable=True),
    PrimaryKeyConstraint("repo", "num", name="pk_issues"),
    # G12: index-backs the per-tick queued-candidate read
    # (Repository.read_candidate_issues → WHERE repo=? AND agent_state='queued')
    # so the tick reads only queued issues, not the full board (added in migration
    # b1c2d3e4f5a6).
    Index("ix_issues_repo_agent_state", "repo", "agent_state"),
)

# --- runs ---------------------------------------------------------------------
# PK is the platform-generated UUID (the engine's YYMMDD-HHMM-…-4hex id is
# collision-weak under concurrency — R-8 — and is stored separately as the
# non-unique, human-readable engine_run_id which arrives *after* start()).
runs = Table(
    "runs",
    metadata,
    Column("id", Text, primary_key=True),
    Column("engine_run_id", Text, nullable=True),
    Column("repo", Text, nullable=False),
    Column("issue_num", Integer, nullable=True),
    Column("workflow_id", Text, nullable=True),
    Column("agent", Text, nullable=True),
    Column("model", Text, nullable=True),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("branch", Text, nullable=True),
    Column("feature_name", Text, nullable=True),
    Column("cost_usd", Float, nullable=True),
    Column("tokens_in", Integer, nullable=False, server_default="0"),
    Column("tokens_out", Integer, nullable=False, server_default="0"),
    Column("turns", Integer, nullable=False, server_default="0"),
    Column("duration_s", Float, nullable=True),
    Column("started_at", Text, nullable=True),
    Column("finished_at", Text, nullable=True),
    Column("pr_num", Integer, nullable=True),
    Column("error", Text, nullable=True),
    # Launched guardrails (FR-04-5 / §8.9 config block) — persisted at launch so
    # GET /runs/{id}'s config block reflects the *actual* launched values, not a
    # default. max_turns / max_budget_usd are NULL for a Codex run (the engine has
    # no such cap — INV-8). Added additively in migration 0aae30d54010.
    Column("max_turns", Integer, nullable=True),
    Column("timeout_minutes", Integer, nullable=True),
    Column("max_budget_usd", Float, nullable=True),
    Column("memory_limit", Text, nullable=True),
    Column("idempotency_key", Text, nullable=False),
    Column("tenant_id", Text, nullable=True),
    UniqueConstraint("idempotency_key", name="uq_runs_idempotency_key"),
    # boot scan + history sort
    Index("ix_runs_status_started_at", "status", "started_at"),
    # issue → runs lookup
    Index("ix_runs_issue_num", "issue_num"),
    # active-runs-per-repo (authority rule, §8.1): index-backs
    # Repository.read_active_runs / board_aggregate's WHERE repo=? AND status IN (…)
    # so the per-poll board read does not table-scan runs (added in migration
    # 75c6c8e45770).
    Index("ix_runs_repo_status", "repo", "status"),
    # history default ordering (F10 landing read): the GET /runs page does
    # ORDER BY started_at DESC, id DESC LIMIT 101 with no leading status/repo
    # predicate. ix_runs_status_started_at (status, started_at) cannot serve it
    # (status is not bound), so without this it SCANs runs + builds a temp B-tree.
    # A (started_at, id) composite backs both the sort key and the id DESC
    # tiebreak from the index (added in migration 9b1f4c2a7e30).
    Index("ix_runs_started_at_id", "started_at", "id"),
)

# --- run_stages (mutable read model) ------------------------------------------
run_stages = Table(
    "run_stages",
    metadata,
    Column("run_id", Text, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
    Column("idx", Integer, nullable=False),
    Column("name", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("cost_usd", Float, nullable=True),
    Column("turns", Integer, nullable=False, server_default="0"),
    Column("duration_s", Float, nullable=True),
    PrimaryKeyConstraint("run_id", "idx", name="pk_run_stages"),
)

# --- events (append-only; monotonic id is the SSE replay cursor) --------------
events = Table(
    "events",
    metadata,
    # INTEGER PRIMARY KEY AUTOINCREMENT — strictly monotonic, never reused.
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", Text, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
    Column("sequence", BigInteger, nullable=False),
    Column("ts", Text, nullable=False),
    Column("event_type", Text, nullable=False),
    # task_index is materialized out of the payload so the spend projection can
    # dedup last-cumulative cost per (run_id, task_index) without re-parsing JSON
    # for every event (INV-7 prep). NULL for events without a task context.
    Column("task_index", Integer, nullable=True),
    Column("cost_usd", Float, nullable=True),
    Column("agent", Text, nullable=True),
    Column("payload_json", Text, nullable=False),
    # (run_id, sequence) uniqueness — the engine's per-run monotonic sequence.
    UniqueConstraint("run_id", "sequence", name="uq_events_run_id_sequence"),
    # replay scan: WHERE run_id=? AND id > :last ORDER BY id
    Index("ix_events_run_id_id", "run_id", "id"),
    # segment-sum spend grouping (INV-7): the run_spend / run_spends /
    # total_spend / _spend_today projections GROUP BY (run_id, task_index) over
    # cost-bearing events to take the last-cumulative id per task. A covering
    # (run_id, task_index, id) index lets that grouping + MAX(id) be served from
    # the index instead of re-scanning the events PK by run_id (added in
    # migration 0aae30d54010).
    Index("ix_events_run_id_task_index_id", "run_id", "task_index", "id"),
    # Emit AUTOINCREMENT so events.id is never reused (append-only + future prune).
    sqlite_autoincrement=True,
)

# --- pause_decisions (HITL) ---------------------------------------------------
pause_decisions = Table(
    "pause_decisions",
    metadata,
    Column("id", Text, primary_key=True),
    Column("run_id", Text, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
    Column("task_name", Text, nullable=True),
    Column("request_json", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("answer_json", Text, nullable=True),
    Column("resolved_by", Text, nullable=True),
    Column("timeout_at", Text, nullable=True),
    Column("created_at", Text, nullable=False),
    # expiry sweep: WHERE status='pending' AND timeout_at <= now
    Index("ix_pause_decisions_status_timeout_at", "status", "timeout_at"),
)

# --- run_totals (completion snapshot) -----------------------------------------
# Snapshot written at run completion so events can be retention-pruned without
# losing spend/audit totals. run_id is both PK and FK → runs(id).
run_totals = Table(
    "run_totals",
    metadata,
    Column("run_id", Text, ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
    Column("cost_usd", Float, nullable=True),
    Column("tokens_in", Integer, nullable=False, server_default="0"),
    Column("tokens_out", Integer, nullable=False, server_default="0"),
    Column("turns", Integer, nullable=False, server_default="0"),
    Column("duration_s", Float, nullable=True),
)

# --- settings (key/value) -----------------------------------------------------
settings = Table(
    "settings",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=True),
)

# --- secrets (encrypted at rest, §8.6) ----------------------------------------
secrets = Table(
    "secrets",
    metadata,
    Column("key", Text, primary_key=True),
    # Ciphertext only — the SecretStore (slice 0.5) owns encrypt/decrypt; plain
    # values never land here.
    Column("ciphertext", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("expires_at", Text, nullable=True),
)

#: The nine table names the AC-0.3-4 schema assertion checks for.
ALL_TABLE_NAMES: frozenset[str] = frozenset(
    {
        "projects",
        "issues",
        "runs",
        "run_stages",
        "events",
        "pause_decisions",
        "run_totals",
        "settings",
        "secrets",
    }
)

#: Child tables whose FK → runs(id) must be ON DELETE CASCADE (AC-0.3-4).
CASCADE_CHILD_TABLES: frozenset[str] = frozenset(
    {"run_stages", "events", "pause_decisions", "run_totals"}
)

#: The module's public surface: the table objects, the metadata, and the
#: assertion constants the schema tests bind to. ``Column`` is used directly in
#: the Table definitions above (a real reference — no re-export needed to keep
#: mypy/ruff happy).
__all__ = [
    "ALL_TABLE_NAMES",
    "CASCADE_CHILD_TABLES",
    "NAMING_CONVENTION",
    "events",
    "issues",
    "metadata",
    "pause_decisions",
    "projects",
    "run_stages",
    "run_totals",
    "runs",
    "secrets",
    "settings",
]
