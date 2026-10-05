/**
 * Pairing QR payload parsing (§15.4 QR: `localmesh://pair?v=1&aid&fp&pid&sec&ep…`)
 * and the §17.8 deep-link rule: a deep link may open the pairing flow, but the
 * user MUST explicitly confirm before anything is sent. Pure functions only.
 */

import type { PairPayload, Tier } from '../../domain/entities';
import { classifyEndpoint } from '../../domain/connection/race-planner';

export const QR_MAX_LENGTH = 2048;
export const MAX_ENDPOINTS = 4;

const ID_RE = /^[A-Za-z0-9_-]+$/;

export type QrParseError =
  | { code: 'NOT_LOCALMESH'; detail: string }
  | { code: 'BAD_VERSION'; detail: string }
  | { code: 'MISSING_FIELD'; detail: string }
  | { code: 'OVERSIZED_FIELD'; detail: string }
  | { code: 'BAD_FIELD'; detail: string }
  | { code: 'TOO_LONG'; detail: string };

export interface ParsedPairPayload extends PairPayload {
  /** §17.8: always true — the flow requires explicit user confirmation. */
  requiresConfirmation: true;
}

function checkLen(field: string, value: string, max: number): QrParseError | null {
  if (value.length === 0) return { code: 'MISSING_FIELD', detail: field };
  if (value.length > max) return { code: 'OVERSIZED_FIELD', detail: `${field}>${max}` };
  return null;
}

/**
 * Parse a scanned/deep-linked pairing URI. Rejects non-localmesh schemes,
 * wrong versions, missing/oversized fields. `sec` is kept in memory only and
 * never persisted (§15.2).
 */
export function parsePairUri(uri: string): { ok: true; payload: ParsedPairPayload } | { ok: false; error: QrParseError } {
  if (uri.length > QR_MAX_LENGTH) return { ok: false, error: { code: 'TOO_LONG', detail: `${uri.length}>${QR_MAX_LENGTH}` } };

  let u: URL;
  try {
    u = new URL(uri);
  } catch {
    return { ok: false, error: { code: 'NOT_LOCALMESH', detail: 'unparseable' } };
  }
  if (u.protocol !== 'localmesh:' || u.host !== 'pair') {
    return { ok: false, error: { code: 'NOT_LOCALMESH', detail: `${u.protocol}//${u.host}` } };
  }

  const v = u.searchParams.get('v');
  if (v !== '1') return { ok: false, error: { code: 'BAD_VERSION', detail: String(v) } };

  const aid = u.searchParams.get('aid') ?? '';
  const fp = u.searchParams.get('fp') ?? '';
  const n = u.searchParams.get('n') ?? '';
  const pid = u.searchParams.get('pid') ?? '';
  const sec = u.searchParams.get('sec') ?? '';

  const aidErr = checkLen('aid', aid, 64);
  if (aidErr) return { ok: false, error: aidErr };
  if (!ID_RE.test(aid)) return { ok: false, error: { code: 'BAD_FIELD', detail: 'aid' } };

  const fpErr = checkLen('fp', fp, 64);
  if (fpErr) return { ok: false, error: fpErr };
  if (!ID_RE.test(fp)) return { ok: false, error: { code: 'BAD_FIELD', detail: 'fp' } };

  const nErr = n ? checkLen('n', n, 128) : null;
  if (nErr) return { ok: false, error: nErr };
  const pidErr = pid ? checkLen('pid', pid, 64) : null;
  if (pidErr) return { ok: false, error: pidErr };
  const secErr = sec ? checkLen('sec', sec, 128) : null;
  if (secErr) return { ok: false, error: secErr };

  // ep: repeated `ep=` params; each a URL, at least one required.
  const eps = u.searchParams.getAll('ep').filter((s) => s.length > 0);
  if (eps.length === 0) return { ok: false, error: { code: 'MISSING_FIELD', detail: 'ep' } };
  if (eps.length > MAX_ENDPOINTS) return { ok: false, error: { code: 'OVERSIZED_FIELD', detail: `ep-count>${MAX_ENDPOINTS}` } };
  const endpoints: { url: string; tier: Tier }[] = [];
  for (const ep of eps) {
    if (ep.length > 256) return { ok: false, error: { code: 'OVERSIZED_FIELD', detail: 'ep>256' } };
    let parsed: URL;
    try {
      parsed = new URL(ep);
    } catch {
      return { ok: false, error: { code: 'BAD_FIELD', detail: 'ep' } };
    }
    if (parsed.protocol !== 'https:') return { ok: false, error: { code: 'BAD_FIELD', detail: 'ep-scheme' } };
    endpoints.push({ url: ep, tier: classifyEndpoint(ep) });
  }

  return {
    ok: true,
    payload: {
      v: 1,
      agentId: aid,
      fingerprint: fp,
      ...(n ? { name: n } : {}),
      ...(pid ? { sessionId: pid } : {}),
      ...(sec ? { secret: sec } : {}),
      endpoints,
      requiresConfirmation: true,
    },
  };
}

/** Format the SAS comparison code (UI spec 6.2: "482 917"). */
export function formatSas(code: string): string {
  const digits = code.replace(/\D/g, '').slice(0, 6);
  if (digits.length <= 3) return digits;
  return `${digits.slice(0, 3)} ${digits.slice(3)}`;
}
