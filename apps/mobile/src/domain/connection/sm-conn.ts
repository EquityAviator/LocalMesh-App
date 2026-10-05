/**
 * §15.1 — SM-CONN, Connection Manager state machine (one instance per paired
 * Agent; PURE reducer in domain/connection, §11.1/§11.3).
 *
 * States, transitions and the four invariants are normative (§15.1 table +
 * mermaid diagram). This module performs no I/O and imports nothing from
 * react-native/expo — the native layer executes probes and reports results as
 * events (§11.3).
 */

import type { Endpoint, PermState, Tier } from '../entities';
import type { ReasonCode } from './reasons';

export type ConnStateName =
  | 'IDLE'
  | 'PLANNING'
  | 'CONNECTING'
  | 'AUTHENTICATING'
  | 'CONNECTED'
  | 'DEGRADED'
  | 'RECONNECTING'
  | 'BLOCKED_PERMISSION'
  | 'UNREACHABLE'
  | 'PIN_MISMATCH'
  | 'REVOKED'
  | 'VERSION_INCOMPATIBLE';

export interface ConnState {
  s: ConnStateName;
  /** Invariant 1: exactly one active Endpoint while CONNECTED. */
  endpoint?: Endpoint;
  tier?: Tier;
  /** Aggregated §18.3 reason for UNREACHABLE; CI id exposed to the UI. */
  reason?: ReasonCode;
  /**
   * Invariant 3 bookkeeping: a network change arrived while a stream was
   * active. We stayed on the endpoint; re-plan AFTER the stream ends.
   */
  pendingReplanAfterStream?: boolean;
  /** Set when APP_BACKGROUND was accepted; drives the 30 s grace rule. */
  backgroundedAt?: number;
}

export type ConnEvent =
  | { t: 'APP_FOREGROUND'; at: number }
  | { t: 'USER_CONNECT' }
  | { t: 'APP_BACKGROUND'; at: number }
  /** Manager timer: 30 s after APP_BACKGROUND with no active stream. */
  | { t: 'GRACE_EXPIRED'; at: number; activeStream?: boolean }
  /** Manager timer: DEGRADED re-plan after 10 s (§15.1). */
  | { t: 'DEGRADED_TIMER' }
  /** Result of PLANNING: 0 candidates, LAN-only candidates + denied permission, or >0. */
  | { t: 'CANDIDATES_READY'; count: number; onlyLan: boolean; permission: PermState; zeroReason?: ReasonCode }
  | { t: 'PROBE_OK'; endpoint: Endpoint }
  | { t: 'ALL_PROBES_FAIL'; reason: ReasonCode }
  | { t: 'PIN_MISMATCH' }
  | { t: 'AUTH_OK'; endpoint: Endpoint; tier: Tier }
  | { t: 'DEVICE_REVOKED' }
  | { t: 'VERSION_INCOMPATIBLE' }
  | { t: 'AUTH_TRANSPORT_FAIL'; reason?: ReasonCode }
  /** SM-STREAM 401 path exhausted its single refresh+retry (§15.3). */
  | { t: 'AUTH_FAIL' }
  | { t: 'HEALTH_FAIL_STREAK'; count: number }
  | { t: 'HEALTH_OK' }
  | { t: 'NETWORK_CHANGED'; activeStream?: boolean }
  | { t: 'STREAM_ERROR_NETWORK'; activeStream?: boolean }
  | { t: 'STREAM_ENDED' }
  | { t: 'USER_RETRY' }
  | { t: 'DISCOVERY_FOUND' }
  /** Backoff timer fired while foregrounded (§16.1). */
  | { t: 'BACKOFF_TICK' }
  | { t: 'PERMISSION_CHANGED'; granted: boolean }
  /** User explicitly chose "Trust new identity" / re-pair / update (invariant 2). */
  | { t: 'USER_REPAIR' }
  /** Agent removed by the user. */
  | { t: 'REMOVE' };

/** Events a terminal (PIN_MISMATCH/REVOKED/VERSION_INCOMPATIBLE) state accepts. */
const TERMINAL_RECOVERY: ReadonlySet<ConnEvent['t']> = new Set(['USER_REPAIR', 'REMOVE']);

const INITIAL: ConnState = { s: 'IDLE' };

/**
 * The reducer. Unknown/inaaplicable events return the SAME state object
 * (ignored), which makes "hard stop" assertions trivial.
 */
