/**
 * Pair confirmation flow (UI spec 6.2 — steps 2..4; §15.4 sequence; §17.8
 * confirmation rule). Pure view-model helpers for the pair/confirm screen.
 */

import type { ParsedPairPayload } from './qr';

export const PAIR_STEPS = ['scan', 'verify', 'name', 'remote'] as const;
export type PairStep = (typeof PAIR_STEPS)[number];

export function stepLabel(step: PairStep): string {
  const idx = PAIR_STEPS.indexOf(step);
  return `Step ${idx + 1} of ${PAIR_STEPS.length}`;
}

export interface ConfirmGate {
  /** SAS matched on both screens (§15.4 steps 10-11). */
  sasMatched: boolean;
  /** Machine named by the user (prefilled from `n`). */
  named: boolean;
}

/** Advance only when the current step's gate is satisfied. */
export function canAdvance(from: PairStep, gate: ConfirmGate): boolean {
  switch (from) {
    case 'scan':
      return true;
    case 'verify':
      return gate.sasMatched; // "They match" — mismatch cancels pairing
    case 'name':
      return gate.named;
    case 'remote':
      return false; // terminal step; completion happens outside
  }
}

export interface RemoteCheckRow {
  id: 'signed-in' | 'paired' | 'tunnel-app';
  title: string;
  detail: string;
  needsAction: boolean;
}

/**
 * Remote access check rows (UI spec 6.2 step 4) — driven by live status, so a
 * transport that needs no extra app simply has no third row.
 */
export function buildRemoteCheckRows(input: {
  signedIn: boolean;
  pairedName?: string;
  tunnelAppInstalled: boolean;
}): RemoteCheckRow[] {
  const rows: RemoteCheckRow[] = [
    {
      id: 'signed-in',
      title: 'Signed in',
      detail: 'Identity only. Chats never go through Google.',
      needsAction: !input.signedIn,
    },
    {
      id: 'paired',
      title: 'Paired',
      detail: input.pairedName ? `Named "${input.pairedName}"` : 'Not paired yet',
      needsAction: !input.pairedName,
    },
  ];
  if (!input.tunnelAppInstalled) {
    rows.push({
      id: 'tunnel-app',
      title: 'Secure tunnel app',
      detail: 'Not installed on this phone',
      needsAction: true,
    });
  }
  return rows;
}

/** The payload summary shown on the confirm screen (no secret rendered). */
export function payloadSummary(p: ParsedPairPayload): { name: string; agentId: string; fpPrefix: string; endpointCount: number } {
  return {
    name: p.name ?? 'This machine',
    agentId: p.agentId,
    fpPrefix: p.fingerprint.slice(0, 12),
    endpointCount: p.endpoints.length,
  };
}
