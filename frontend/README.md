# Security Agent WebUI (MVP)

Cursor-like web interface for the cybersecurity AI agent.

## User flow

1. User adds Git repositories on a dedicated repositories screen.
2. Repositories are stored in browser `localStorage`.
3. User opens a dedicated workspace per repository.
4. Workspace provides:
   - left sidebar with agent run history for this repository,
   - chat-like message stream,
   - prompt input area,
   - markdown rendering for AI replies.
5. Each prompt triggers scan API and appends the response to current run history.

## API contract used by frontend

### Start scan

- `POST /scan/start`
- Request body:

```json
{
  "repo_url": "https://github.com/org/repo",
  "interactive": true,
  "query": "Check release blockers and summarize critical risks"
}
```

- Response: `202` with:

```json
{
  "scan_id": "uuid"
}
```

### Get report

- `GET /scan/{scan_id}/report`
- Responses:
  - `202 { "status": "running" | "awaiting_input", "report": "string | null" }`
  - `200 { "status": "completed" | "failed", "report": "string | null" }`
  - `404 { "detail": "scan not found" }`

### Resume interrupted run

- `POST /scan/{scan_id}/resume`
- Request body:

```json
{ "answer": "..." }
```

- Response codes:
  - `202` accepted
  - `409` session is not awaiting input
  - `404` scan not found

### List sessions

- `GET /scan/sessions?limit=50&offset=0`
- Used by frontend as source of truth for per-repository run history.

## Tech stack

- Next.js 16 (App Router)
- TypeScript
- Tailwind CSS + shadcn/ui
- Axios
- React Hook Form + Zod
- react-markdown + remark-gfm
- next-intl (EN/RU) + next-themes

## Project structure

```text
frontend/
├── app/
│   └── [locale]/repos/[repoId]  # Per-repository workspace
├── components/
├── features/
│   ├── repositories/            # Local storage models and helpers
│   └── security-scan/           # API client for scan endpoints
├── messages/
├── shared/providers/
├── views/
└── widgets/
```

## Environment variables

Create `.env.local`:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

If not set, browser requests use current origin and SSR uses `http://localhost:8000`.

## Run locally

```bash
pnpm install
pnpm dev
```

## Quality checks

```bash
pnpm lint
pnpm build
```

## MVP limitations

- No authentication or server-side repository persistence.
- Repository list and workspace history are local to browser/device.
- Report retrieval is polling-based (no SSE/WebSocket streaming).
- Chat transcript is stored locally, while session states are synced from `/scan/sessions`.
