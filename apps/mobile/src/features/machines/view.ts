/**
 * Machine card view-model (UI spec §5 + §6.3): the ONE status language —
 * four connection paths, each with a fixed colour, icon and label, used
 * identically on every screen. Colour is never the only signal.
 */

import type { ConnState } from '../../domain/connection/sm-conn';
import type { PairedAgent, Tier } from '../../domain/entities';

export type PathKey = 'wifi' | 'tunnel' | 'relay' | 'offline';

export interface ChipView {
  /** Chip label per UI spec §5.1. */
  label: string;
  path: PathKey;
  icon: 'wifi' | 'shield' | 'cloud' | 'wifi-off';
  /** Connecting keeps the previous colour with a pulsing dot. */
  pulsing?: boolean;
  /** Needs attention → Error colour (§5.1 transient state). */
  attention?: boolean;
  /** Optional detail line for the connection details sheet (§5.4). */
  detail?: string;
}

export function tierToPath(tier: Tier): PathKey {
  switch (tier) {
    case 'T0':
    case 'T1':
      return 'wifi';
    case 'T2':
      return 'tunnel';
    case 'T3':
      return 'relay';
  }
}

const PATH_META: Record<PathKey, { icon: ChipView['icon']; label: string }> = {
  wifi: { icon: 'wifi', label: 'Wi-Fi' },
  tunnel: { icon: 'shield', label: 'Secure tunnel' },
  relay: { icon: 'cloud', label: 'Relay' },
  offline: { icon: 'wifi-off', label: 'Offline' },
};

export function pathChip(path: PathKey, detail?: string): ChipView {
  return { ...PATH_META[path], path, detail };
}

/**
 * Project a SM-CONN state onto the chip system. UI never infers state
 * (invariant 4) — this is the ONLY place the mapping lives.
 */
export function connStateToChip(state: ConnState): ChipView {
  switch (state.s) {
    case 'CONNECTED':
      return pathChip(tierToPath(state.tier ?? 'T0'));
    case 'DEGRADED':
      return { ...pathChip('relay', 'Connected, health checks failing'), label: 'Relay' };
    case 'IDLE':
      return pathChip('offline');
    case 'UNREACHABLE':
      return pathChip('offline', state.reason ? `Reason: ${state.reason}` : undefined);
    case 'PLANNING':
    case 'CONNECTING':
    case 'AUTHENTICATING':
    case 'RECONNECTING':
      // Transient "Connecting": previous colour if known, else offline grey.
      return {
        ...(state.tier ? PATH_META[tierToPath(state.tier)] : PATH_META['offline']),
        path: state.tier ? tierToPath(state.tier) : 'offline',
        label: 'Connecting',
        pulsing: true,
      };
    case 'BLOCKED_PERMISSION':
      return { icon: 'wifi-off', label: 'Allow access', path: 'offline', attention: true };
    case 'PIN_MISMATCH':
      return { icon: 'wifi-off', label: 'Trust check', path: 'offline', attention: true };
    case 'REVOKED':
      return { icon: 'wifi-off', label: 'Access removed', path: 'offline', attention: true };
    case 'VERSION_INCOMPATIBLE':
      return { icon: 'wifi-off', label: 'Update required', path: 'offline', attention: true };
  }
}

export interface MachineCardVM {
  agentId: string;
  name: string;
  chip: ChipView;
  /** e.g. "RTX 4070 · 12 GB" or "CPU only" (§6.3 card anatomy). */
  hardwareLine?: string;
  /** e.g. "Qwen 3.5 9B · 18 tok/s" (§6.3). */
  modelLine?: string;
  /** Offline cards stay legible at 78 % opacity (§6.3 behaviour). */
  dimmed: boolean;
  /** Online machines first, preferred on top, then most recently used (§6.3). */
  sortKey: [number, number, number];
}

export interface MachineCardInput {
  agent: PairedAgent;
  conn: ConnState;
  /** This agent is the user's preferred machine. */
  preferred?: boolean;
  hardwareLine?: string;
  modelLine?: string;
  now: number;
}

export function buildMachineCard(input: MachineCardInput): MachineCardVM {
  const chip = connStateToChip(input.conn);
  const online = input.conn.s === 'CONNECTED';
  const recency = input.agent.lastConnectedAt ?? 0;
  return {
    agentId: input.agent.agentId,
    name: input.agent.displayName,
    chip,
    hardwareLine: input.hardwareLine,
    modelLine: input.modelLine,
    dimmed: !online,
    sortKey: [online ? 0 : 1, input.preferred ? 0 : 1, -recency],
  };
}

export function sortCards(cards: MachineCardVM[], keys: Record<string, [number, number, number]>): MachineCardVM[] {
  return [...cards].sort((a, b) => {
    const ka = keys[a.agentId] ?? a.sortKey;
    const kb = keys[b.agentId] ?? b.sortKey;
    for (let i = 0; i < 3; i++) {
      if (ka[i] !== kb[i]) return (ka[i] as number) - (kb[i] as number);
    }
    return a.name.localeCompare(b.name);
  });
}
