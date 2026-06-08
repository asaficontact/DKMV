"""Alembic migration environment for the DKMV Platform backend.

Phase 0 / slice 0.1 ships the *runnable scaffold* of the Alembic env. The
initial migration that creates all nine tables (`projects, issues, runs,
run_stages, events, pause_decisions, run_totals, settings, secrets`) with the
binding indexes and FK CASCADE lands in slice 0.3-persistence; the `versions/`
directory is intentionally empty here.

The database URL is taken from the platform's typed settings
(`Settings.DATABASE_URL`) so migrations and the running app agree on one source
of truth.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from app.config import get_settings
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override the .ini URL with the platform settings URL (single source of truth).
config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL)

# target_metadata is wired to the ORM/Table metadata in slice 0.3; None until then.
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DBAPI connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (with a live connection)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # batch mode: required for SQLite ALTER TABLE in later migrations.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
