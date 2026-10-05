/**
 * §11.2 mesh-core native interface — NORMATIVE TypeScript contract.
 * Copied verbatim from docs/LocalMesh_AI_Architecture_and_Requirements.md
 * §11.2 (the Kotlin module itself is built by another agent; this file is the
 * contract both sides compile against).
 *
 * Rules (§11.2): the pin is mandatory on every call (no overload without it);
 * `tlsSpkiSha256B64Url` is returned so the JS layer can assert equality; the
 * module rejects HTTP (non-https) URLs outright (SEC-N1) except when built
 * with the debug-only emulator flag (§17.9).
 */

export interface MeshCoreStreamEventPayload {
  event?: string;
  data: string;
}
export interface MeshCoreStreamErrorPayload {
  code: string;
  message: string;
}
export interface MeshCoreStreamClosedPayload {
  reason: string;
}

export interface StreamHandle {
  on(name: 'event', cb: (p: MeshCoreStreamEventPayload) => void): void;
  on(name: 'error', cb: (p: MeshCoreStreamErrorPayload) => void): void;
  on(name: 'closed', cb: (p: MeshCoreStreamClosedPayload) => void): void;
  /** Closes the socket (Agent cancels upstream on disconnect). */
  cancel(): void;
}

export interface MeshCoreRequest {
  url: string;
  method: 'GET' | 'POST' | 'DELETE';
  headers?: Record<string, string>;
  bodyJson?: unknown;
  pinSpkiSha256B64Url: string;
  timeoutMs: number;
}

export interface MeshCoreResponse {
  status: number;
  headers: Record<string, string>;
  bodyJson?: unknown;
  /** Observed TLS SPKI SHA-256 (b64url) — the JS layer asserts equality. */
  tlsSpkiSha256B64Url: string;
}

export interface MeshCoreStreamRequest {
  url: string;
  method: 'POST';
  headers?: Record<string, string>;
  bodyJson: unknown;
  pinSpkiSha256B64Url: string;
  idleTimeoutMs: number;
}

export type NetworkStateNative = {
  transport: 'wifi' | 'cellular' | 'ethernet' | 'none';
  vpnActive: boolean;
  metered: boolean;
};

export interface MeshCore {
  // --- keys (private key never crosses the bridge) ---
  createDeviceKey(alias: string): Promise<{ publicKeySpkiB64Url: string; hardwareBacked: boolean }>;
  /** ECDSA P-256 SHA-256, DER sig, base64url. */
  signWithDeviceKey(alias: string, dataB64Url: string): Promise<string>;
  deleteDeviceKey(alias: string): Promise<void>;

  // --- pinned HTTP (JSON) ---
  request(req: MeshCoreRequest): Promise<MeshCoreResponse>;

  // --- pinned SSE ---
  openStream(req: MeshCoreStreamRequest): Promise<StreamHandle>;

  // --- discovery & network ---
  /** events: 'agentFound' | 'agentLost' */
  startDiscovery(serviceType: '_localmesh._tcp'): Promise<void>;
  stopDiscovery(): Promise<void>;
  getNetworkState(): Promise<NetworkStateNative>;
  /** event: 'networkChanged' */
  getLocalNetworkPermission(): Promise<'granted' | 'denied' | 'not_required' | 'unknown'>;
  requestLocalNetworkPermission(): Promise<'granted' | 'denied'>;
  /** used for the Tailscale hint only (CI-13) */
  isPackageInstalled(pkg: string): Promise<boolean>;
}

/** Event names emitted by the native module (added to the instance). */
export type MeshCoreEventName = 'agentFound' | 'agentLost' | 'networkChanged';
