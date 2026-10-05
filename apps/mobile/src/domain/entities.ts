/**
 * LocalMesh AI — App domain entities (pure TypeScript).
 *
 * Layering rule (§11.3): this file is imported by the connection manager, the
 * data layer and the UI. It must NEVER import react-native, expo, zustand or
 * any I/O-capable module. Enforced by test/purity.test.ts.
 *
 * Normative shapes:
 *  - Endpoint record: §16.1 (`{ url, tier, origin, lastOkAt? }`).
 *  - Agent record columns: §14.2 `agents` table.
 *  - NetState: §11.2 `getNetworkState()`; PermState: `getLocalNetworkPermission()`.
 */

export type Tier = 'T0' | 'T1' | 'T2' | 'T3';

export type EndpointOrigin = 'mdns' | 'paired' | 'manual' | 'learned';

/** §16.1 endpoint record (verbatim shape). */
export interface Endpoint {
  url: string;
  tier: Tier;
  origin: EndpointOrigin;
  lastOkAt?: number;
}

/** §14.2 `agents` row lifted into the domain. */
export interface PairedAgent {
  agentId: string;
  displayName: string;
  /** b64url(no padding) SHA-256 of the Agent TLS SPKI (§14.2). */
  spkiPin: string;
  /** Our device id at this Agent. */
  deviceId: string;
  /** Keystore alias; the key material itself is never stored (§14.2). */
  keyAlias: string;
  /** Ordered Endpoint[] with tier + last_ok_at (§14.2 endpoints_json). */
  endpoints: Endpoint[];
  /** `<hostname>.local` if known (feeds lanName candidates, §16.1 rule 3). */
  hostname?: string;
  /** Tailnet MagicDNS name if known (feeds tailnet candidates, §16.1 rule 4). */
  magicDnsName?: string;
  lastTier?: Tier;
  lastConnectedAt?: number;
  pairedAt: number;
}

/** §11.2 network state. */
export interface NetState {
  transport: 'wifi' | 'cellular' | 'ethernet' | 'none';
  vpnActive: boolean;
  metered: boolean;
}

/** §11.2 local-network permission state (Android 17 ACCESS_LOCAL_NETWORK, §6.4). */
export type PermState = 'granted' | 'denied' | 'not_required' | 'unknown';

/** A discovery advertisement for an Agent seen on the LAN (mDNS, §16.2). */
export interface DiscoveryEntry {
  agentId: string;
  name: string;
  /** b64url SPKI SHA-256 hint (first 16 chars; full pin verified via TLS). */
  fingerprintHint?: string;
  /** Advertised URLs, e.g. `https://192.168.1.100:8443`. */
  urls: string[];
  seenAt: number;
}

/** §14.2 `conversations` row. */
export interface Conversation {
  id: string;
  title: string;
  /** Last used Agent; nullable — history is portable (§14.2). */
  agentId?: string;
  /** Last mesh_model_id (hint). */
  modelRef?: string;
  createdAt: number;
  updatedAt: number;
  archived: boolean;
}

export type MessageRole = 'system' | 'user' | 'assistant';

/**
 * App message status (§15.3). The persisted CHECK constraint covers
 * complete/streaming/interrupted/error; submitting/cancelled are in-memory
 * states of SM-STREAM that are persisted as their terminal form.
 */
export type MessageStatus = 'complete' | 'streaming' | 'interrupted' | 'error';

/** §14.2 `messages` row. */
export interface Message {
  id: string;
  conversationId: string;
  role: MessageRole;
  content: string;
  status: MessageStatus;
  modelRef?: string;
  /** Token counts, ttft, tok/s — Metadata only (§13.10). */
  stats?: Record<string, number | string>;
  createdAt: number;
}

/** Model row shown in Machine detail / Model sheet (§6.4, §6.6 UI spec). */
export interface ModelEntry {
  meshModelId: string;
  displayName: string;
  quantisation?: string;
  contextLength?: number;
  loaded: boolean;
  /** capability tags from the backend, e.g. 'chat' | 'vision' | 'tools'. */
  capabilities: string[];
}

/** Subset of GET /mesh/v1/device used by the Machines screens (§13.2). */
export interface DeviceInfo {
  agentId: string;
  displayName: string;
  agentVersion?: string;
  gpuName?: string;
  vramTotalMb?: number;
  ramTotalMb?: number;
}

/** One candidate failure fed to the §18.3 aggregator. */
export type ProbeFailureKind =
  | 'pin_mismatch'
  | 'revoked'
  | 'timeout'
  | 'refused'
  | 'dns'
  | 'info_mismatch'
  | 'permission'
  | 'unknown';

export interface ProbeFailure {
  url: string;
  tier: Tier;
  kind: ProbeFailureKind;
  /** true when discovery saw this Agent on the current network (§18.3 rank 8). */
  sawInDiscovery?: boolean;
}

/** Deep-link / scanned pairing payload (§17.8). */
export interface PairPayload {
  v: 1;
  agentId: string;
  fingerprint: string;
  name?: string;
  sessionId?: string;
  /** pairing secret — held in memory only, never persisted (§15.2). */
  secret?: string;
  endpoints: { url: string; tier: Tier }[];
}
