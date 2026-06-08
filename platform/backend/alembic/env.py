"""Alembic migration environment for the DKMV Platform backend.

The initial migration (slice 0.3-persistence) creates all nine tables
(`projects, issues, runs, run_stages, events, pause_decisions, run_totals,
settings, secrets`) with the binding indexes and FK ``ON DELETE CASCADE``.
``target_metadata`` is wired to :data:`app.db.schema.metadata` so autogenerate /
schema comparison run against the single declarative source.

The database URL is taken from the platform's typed settings
(`Settings.DATABASE_URL`) so migrations and the running app agree on one source
of truth. ``render_as_batch`` is on so SQLite ``ALTER TABLE`` in later
migrations works, and so the ``ON DELETE CASCADE`` foreign keys are emitted
inside the ``CREATE TABLE`` (SQLite cannot add an FK via ALTER).
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from app.config import get_settings
from app.db.schema import metadata
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# The default URL baked into alembic.ini; a value differing from this means a
# caller set it intentionally (programmatic Config), so we respect it.
_INI_DEFAULT_URL = "sqlite:///./data/dkmv.db"


def _database_url() -> str:
    """Resolve the migration DB URL with a clear precedence.

    1. An explicit ``sqlalchemy.url`` set programmatically on this ``Config``
       (e.g. a test that runs ``command.upgrade`` against a temp DB) — that
       wins so callers can target an isolated DB.
    2. Otherwise the platform's typed settings (``Settings.DATABASE_URL``) —
       the single source of truth shared with the running app.
    """
    explicit = config.get_main_option("sqlalchemy.url")
    if explicit and explicit != _INI_DEFAULT_URL:
        return explicit
    return get_settings().DATABASE_URL


config.set_main_option("sqlalchemy.url", _database_url())

# Wired to the single declarative schema source (app/db/schema.py).
target_metadata = metadata


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
