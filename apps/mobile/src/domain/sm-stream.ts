/**
 * §15.3 — SM-STREAM, one chat generation.
 *
 * App message status: submitting → streaming → complete | interrupted | error
 * | cancelled. Persisted status (§14.2 CHECK) covers
 * complete/streaming/interrupted/error only, so `cancelled` persists as
 * `complete` (partial kept, shown as complete-with-note) and `submitting`
 * persists as `interrupted`.
 *
 * Pure with respect to I/O: chunks arrive via methods, timing via Clock.
 */

import type { Clock, TimeoutHandle } from './connection/clock';
import type { MessageStatus } from './entities';

export type StreamStatus =
  | 'submitting'
  | 'streaming'
  | 'complete'
  | 'interrupted'
  | 'error'
  | 'cancelled';

/** Idle timeout before [DONE] → interrupted (§15.3; §13.7: 45 s without ANY
 *  bytes — the Agent's 15 s pings are bytes and re-arm this window). */
export const STREAM_IDLE_TIMEOUT_MS = 45_000;

export interface StreamListener {
  onStatus?(status: StreamStatus, detail?: { retryable?: boolean; note?: string }): void;
  /** Raw delta text; batching/render policy lives in features/chat (§16.7). */
  onDelta?(text: string): void;
  /** 401 path exhausted: refresh once + retry once both failed (§15.3). */
  onAuthFail?(): void;
  /** Refresh succeeded; the caller must re-issue the request exactly once. */
  onRetryRequest?(): void;
}

export interface StreamMachineOptions {
  idleTimeoutMs?: number;
}

export class StreamMachine {
  private status: StreamStatus = 'submitting';
  private partial = '';
  private idleHandle?: TimeoutHandle;
  private authRetryUsed = false;
  private finished = false;

  constructor(
    private readonly clock: Clock,
    private readonly listener: StreamListener,
    private readonly opts: StreamMachineOptions = {},
  ) {}

  get current(): StreamStatus {
    return this.status;
  }

  /** Text received so far — retained on interrupt/cancel (§15.3, UI spec 6.5). */
  get text(): string {
    return this.partial;
  }

  /** Issue a new generation: resets per-generation state, starts idle timer. */
  begin(): void {
    this.status = 'submitting';
    this.finished = false;
    this.partial = '';
    this.armIdle();
    this.listener.onStatus?.('submitting');
  }

  private armIdle(): void {
    this.disarmIdle();
    this.idleHandle = this.clock.setTimeout(() => {
      if (this.finished) return;
      // Idle timeout (45 s) before [DONE] → interrupted (§15.3).
      this.transition('interrupted', { note: 'idle_timeout' });
    }, this.opts.idleTimeoutMs ?? STREAM_IDLE_TIMEOUT_MS);
  }

  private disarmIdle(): void {
    if (this.idleHandle !== undefined) {
      this.clock.clearTimeout(this.idleHandle);
      this.idleHandle = undefined;
    }
  }

  /** HTTP status of the submit request (200/202 ok; 401 → refresh+retry once). */
  onHttpStatus(status: number): void {
    if (this.finished) return;
    if (status === 401 || status === 403) {
      if (this.authRetryUsed) {
        // §15.3: else SM-CONN event AUTH_FAIL.
        this.listener.onAuthFail?.();
        this.transition('error', { note: 'AUTH_FAIL' });
        return;
      }
      this.authRetryUsed = true;
      // The token layer performs the single-flight refresh; on success the
      // caller re-issues the request exactly once (onRetryRequest).
      this.listener.onRetryRequest?.();
      return;
    }
    if (status >= 400) {
      this.transition('error', { note: `http_${status}` });
    }
  }

  /**
   * Result of the single token refresh after a 401. `true` → the caller
   * retries once; `false` → AUTH_FAIL surfaced to SM-CONN.
   */
  onAuthRefreshed(ok: boolean): void {
    if (this.finished) return;
    if (!ok) {
      this.listener.onAuthFail?.();
      this.transition('error', { note: 'AUTH_FAIL' });
    }
    // ok → caller calls onRetryRequest path; status stays `submitting`.
  }

  /** SSE frame from the pinned stream. `event`/`data` per the mesh SSE format. */
  onEvent(event: string | undefined, data: string): void {
    if (this.finished) return;
    if (data === '[DONE]' || event === 'done') {
      this.transition('complete');
      return;
    }
    if (event === 'mesh.error') {
      let retryable = false;
      try {
        const parsed: unknown = JSON.parse(data);
        if (parsed && typeof parsed === 'object') {
          const obj = parsed as Record<string, unknown>;
          // §13.4 error envelope: {error:{code,message,retryable?}}; a bare
          // top-level retryable flag is also accepted (additive, §13.10).
          const env = obj['error'];
          if (obj['retryable'] !== undefined) {
            retryable = obj['retryable'] === true;
          } else if (env && typeof env === 'object' && 'retryable' in (env as Record<string, unknown>)) {
            retryable = (env as Record<string, unknown>)['retryable'] === true;
          }
        }
      } catch {
        /* mesh.error payload is not machine-readable → non-retryable */
      }
      this.transition('error', { retryable, note: 'mesh_error' });
      return;
    }
    if (event === 'ping') {
      // §13.7: pings are bytes — they re-arm the 45 s idle window (CI-21 cold
      // loads stay alive) but never advance the status machine itself.
      this.armIdle();
      return;
    }
    if (data !== '') {
      this.partial += data;
      if (this.status === 'submitting') {
        this.status = 'streaming';
        this.listener.onStatus?.('streaming');
      }
      // Real content also re-arms the idle timer (§13.7: any bytes).
      this.armIdle();
      this.listener.onDelta?.(data);
    }
  }

  /** Native socket closed before [DONE] → interrupted (§15.3). */
  onClosed(reason: string): void {
    if (this.finished) return;
    void reason;
    this.transition('interrupted', { note: 'closed' });
  }

  /** User pressed Stop → cancelled; partial kept (§15.3, UI spec 6.5 rule 6). */
  cancel(): void {
    if (this.finished) return;
    this.transition('cancelled');
  }

  private transition(status: StreamStatus, detail?: { retryable?: boolean; note?: string }): void {
    if (this.finished) return;
    this.finished = true;
    this.disarmIdle();
    this.status = status;
    this.listener.onStatus?.(status, detail);
  }

  /** §14.2 persistence mapping (CHECK constraint has no submitting/cancelled). */
  persistedStatus(): MessageStatus {
    switch (this.status) {
      case 'complete':
      case 'cancelled': // complete-with-note (UI spec 6.5; partial retained)
        return 'complete';
      case 'error':
        return 'error';
      case 'streaming':
      case 'submitting': // process death mid-submit → interrupted (§11.6)
      case 'interrupted':
        return 'interrupted';
    }
  }
}
