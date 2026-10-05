/**
 * §11.2 MeshCore contract implemented over fetch() — SANDBOX WEB DEMO ONLY.
 *
 * The production App talks to the Agent through the native mesh-core module
 * (PinnedHttp: TLS 1.3 + SPKI pinning, §17.3; HTTP rejected per SEC-N1 except
 * the debug-only loopback carve-out of §17.9). A browser bundle has no native
 * module, so this class implements the same contract for the virtual-device
 * demo: every logical `https://…/mesh/v1/*` URL is mapped onto a same-origin
 * proxy path (`{proxyBase}/{path-after-/mesh/v1}`) that forwards to the REAL
 * Agent running in the sandbox with `--dev-insecure-loopback` (plain HTTP on
 * the loopback interface, token auth bypassed — §17.9 / QUESTION-105).
 *
 * SECURITY (sandbox demo only — do not ship):
 *  - `tlsSpkiSha256B64Url` is ALWAYS the configured demo pin. No TLS is
 *    involved and no pin verification happens here; the client-side equality
 *    assert (MeshApiClient) is green by construction. Production keeps the
 *    native PinnedHttp TLS-pinning path (§17.3) — this file is never used there.
 *  - The demo key API returns deterministic stubs with NO crypto claims
 *    (no hardware keystore, no ECDSA); pairing crypto is native-only (§17.2).
 *  - No request/response logging (§17.10).
 *
 * SSE: `openStream()` parses the §13.7 wire format incrementally by reusing
 * the pure SseParser from src/data/mesh/sse.ts; the idle watchdog mirrors
 * §13.7 ("45 s without ANY bytes") and is re-armed on EVERY read — partial
 * lines and pings included — before framing, so a slow-dribbling chunk can
 * never trip it (same semantics as the Kotlin SseStream).
 */

import type {
  MeshCore,
  MeshCoreRequest,
  MeshCoreResponse,
  MeshCoreStreamClosedPayload,
  MeshCoreStreamErrorPayload,
  MeshCoreStreamEventPayload,
  MeshCoreStreamRequest,
  NetworkStateNative,
  StreamHandle,
} from '../../modules/mesh-core/src/MeshCore.types';
import { SseParser, type SseFrame } from '../data/mesh/sse';

export interface WebMeshCoreOptions {
  /** Same-origin proxy prefix, e.g. `/api/localmesh/demo` (Next.js route). */
  proxyBase: string;
  /** Logical Agent origin the client builds URLs against (documentation only). */
  logicalBase: string;
  /** Demo pin echoed as `tlsSpkiSha256B64Url` (see header — no TLS here). */
  pin: string;
}

/** Typed transport error (mirrors the native MeshCoreException codes). */
export class WebMeshCoreError extends Error {
  constructor(
    readonly code: 'NETWORK' | 'TIMEOUT' | 'IDLE_TIMEOUT' | 'CANCELLED' | 'HTTP',
    message: string,
  ) {
    super(message);
    this.name = 'WebMeshCoreError';
  }
}

/**
 * Logical Agent URL → same-origin proxy path. The client builds §13.2 URLs
 * like `${logicalBase}/mesh/v1/info`; those map to `${proxyBase}/info`.
 * Query strings are preserved.
 */
