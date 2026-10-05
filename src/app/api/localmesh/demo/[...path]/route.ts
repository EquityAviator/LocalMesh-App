/**
 * Sandbox demo bridge — proxies the LocalMesh virtual device (apps/mobile web
 * export, served from /virtual-device/) to the REAL Python Agent running in
 * this sandbox at http://127.0.0.1:8443 (started with --dev-insecure-loopback,
 * §17.9 dev-only mode: loopback + token auth bypassed, QUESTION-105 context).
 *
 * Scope guard (governance):
 * - This route exists ONLY for the sandbox virtual-device demo. The production
 *   App talks to the Agent over pinned TLS 1.3 via the native mesh-core module
 *   (§17.3/§17.9) — never through this bridge.
 * - SSE streams are passed through byte-for-byte (§13.7); no buffering of the
 *   whole stream (idle watchdog lives in the client).
 * - No logging of request/response bodies (Content never touches logs; §17.10).
 */

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const AGENT_BASE = 'http://127.0.0.1:8443/mesh/v1';

const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'transfer-encoding',
  'upgrade',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
]);

async function forward(req: Request, params: Promise<{ path: string[] }>): Promise<Response> {
  const { path } = await params;
  const target = `${AGENT_BASE}/${path.join('/')}${new URL(req.url).search}`;

  const headers = new Headers();
  for (const [k, v] of req.headers.entries()) {
    if (!HOP_BY_HOP.has(k.toLowerCase()) && k.toLowerCase() !== 'host' && k.toLowerCase() !== 'content-length') {
      headers.set(k, v);
    }
  }

  const upstream = await fetch(target, {
    method: req.method,
    headers,
    body: req.method === 'GET' || req.method === 'HEAD' ? undefined : await req.arrayBuffer(),
    cache: 'no-store',
  });

  const respHeaders = new Headers();
  upstream.headers.forEach((v, k) => {
    if (!HOP_BY_HOP.has(k.toLowerCase()) && k.toLowerCase() !== 'content-encoding' && k.toLowerCase() !== 'content-length') {
      respHeaders.set(k, v);
    }
  });
  // Same-origin caller (the virtual device iframe); no CORS headers needed.

  return new Response(upstream.body, { status: upstream.status, headers: respHeaders });
}

export async function GET(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, ctx.params);
}
export async function POST(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, ctx.params);
}
export async function PUT(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, ctx.params);
}
export async function PATCH(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, ctx.params);
}
export async function DELETE(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, ctx.params);
}
