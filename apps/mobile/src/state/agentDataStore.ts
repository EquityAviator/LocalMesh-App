/**
 * Per-Agent live data fetched through MeshApiClient (§11.3): /health backends
 * + /models snapshot + last refresh error. Metadata only — never Content, no
 * secrets (§13.10, §17.10). Web demo fills this via features/machines/live.
 */

import type { ModelEntry } from '../domain/entities';
import { createStore, type TinyStore } from './store';

export interface BackendStatus {
  id: string;
  status: string;
}

export interface AgentLive {
  /** Overall §13.2 health status (ok/degraded/down). */
  status?: string;
  backends: BackendStatus[];
  models: ModelEntry[];
  fetchedAt?: number;
  /** Last refresh failure, machine-readable detail only (§17.10). */
  error?: string;
}

export type AgentDataState = Record<string, AgentLive>;

export const agentDataStore: TinyStore<AgentDataState> = createStore({});

export function emptyAgentLive(): AgentLive {
  return { backends: [], models: [] };
}

export function setAgentData(agentId: string, live: AgentLive): void {
  agentDataStore.setState((prev) => ({ ...prev, [agentId]: live }));
}

/** Optimistic patch for one model row (load/unload, §13.2 API-MODEL-02/03). */
export function patchAgentModel(agentId: string, meshModelId: string, patch: Partial<ModelEntry>): void {
  agentDataStore.setState((prev) => {
    const live = prev[agentId];
    if (!live) return prev;
    return {
      ...prev,
      [agentId]: {
        ...live,
        models: live.models.map((m) => (m.meshModelId === meshModelId ? { ...m, ...patch } : m)),
      },
    };
  });
}
