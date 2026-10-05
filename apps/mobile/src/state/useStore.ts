/**
 * React binding for TinyStore (zustand-shaped) via useSyncExternalStore.
 * Lives in src/state but only imports React — safe for bundling, unused by
 * the domain/data layers.
 */

import { useSyncExternalStore } from 'react';
import type { TinyStore } from './store';

export function useStore<T>(store: TinyStore<T>): T {
  return useSyncExternalStore(
    (onChange) => store.subscribe(() => onChange()),
    () => store.getState(),
    () => store.getState(),
  );
}
