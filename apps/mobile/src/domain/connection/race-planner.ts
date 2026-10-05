/**
 * §16.1 — Candidate planning & staggered race (App, `domain/connection`).
 *
 * PURE: generation, pruning, ordering and the race executor over an injected
 * Clock + probe function. The native layer executes probes (pinned TLS
 * handshake → GET /info) and reports results; this module owns ALL timing
 * policy (stagger, tier timeouts, preempt grace, overall deadline).
 *
 * Tunable defaults are the §16.1 defaults (normative values unless the owner
 * overrides the tunables).
 */

import type { DiscoveryEntry, Endpoint, EndpointOrigin, NetState, PairedAgent, PermState, ProbeFailure, Tier } from '../entities';
import type { Clock, TimeoutHandle } from './clock';

// ---------------------------------------------------------------------------
// §16.1 race parameters (defaults; "parameters tunable, defaults shown")
// ---------------------------------------------------------------------------

export const STAGGER_MS = 250;
export const TIER_TIMEOUT_MS: Readonly<Record<Tier, number>> = {
  T0: 1500,
  T1: 2500,
  T2: 4000,
  T3: 4000,
};
export const PREEMPT_GRACE_MS = 400;
export const OVERALL_DEADLINE_MS = 8000;
/** mdnsFresh window: discovery information seen ≤ 30 s ago (§16.1 rule 1). */
export const MDNS_FRESH_MS = 30_000;
/** Pruning cap (§16.1). */
export const MAX_CANDIDATES = 6;

// ---------------------------------------------------------------------------
// Candidate classification (§16.1 rule 5 for manual; rules 1-4 for known pools)
// ---------------------------------------------------------------------------

function ipv4Parts(host: string): number[] | null {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (!m) return null;
  return m.slice(1).map((s) => Number(s));
}

function isPrivate(host: string): boolean {
  const p = ipv4Parts(host);
  if (!p) return false;
  const [a, b] = p as [number, number, number, number];
  if (a === 10 || a === 127) return true; // RFC1918 10/8; loopback (emulator 10.0.2.2 included)
  if (a === 192 && b === 168) return true; // RFC1918 192.168/16
  if (a === 172 && b! >= 16 && b! <= 31) return true; // RFC1918 172.16/12
  return false;
}

/** CGNAT / Tailnet range 100.64.0.0/10 (§6.3). */
export function isTailnetIp(host: string): boolean {
  const p = ipv4Parts(host);
  if (!p) return false;
  const [a, b] = p as [number, number, number, number];
  return a === 100 && b! >= 64 && b! <= 127;
}

/**
 * Manual endpoint classification (§16.1 rule 5, verbatim):
 * RFC1918 → T0; 100.64.0.0/10 → T2; hostname ending `.ts.net` → T2;
 * other hostname → T1.
 */
export function classifyEndpoint(url: string): Tier {
  let host: string;
  try {
    host = new URL(url).hostname;
  } catch {
    return 'T1';
  }
  if (isPrivate(host)) return 'T0';
  if (isTailnetIp(host)) return 'T2';
  if (host.endsWith('.ts.net')) return 'T2';
  return 'T1';
}

const ORIGIN_PRIORITY: Readonly<Record<EndpointOrigin, number>> = {
  mdns: 0,
  paired: 1,
  manual: 2,
  learned: 3,
};

function normalizeUrl(url: string): string {
  return url.trim().replace(/\/+$/, '');
}

// ---------------------------------------------------------------------------
// Planning
// ---------------------------------------------------------------------------

export interface PlannedCandidate {
  endpoint: Endpoint;
  /** discovery currently advertises this Agent on this network (§18.3 rank 8/9). */
  sawInDiscovery: boolean;
}

export interface PlanResult {
  candidates: PlannedCandidate[];
  /** CI hints produced by pruning, e.g. 'CI-13' (§16.1). */
  hints: string[];
  /** §15.1 PLANNING → BLOCKED_PERMISSION condition. */
  blockedPermission: boolean;
}

export interface PlanContext {
  net: NetState;
  permission: PermState;
  discovery: readonly DiscoveryEntry[];
  now: number;
}

/**
 * Candidate generation (§16.1 rules 1-5) + pruning rules + dedupe + cap 6.
 * Pure function of the PairedAgent record, discovery results and network state.
 */