export function proxyPathFor(proxyBase: string, logicalUrl: string): string {
  const u = new URL(logicalUrl);
  const rest = u.pathname.replace(/^\/mesh\/v1/, '');
  return `${proxyBase.replace(/\/+$/, '')}${rest}${u.search}`;
}

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export class WebMeshCore implements MeshCore {
  constructor(private readonly opts: WebMeshCoreOptions) {}

  // --- keys: demo stubs, no crypto claims (see header) ---

  async createDeviceKey(_alias: string): Promise<{ publicKeySpkiB64Url: string; hardwareBacked: boolean }> {
    void _alias;
    return { publicKeySpkiB64Url: 'demo-key', hardwareBacked: false };
  }

  /** Deterministic b64url stub ("demo-signature") — NOT a real signature. */
  async signWithDeviceKey(_alias: string, dataB64Url: string): Promise<string> {
    void _alias;
    void dataB64Url;
    return 'ZGVtby1zaWduYXR1cmU';
  }

  async deleteDeviceKey(_alias: string): Promise<void> {
    void _alias;
  }

  // --- pinned HTTP (JSON) over the proxy ---

  async request(req: MeshCoreRequest): Promise<MeshCoreResponse> {
    const ctrl = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      ctrl.abort();
    }, Math.max(0, req.timeoutMs));
    try {
      const headers: Record<string, string> = { ...(req.headers ?? {}) };
      let body: string | undefined;
      if (req.bodyJson !== undefined) {
        body = JSON.stringify(req.bodyJson);
        headers['Content-Type'] = headers['Content-Type'] ?? 'application/json';
      }
      const res = await fetch(proxyPathFor(this.opts.proxyBase, req.url), {
        method: req.method,
        headers,
        body,
        signal: ctrl.signal,
        cache: 'no-store',
      });
      const resHeaders: Record<string, string> = {};
      res.headers.forEach((v, k) => {
        resHeaders[k.toLowerCase()] = v;
      });
      // Tolerate empty bodies (204/HEAD): an empty payload is bodyJson-less.
      const text = await res.text();
      let bodyJson: unknown;
      if (text.trim() !== '') {
        try {
          bodyJson = JSON.parse(text) as unknown;
        } catch {
          bodyJson = undefined; // non-JSON body → surfaced via status by the caller
        }
      }
      return { status: res.status, headers: resHeaders, bodyJson, tlsSpkiSha256B64Url: this.opts.pin };
    } catch (e) {
      throw new WebMeshCoreError(
        timedOut ? 'TIMEOUT' : 'NETWORK',
        `${req.method} request failed${timedOut ? ' (timeout)' : ''}: ${errorText(e)}`,
      );
    } finally {
      clearTimeout(timer);
    }
  }

  // --- pinned SSE over the proxy ---

  async openStream(req: MeshCoreStreamRequest): Promise<StreamHandle> {
    const handle = new WebStreamHandle(req, this.opts);
    // The handle resolves immediately; connection failures surface as
    // 'error' (+ 'closed') events, mirroring the native event surface.
    void handle.start();
    return handle;
  }

  // --- discovery & network: fixed demo answers ---

  /** mDNS discovery is native-only (§16.2) — a no-op on the web demo. */
  async startDiscovery(_serviceType: '_localmesh._tcp'): Promise<void> {
    void _serviceType;
  }
  async stopDiscovery(): Promise<void> {}
  async getNetworkState(): Promise<NetworkStateNative> {
    return { transport: 'wifi', vpnActive: false, metered: false };
  }
  async getLocalNetworkPermission(): Promise<'granted' | 'denied' | 'not_required' | 'unknown'> {
    return 'granted';
  }
  async requestLocalNetworkPermission(): Promise<'granted' | 'denied'> {
    return 'granted';
  }
  /** Tailscale hint (CI-13): not detectable from a browser → false. */
  async isPackageInstalled(_pkg: string): Promise<boolean> {
    void _pkg;
    return false;
  }
}

type StreamCallback =
  | ((p: MeshCoreStreamEventPayload) => void)
  | ((p: MeshCoreStreamErrorPayload) => void)
  | ((p: MeshCoreStreamClosedPayload) => void);

/**
 * One §13.7 SSE generation over fetch(). Events:
 *  - 'event'  — every SSE frame (pings as `{event:'ping', data:''}`; the
 *               `[DONE]` sentinel is emitted as a default frame before close);
 *  - 'error'  — fetch/HTTP/abort failures (code, message — no Content, §17.10);
 *  - 'closed' — 'done' after [DONE] or EOF, 'cancelled' after cancel(),
 *               'error' after a failure (always the last event).
 */
class WebStreamHandle implements StreamHandle {
  private eventCb?: (p: MeshCoreStreamEventPayload) => void;
  private errorCb?: (p: MeshCoreStreamErrorPayload) => void;
  private closedCb?: (p: MeshCoreStreamClosedPayload) => void;
  private ctrl = new AbortController();
  private idleTimer?: ReturnType<typeof setTimeout>;
  private finished = false;
  private cancelled = false;
  private idleFired = false;

  constructor(
    private readonly req: MeshCoreStreamRequest,
    private readonly opts: WebMeshCoreOptions,
  ) {}

