/**
 * Virtual device static server — serves the Expo web export (apps/mobile/dist)
 * at /virtual-device/*. Served from the dist source directory instead of
 * public/ because the dev server prunes foreign `_expo` directories from
 * public/ (observed with Next 16 dev). Rebuild the dist with:
 *   cd apps/mobile && bunx expo export --platform web --output-dir dist
 *
 * Read-only; path-traversal guarded; no caching (dev surface).
 */

import { readFile, stat } from "node:fs/promises";
import path from "node:path";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const DIST = path.resolve(process.cwd(), "apps/mobile/dist");

const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".svg": "image/svg+xml",
  ".ttf": "font/ttf",
  ".otf": "font/otf",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".wasm": "application/wasm",
};

async function serveFile(rel: string): Promise<Response> {
  const target = path.resolve(DIST, rel);
  if (target !== DIST && !target.startsWith(DIST + path.sep)) {
    return new Response("Forbidden", { status: 403 });
  }
  let st;
  try {
    st = await stat(target);
  } catch {
    return new Response("Not found", { status: 404 });
  }
  if (st.isDirectory()) {
    return serveFile(path.join(rel, "index.html"));
  }
  const body = await readFile(target);
  const type = MIME[path.extname(target).toLowerCase()] ?? "application/octet-stream";
  let payload: Uint8Array = new Uint8Array(body);
  if (rel === "index.html") {
    // Sandbox-demo bootstrap: present "/machines" to the router so expo-router
    // mounts at the app's entry tab (the export lives under /virtual-device/,
    // and the app has no index route). Owner machines serving dist at a root
    // don't need this injection.
    const html = body
      .toString("utf-8")
      .replace(
        "<head>",
        "<head><script>history.replaceState(null,'','/machines');</script>",
      );
    payload = new Uint8Array(Buffer.from(html, "utf-8"));
  }
  return new Response(payload, {
    status: 200,
    headers: { "Content-Type": type, "Cache-Control": "no-store" },
  });
}

export async function GET(_req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  const { path: segments } = await ctx.params;
  const rel = (segments ?? []).join("/");
  return serveFile(rel === "" ? "index.html" : rel);
}
