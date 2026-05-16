# Security Agent WebUI

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
5. Each prompt triggers the scan API and appends the response to the
   current run history.

## Backend connectivity (BFF proxy)

The backend requires a Bearer API key on every `/scan/*` request. The
browser never holds that key: it calls the same-origin proxy at `/api/*`
(`app/api/[...path]/route.ts`), which forwards the request to the backend
server-side and injects `Authorization: Bearer <API_KEY>`.

```
browser ──/api/scan/start──▶ Next.js route handler ──Bearer──▶ FastAPI /scan/start
```

Server-side env (`.env`, never exposed to the client):

- `BACKEND_INTERNAL_URL` — backend origin the proxy forwards to.
- `API_KEY` — backend API key, injected by the proxy.

A live `/health` poll in the navbar shows backend reachability.

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

- Response: `202` with `{ "scan_id": "uuid" }`.

### Get report

- `GET /scan/{scan_id}/report`
- Responses:
  - `202 { "status": "running" | "awaiting_input", "report": null, "interrupt_type": "clarify" | "gate" | null, "question": "string | null" }`
  - `200 { "status": "completed" | "failed", "report": "string | null", "interrupt_type": null, "question": null }`
  - `404 { "detail": "scan not found" }`
- When `status` is `awaiting_input`, `question` carries the agent's
  clarifying prompt; the workspace renders it as the assistant message.

### Resume interrupted run

- `POST /scan/{scan_id}/resume`
- Request body: `{ "answer": "..." }`
- Response codes: `202` accepted, `409` not awaiting input, `404` not found.

### List sessions

- `GET /scan/sessions?limit=50&offset=0`
- Source of truth for per-repository run history. Each item exposes
  `repo_url` (original git URL) — the frontend correlates sessions to
  registry entries by it, not by the server-side `repo` clone path.

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
│   ├── [locale]/repos/[repoId]  # Per-repository workspace
│   └── api/[...path]            # BFF proxy to the scan backend
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

Copy `env.example` to `.env.local`:

```env
BACKEND_INTERNAL_URL=http://localhost:8000
API_KEY=changeme
NEXT_OUTPUT=standalone
```

`API_KEY` must match the backend's `API_KEY`.

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

## End-to-end tests

Playwright drives the full flow (add repo → run scan → read report) against
the live stack.

```bash
# brings the whole stack up via the root docker-compose.yml automatically
pnpm exec playwright install chromium
pnpm e2e
```

To test an already-running deployment, skip the bring-up:

```bash
E2E_NO_WEBSERVER=1 E2E_BASE_URL=http://localhost:8080 pnpm e2e
```

## Known limitations

- Repository registry is local to the browser/device (no server-side
  repository persistence).
- Report retrieval is polling-based (no SSE/WebSocket streaming).
- Chat transcript is stored locally; session states are synced from
  `/scan/sessions`.