export function planCandidates(agent: PairedAgent, ctx: PlanContext): PlanResult {
  const hints: string[] = [];
  const out: Endpoint[] = [];
  const seen = new Set<string>();
  const push = (e: Endpoint) => {
    const url = normalizeUrl(e.url);
    if (seen.has(url)) return;
    seen.add(url);
    out.push({ ...e, url });
  };

  const discovery = ctx.discovery.filter((d) => d.agentId === agent.agentId);
  const discoveryFresh = discovery.some((d) => ctx.now - d.seenAt <= MDNS_FRESH_MS);
  const discoveryUrls = discovery.flatMap((d) => d.urls);

  // 1. mdnsFresh — seen ≤ 30 s ago → T0, ranked first.
  if (discoveryFresh) {
    for (const d of discovery) {
      for (const url of d.urls) push({ url, tier: 'T0', origin: 'mdns', lastOkAt: d.seenAt });
    }
  }

  // 2. lanKnown — stored LAN IPs (paired/previous success), most-recent-success first.
  const lanKnown = agent.endpoints
    .filter((e) => e.tier === 'T0' && e.origin !== 'mdns')
    .sort((a, b) => (b.lastOkAt ?? -1) - (a.lastOkAt ?? -1));
  for (const e of lanKnown) push(e);

  // 3. lanName — `<hostname>.local` if known → T1.
  if (agent.hostname && agent.hostname.endsWith('.local')) {
    const port = defaultPortFrom(agent.endpoints) ?? 8443;
    push({ url: `https://${agent.hostname}:${port}`, tier: 'T1', origin: 'paired' });
  }

  // 4. tailnet — MagicDNS name, then 100.x IP (from pairing/GET /device).
  //    Stored T2 endpoints were already classified at pairing time (MagicDNS
  //    `.ts.net` names and 100.64.0.0/10 addresses both qualify), so the whole
  //    stored T2 pool is taken, MagicDNS first.
  if (agent.magicDnsName) {
    const port = defaultPortFrom(agent.endpoints) ?? 8443;
    push({ url: `https://${agent.magicDnsName}:${port}`, tier: 'T2', origin: 'paired' });
  }
  for (const e of agent.endpoints.filter((e) => e.tier === 'T2')) {
    push(e);
  }

  // 5. manual — user-entered endpoints, classified.
  for (const e of agent.endpoints.filter((e) => e.origin === 'manual')) {
    push({ url: e.url, tier: classifyEndpoint(e.url), origin: 'manual', lastOkAt: e.lastOkAt });
  }

  const allGenerated = [...out];

  // --- Pruning rules (§16.1, verbatim conditions) ---
  const permissionDenied = ctx.permission === 'denied';
  const cellularNoVpn = ctx.net.transport === 'cellular' && !ctx.net.vpnActive;
  const noVpn = !ctx.net.vpnActive;

  let kept = allGenerated;
  if (permissionDenied) {
    kept = kept.filter((e) => e.tier !== 'T0' && e.tier !== 'T1');
  }
  if (cellularNoVpn) {
    kept = kept.filter((e) => e.tier !== 'T0' && e.tier !== 'T1');
  }
  if (noVpn) {
    const hadT2 = kept.some((e) => e.tier === 'T2');
    kept = kept.filter((e) => e.tier !== 'T2');
    if (hadT2) hints.push('CI-13'); // Tailnet is a VPN on Android [ASSUMPTION §6.3]
  }
  if (permissionDenied) {
    const hadLan = allGenerated.some((e) => e.tier === 'T0' || e.tier === 'T1');
    if (hadLan) hints.push('CI-09'); // §18.2 CI-09: local-network permission
  }
  if (cellularNoVpn) {
    const hadLan = allGenerated.some((e) => e.tier === 'T0' || e.tier === 'T1');
    // §18.2 CI-02 detection: "transport==cellular & no VPN & no T2 endpoint".
    if (hadLan) hints.push('CI-02');
  }

  // plan := candidates sorted by (tier asc, origin priority, lastOkAt desc)
  const sorted = [...kept].sort((a, b) => {
    const tierCmp = tierRank(a.tier) - tierRank(b.tier);
    if (tierCmp !== 0) return tierCmp;
    const orgCmp = ORIGIN_PRIORITY[a.origin] - ORIGIN_PRIORITY[b.origin];
    if (orgCmp !== 0) return orgCmp;
    return (b.lastOkAt ?? -1) - (a.lastOkAt ?? -1);
  });

  // keep at most 6 candidates
  const capped = sorted.slice(0, MAX_CANDIDATES);

  const onlyLan = allGenerated.length > 0 && allGenerated.every((e) => e.tier === 'T0' || e.tier === 'T1');
  const blockedPermission = permissionDenied && onlyLan && capped.length === 0;

  return {
    candidates: capped.map((endpoint) => ({
      endpoint,
      sawInDiscovery: discoveryUrls.includes(endpoint.url),
    })),
    hints,
    blockedPermission,
  };
}

