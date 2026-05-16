# agent-scan CLI

CLI-клиент к backend сканирования: запуск сканов, ожидание и сохранение отчётов.

## Установка

```bash
cd cli
python3 -m venv venv
source venv/bin/activate
python3 -m pip install -e .
```

## Docker

CLI упакован в образ — локальный Python не нужен.

**Через стек** (рекомендуется; сервис `cli` в корневом `docker-compose.yml`,
профиль `cli`, поэтому `docker compose up` его не запускает):

```bash
# одноразовый запуск; backend берётся из той же compose-сети,
# SCAN_API_KEY = API_KEY из .env; отчёты падают в ./cli/reports
docker compose run --rm cli scan https://github.com/octocat/Hello-World
docker compose run --rm cli                 # интерактивное меню
```

**Отдельный образ** (без стека):

```bash
docker build -t agent-scan-cli ./cli
docker run --rm -it \
  -e SCAN_API_URL=http://host.docker.internal:8000 \
  -e SCAN_API_KEY=changeme \
  -v "$PWD/reports:/reports" \
  agent-scan-cli scan https://github.com/octocat/Hello-World
```

Аргументы после имени образа уходят прямо в `agent-scan`. Отчёты пишутся
в рабочий каталог `/reports` — смонтируй его, чтобы забрать файлы на хост.

## Подключение к backend

Backend требует Bearer-ключ. Адрес и ключ задаются переменными окружения
`SCAN_API_URL` / `SCAN_API_KEY` (или флагами `--base-url` / `--api-key`).

При поднятом стеке (`docker compose up` в корне репозитория) backend
опубликован на `http://localhost:8000`, ключ — `API_KEY` из `.env`
(по умолчанию `changeme`):

```bash
export SCAN_API_URL=http://localhost:8000
export SCAN_API_KEY=changeme

agent-scan scan https://github.com/octocat/Hello-World
```

Если ключ не задан, **скриптовый режим** завершится с понятной ошибкой
(`HTTP 403`, exit code 2). **Интерактивный режим** при ошибке авторизации
сам запросит ключ и повторит запрос — задавать env-переменную заранее
не обязательно.

## Запуск

`agent-scan` без аргументов открывает интерактивный режим с ASCII-баннером,
меню, настройками подключения и сохранением TXT-отчёта.

Скриптовый режим:

```bash
agent-scan start https://github.com/org/repo            # вернёт scan_id
agent-scan report <scan_id> --output report.txt         # скачать отчёт
agent-scan scan https://github.com/org/repo             # запустить и дождаться отчёта
agent-scan result <scan_id>                             # JSON-результат + exit-code для CI
agent-scan scan https://github.com/org/repo --base-url http://127.0.0.1:8000 --api-key changeme
```

Без backend можно поднять встроенный мок: `agent-scan-mock-server`
(слушает `http://localhost:8000`), затем запускать `agent-scan` против него.

API contract:

```http
POST /scan/start
```

```json
{ "repo_url": "https://...", "webhook_url": "https://..." }
```

`webhook_url` is optional. Response:

```json
{ "scan_id": "uuid" }
```

```http
GET /scan/{scan_id}/report
```

Running:

```json
{ "status": "running", "report": null }
```

Finished:

```json
{ "status": "done", "report": "text" }
```

Failed:

```json
{ "status": "failed", "report": "error" }
```

Not found:

```json
{ "detail": "scan not found" }
```

Webhook body:

```json
{ "scan_id": "uuid", "report": "..." }
```
