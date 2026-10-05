/**
 * Clock abstraction for the pure domain machines (§15.1, §16.1).
 *
 * The Connection Manager, SM-STREAM, the token manager and the race runner all
 * take a Clock so the acceptance criterion "Simulated-clock race tests" is
 * deterministic in bun test. No react-native / expo imports (§11.3).
 */

/** Opaque timer handle. */
export type TimeoutHandle = number;

export interface Clock {
  /** Monotonic milliseconds. */
  now(): number;
  setTimeout(fn: () => void, ms: number): TimeoutHandle;
  clearTimeout(handle: TimeoutHandle): void;
}

/** Production clock backed by the JS event loop. */
export class SystemClock implements Clock {
  now(): number {
    return Date.now();
  }
  setTimeout(fn: () => void, ms: number): TimeoutHandle {
    // Node/Bun/Hermes all return a numeric-ish handle; cast through unknown.
    return (setTimeout as unknown as (fn: () => void, ms: number) => number)(fn, ms) as TimeoutHandle;
  }
  clearTimeout(handle: TimeoutHandle): void {
    clearTimeout(handle as unknown as ReturnType<typeof setTimeout>);
  }
}

interface SimTimer {
  handle: number;
  dueAt: number;
  seq: number;
  fn: () => void;
}

/**
 * Deterministic clock for tests: `advance(ms)` fires every timer whose due
 * time falls inside the advanced window, in (dueAt, seq) order. Newly
 * scheduled timers due later are kept; timers scheduled within the window by
 * an earlier callback fire in the same advance call.
 */
export class SimulatedClock implements Clock {
  private timers = new Map<TimeoutHandle, SimTimer>();
  private nextHandle = 1;
  private seq = 0;
  private t: number;

  constructor(start = 0) {
    this.t = start;
  }

  now(): number {
    return this.t;
  }

  setTimeout(fn: () => void, ms: number): TimeoutHandle {
    const handle = this.nextHandle++;
    this.timers.set(handle, { handle, dueAt: this.t + Math.max(0, ms), seq: this.seq++, fn });
    return handle;
  }

  clearTimeout(handle: TimeoutHandle): void {
    this.timers.delete(handle);
  }

  /** Number of pending timers (test introspection). */
  get pendingCount(): number {
    return this.timers.size;
  }

  /**
   * Advance simulated time; returns a promise that resolves after the fired
   * callbacks' synchronous continuations and one microtask drain, so tests can
   * `await clock.advance(x)` and observe promise resolutions deterministically.
   */
  async advance(ms: number): Promise<void> {
    const target = this.t + ms;
    for (;;) {
      const due = [...this.timers.values()]
        .filter((tm) => tm.dueAt <= target)
        .sort((a, b) => a.dueAt - b.dueAt || a.seq - b.seq);
      if (due.length === 0) break;
      const tm = due[0]!;
      this.timers.delete(tm.handle);
      this.t = Math.max(this.t, tm.dueAt);
      tm.fn();
      // Let promise continuations scheduled by the callback settle before the
      // next timer fires (probes resolving on the simulated clock, etc.).
      await Promise.resolve();
    }
    this.t = target;
    await Promise.resolve();
    await Promise.resolve();
  }
}
