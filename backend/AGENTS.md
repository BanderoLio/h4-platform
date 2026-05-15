# Backend Agent Guide

FastAPI + ARQ + SQLAlchemy backend for the hack4 repo pentesting system.

## Stack

| Layer | Choice |
|-------|--------|
| HTTP | FastAPI |
| Job queue | ARQ + Redis |
| DB ORM | SQLAlchemy 2.0 async |
| DB driver | aiosqlite (SQLite) — swap URL for PostgreSQL |
| Migrations | Alembic (async) |
| Auth | Static Bearer token (`API_KEY` env var) |

## Project Layout

```
app/
  config.py       — pydantic-settings, reads from .env
  models.py       — SQLAlchemy ORM models (Scan)
  database.py     — async engine + AsyncSessionLocal factory
  db.py           — DB access functions (create_scan, get_scan, update_scan, …)
  auth.py         — require_api_key FastAPI dependency
  main.py         — FastAPI app, lifespan (runs alembic + ARQ pool)
  routes/
    scan.py       — POST /scan/start, GET /scan/{id}/report
  worker/
    tasks.py      — ARQ job: run_scan + WorkerSettings
alembic/
  env.py          — async migration runner
  versions/       — migration files
tests/
  conftest.py     — isolated SQLite DB per test, mock ARQ
  test_routes.py
  test_worker.py
```

## Running

```bash
cp .env.example .env   # set API_KEY
docker compose up --build
```

API at `http://localhost:8000`, Swagger at `/docs`.

## Testing

```bash
.venv/bin/pytest -v
```

Tests are fully isolated — each test gets its own in-memory SQLite DB via `isolated_db` autouse fixture. No Redis needed; ARQ is mocked via `mock_arq` fixture.

**Never** call `alembic upgrade head` in tests. Table creation uses `Base.metadata.create_all` directly in `conftest.py`.

## Migrations

```bash
# Create a new migration (autogenerate from models)
alembic revision --autogenerate -m "describe change"

# Apply
alembic upgrade head

# Rollback one step
alembic downgrade -1
```

Add new columns to `app/models.py` first, then autogenerate. Always add a matching column to the `upgrade()` in the migration file.

## Key Conventions

**DB access** — use functions from `app/db.py`, never import `AsyncSessionLocal` directly. The session factory is accessed via `database.AsyncSessionLocal` at call time so tests can patch it.

**Worker job signature** — `run_scan(ctx, scan_id, repo_url, webhook_url, query)`. The `ctx` dict is injected by ARQ and contains `job_try` (int, 1-indexed). Check it for retry logic.

**Retry policy** — transient errors (`OSError`, `ConnectionError`, `TimeoutError`, `GitCommandError`) raise `arq.worker.Retry` on attempts 1–2, permanent failure on attempt 3. Non-transient errors fail immediately.

**Status flow** — `running` → `done` | `failed`. Status is set by the worker, never by the route. The route only sets `failed` when ARQ enqueue itself fails.

**Pluggable DB** — change `DATABASE_URL` in `.env` to switch backends:
```
sqlite+aiosqlite:////data/db/scans.db   # default
postgresql+asyncpg://user:pass@host/db  # production
```

## Adding a New Route

1. Add handler to `app/routes/scan.py`
2. Add `require_api_key` as a router-level dependency (already on the router)
3. Add a test in `tests/test_routes.py`

## Adding a New Worker Task

1. Define `async def my_task(ctx, ...)` in `app/worker/tasks.py`
2. Add it to `WorkerSettings.functions`
3. Enqueue with `await arq.enqueue_job("my_task", ...)`
