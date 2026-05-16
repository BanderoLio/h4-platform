# Backend image running the REAL agentsec orchestrator (not the stub).
#
# Build context is the repository ROOT (see docker-compose.real.yml) so the
# `agentsec/` package can be copied in alongside the FastAPI backend.
# Used via: docker compose -f docker-compose.yml -f docker-compose.real.yml up --build

FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git \
    && rm -rf /var/lib/apt/lists/*

# Backend requirements already include the agentsec runtime deps
# (langgraph, langchain-openai, langgraph-checkpoint-sqlite, ...).
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY --from=builder /install /usr/local

# Real agentsec package + the FastAPI backend. scan.py adds the repo root
# (/app) to sys.path, so `import agentsec.session` resolves to this package
# instead of the bundled stub.
COPY agentsec/ ./agentsec/
COPY backend/ ./backend/

WORKDIR /app/backend
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${API_PORT_INTERNAL:-8000}"]
