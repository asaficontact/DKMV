"""runs guardrail columns + events (run_id, task_index, id) spend index

Two purely additive changes (never edit a shipped migration):

* **FIX-1 — covering spend index.** Adds ``ix_events_run_id_task_index_id`` on
  ``events(run_id, task_index, id)``. The segment-sum spend projections
  (:meth:`Repository.run_spend` / :meth:`Repository.run_spends` /
  :meth:`Repository.total_spend` / ``_spend_today``) ``GROUP BY (run_id,
  task_index)`` over cost-bearing events to take ``MAX(id)`` per task; the
  shipped ``(run_id, id)`` index does not back that grouping, so it re-scans the
  PK by run_id. A covering ``(run_id, task_index, id)`` index serves the
  grouping + max-id from the index — important now that the ``GET /runs`` list
  path issues **one** bulk spend query (``run_spends``) over a whole page.

* **FIX-2 — launched-guardrail columns.** Adds ``max_turns`` /
  ``timeout_minutes`` / ``max_budget_usd`` / ``memory_limit`` to ``runs`` so the
  validated launch guardrails are persisted at ``claim_run`` time and the
  ``GET /runs/{id}`` §8.9 ``config`` block reflects the *actual* launched values
  rather than always-``null``. All four are nullable (a Codex run has no
  budget/turns cap — INV-8 — so they stay ``NULL``).

Both mirrored in :mod:`app.db.schema` so ``target_metadata`` stays in sync (an
autogenerate diff would otherwise want to re-add them).

Revision ID: 0aae30d54010
Revises: 75c6c8e45770
Create Date: 2026-06-08 21:10:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0aae30d54010"
down_revision: str | None = "75c6c8e45770"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # FIX-2 — additive guardrail columns on runs (all nullable; Codex → NULL).
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("max_turns", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("timeout_minutes", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("max_budget_usd", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("memory_limit", sa.Text(), nullable=True))

    # FIX-1 — covering index for the segment-sum spend grouping.
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.create_index(
            "ix_events_run_id_task_index_id",
            ["run_id", "task_index", "id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.drop_index("ix_events_run_id_task_index_id")

    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_column("memory_limit")
        batch_op.drop_column("max_budget_usd")
        batch_op.drop_column("timeout_minutes")
        batch_op.drop_column("max_turns")
