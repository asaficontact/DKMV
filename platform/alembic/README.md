# Alembic migrations

The **runnable** Alembic project lives under
[`../backend/alembic/`](../backend/alembic/) with its config at
[`../backend/alembic.ini`](../backend/alembic.ini), because the backend package
(`app`) and its settings (`app.config.Settings.DATABASE_URL`) are the migration
env's source of truth. Run migrations from the backend env:

```bash
cd platform/backend
alembic upgrade head
```

This directory exists at the `platform/` level to match the PRD §8.8 repository
layout. The initial migration (all nine tables + binding indexes + FK CASCADE)
is created in slice **0.3-persistence**.
