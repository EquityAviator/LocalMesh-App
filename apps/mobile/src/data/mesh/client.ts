/**
 * Typed MeshApiClient over the §11.2 MeshCore wrapper (src/infra/meshCore.ts).
 *
 * §11.3 rule: screens never call meshCore directly — only this client.
 * Defense in depth: the pin is passed on EVERY call and the returned
 * `tlsSpkiSha256B64Url` is asserted equal to the stored pin; a mismatch throws
 * PinMismatchError (SM-CONN invariant 2; the native layer enforces the same
 * check inside the TLS stack).
 */

import type { DeviceInfo, PermState } from '../../domain/entities';
import type {
  MeshCore,
  MeshCoreResponse,
  MeshCoreStreamRequest,
  MeshCoreRequest,
  NetworkStateNative,
  StreamHandle,
} from '../../../modules/mesh-core/src/MeshCore.types';
import { MESH_DEMO_CONFIG, getMeshCoreForPlatform } from '../../infra/meshCore';

export type { StreamHandle } from '../../../modules/mesh-core/src/MeshCore.types';

/** Logical demo Agent origin + demo pin (re-exported for feature flows, §17.9). */
export const DEMO_AGENT_BASE_URL = MESH_DEMO_CONFIG.logicalBase;
export const DEMO_AGENT_PIN = MESH_DEMO_CONFIG.pin;

export const DEFAULT_TIMEOUT_MS = 10_000;
export const STREAM_IDLE_TIMEOUT_MS = 45_000;
const API_BASE = '/mesh/v1';

export class PinMismatchError extends Error {
  constructor() {
    super('TLS SPKI does not match the stored pin');
    this.name = 'PinMismatchError';
  }
}

export type MeshErrorCode =
  | 'INVALID_REQUEST'
  | 'INVALID_TOKEN'
  | 'FORBIDDEN'
  | 'FORBIDDEN_SCOPE'
  | 'NOT_FOUND'
  | 'MODEL_NOT_FOUND'
  | 'UNSUPPORTED_CAPABILITY'
  | 'DEVICE_REVOKED'
  | 'VERSION_INCOMPATIBLE'
  | 'UNKNOWN';

export class MeshApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: MeshErrorCode,
    message: string,
  ) {
    super(message);
    this.name = 'MeshApiError';
  }
}

function codeFromStatus(status: number): MeshErrorCode {
  if (status === 401) return 'INVALID_TOKEN';
  if (status === 403) return 'FORBIDDEN';
  if (status === 404) return 'NOT_FOUND';
  if (status === 422) return 'INVALID_REQUEST';
  if (status === 501) return 'UNSUPPORTED_CAPABILITY';
  return 'UNKNOWN';
}

/** GET /mesh/v1/info (API-INFO-01). No OS / model / IP pre-auth (§13.2). */
export interface AgentInfo {
  agent_id: string;
  display_name: string;
  api: { requested?: string; supported?: string[]; negotiated?: string };
  pairing_open: boolean;
}

/** POST /mesh/v1/auth/token response (Device Token, §13.2). */
export interface DeviceTokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  device_id?: string;
  scopes?: string[];
}

export interface HealthReport {
  status?: string;
  uptime_s?: number;
  backends?: Array<{ id?: string; status?: string } & Record<string, unknown>>;
  queue?: Record<string, unknown>;
  [k: string]: unknown;
}

export interface ModelListResponse {
  models?: Array<{
    id?: string;
    mesh_model_id?: string;
    backend_model_id?: string;
    display_name?: string | null;
    /** §13.5 closed state vocabulary (loaded/unloaded/…); the App projects
     * this onto the domain `loaded` boolean. */
    state?: string;
    loaded?: boolean;
    /** §13.5: `{values: string[], source: string}` (additive-tolerant). */
    capabilities?: { values?: string[] } | string[];
    [k: string]: unknown;
  }>;
  [k: string]: unknown;
}

/** OpenAI-style chat body (§13.6); `model` carries the mesh_model_id. */
export interface ChatRequestBody {
  model: string;
  messages: Array<{ role: 'system' | 'user' | 'assistant'; content: unknown }>;
  stream?: boolean;
  [k: string]: unknown;
}

export interface MeshApiClientConfig {
  core: MeshCore;
  baseUrl: string;
  /** b64url(no padding) SHA-256 of the Agent TLS SPKI — mandatory (§14.2). */
  pin: string;
  tokenProvider?: () => string | null;
  timeoutMs?: number;
}

export class MeshApiClient {
  constructor(private readonly cfg: MeshApiClientConfig) {
    if (!cfg.baseUrl.startsWith('https://')) {
      // SEC-N1: the native module rejects http outright; fail fast in JS too.
      throw new Error('MeshApiClient requires an https base URL (SEC-N1)');
    }
    if (!cfg.pin) throw new Error('MeshApiClient requires a pin');
  }

  private url(path: string): string {
    return this.cfg.baseUrl.replace(/\/+$/, '') + API_BASE + path;
  }

  private async raw(req: Omit<MeshCoreRequest, 'pinSpkiSha256B64Url'>): Promise<MeshCoreResponse> {
    const res = await this.cfg.core.request({
      ...req,
      pinSpkiSha256B64Url: this.cfg.pin, // pin mandatory on EVERY call (§11.2)
    });
    if (res.tlsSpkiSha256B64Url !== this.cfg.pin) throw new PinMismatchError();
    return res;
  }