export function reduceConn(state: ConnState, ev: ConnEvent): ConnState {
  // Invariant 2: PIN_MISMATCH never auto-retries and never falls through to
  // another candidate — only explicit user action leaves the state.
  if (state.s === 'PIN_MISMATCH') {
    if (!TERMINAL_RECOVERY.has(ev.t)) return state;
    if (ev.t === 'REMOVE') return { s: 'IDLE' };
    return { s: 'PLANNING' }; // full re-pair ("Trust new identity") → plan again
  }
  if (state.s === 'REVOKED' || state.s === 'VERSION_INCOMPATIBLE') {
    if (!TERMINAL_RECOVERY.has(ev.t)) return state;
    if (ev.t === 'REMOVE') return { s: 'IDLE' };
    return { s: 'PLANNING' };
  }

  switch (state.s) {
    case 'IDLE':
      if (ev.t === 'APP_FOREGROUND' || ev.t === 'USER_CONNECT') return { s: 'PLANNING' };
      return state;

    case 'PLANNING': {
      if (ev.t === 'CANDIDATES_READY') {
        if (ev.count > 0) return { s: 'CONNECTING' };
        // §15.1: PLANNING → BLOCKED_PERMISSION when only LAN candidates and
        // permission denied; PLANNING → UNREACHABLE when candidates == 0.
        if (ev.onlyLan && ev.permission === 'denied') return { s: 'BLOCKED_PERMISSION' };
        return { s: 'UNREACHABLE', reason: ev.zeroReason ?? 'UNKNOWN' };
      }
      return state;
    }

    case 'CONNECTING':
      if (ev.t === 'PROBE_OK') return { s: 'AUTHENTICATING', endpoint: ev.endpoint };
      if (ev.t === 'ALL_PROBES_FAIL') return { s: 'UNREACHABLE', reason: ev.reason };
      if (ev.t === 'PIN_MISMATCH') return { s: 'PIN_MISMATCH' };
      return state;

    case 'AUTHENTICATING':
      if (ev.t === 'AUTH_OK') return { s: 'CONNECTED', endpoint: ev.endpoint, tier: ev.tier };
      if (ev.t === 'DEVICE_REVOKED') return { s: 'REVOKED' };
      if (ev.t === 'VERSION_INCOMPATIBLE') return { s: 'VERSION_INCOMPATIBLE' };
      if (ev.t === 'AUTH_TRANSPORT_FAIL') return { s: 'UNREACHABLE', reason: ev.reason ?? 'UNKNOWN' };
      return state;

    case 'CONNECTED': {
      if (ev.t === 'HEALTH_FAIL_STREAK' && ev.count >= 2) {
        return { s: 'DEGRADED', endpoint: state.endpoint, tier: state.tier };
      }
      // Invariant 3: a network change during an ACTIVE stream does NOT switch
      // endpoints mid-stream. Keep CONNECTED, mark the stream interrupted
      // (SM-STREAM) and re-plan AFTER it ends.
      if (ev.t === 'NETWORK_CHANGED' || ev.t === 'STREAM_ERROR_NETWORK') {
        if (ev.activeStream === true && state.endpoint !== undefined) {
          return { ...state, pendingReplanAfterStream: true };
        }
        return { s: 'RECONNECTING' };
      }
      if (ev.t === 'STREAM_ENDED') {
        if (state.pendingReplanAfterStream) return { s: 'RECONNECTING' };
        return state;
      }
      if (ev.t === 'APP_BACKGROUND') {
        return { ...state, backgroundedAt: ev.at };
      }
      if (ev.t === 'GRACE_EXPIRED') {
        // 30 s grace with no active stream → IDLE (§15.1 edge).
        if (state.backgroundedAt !== undefined && ev.activeStream !== true) return { s: 'IDLE' };
        return state;
      }
      if (ev.t === 'APP_FOREGROUND') {
        return { ...state, backgroundedAt: undefined };
      }
      return state;
    }

    case 'DEGRADED':
      if (ev.t === 'HEALTH_OK') return { s: 'CONNECTED', endpoint: state.endpoint, tier: state.tier };
      if (ev.t === 'DEGRADED_TIMER') return { s: 'RECONNECTING' };
      if (ev.t === 'NETWORK_CHANGED') return { s: 'RECONNECTING' };
      return state;

    case 'RECONNECTING':
      // §15.1: RECONNECTING → PLANNING "immediate". The manager dispatches
      // REPLAN right after entering; the reducer collapses on any event.
      if (ev.t === 'REMOVE') return { s: 'IDLE' };
      return { ...state, s: 'PLANNING' };

    case 'BLOCKED_PERMISSION':
      if (ev.t === 'PERMISSION_CHANGED' && ev.granted) return { s: 'PLANNING' };
      return state;

    case 'UNREACHABLE':
      if (
        ev.t === 'USER_RETRY' ||
        ev.t === 'NETWORK_CHANGED' ||
        ev.t === 'DISCOVERY_FOUND' ||
        ev.t === 'BACKOFF_TICK'
      ) {
        return { s: 'PLANNING' };
      }
      return state;

    default:
      return state;
  }
}

/** Convenience wrapper mirroring how the Connection Manager pumps events. */
export function createConnectionManager(initial: ConnState = INITIAL) {
  let state = initial;
  return {
    get state(): ConnState {
      return state;
    },
    dispatch(ev: ConnEvent): ConnState {
      state = reduceConn(state, ev);
      return state;
    },
    /** RECONNECTING → PLANNING "immediate" (§15.1). */
    replan(): ConnState {
      return this.dispatch({ t: 'DISCOVERY_FOUND' });
    },
  };
}

/** Invariant 1 helper: while CONNECTED exactly one Endpoint is active. */
export function assertSingleActiveEndpoint(state: ConnState): void {
  if (state.s === 'CONNECTED') {
    if (!state.endpoint) throw new Error('INVARIANT-1 violated: CONNECTED without an active endpoint');
  }
}

/**
 * Invariant 4: the UI receives state + reason and never infers connectivity
 * itself. This is the single projection every screen renders.
 */
export function connView(state: ConnState): {
  state: ConnStateName;
  reason?: ReasonCode;
  tier?: Tier;
  endpointUrl?: string;
} {
  return {
    state: state.s,
    reason: state.reason,
    tier: state.tier,
    endpointUrl: state.endpoint?.url,
  };
}
