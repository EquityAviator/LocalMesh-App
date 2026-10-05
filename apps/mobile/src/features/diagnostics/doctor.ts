/**
 * §18.4 App Doctor — ordered checks (Diagnostics screen):
 *   network type/VPN → local-network permission → Tailscale installed hint →
 *   discovery sees Agent? → each candidate: DNS/TCP/TLS-pin//info with timing →
 *   auth result → /health → backend status → shareable text report with
 *   NO Content and NO secrets (pin prefix only, first 12 chars).
 */

import type { Clock } from '../../domain/connection/clock';
import { REASON_CI } from '../../domain/connection/reasons';
import type { Endpoint, NetState, PermState } from '../../domain/entities';

export interface CandidateProbeReport {
  dns: boolean;
  tcp: boolean;
  tlsPin: boolean;
  info: boolean;
  agentIdOk: boolean;
}

export interface DoctorCheck {
  id: 'network' | 'permission' | 'tailscale' | 'discovery' | 'candidate' | 'auth' | 'health' | 'backends';
  ci?: string;
  ok: boolean;
  detail?: string;
  ms?: number;
  candidateUrl?: string;
  timings?: { dnsMs?: number; tcpMs?: number; tlsMs?: number; infoMs?: number };
}

export interface DoctorDeps {
  clock: Clock;
  getNetwork(): Promise<NetState>;
  getPermission(): Promise<PermState>;
  isTailscaleInstalled(): Promise<boolean>;
  discoverySawAgent(): boolean;
  candidates: readonly Endpoint[];
  probeCandidate(e: Endpoint): Promise<CandidateProbeReport>;
  authCheck(): Promise<{ ok: boolean; revoked?: boolean }>;
  healthCheck(): Promise<{ ok: boolean }>;
  backendStatus(): Promise<{ ok: boolean; summary?: string }>;
}

async function timed<T>(clock: Clock, fn: () => Promise<T>): Promise<{ value: T; ms: number }> {
  const t0 = clock.now();
  const value = await fn();
  return { value, ms: clock.now() - t0 };
}

/** §18.4 ladder, in order. Every step is timed with the injected clock. */
export async function runDoctor(deps: DoctorDeps): Promise<DoctorCheck[]> {
  const checks: DoctorCheck[] = [];

  // 1. network type / VPN
  const net = await timed(deps.clock, deps.getNetwork);
  checks.push({
    id: 'network',
    ok: net.value.transport !== 'none',
    ci: net.value.transport === 'none' ? REASON_CI.NO_NETWORK : undefined,
    detail: `transport=${net.value.transport} vpn=${net.value.vpnActive ? 'on' : 'off'} metered=${net.value.metered ? 'yes' : 'no'}`,
    ms: net.ms,
  });

  // 2. local-network permission (CI-09, §6.4)
  const perm = await timed(deps.clock, deps.getPermission);
  checks.push({
    id: 'permission',
    ok: perm.value === 'granted' || perm.value === 'not_required',
    ci: perm.value === 'denied' ? REASON_CI.PERMISSION_DENIED : undefined,
    detail: `localNetworkPermission=${perm.value}`,
    ms: perm.ms,
  });

  // 3. Tailscale installed hint (CI-13)
  const ts = await timed(deps.clock, () => deps.isTailscaleInstalled());
  checks.push({
    id: 'tailscale',
    ok: true, // informational row — never a failure
    ci: ts.value ? undefined : REASON_CI.TAILNET_NOT_ACTIVE,
    detail: ts.value ? 'tunnel app installed' : 'tunnel app not installed (hint only)',
    ms: ts.ms,
  });

  // 4. discovery sees the Agent?
  checks.push({
    id: 'discovery',
    ok: deps.discoverySawAgent(),
    ci: deps.discoverySawAgent() ? undefined : REASON_CI.NOT_FOUND_LAN,
    detail: deps.discoverySawAgent() ? 'agent seen on this network' : 'no discovery results on this network',
  });

  // 5. per-candidate DNS/TCP/TLS-pin//info with timing
  for (const e of deps.candidates) {
    const r = await timed(deps.clock, () => deps.probeCandidate(e));
    const v = r.value;
    checks.push({
      id: 'candidate',
      ok: v.info && v.tlsPin && v.agentIdOk,
      // Ladder order matters: DNS → TCP → TLS pin → /info. TCP is checked
      // BEFORE the pin because a refused connection can never present a
      // certificate — labelling that CI-12 would hide the real cause.
      ci: !v.tcp ? REASON_CI.TCP_REFUSED : !v.tlsPin ? REASON_CI.PIN_MISMATCH : !v.info ? REASON_CI.TIMEOUT_LAN : undefined,
      candidateUrl: e.url,
      detail: `tier=${e.tier} dns=${v.dns} tcp=${v.tcp} tlsPin=${v.tlsPin} info=${v.info} agentId=${v.agentIdOk}`,
      ms: r.ms,
    });
  }

  // 6. auth result
  const auth = await timed(deps.clock, deps.authCheck);
  checks.push({
    id: 'auth',
    ok: auth.value.ok,
    ci: auth.value.revoked ? REASON_CI.REVOKED : auth.value.ok ? undefined : REASON_CI.UNKNOWN,
    detail: auth.value.ok ? 'device token accepted' : auth.value.revoked ? 'device revoked at agent' : 'token rejected',
    ms: auth.ms,
  });

  // 7. /health
  const health = await timed(deps.clock, deps.healthCheck);
  checks.push({
    id: 'health',
    ok: health.value.ok,
    ms: health.ms,
  });

  // 8. backend status
  const be = await timed(deps.clock, deps.backendStatus);
  checks.push({
    id: 'backends',
    ok: be.value.ok,
    detail: be.value.summary,
    ms: be.ms,
  });

  return checks;
}

