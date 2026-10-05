/**
 * SSE parser + feed for the mesh streaming endpoints (§13.7 chat events,
 * §13.9 task events). Testable without native code: text arrives via
 * `feed(chunk)`; the idle timeout (45 s without ANY bytes — §13.7; the Agent's
 * 15 s pings are bytes and keep the stream alive) drives `onInterrupted`.
 *
 * Format: standard SSE — `event:` lines, multi-line `data:` frames joined with
 * `\n`, comment lines starting with `:`, terminal `data: [DONE]` sentinel,
 * `event: mesh.error` for in-stream failures.
 */

import type { Clock, TimeoutHandle } from '../../domain/connection/clock';

/**
 * §13.7 keepalive/idle contract: the Agent sends `: ping` comments every 15 s
 * while waiting, and the client idle timeout is "45 s without ANY bytes ⇒
 * treat as dead (CI-18)" — pings ARE bytes, so every frame (pings included)
 * re-arms the window. This is what keeps a cold model load alive (CI-21:
 * "Pings + UI Loading model…; first-token timeout 120 s" — a separate,
 * longer budget).
 */

export const SSE_IDLE_TIMEOUT_MS = 45_000;

export interface SseFrame {
  /** SSE event name ('mesh.error', 'ping', …); undefined for default frames. */
  event?: string;
  /** Data payload, multi-line frames joined with '\n'. */
  data: string;
  /** True for the `data: [DONE]` sentinel. */
  done: boolean;
  /** True for keep-alive pings/comments — never resets the idle window. */
  ping: boolean;
  /** True for `event: mesh.error` frames. */
  error: boolean;
}

export class SseParser {
  private buf = '';
  private eventName?: string;
  private dataLines: string[] = [];

  /** Feed a chunk (possibly split mid-frame); returns fully parsed frames. */
  push(chunk: string): SseFrame[] {
    this.buf += chunk;
    const frames: SseFrame[] = [];
    for (;;) {
      const nl = this.buf.indexOf('\n');
      if (nl === -1) break;
      let line = this.buf.slice(0, nl);
      this.buf = this.buf.slice(nl + 1);
      if (line.endsWith('\r')) line = line.slice(0, -1);
      const frame = this.handleLine(line);
      if (frame) frames.push(frame);
    }
    return frames;
  }

  /** Flush a stream that ended without a trailing blank line (best effort). */
  flush(): SseFrame[] {
    const out: SseFrame[] = [];
    if (this.buf !== '') {
      const line = this.buf.replace(/\r$/, '');
      this.buf = '';
      const frame = this.handleLine(line);
      if (frame) out.push(frame);
    }
    if (this.eventName !== undefined || this.dataLines.length > 0) {
      out.push(this.dispatch());
    }
    return out;
  }

  private handleLine(line: string): SseFrame | null {
    if (line === '') {
      if (this.eventName === undefined && this.dataLines.length === 0) return null; // keep-alive CRLF
      return this.dispatch();
    }
    if (line.startsWith(':')) {
      // Comment — used by the Agent as 15 s keep-alive ping (§13.7).
      return { data: '', done: false, ping: true, error: false };
    }
    if (line.startsWith('event:')) {
      this.eventName = line.slice(6).trim();
      return null;
    }
    if (line.startsWith('data:')) {
      this.dataLines.push(line.slice(5).replace(/^ /, ''));
      return null;
    }
    // Unknown field (id:, retry:, …) — ignored per SSE spec.
    return null;
  }

  private dispatch(): SseFrame {
    const event = this.eventName;
    const data = this.dataLines.join('\n');
    this.eventName = undefined;
    this.dataLines = [];
    if (data === '[DONE]') return { data, done: true, ping: false, error: false };
    const isError = event === 'mesh.error';
    const isPing = event === 'ping';
    return { event, data, done: false, ping: isPing, error: isError };
  }
}

export interface SseFeedDeps {
  onFrame(frame: SseFrame): void;
  /** Fired when 45 s pass with NO bytes at all (§13.7; pings count as bytes). */
  onInterrupted(): void;
  clock: Clock;
  idleTimeoutMs?: number;
}

export interface SseFeed {
  feed(chunk: string): void;
  /** Stop the idle timer (socket closed by us or after [DONE]). */
  cancel(): void;
}

/**
 * Idle-timeout wrapper: 45 s without ANY bytes → interrupted (§13.7).
 * Every frame — pings included — re-arms the window; only byte silence trips.
 */
export function createSseFeed(deps: SseFeedDeps): SseFeed {
  const parser = new SseParser();
  const idleMs = deps.idleTimeoutMs ?? SSE_IDLE_TIMEOUT_MS;
  let handle: TimeoutHandle | undefined;
  let cancelled = false;

  const rearm = (): void => {
    if (handle !== undefined) deps.clock.clearTimeout(handle);
    handle = deps.clock.setTimeout(() => {
      if (cancelled) return;
      cancelled = true;
      deps.onInterrupted();
    }, idleMs);
  };

  rearm();

  return {
    feed(chunk: string): void {
      if (cancelled) return;
      for (const frame of parser.push(chunk)) {
        // §13.7: "45 s without ANY bytes" — pings are bytes. Every frame of
        // any kind re-arms the window; only true byte silence trips CI-18.
        rearm();
        deps.onFrame(frame);
      }
    },
    cancel(): void {
      cancelled = true;
      if (handle !== undefined) {
        deps.clock.clearTimeout(handle);
        handle = undefined;
      }
    },
  };
}
