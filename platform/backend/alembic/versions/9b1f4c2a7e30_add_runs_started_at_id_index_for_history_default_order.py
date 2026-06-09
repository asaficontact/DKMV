"""add runs (started_at, id) index for the history default ordering

Adds ``ix_runs_started_at_id`` on ``runs(started_at, id)`` so the F10 history
landing read — ``GET /runs`` default page — is index-backed:

* :func:`app.db.queries_history.list_runs_filtered` orders the unfiltered (and
  filtered) history page by ``started_at DESC, id DESC LIMIT 101``. The only
  pre-existing index touching ``started_at`` is the composite
  ``ix_runs_status_started_at`` on ``(status, started_at)`` — its leading
  ``status`` column is **not** bound on the default page, so SQLite cannot use it
  for the bare ``ORDER BY started_at`` and instead ``SCAN``s the whole ``runs``
  table and builds a ``TEMP B-TREE FOR ORDER BY``.

A ``(started_at, id)`` composite serves both the sort key and the ``id DESC``
tiebreak straight from the index (``USE TEMP B-TREE`` disappears; the plan walks
the index in reverse). Purely additive — no table/data change — kept separate
from the shipped migrations (never edit a shipped migration). Mirrored in
:mod:`app.db.schema` so ``target_metadata`` stays in sync (an autogenerate diff
would otherwise want to re-add it).

Revision ID: 9b1f4c2a7e30
Revises: 0aae30d54010
Create Date: 2026-06-09 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9b1f4c2a7e30"
down_revision: str | None = "0aae30d54010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.create_index("ix_runs_started_at_id", ["started_at", "id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_index("ix_runs_started_at_id")