// ---------------------------------------------------------------------------
// Shareable report — metadata only, sanitized (§18.4 "no Content, no secrets")
// ---------------------------------------------------------------------------

/** Field names that must NEVER appear in a shareable report. */
export const DENY_KEYS: readonly string[] = [
  'token',
  'access_token',
  'secret',
  'sec',
  'authorization',
  'bearer',
  'password',
  'content',
  'prompt',
  'messages',
  'body',
];

/** Pin prefix: first 12 chars only (metadata; full pin never leaves the app). */
export function truncatePin(pin: string): string {
  return pin.slice(0, 12);
}

/** Strip deny-listed `key=value` / `key: value` fragments from free text. */
export function sanitizeText(text: string): string {
  // Pass 1 — credential-bearer keys: redact the REST OF THE LINE (scheme +
  // value, e.g. "authorization: Bearer xyz"), preserving the separator.
  const restOfLine = new RegExp(
    `\\b(${['authorization', 'bearer'].join('|')})\\b(\\s*[=:]{1,2}\\s*).*$`,
    'gim',
  );
  let out = text.replace(restOfLine, '$1$2[redacted]');
  // Pass 2 — value-only keys: redact up to the first delimiter so following
  // context ("status ok") survives. The lookahead skips values that pass 1
  // already redacted (no double-redaction, no stray bracket).
  const valueOnly = new RegExp(
    `\\b(${DENY_KEYS.join('|')})\\b(\\s*[=:]{1,2}\\s*)(?!\\[redacted\\])[^\\s,;)}\\]]+`,
    'gi',
  );
  out = out.replace(valueOnly, '$1$2[redacted]');
  return out;
}

export interface ReportMeta {
  agentName: string;
  /** Full pin — ALWAYS truncated to 12 chars in the report (§18.4). */
  pin?: string;
  at: number;
  generatedBy?: string;
}

export function buildDoctorReport(checks: readonly DoctorCheck[], meta: ReportMeta): string {
  const lines: string[] = [];
  lines.push('LocalMesh diagnostics');
  lines.push(`machine: ${meta.agentName}`);
  lines.push(`pin: ${meta.pin ? truncatePin(meta.pin) : '(none)'}`);
  lines.push(`at: ${new Date(meta.at).toISOString()}`);
  if (meta.generatedBy) lines.push(`by: ${meta.generatedBy}`);
  lines.push('');
  for (const c of checks) {
    const status = c.ok ? 'ok' : 'fail';
    const bits: string[] = [];
    if (c.detail) bits.push(sanitizeText(c.detail));
    if (c.candidateUrl) bits.push(`target=${c.candidateUrl}`);
    if (c.ms !== undefined) bits.push(`${c.ms} ms`);
    if (c.timings?.dnsMs !== undefined) bits.push(`dns=${c.timings.dnsMs}ms`);
    if (c.timings?.tcpMs !== undefined) bits.push(`tcp=${c.timings.tcpMs}ms`);
    if (c.timings?.tlsMs !== undefined) bits.push(`tls=${c.timings.tlsMs}ms`);
    if (c.timings?.infoMs !== undefined) bits.push(`info=${c.timings.infoMs}ms`);
    if (c.ci) bits.push(c.ci);
    lines.push(`[${status}] ${c.id}${bits.length ? ' — ' + bits.join(' · ') : ''}`);
  }
  lines.push('');
  lines.push('Report contains no chat content and no secrets.');
  return lines.join('\n');
}
