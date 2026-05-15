# GitHub Webhook Test Backend (FastAPI)

Тестовый backend для проверки GitHub webhook-сценария:
- принимает webhook от GitHub;
- валидирует подпись `X-Hub-Signature-256` (если задан секрет);
- на событие `pull_request` отправляет комментарий в PR через GitHub API.

## 1) Запуск локально

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

Проверка:
- `GET http://localhost:8000/health` -> `{"status":"ok"}`

## 2) Подготовка токена GitHub

Создай Personal Access Token (classic fine-grained тоже можно), минимум с доступом:
- `Pull requests: Read and write`
- `Contents: Read`

Запиши токен в `.env`:

```env
GITHUB_TOKEN=...
GITHUB_WEBHOOK_SECRET=...
```

## 3) Настройка webhook в репозитории GitHub

`Settings` -> `Webhooks` -> `Add webhook`:
- `Payload URL`: публичный URL твоего backend + `/webhooks/github`
  - пример: `https://<your-ngrok-domain>/webhooks/github`
- `Content type`: `application/json`
- `Secret`: тот же, что `GITHUB_WEBHOOK_SECRET`
- `Which events`: `Let me select individual events` -> `Pull requests`

## 4) Локальный тест через ngrok (пример)

```bash
ngrok http 8000
```

Скопируй `https` URL от ngrok в `Payload URL`.

## 5) Что обрабатывается

Сервис реагирует только на событие `pull_request` и action:
- `opened`
- `reopened`
- `synchronize`
- `ready_for_review`

Для других событий/действий возвращается `ignored`.

## 6) Кастомизация текста комментария

Через переменную:

```env
PR_COMMENT_TEMPLATE=Automated test comment for `{repo}` PR #{pr_number} (action: `{action}`).
```

Доступные шаблонные поля:
- `{owner}`
- `{repo}`
- `{pr_number}`
- `{action}`
- `{pr_title}`

## 7) Пример ответа webhook endpoint

```json
{
  "ok": true,
  "event": "pull_request",
  "delivery": "8f9f8f24-...",
  "repository": "owner/repo",
  "pr_number": 42,
  "comment_id": 1234567890,
  "comment_url": "https://github.com/owner/repo/pull/42#issuecomment-..."
}
```
