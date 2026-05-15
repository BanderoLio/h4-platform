To setup:
```bash
python3 -m venv venv
source venv/bin/activate
python3 -m pip install -e .
agent-scan
```

`agent-scan` без аргументов открывает интерактивный режим с большим ASCII-баннером,
меню, настройками подключения и сохранением TXT-отчета.

Скриптовый режим тоже доступен:

```bash
agent-scan start https://github.com/org/repo
agent-scan report <scan_id> --output report.txt
agent-scan scan https://github.com/org/repo --base-url http://127.0.0.1:8000
agent-scan scan https://github.com/org/repo --webhook-url https://example.com/webhook
```

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