  on(name: 'event', cb: (p: MeshCoreStreamEventPayload) => void): void;
  on(name: 'error', cb: (p: MeshCoreStreamErrorPayload) => void): void;
  on(name: 'closed', cb: (p: MeshCoreStreamClosedPayload) => void): void;
  on(name: 'event' | 'error' | 'closed', cb: StreamCallback): void {
    if (name === 'event') this.eventCb = cb as (p: MeshCoreStreamEventPayload) => void;
    else if (name === 'error') this.errorCb = cb as (p: MeshCoreStreamErrorPayload) => void;
    else this.closedCb = cb as (p: MeshCoreStreamClosedPayload) => void;
  }

  cancel(): void {
    this.cancelled = true;
    this.ctrl.abort();
  }

  /** Connect + pump. Never throws — failures become 'error' events. */
  async start(): Promise<void> {
    this.armIdle();
    try {
      const res = await fetch(proxyPathFor(this.opts.proxyBase, this.req.url), {
        method: this.req.method,
        headers: { 'Content-Type': 'application/json', ...(this.req.headers ?? {}) },
        body: JSON.stringify(this.req.bodyJson),
        signal: this.ctrl.signal,
        cache: 'no-store',
      });
      if (res.status >= 400) {
        // §13.4 error envelope when the Agent rejects before streaming.
        let code = `HTTP_${res.status}`;
        let message = `stream rejected with HTTP ${res.status}`;
        try {
          const text = await res.text();
          const parsed: unknown = text.trim() === '' ? undefined : JSON.parse(text);
          if (parsed && typeof parsed === 'object') {
            const env = (parsed as Record<string, unknown>)['error'];
            if (env && typeof env === 'object') {
              const e = env as Record<string, unknown>;
              if (typeof e['code'] === 'string') code = e['code'];
              if (typeof e['message'] === 'string') message = e['message'];
            }
          }
        } catch {
          /* body unreadable → keep the generic HTTP message */
        }
        this.fail(code, message);
        return;
      }
      if (!res.body) {
        this.fail('NETWORK', 'stream response has no body');
        return;
      }
      await this.pump(res.body);
      this.finish('done');
    } catch (e) {
      if (this.cancelled) {
        this.finish('cancelled');
        return;
      }
      if (this.idleFired) return; // IDLE_TIMEOUT already emitted by the watchdog
      this.fail('NETWORK', `stream failed: ${errorText(e)}`);
    }
  }

  private async pump(body: ReadableStream<Uint8Array>): Promise<void> {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    const parser = new SseParser();
    let sawDone = false;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      // §13.7: ANY bytes — pings and partial lines included — reset the window.
      this.armIdle();
      const text = decoder.decode(value, { stream: true });
      for (const frame of parser.push(text)) {
        this.emitFrame(frame);
        if (frame.done) {
          sawDone = true;
          break;
        }
      }
      if (sawDone) break;
    }
    if (!sawDone) {
      for (const frame of parser.flush()) this.emitFrame(frame);
    }
  }

  private emitFrame(frame: SseFrame): void {
    if (this.finished) return;
    if (frame.ping) {
      this.eventCb?.({ event: 'ping', data: '' });
      return;
    }
    this.eventCb?.({ event: frame.event, data: frame.data });
  }

  /** §13.7 idle watchdog: armed at connect, re-armed on every byte batch. */
  private armIdle(): void {
    if (this.idleTimer !== undefined) clearTimeout(this.idleTimer);
    const ms = this.req.idleTimeoutMs;
    if (!(ms > 0)) return;
    this.idleTimer = setTimeout(() => {
      this.idleFired = true;
      this.fail('IDLE_TIMEOUT', `no bytes for ${ms} ms (§13.7)`);
    }, ms);
  }

  private fail(code: string, message: string): void {
    if (this.finished) return;
    this.finished = true;
    if (this.idleTimer !== undefined) clearTimeout(this.idleTimer);
    this.ctrl.abort();
    this.errorCb?.({ code, message });
    this.closedCb?.({ reason: 'error' });
  }

  private finish(reason: string): void {
    if (this.finished) return;
    this.finished = true;
    if (this.idleTimer !== undefined) clearTimeout(this.idleTimer);
    this.closedCb?.({ reason });
  }
}
