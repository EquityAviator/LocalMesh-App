/**
 * §18.3 — Aggregating probe failures → reason → CI mapping (normative).
 *
 * After a race with no winner, each candidate failure is classified and the
 * HIGHEST-RANKED reason present is reported. The UI never re-derives the
 * reason (SM-CONN invariant 4); it only renders state + reason.
 */

export type ReasonCode =
  | 'PIN_MISMATCH'
  | 'REVOKED'
  | 'PERMISSION_DENIED'
  | 'NO_NETWORK'
  | 'TAILNET_NOT_ACTIVE'
  | 'OTHER_VPN_ACTIVE'
  | 'TCP_REFUSED'
  | 'TIMEOUT_LAN'
  | 'NOT_FOUND_LAN'
  | 'UNKNOWN';

/** Rank 1 is the most severe; lower number wins. */
export const REASON_RANK: Readonly<Record<ReasonCode, number>> = {
  PIN_MISMATCH: 1,
  REVOKED: 2,
  PERMISSION_DENIED: 3,
  NO_NETWORK: 4,
  TAILNET_NOT_ACTIVE: 5,
  OTHER_VPN_ACTIVE: 6,
  TCP_REFUSED: 7,
  TIMEOUT_LAN: 8,
  NOT_FOUND_LAN: 9,
  UNKNOWN: 10,
};

/** §18.3 "Maps to" column (verbatim). */
export const REASON_CI: Readonly<Record<ReasonCode, string>> = {
  PIN_MISMATCH: 'CI-12',
  REVOKED: 'CI-12b',
  PERMISSION_DENIED: 'CI-09',
  NO_NETWORK: 'L0',
  TAILNET_NOT_ACTIVE: 'CI-13',
  OTHER_VPN_ACTIVE: 'CI-14',
  TCP_REFUSED: 'CI-04',
  TIMEOUT_LAN: 'CI-03',
  NOT_FOUND_LAN: 'CI-01',
  UNKNOWN: 'generic',
};

export const ALL_REASONS: readonly ReasonCode[] = Object.keys(REASON_RANK) as ReasonCode[];

/** Context the aggregator needs to apply the §18.3 conditions. */
export interface FailureContext {
  transport: 'wifi' | 'cellular' | 'ethernet' | 'none';
  vpnActive: boolean;
  permission: 'granted' | 'denied' | 'not_required' | 'unknown';
  /** Every candidate that raced was a LAN candidate (T0/T1). */
  onlyLanCandidates: boolean;
  /** Discovery currently sees this Agent (drives rank 8 vs rank 9). */
  sawInDiscovery: boolean;
  /** Some candidate presented a different SPKI (rank 1 shorthand). */
  sawPinMismatch?: boolean;
  /** /auth/token answered 403 (rank 2 shorthand). */
  sawRevoked?: boolean;
}

/**
 * Pick the highest-ranked §18.3 reason from the failure list.
 * `failures` entries use ProbeFailureKind from entities; PIN_MISMATCH /
 * REVOKED may also arrive via the context shorthands.
 */
export function aggregateReasons(
  failures: readonly { kind: string; tier?: string; sawInDiscovery?: boolean }[],
  ctx: FailureContext,
): ReasonCode {
  const present = new Set<ReasonCode>();

  if (ctx.sawPinMismatch || failures.some((f) => f.kind === 'pin_mismatch')) present.add('PIN_MISMATCH');
  if (ctx.sawRevoked || failures.some((f) => f.kind === 'revoked')) present.add('REVOKED');

  if (ctx.onlyLanCandidates && ctx.permission === 'denied') present.add('PERMISSION_DENIED');
  if (ctx.transport === 'none') present.add('NO_NETWORK');

  // Rank 5: T2 only, !vpnActive. Rank 6: T2 timeouts with vpnActive.
  const t2Fails = failures.filter((f) => f.tier === 'T2');
  if (failures.length > 0 && t2Fails.length === failures.length && !ctx.vpnActive) {
    present.add('TAILNET_NOT_ACTIVE');
  }
  if (t2Fails.some((f) => f.kind === 'timeout') && ctx.vpnActive) {
    present.add('OTHER_VPN_ACTIVE');
  }

  if (failures.some((f) => f.kind === 'refused')) present.add('TCP_REFUSED');

  const lanTimedOut = failures.some(
    (f) => (f.tier === 'T0' || f.tier === 'T1') && (f.kind === 'timeout' || f.kind === 'dns' || f.kind === 'info_mismatch'),
  );
  if (lanTimedOut && ctx.sawInDiscovery) present.add('TIMEOUT_LAN');
  if (lanTimedOut && !ctx.sawInDiscovery) present.add('NOT_FOUND_LAN');

  if (present.size === 0) present.add('UNKNOWN');

  let best: ReasonCode = 'UNKNOWN';
  for (const r of present) {
    if (REASON_RANK[r] < REASON_RANK[best]) best = r;
  }
  return best;
}

/** Public shape handed to the UI (invariant 4: state + reason exposed). */
export function reasonView(reason: ReasonCode): { reason: ReasonCode; ci: string } {
  return { reason, ci: REASON_CI[reason] };
}
