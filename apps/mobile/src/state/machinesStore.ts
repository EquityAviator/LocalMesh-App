/**
 * Machines store — per-Agent SM-CONN view + the paired-agent list (§11.1
 * src/state). Data arrives from repositories; connection views are projected
 * from the pure reducer state (invariant 4: UI never infers state itself).
 */

import type { ConnState } from '../domain/connection/sm-conn';
import type { DiscoveryEntry, PairedAgent } from '../domain/entities';
import { createStore, type TinyStore } from './store';

export interface MachinesState {
  agents: PairedAgent[];
  /** agent_id → SM-CONN state (one Connection Manager instance per Agent, §15.1). */
  conn: Record<string, ConnState>;
  discovery: DiscoveryEntry[];
}

export type MachinesStore = TinyStore<MachinesState>;

export const machinesStore: MachinesStore = createStore<MachinesState>({
  agents: [],
  conn: {},
  discovery: [],
});

export function setConnState(agentId: string, state: ConnState): void {
  machinesStore.setState((prev) => ({
    ...prev,
    conn: { ...prev.conn, [agentId]: state },
  }));
}

export function setAgents(agents: PairedAgent[]): void {
  machinesStore.setState((prev) => ({ ...prev, agents }));
}

export function setDiscovery(discovery: DiscoveryEntry[]): void {
  machinesStore.setState((prev) => ({ ...prev, discovery }));
}
