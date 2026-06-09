"""add runs (repo, status) index for read_active_runs

Adds the deferred composite index ``ix_runs_repo_status`` on ``runs(repo,
status)`` so the active-runs-per-repo read path is index-backed:

* :meth:`app.db.repository.Repository.read_active_runs` —
  ``WHERE repo = ? AND issue_num IS NOT NULL AND status IN (…)`` (the §8.1
  authority rule, evaluated on every board read / list_issues call), and
* :meth:`app.db.repository.Repository.board_aggregate`'s per-status counts.

Without the index these scan the whole ``runs`` table; with it the per-poll
board reads use the ``(repo, status)`` prefix. A purely additive migration —
no table/data change — kept separate from ``0001`` (never edit a shipped
migration). Mirrored in :mod:`app.db.schema` so ``target_metadata`` stays in
sync (an Alembic autogenerate diff would otherwise want to re-add it).

Revision ID: 75c6c8e45770
Revises: 0001
Create Date: 2026-06-08 20:53:29.508457

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "75c6c8e45770"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.create_index("ix_runs_repo_status", ["repo", "status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_index("ix_runs_repo_status")
