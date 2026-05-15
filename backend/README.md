# hack4 backend

Pentesting agent backend. Accepts a repo URL, runs a security scan, returns a report.

## Requirements

- Docker + Docker Compose

## Setup

```bash
cp .env.example .env
```

Edit `.env` and set `API_KEY` to a secret value.

## Start

```bash
docker compose up --build
```

On first boot the API runs database migrations automatically, then starts the server.

- API: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`

## Usage

**Start a scan:**

```bash
curl -X POST http://localhost:8000/scan/start \
  -H "Authorization: Bearer <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/example/repo"}'
```

Response: `{"scan_id": "<uuid>"}`

**Poll for result:**

```bash
curl http://localhost:8000/scan/<scan_id>/report \
  -H "Authorization: Bearer <API_KEY>"
```

- `202` + `{"status": "running", "report": null}` — scan in progress
- `200` + `{"status": "done", "report": "..."}` — complete
- `200` + `{"status": "failed", "report": "..."}` — failed

**With a CI webhook** (called automatically when scan completes):

```bash
curl -X POST http://localhost:8000/scan/start \
  -H "Authorization: Bearer <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/example/repo", "webhook_url": "https://ci.example.com/hook"}'
```

**With a query** (passed to the agent):

```bash
-d '{"repo_url": "...", "query": "find hardcoded secrets"}'
```

## Stop

```bash
docker compose down
```

To also wipe the database and queued jobs:

```bash
docker compose down
docker volume rm backend_sqlite_data backend_redis_data
```

## Development

**Run tests** (no Docker needed):

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -v
```

**Add a database migration:**

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

## Configuration

All config is via `.env`. See `.env.example` for available variables.

| Variable | Description |
|----------|-------------|
| `API_KEY` | Bearer token required on all requests |
| `DATABASE_URL` | SQLAlchemy async URL (`sqlite+aiosqlite://` or `postgresql+asyncpg://`) |
| `REDIS_URL` | Redis connection URL |
| `REPOS_DIR` | Path where repos are cloned during scans |
| `API_PORT_EXTERNAL` | Host port for the API |