function tierRank(t: Tier): number {
  return { T0: 0, T1: 1, T2: 2, T3: 3 }[t];
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return '';
  }
}

function defaultPortFrom(endpoints: readonly Endpoint[]): number | null {
  for (const e of endpoints) {
    try {
      const u = new URL(e.url);
      if (u.port) return Number(u.port);
      return u.protocol === 'https:' ? 443 : 80;
    } catch {
      /* skip malformed */
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Staggered race
// ---------------------------------------------------------------------------

export type ProbeOutcome = { ok: true } | { ok: false; kind: ProbeFailure['kind'] };

export type ProbeFn = (endpoint: Endpoint) => Promise<ProbeOutcome>;

export type RaceResult =
  | { outcome: 'won'; endpoint: Endpoint; index: number; wonAt: number; probedCount: number }
  | { outcome: 'pin_mismatch'; failures: ProbeFailure[] }
  | { outcome: 'unreachable'; failures: ProbeFailure[]; at: number };

export interface RaceOptions {
  clock: Clock;
  probe: ProbeFn;
  staggerMs?: number;
  tierTimeouts?: Readonly<Record<Tier, number>>;
  preemptGraceMs?: number;
  overallDeadlineMs?: number;
}

interface ProbeSlot {
  index: number;
  candidate: PlannedCandidate;
  status: 'scheduled' | 'running' | 'failed' | 'won' | 'cancelled';
  failure?: ProbeFailure;
  timeoutHandle?: TimeoutHandle;
}

/**
 * §16.1 race, executed on the injected clock:
 *  - probe(i) scheduled at t0 + i*stagger (250 ms default);
 *  - per-candidate timeout by tier (T0=1500, T1=2500, T2=4000);
 *  - probe := pinned TLS handshake (SPKI == pin, else PIN_MISMATCH global)
 *    THEN GET /info; require info.agent_id == agent.agent_id (caller enforces);
 *  - first success wins; wait preemptGrace (400 ms) for a better-index late
 *    winner; cancel all others;
 *  - overall deadline 8000 ms.
 *
 * PIN_MISMATCH aborts the race globally (never falls through, invariant 2).
 */
export async function runRace(candidates: readonly PlannedCandidate[], opts: RaceOptions): Promise<RaceResult> {
  const staggerMs = opts.staggerMs ?? STAGGER_MS;
  const tierTimeouts = opts.tierTimeouts ?? TIER_TIMEOUT_MS;
  const preemptGraceMs = opts.preemptGraceMs ?? PREEMPT_GRACE_MS;
  const overallDeadlineMs = opts.overallDeadlineMs ?? OVERALL_DEADLINE_MS;
  const clock = opts.clock;
  const t0 = clock.now();

  const slots: ProbeSlot[] = candidates.map((candidate, index) => ({
    index,
    candidate,
    status: 'scheduled',
  }));

  const handles = new Set<TimeoutHandle>();
  let settled: RaceResult | null = null;
  let resolveFn!: (r: RaceResult) => void;
  const done = new Promise<RaceResult>((res) => {
    resolveFn = res;
  });
  let graceDeadline: number | null = null;
  let best: { index: number; endpoint: Endpoint; okAt: number } | null = null;

  const fail = (slot: ProbeSlot, kind: ProbeFailure['kind']): void => {
    if (slot.status === 'failed' || slot.status === 'won' || slot.status === 'cancelled') return;
    slot.status = 'failed';
    slot.failure = {
      url: slot.candidate.endpoint.url,
      tier: slot.candidate.endpoint.tier,
      kind,
      sawInDiscovery: slot.candidate.sawInDiscovery,
    };
    if (slot.timeoutHandle !== undefined) {
      clock.clearTimeout(slot.timeoutHandle);
      handles.delete(slot.timeoutHandle);
      slot.timeoutHandle = undefined;
    }
  };

  const finish = (result: RaceResult): void => {
    if (settled) return;
    settled = result;
    for (const h of handles) clock.clearTimeout(h);
    handles.clear();
    for (const slot of slots) {
      if (slot.status === 'scheduled' || slot.status === 'running') slot.status = 'cancelled';
    }
    resolveFn(result);
  };

  // Fresh status reads through a closure — defeats TS property narrowing so
  // the defensive 'cancelled' checks below stay well-typed (timers may have
  // cancelled the slot while the probe promise was in flight).
  const statusOf = (slot: ProbeSlot): ProbeSlot['status'] => slot.status;

  const probe = async (slot: ProbeSlot): Promise<void> => {
    if (settled) return;
    slot.status = 'running';
    const tier = slot.candidate.endpoint.tier;
    slot.timeoutHandle = clock.setTimeout(() => {
      fail(slot, 'timeout');
      maybeFinishAllFailed();
    }, tierTimeouts[tier]);
    handles.add(slot.timeoutHandle);
    try {
      const outcome = await opts.probe(slot.candidate.endpoint);
      if (settled || statusOf(slot) === 'cancelled') return;
      if (outcome.ok) {
        slot.status = 'won';
        onProbeWon(slot);
      } else {
        fail(slot, outcome.kind);
        if (outcome.kind === 'pin_mismatch') {
          finish({ outcome: 'pin_mismatch', failures: collectFailures() });
          return;
        }
        maybeFinishAllFailed();
      }
    } catch {
      if (settled || statusOf(slot) === 'cancelled') return;
      fail(slot, 'unknown');
      maybeFinishAllFailed();
    }
  };

  const collectFailures = (): ProbeFailure[] =>
    slots
      .filter((s) => s.status === 'failed' && s.failure !== undefined)
      .map((s) => s.failure as ProbeFailure);

  const maybeFinishAllFailed = (): void => {
    if (settled) return;
    const allDone = slots.every((s) => s.status === 'failed' || s.status === 'cancelled');
    const anyWon = slots.some((s) => s.status === 'won');
    if (allDone && !anyWon) {
      finish({ outcome: 'unreachable', failures: collectFailures(), at: clock.now() });
    }
  };

  const onProbeWon = (slot: ProbeSlot): void => {
    const okAt = clock.now();
    if (best === null || slot.index < best.index) {
      best = { index: slot.index, endpoint: slot.candidate.endpoint, okAt };
    }
    if (best.index === 0) {
      // No probe has a better plan index → grace cannot improve the outcome.
      finish({
        outcome: 'won',
        endpoint: best.endpoint,
        index: 0,
        wonAt: okAt,
        probedCount: slots.length,
      });
      return;
    }
    if (graceDeadline === null) {
      graceDeadline = okAt + preemptGraceMs;
      const h = clock.setTimeout(() => {
        if (settled || best === null) return;
        finish({
          outcome: 'won',
          endpoint: best.endpoint,
          index: best.index,
          // §16.1: "first := first successful probe at time t" — wonAt is the
          // winner's own success time, not the settle time.
          wonAt: best.okAt,
          probedCount: slots.length,
        });
      }, preemptGraceMs);
      handles.add(h);
    }
  };

  // overall deadline
  handles.add(
    clock.setTimeout(() => {
      if (settled) return;
      // Unresolved probes at the deadline count as timeouts (§16.1 "all probes failed").
      for (const slot of slots) {
        if (slot.status === 'scheduled' || slot.status === 'running') fail(slot, 'timeout');
      }
      if (best !== null) {
        finish({
          outcome: 'won',
          endpoint: best.endpoint,
          index: best.index,
          wonAt: best.okAt, // first-success time (§16.1 "first")
          probedCount: slots.length,
        });
      } else {
        finish({ outcome: 'unreachable', failures: collectFailures(), at: clock.now() });
      }
    }, overallDeadlineMs),
  );

  // staggered schedule: probe(i) at t0 + i*stagger
  slots.forEach((slot, i) => {
    const h = clock.setTimeout(() => {
      void probe(slot);
    }, i * staggerMs);
    handles.add(h);
  });

  return done;
}

// ---------------------------------------------------------------------------
// Learning (§16.1)
// ---------------------------------------------------------------------------

/** On success: set lastOkAt and promote the Endpoint in the stored list. */
export function recordSuccess(endpoints: readonly Endpoint[], url: string, now: number): Endpoint[] {
  const norm = normalizeUrl(url);
  const updated = endpoints.map((e) =>
    normalizeUrl(e.url) === norm ? { ...e, lastOkAt: now } : e,
  );
  const idx = updated.findIndex((e) => normalizeUrl(e.url) === norm);
  if (idx <= 0) return updated;
  const [promoted] = updated.splice(idx, 1);
  updated.unshift(promoted as Endpoint);
  return updated;
}

/** mDNS / GET /device reported a new address → add as `learned` (§16.1). */
export function addLearnedEndpoint(agent: PairedAgent, url: string, tier: Tier, now: number): PairedAgent {
  const norm = normalizeUrl(url);
  if (agent.endpoints.some((e) => normalizeUrl(e.url) === norm)) return agent;
  const learned: Endpoint = { url: norm, tier, origin: 'learned', lastOkAt: now };
  return { ...agent, endpoints: [...agent.endpoints, learned] };
}

export const LEARNED_DROP_CONSECUTIVE_FAILURES = 5;
export const LEARNED_DROP_WINDOW_MS = 2 * 24 * 60 * 60 * 1000; // ≥ 2 days

export interface FailureLedgerEntry {
  consecutive: number;
  firstFailedAt: number;
  lastFailedAt: number;
}
export type FailureLedger = Map<string, FailureLedgerEntry>;

export function recordEndpointFailure(ledger: FailureLedger, url: string, now: number): void {
  const norm = normalizeUrl(url);
  const prev = ledger.get(norm);
  ledger.set(norm, {
    consecutive: (prev?.consecutive ?? 0) + 1,
    firstFailedAt: prev?.firstFailedAt ?? now,
    lastFailedAt: now,
  });
}

export function recordEndpointOk(ledger: FailureLedger, url: string): void {
  ledger.delete(normalizeUrl(url));
}

/**
 * Drop learned endpoints that failed 5 consecutive races across ≥ 2 days
 * (§16.1). Only `origin === 'learned'` entries are ever dropped.
 */
export function pruneLearnedEndpoints(
  endpoints: readonly Endpoint[],
  ledger: FailureLedger,
): Endpoint[] {
  return endpoints.filter((e) => {
    if (e.origin !== 'learned') return true;
    const entry = ledger.get(normalizeUrl(e.url));
    if (!entry) return true;
    const span = entry.lastFailedAt - entry.firstFailedAt;
    return !(entry.consecutive >= LEARNED_DROP_CONSECUTIVE_FAILURES && span >= LEARNED_DROP_WINDOW_MS);
  });
}

// ---------------------------------------------------------------------------
// Backoff (§16.1): 2 s, 5 s, 10 s, 30 s, then every 60 s, each ± 20 % jitter;
// reset on any re-race trigger.
// ---------------------------------------------------------------------------

export const BACKOFF_BASE_MS: readonly number[] = [2_000, 5_000, 10_000, 30_000, 60_000];
export const BACKOFF_JITTER = 0.2;

export class Backoff {
  private idx = 0;

  constructor(
    private readonly clock: Clock,
    /** Deterministic rng for tests; defaults to Math.random. */
    private readonly jitterSource: () => number = Math.random,
  ) {}

  reset(): void {
    this.idx = 0;
  }

  /** Next delay in ms with ±20 % jitter (0.8×..1.2× base). */
  nextDelayMs(): number {
    const base = BACKOFF_BASE_MS[Math.min(this.idx, BACKOFF_BASE_MS.length - 1)] as number;
    const j = this.jitterSource() * 2 - 1; // -1..1
    const delay = Math.round(base * (1 + j * BACKOFF_JITTER));
    this.idx += 1;
    return delay;
  }

  /** Foreground-only backoff timer (§16.1). Fires `onFire` after the delay. */
  schedule(onFire: () => void): TimeoutHandle {
    return this.clock.setTimeout(onFire, this.nextDelayMs());
  }
}
