"""add issues.agent_state column + (repo, agent_state) index + backfill (G12)

Purely additive (never edit a shipped migration):

* **G12 — indexed dispatch-candidate read.** The orchestrator tick's candidate
  read previously read the ENTIRE board (all issues for the repo) and JSON-parsed
  ``labels_json`` to filter for ``agent:queued`` in Python every ``TICK_INTERVAL_S``
  — a per-tick full-board scan that scales with total board size. This adds a
  derived, indexed ``agent_state`` column (the precedence-resolved ``agent:*``
  suffix, or NULL for Backlog) written at board-sync time alongside ``labels_json``
  (:func:`app.github.sync.derive_agent_state`), plus ``ix_issues_repo_agent_state``
  on ``(repo, agent_state)`` so :meth:`Repository.read_candidate_issues` is an
  index-backed ``WHERE repo=? AND agent_state='queued'`` — only the queued issues
  are read, not the whole board.

The column is **backfilled** for existing rows from ``labels_json`` using the same
precedence as the runtime derivation (``in-progress > paused > review > queued``),
so a repo synced before this migration still dispatches correctly without a
re-sync. A row with no ``agent:*`` label backfills to NULL (Backlog).

Mirrored in :mod:`app.db.schema` so ``target_metadata`` stays in sync (an
autogenerate diff would otherwise want to re-add the column + index).

Revision ID: b1c2d3e4f5a6
Revises: 9b1f4c2a7e30
Create Date: 2026-06-10 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "9b1f4c2a7e30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Additive nullable column (Backlog rows stay NULL).
    with op.batch_alter_table("issues", schema=None) as batch_op:
        batch_op.add_column(sa.Column("agent_state", sa.Text(), nullable=True))
        batch_op.create_index("ix_issues_repo_agent_state", ["repo", "agent_state"], unique=False)

    # Backfill existing rows from labels_json using the SAME precedence as the
    # runtime derivation (in-progress > paused > review > queued). labels_json is a
    # JSON array of label-name strings (e.g. '["agent:queued","bug"]'); the LIKE
    # tests for the quoted label token. A row with no agent:* label stays NULL.
    op.execute(
        """
        UPDATE issues SET agent_state = CASE
            WHEN labels_json LIKE '%"agent:in-progress"%' THEN 'in-progress'
            WHEN labels_json LIKE '%"agent:paused"%'      THEN 'paused'
            WHEN labels_json LIKE '%"agent:review"%'      THEN 'review'
            WHEN labels_json LIKE '%"agent:queued"%'      THEN 'queued'
            ELSE NULL
        END
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("issues", schema=None) as batch_op:
        batch_op.drop_index("ix_issues_repo_agent_state")
        batch_op.drop_column("agent_state")