  private authHeaders(auth: boolean): Record<string, string> {
    if (!auth) return {};
    const token = this.cfg.tokenProvider?.() ?? null;
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  private mapError(status: number, body: unknown): MeshApiError {
    let code = codeFromStatus(status);
    let message = `HTTP ${status}`;
    if (body && typeof body === 'object') {
      const err = (body as Record<string, unknown>)['error'];
      if (err && typeof err === 'object') {
        const e = err as Record<string, unknown>;
        if (typeof e['code'] === 'string') code = e['code'] as MeshErrorCode;
        if (typeof e['message'] === 'string') message = e['message'];
      }
    }
    return new MeshApiError(status, code, message);
  }

  async request<T = unknown>(
    method: MeshCoreRequest['method'],
    path: string,
    opts: { body?: unknown; auth?: boolean; timeoutMs?: number } = {},
  ): Promise<T> {
    const res = await this.raw({
      url: this.url(path),
      method,
      headers: { Accept: 'application/json', ...this.authHeaders(opts.auth ?? false) },
      bodyJson: opts.body,
      timeoutMs: opts.timeoutMs ?? this.cfg.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    });
    if (res.status >= 400) throw this.mapError(res.status, res.bodyJson);
    return res.bodyJson as T;
  }

  // --- §13.2 endpoints used by the App ---

  info(): Promise<AgentInfo> {
    return this.request<AgentInfo>('GET', '/info');
  }

  health(): Promise<HealthReport> {
    return this.request<HealthReport>('GET', '/health', { auth: true });
  }

  device(): Promise<DeviceInfo & Record<string, unknown>> {
    return this.request('GET', '/device', { auth: true });
  }

  listModels(): Promise<ModelListResponse> {
    return this.request<ModelListResponse>('GET', '/models', { auth: true });
  }

  /** §13.2 API-MODEL-02/03: 202 with `{"state":"loading"|"unloaded"}`. */
  loadModel(meshModelId: string): Promise<{ state: string }> {
    return this.request('POST', '/models/load', { body: { mesh_model_id: meshModelId }, auth: true });
  }

  unloadModel(meshModelId: string): Promise<{ state: string }> {
    return this.request('POST', '/models/unload', { body: { mesh_model_id: meshModelId }, auth: true });
  }

  authChallenge(body: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.request('POST', '/auth/challenge', { body });
  }

  authToken(body: Record<string, unknown>): Promise<DeviceTokenResponse> {
    return this.request<DeviceTokenResponse>('POST', '/auth/token', { body });
  }

  cancelRequest(requestId: string): Promise<unknown> {
    return this.request('DELETE', `/requests/${encodeURIComponent(requestId)}`, { auth: true });
  }

  createTask(body: Record<string, unknown>): Promise<{ task_id?: string; status?: string }> {
    return this.request('POST', '/tasks', { body, auth: true });
  }

  getTask(taskId: string): Promise<Record<string, unknown>> {
    return this.request('GET', `/tasks/${encodeURIComponent(taskId)}`, { auth: true });
  }

  deleteTask(taskId: string): Promise<unknown> {
    return this.request('DELETE', `/tasks/${encodeURIComponent(taskId)}`, { auth: true });
  }

  // --- pinned SSE (chat, §13.7) ---

  /**
   * Open the pinned chat stream. Frames arrive through the StreamHandle; the
   * JS-side idle window (45 s) mirrors SseFeed semantics.
   */
  async openChatStream(body: ChatRequestBody): Promise<StreamHandle> {
    const req: MeshCoreStreamRequest = {
      url: this.url('/chat/completions'),
      method: 'POST',
      headers: {
        Accept: 'text/event-stream',
        'Content-Type': 'application/json',
        ...this.authHeaders(true),
      },
      bodyJson: { ...body, stream: true },
      pinSpkiSha256B64Url: this.cfg.pin,
      idleTimeoutMs: STREAM_IDLE_TIMEOUT_MS,
    };
    return this.cfg.core.openStream(req);
  }
}

let demoClient: MeshApiClient | null = null;

/**
 * §11.3 gateway for screens: the ONLY way UI code reaches the transport.
 * The web demo binds the client to the sandbox demo transport (logical base
 * + demo pin, §17.9); the native pairing flow will construct per-Agent
 * clients from the §14.2 row (base URL + stored pin) in a later WP.
 */
export function getMeshApiClient(): MeshApiClient {
  if (!demoClient) {
    demoClient = new MeshApiClient({
      core: getMeshCoreForPlatform(),
      baseUrl: MESH_DEMO_CONFIG.logicalBase,
      pin: MESH_DEMO_CONFIG.pin,
    });
  }
  return demoClient;
}

/**
 * §11.2 transport probes for the §18.4 Doctor ladder (no API semantics —
 * network/permission/package checks go straight to the platform transport).
 */
export function meshCoreProbes(): {
  getNetworkState(): Promise<NetworkStateNative>;
  getLocalNetworkPermission(): Promise<PermState>;
  isPackageInstalled(pkg: string): Promise<boolean>;
} {
  const core = getMeshCoreForPlatform();
  return {
    getNetworkState: () => core.getNetworkState(),
    getLocalNetworkPermission: () => core.getLocalNetworkPermission(),
    isPackageInstalled: (pkg: string) => core.isPackageInstalled(pkg),
  };
}
