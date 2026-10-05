/**
 * Minimal hand-rolled store (zustand-shaped: getState/setState/subscribe) so
 * the app and tests share one tiny reactive primitive without pulling a
 * runtime dependency into the domain/data layers (§11.3).
 */

export interface TinyStore<T> {
  getState(): T;
  setState(updater: T | ((prev: T) => T)): void;
  subscribe(fn: (state: T, prev: T) => void): () => void;
}

export function createStore<T>(initial: T): TinyStore<T> {
  let state = initial;
  const listeners = new Set<(s: T, prev: T) => void>();
  return {
    getState: () => state,
    setState(updater) {
      const prev = state;
      const next = typeof updater === 'function' ? (updater as (p: T) => T)(prev) : updater;
      if (Object.is(next, prev)) return;
      state = next;
      for (const fn of listeners) fn(state, prev);
    },
    subscribe(fn) {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
  };
}
