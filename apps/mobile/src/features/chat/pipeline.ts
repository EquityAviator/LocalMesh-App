/**
 * Chat streaming render pipeline (§16.7, UI spec 6.5):
 *  - batch UI updates every 50-100 ms (default 80 ms), never per token;
 *  - markdown applied once at [DONE] (plain text + cursor while streaming);
 *  - DB flush at most every 1 s (partial retention §11.6/§15.3).
 * Timing runs on the injected Clock (simulated-clock testable).
 */

import type { Clock, TimeoutHandle } from '../../domain/connection/clock';
import type { StreamStatus } from '../../domain/sm-stream';

export const RENDER_FLUSH_MS = 80; // within the 50–100 ms window (§16.7)
export const DB_FLUSH_MS = 1000;

export interface StreamBatcherDeps {
  clock: Clock;
  intervalMs?: number;
  /** Receives the accumulated text to render. */
  onFlush(text: string, final: boolean): void;
}

/**
 * Collects deltas and flushes at most every `intervalMs`; `end()` performs the
 * final flush (called on terminal status; markdown rendering starts here).
 */
export class StreamBatcher {
  private acc = '';
  private handle?: TimeoutHandle;
  private ended = false;

  constructor(private readonly deps: StreamBatcherDeps) {}

  push(text: string): void {
    if (this.ended) return;
    this.acc += text;
    if (this.handle === undefined) {
      this.handle = this.deps.clock.setTimeout(() => {
        this.handle = undefined;
        if (this.ended) return;
        this.deps.onFlush(this.acc, false);
      }, this.deps.intervalMs ?? RENDER_FLUSH_MS);
    }
  }

  /** Final flush; safe to call multiple times (idempotent). */
  end(): void {
    if (this.handle !== undefined) {
      this.deps.clock.clearTimeout(this.handle);
      this.handle = undefined;
    }
    if (this.ended) return;
    this.ended = true;
    this.deps.onFlush(this.acc, true);
  }

  get buffered(): string {
    return this.acc;
  }
}

export interface DbFlusherDeps {
  clock: Clock;
  minIntervalMs?: number;
  write(text: string): void;
}

/**
 * Persist partial text at most every 1 s (§16.7 "DB flush ≥ 1 s"), with a
 * trailing write so the last partial is never lost.
 */
export class DbFlusher {
  private pending = '';
  private lastWriteAt = -Infinity;
  private scheduled?: TimeoutHandle;

  constructor(private readonly deps: DbFlusherDeps) {}

  push(text: string): void {
    this.pending = text;
    const now = this.deps.clock.now();
    if (now - this.lastWriteAt >= (this.deps.minIntervalMs ?? DB_FLUSH_MS)) {
      this.flushPending(now);
      return;
    }
    if (this.scheduled === undefined) {
      const wait = (this.deps.minIntervalMs ?? DB_FLUSH_MS) - (now - this.lastWriteAt);
      this.scheduled = this.deps.clock.setTimeout(() => {
        this.scheduled = undefined;
        this.flushPending(this.deps.clock.now());
      }, wait);
    }
  }

  private flushPending(now: number): void {
    this.lastWriteAt = now;
    this.deps.write(this.pending);
  }

  /** Final synchronous write (terminal status). */
  finalize(): void {
    if (this.scheduled !== undefined) {
      this.deps.clock.clearTimeout(this.scheduled);
      this.scheduled = undefined;
    }
    this.flushPending(this.deps.clock.now());
  }
}

/**
 * §16.7: while streaming render plain text with a thin cursor; apply full
 * markdown once at [DONE] ("no visible jump"). Interrupted/cancelled partials
 * also get markdown applied (they are terminal).
 */
export function renderModeFor(status: StreamStatus | 'submitting'): 'plain' | 'markdown' {
  return status === 'streaming' || status === 'submitting' ? 'plain' : 'markdown';
}
