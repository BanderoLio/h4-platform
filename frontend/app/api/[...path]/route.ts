/**
 * BFF proxy for the security-scan backend.
 *
 * The browser never talks to the FastAPI backend directly: it calls
 * same-origin `/api/*`, and this handler forwards the request server-side,
 * injecting the `Authorization: Bearer <API_KEY>` header. The API key lives
 * only in the server process environment and is never shipped to the client.
 *
 * `/api/scan/start` -> `<BACKEND_INTERNAL_URL>/scan/start`
 * `/api/health`     -> `<BACKEND_INTERNAL_URL>/health`
 */
import type { NextRequest } from 'next/server';

// Always run this route dynamically — it proxies live backend state.
export const dynamic = 'force-dynamic';

const BACKEND_URL = (
  process.env.BACKEND_INTERNAL_URL ?? 'http://localhost:8000'
).replace(/\/+$/, '');
const API_KEY = process.env.API_KEY ?? '';

// Hop-by-hop headers must not be forwarded; the rest we copy selectively.
const FORWARDED_REQUEST_HEADERS = ['content-type', 'accept'];
const FORWARDED_RESPONSE_HEADERS = ['content-type', 'cache-control'];

type RouteContext = { params: Promise<{ path: string[] }> };

async function proxy(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const targetUrl = `${BACKEND_URL}/${path.join('/')}${request.nextUrl.search}`;

  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) {
      headers.set(name, value);
    }
  }
  if (API_KEY) {
    headers.set('authorization', `Bearer ${API_KEY}`);
  }

  const hasBody = request.method !== 'GET' && request.method !== 'HEAD';
  const body = hasBody ? await request.arrayBuffer() : undefined;

  let backendResponse: Response;
  try {
    backendResponse = await fetch(targetUrl, {
      method: request.method,
      headers,
      body,
      cache: 'no-store',
      // Backend scans can pause the request briefly; keep a sane ceiling.
      signal: AbortSignal.timeout(30_000),
    });
  } catch {
    return Response.json(
      { detail: 'Security scan backend is unreachable.' },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = backendResponse.headers.get(name);
    if (value) {
      responseHeaders.set(name, value);
    }
  }

  return new Response(await backendResponse.arrayBuffer(), {
    status: backendResponse.status,
    headers: responseHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;
