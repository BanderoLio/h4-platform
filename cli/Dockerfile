# agent-scan CLI — containerised client for the security-scan backend.
#
# Standalone build & run:
#   docker build -t agent-scan-cli ./cli
#   docker run --rm -it \
#     -e SCAN_API_URL=http://host.docker.internal:8000 \
#     -e SCAN_API_KEY=changeme \
#     -v "$PWD/reports:/reports" \
#     agent-scan-cli scan https://github.com/octocat/Hello-World
#
# Inside the compose stack use the `cli` service (see docker-compose.yml):
#   docker compose run --rm cli scan https://github.com/octocat/Hello-World

FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml readme.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1
COPY --from=builder /install /usr/local

# Reports (TXT/JSON) are written to the working directory — mount a volume
# here to collect them on the host.
WORKDIR /reports

# Args after the image name are passed straight to `agent-scan`; with no
# args (and a TTY) it opens the interactive menu.
ENTRYPOINT ["agent-scan"]
