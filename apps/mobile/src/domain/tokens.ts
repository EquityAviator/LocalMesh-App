/**
 * §16.1 token handling: hold the Device Token in MEMORY ONLY (never persisted,
 * §14.2); refresh at 80 % of `expires_in` or once on 401. Refreshes are
 * single-flight.
 */

import type { Clock, TimeoutHandle } from './connection/clock';

export interface TokenBundle {
  token: string;
  expiresInSeconds: number;
}

export type Refresher = () => Promise<TokenBundle>;

/** Refresh point = 80 % of expires_in (§16.1, normative). */
export const REFRESH_AT_FRACTION = 0.8;

export class TokenManager {
  private bundle: TokenBundle | null = null;
  private refreshHandle?: TimeoutHandle;
  private inflight: Promise<TokenBundle> | null = null;

  constructor(
    private readonly refresh: Refresher,
    private readonly clock: Clock,
  ) {}

  get current(): string | null {
    return this.bundle?.token ?? null;
  }

  /** Store a fresh bundle and schedule the 80 % refresh. */
  setToken(token: string, expiresInSeconds: number): void {
    this.apply({ token, expiresInSeconds });
  }

  private apply(b: TokenBundle): void {
    this.bundle = b;
    if (this.refreshHandle !== undefined) this.clock.clearTimeout(this.refreshHandle);
    const atMs = b.expiresInSeconds * 1000 * REFRESH_AT_FRACTION;
    this.refreshHandle = this.clock.setTimeout(() => {
      void this.refreshNow();
    }, atMs);
  }

  /**
   * Single-flight refresh: concurrent callers share one in-flight promise.
   * Also used by the 401 path (refresh once, §15.3).
   */
  refreshNow(): Promise<TokenBundle> {
    if (this.inflight) return this.inflight;
    this.inflight = this.refresh()
      .then((b) => {
        this.apply(b);
        return b;
      })
      .finally(() => {
        this.inflight = null;
      });
    return this.inflight;
  }

  /** Test/introspection: ms until the scheduled refresh fires. */
  msUntilRefresh(): number | null {
    return null; // kept abstract — the Clock owns absolute scheduling
  }

  dispose(): void {
    if (this.refreshHandle !== undefined) this.clock.clearTimeout(this.refreshHandle);
    this.refreshHandle = undefined;
  }
}
