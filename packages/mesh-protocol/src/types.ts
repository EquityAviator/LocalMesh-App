/**
 * GENERATED — do not edit; regenerate via bun run gen:types (mesh-protocol).
 *
 * Source: docs/openapi/mesh-v1.json (LM-ARCH-001 §13; OpenAPI 3.1.0; info.version "1")
 *         ADR-015 / §21.3: this package is generated from the drift-checked export — nothing hand-written.
 * Spec file sha256: 15d5e788f97038195a2d8f910e10bf2c23827a860174739e6b15c48487b9e2f9
 * Generated at (source spec mtime, UTC): 2026-10-04T20:28:19.940Z
 *         Deterministic by design: derived from the spec file, not the wall clock, so two
 *         runs on the same inputs are byte-identical (asserted by test/generated.test.ts).
 * 
 * Contains: components.schemas → interfaces; per-operation Request/Response types;
 * Paths map; MeshApiMethod/MeshApiPath/MeshApiEndpoint literals; §13.4 ErrorEnvelope;
 * §13-normative narrow response shapes for endpoints the export leaves untyped
 * (each carries its own source comment — nothing is invented).
 */

// ---------------------------------------------------------------------------
// Schema interfaces (docs/openapi/mesh-v1.json → components.schemas, sorted by name)
// ---------------------------------------------------------------------------

/**
 * `api` block of the API-INFO-01 response (§13.2).
 * OpenAPI schema: components.schemas.AgentApiInfo.
 */
export interface AgentApiInfo {
  /**
   * Mesh API versions served, e.g. ['v1'] (§13.10).
   */
  versions: string[];
  /**
   * Semantic Agent version (§13.2, NFR-COMP-02).
   */
  agent_version: string;
}

/**
 * Body of `GET /mesh/v1/info` (API-INFO-01, §13.2).
 * 
 * No OS, no model info, no IPs (limits pre-auth disclosure).
 * OpenAPI schema: components.schemas.AgentInfo.
 */
export interface AgentInfo {
  /**
   * Stable Agent identifier (§13.2).
   */
  agent_id: string;
  /**
   * Operator-set Agent display name (§13.2).
   */
  display_name: string;
  /**
   * API version block (§13.2).
   */
  api: AgentApiInfo;
  /**
   * Whether a PairingSession is currently OPEN (§13.2).
   */
  pairing_open: boolean;
}

/**
 * OpenAPI schema: components.schemas.CpuInfo.
 */
export interface CpuInfo {
  /**
   * CPU model string if reported (§13.2).
   */
  model: string | null;
  /**
   * Logical core count if reported (§13.2).
   */
  logical_cores: number | null;
}

/**
 * OpenAPI schema: components.schemas.DeviceResponse.
 */
export interface DeviceResponse {
  /**
   * Stable Agent identifier (§13.2).
   */
  agent_id: string;
  /**
   * Operator-set Agent display name (§13.2).
   */
  display_name: string;
  /**
   * Semantic Agent version (NFR-COMP-02).
   */
  agent_version: string;
  /**
   * OS block, all fields nullable (FR-STAT-01).
   */
  os: OsInfo;
  /**
   * CPU block, all fields nullable (FR-STAT-01).
   */
  cpu: CpuInfo;
  /**
   * RAM block, all fields nullable (FR-STAT-01).
   */
  ram: RamInfo;
  /**
   * Detected GPUs; empty when none reported (§13.2).
   */
  gpus: GpuEntry[];
  /**
   * LAN + Tailnet addressing (§13.2).
   */
  network: NetworkInfo;
}

/**
 * OpenAPI schema: components.schemas.GpuEntry.
 */
export interface GpuEntry {
  /**
   * GPU name if reported (§13.2).
   */
  name: string | null;
  /**
   * Total VRAM in bytes (§13.2).
   */
  vram_total_bytes: number | null;
  /**
   * Used VRAM in bytes (§13.2).
   */
  vram_used_bytes: number | null;
  /**
   * GPU utilization percent (§13.2).
   */
  utilization_pct: number | null;
  /**
   * GPU temperature in °C (§13.2).
   */
  temperature_c: number | null;
}

/**
 * OpenAPI schema: components.schemas.HTTPValidationError.
 */
export interface HTTPValidationError {
  detail?: ValidationError[];
}

/**
 * OpenAPI schema: components.schemas.NetworkInfo.
 */
export interface NetworkInfo {
  /**
   * Private LAN IPv4s (§16.2 selection).
   */
  lan_addresses: string[];
  /**
   * Tailnet block, null when Tailscale is absent (§13.2).
   */
  tailnet: TailnetBlock | null;
}

/**
 * OpenAPI schema: components.schemas.OsInfo.
 */
export interface OsInfo {
  /**
   * OS family, e.g. 'windows'/'linux'/'darwin' (§13.2).
   */
  family: string | null;
  /**
   * OS version/release if reported (§13.2).
   */
  version: string | null;
}

/**
 * OpenAPI schema: components.schemas.RamInfo.
 */
export interface RamInfo {
  /**
   * Total physical RAM in bytes (§13.2).
   */
  total_bytes: number | null;
  /**
   * Currently available RAM in bytes (§13.2).
   */
  available_bytes: number | null;
}

/**
 * OpenAPI schema: components.schemas.TailnetBlock.
 */
export interface TailnetBlock {
  /**
   * Tailscale probe state (§6.3, WP-14).
   */
  state: string;
  /**
   * MagicDNS name without trailing dot (§6.3).
   */
  dns_name: string | null;
  /**
   * 100.64.0.0/10 addresses (§6.3).
   */
  ips: string[];
}

/**
 * OpenAPI schema: components.schemas.ValidationError.
 */
export interface ValidationError {
  loc: string | number[];
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Error envelope — LM-ARCH-001 §13.4 (all non-2xx JSON responses, and the
// `mesh.error` SSE payload).
//
// NOT declared in docs/openapi/mesh-v1.json (the export carries no 4xx/5xx
// responses and no error schema). Emitted here from §13.4 so the App has one
// import; `message` is human-readable and never contains Content or raw
// backend bodies (§13.4). Code vocabulary: Appendix D.
// ---------------------------------------------------------------------------

/** Optional details object (§13.4 example: {"hint": "load_model"}). */
export type ErrorDetails = Record<string, unknown>;

/** §13.4 `error` block. `retryable`/`request_id`/`details` are optional
 *  in the spec text and always sent by the current Agent implementation. */
export interface ErrorEnvelopeError {
  code: string;
  message: string;
  retryable?: boolean;
  request_id?: string;
  details?: ErrorDetails;
}

/** The §13.4 envelope: { error: { code, message, retryable?, request_id?, details? } }. */
export interface ErrorEnvelope {
  error: ErrorEnvelopeError;
}


// ---------------------------------------------------------------------------
// §13-normative response shapes
//
// The OpenAPI export leaves these 2xx responses untyped (additionalProperties:
// true or no schema at all). The shapes below are normative in
// docs/LocalMesh_AI_Architecture_and_Requirements.md (LM-ARCH-001) and are
// emitted here — clearly sourced — so the App data layer imports ONE module.
// They are NOT invented: every field traces to the cited spec section
// (implementation-only fields are explicitly marked as such). Runtime guards
// for all of them live in validators.ts.
// ---------------------------------------------------------------------------

/** API-PAIR-01 202 body (§13.2, verbatim). */
export interface PairCompleteResponse {
  status: "awaiting_confirmation";
}

/** Closed status set of API-PAIR-02 (§13.2). */
export type PairingStatus = "awaiting_confirmation" | "approved" | "denied" | "expired";

/** endpoints block of API-PAIR-02 (§13.2). tailnet is null when Tailscale is absent. */
export interface PairStatusEndpoints {
  lan: string[];
  tailnet: { dns?: string | null; ips?: string[] } | null;
}

/**
 * API-PAIR-02 200 body (§13.2). `device_id` is present only when
 * `approved` (§13.2); the Agent additionally sends `endpoints` before
 * approval — accepted additively (§13.10).
 */
export interface PairStatusResponse {
  status: PairingStatus;
  agent_id: string;
  scopes: string[];
  endpoints?: PairStatusEndpoints;
  device_id?: string;
}

/** API-AUTH-01 200 body (§13.2). Single use, TTL 30 s (§17.3). */
export interface AuthChallengeResponse {
  challenge_id: string;
  nonce: string;
  expires_in: number;
}

/** API-AUTH-02 200 body (§13.2). pin_backup is M9 pin-rotation staging (§17.5). */
export interface AuthTokenResponse {
  access_token: string;
  token_type: "Bearer";
  expires_in: number;
  scopes: string[];
  pin_backup?: string;
}

/** Overall health state (§13.2 API-HEALTH-01). */
export type HealthState = "ok" | "degraded" | "down";

/** One Backend probe row of the health payload (§13.2). */
export interface HealthBackendStatus {
  id: string;
  status: "up" | "down" | "unknown";
}

/** Scheduler queue block (§13.2). */
export interface HealthQueue {
  active: number;
  queued: number;
  max_queued: number;
}

/** API-HEALTH-01 200 body (§13.2). */
export interface HealthResponse {
  status: HealthState;
  uptime_s: number;
  backends: HealthBackendStatus[];
  queue: HealthQueue;
}

/** Model lifecycle state, closed set (§13.5). */
export type ModelLifecycleState = "loaded" | "unloaded" | "loading" | "unknown";

/** Provenance source for every registry value (§13.5: backend|user|unknown; never name-inferred). */
export type ValueSource = "backend" | "user" | "unknown";

/** Backend row of the registry envelope, with declared caps (§13.5). */
export interface BackendStatusEntry {
  id: string;
  kind: string;
  status: string;
  caps: { load_unload: boolean; keep_warm: boolean };
}

/** {value, source} triple for optional registry values (§13.5).
 *  value is number|string|null depending on the field (context_length → number,
 *  quantization/parameter_size → string); §13.5 does not pin the value type. */
export interface TypedValue {
  value: number | string | null;
  source: ValueSource;
}

/** §13.5 Capability Registry `models[]` entry (normalized, provenance-carrying). */
export interface ModelEntry {
  mesh_model_id: string;
  backend_id: string;
  backend_model_id: string;
  display_name: string | null;
  state: ModelLifecycleState;
  modalities: { input: string[]; output: string[]; source: ValueSource };
  capabilities: { values: string[]; source: ValueSource };
  context_length: TypedValue;
  quantization: TypedValue;
  parameter_size: TypedValue;
  size_bytes: number | null;
  vram_estimate_bytes: number | null;
  tags: string[];
}

/** API-MODEL-01 200 body — the §13.5 envelope, keys exactly. */
export interface ModelsResponse {
  agent_id: string;
  generated_at: string;
  backends: BackendStatusEntry[];
  models: ModelEntry[];
}

/** API-MODEL-02 202 body (§13.2, verbatim `{"state":"loading"}`). */
export type LoadModelResponse = { state: "loading" };

/** API-MODEL-03 202 body (§13.5 vocabulary mirror; owner note in QUESTION-106). */
export type UnloadModelResponse = { state: "unloaded" };

/** API-REQ-01 202 body (§13.2). */
export type CancelRequestResponse = { status: "cancelling" };

/** POST /tasks 202 body (§13.9). Status enum is not §-pinned; kept `string`. */
export type TaskCreateResponse = { task_id: string; status: string };

/** Terminal-task error block (§13.9 `error?`). */
export interface TaskStatusError {
  code: string;
  message: string;
}

/** GET /tasks/{id} body. §13.9 pins {status, progress, result?, error?};
 *  task_id/type/created_at/expires_at are the Agent implementation's additive
 *  fields (core/tasks.py task_view) — treat the §13.9 four as the contract. */
export interface TaskStatusResponse {
  task_id: string;
  type: string;
  status: string;
  progress: number;
  created_at: number;
  expires_at?: number;
  result?: unknown;
  error?: TaskStatusError;
}


// ---------------------------------------------------------------------------
// Per-operation types (sorted by path, then HTTP method)
// ---------------------------------------------------------------------------

/** Request body of POST /mesh/v1/auth/challenge.
 *  NOT declared in docs/openapi/mesh-v1.json (the export has no requestBody for this
 *  operation). Normative shape: LM-ARCH-001 §13.2 API-AUTH-01 — deliberately NOT invented here (ADR-015).
 *  `unknown` keeps call sites honest until the export pins the body. */
export type AuthChallengeRequest = unknown;


/** Request body of POST /mesh/v1/auth/token.
 *  NOT declared in docs/openapi/mesh-v1.json (the export has no requestBody for this
 *  operation). Normative shape: LM-ARCH-001 §13.2 API-AUTH-02 — deliberately NOT invented here (ADR-015).
 *  `unknown` keeps call sites honest until the export pins the body. */
export type AuthTokenRequest = unknown;


/** Request body of POST /mesh/v1/chat/completions.
 *  NOT declared in docs/openapi/mesh-v1.json (the export has no requestBody for this
 *  operation). Normative shape: LM-ARCH-001 §13.6 chat parameter allow-list — deliberately NOT invented here (ADR-015).
 *  `unknown` keeps call sites honest until the export pins the body. */
export type ChatCompletionsRequest = unknown;

/** Success response of POST /mesh/v1/chat/completions (200).
 *  untyped in the OpenAPI export (no schema / title only). Normative shape: LM-ARCH-001 §13.2/§13.7/§13.9 — not invented here.
 */
export type ChatCompletionsResponse = unknown;

/** Request body of GET /mesh/v1/device.
 *  NOT declared in docs/openapi/mesh-v1.json (the export has no requestBody for this
 *  operation). Normative shape: LM-ARCH-001 §13 — deliberately NOT invented here (ADR-015).
 *  `unknown` keeps call sites honest until the export pins the body. */
export type GetDeviceRequest = unknown;

/** Success response of GET /mesh/v1/device (200).
 */
export type GetDeviceResponse = DeviceResponse;

/** Request body of GET /mesh/v1/health.
 *  NOT declared in docs/openapi/mesh-v1.json (the export has no requestBody for this
 *  operation). Normative shape: LM-ARCH-001 §13 — deliberately NOT invented here (ADR-015).
 *  `unknown` keeps call sites honest until the export pins the body. */
export type HealthRequest = unknown;


/** Request body of GET /mesh/v1/info.
 *  NOT declared in docs/openapi/mesh-v1.json (the export has no requestBody for this
 *  operation). Normative shape: LM-ARCH-001 §13 — deliberately NOT invented here (ADR-015).
 *  `unknown` keeps call sites honest until the export pins the body. */
export type GetInfoRequest = unknown;

/** Success response of GET /mesh/v1/info (200).
 */
export type GetInfoResponse = AgentInfo;

/** Request body of GET /mesh/v1/models.
 *  NOT declared in docs/openapi/mesh-v1.json (the export has no requestBody for this
 *  operation). Normative shape: LM-ARCH-001 §13 — deliberately NOT invented here (ADR-015).
 *  `unknown` keeps call sites honest until the export pins the body. */
export type ListModelsRequest = unknown;

/** Success response of GET /mesh/v1/models (200).
 *  Untyped in the OpenAPI export; shape sourced from LM-ARCH-001 §13.5 (Capability Registry envelope).
 *  Narrow type declared in the §13 section above — this alias names it for call sites. */
export type ListModelsResponse = ModelsResponse;

/** Request body of POST /mesh/v1/models/load.
 *  NOT declared in docs/openapi/mesh-v1.json (the export has no requestBody for this
 *  operation). Normative shape: LM-ARCH-001 §13.2 API-MODEL-02 ({mesh_model_id}) — deliberately NOT invented here (ADR-015).
 *  `unknown` keeps call sites honest until the export pins the body. */
export type LoadModelRequest = unknown;


/** Request body of POST /mesh/v1/models/unload.
 *  NOT declared in docs/openapi/mesh-v1.json (the export has no requestBody for this
 *  operation). Normative shape: LM-ARCH-001 §13.2 API-MODEL-03 ({mesh_model_id}) — deliberately NOT invented here (ADR-015).
 *  `unknown` keeps call sites honest until the export pins the body. */
export type UnloadModelRequest = unknown;


/** Request body of POST /mesh/v1/pair/complete.
 *  NOT declared in docs/openapi/mesh-v1.json (the export has no requestBody for this
 *  operation). Normative shape: LM-ARCH-001 §13.2 API-PAIR-01 — deliberately NOT invented here (ADR-015).
 *  `unknown` keeps call sites honest until the export pins the body. */
export type PairCompleteRequest = unknown;


/** Request body of POST /mesh/v1/pair/status.
 *  NOT declared in docs/openapi/mesh-v1.json (the export has no requestBody for this
 *  operation). Normative shape: LM-ARCH-001 §13.2 API-PAIR-02 — deliberately NOT invented here (ADR-015).
 *  `unknown` keeps call sites honest until the export pins the body. */
export type PairStatusRequest = unknown;


/** Request body of DELETE /mesh/v1/requests/{request_id}.
 *  NOT declared in docs/openapi/mesh-v1.json (the export has no requestBody for this
 *  operation). Normative shape: LM-ARCH-001 §13 — deliberately NOT invented here (ADR-015).
 *  `unknown` keeps call sites honest until the export pins the body. */
export type CancelRequestRequest = unknown;


/** Request body of POST /mesh/v1/tasks.
 *  NOT declared in docs/openapi/mesh-v1.json (the export has no requestBody for this
 *  operation). Normative shape: LM-ARCH-001 §13.9 ({type, input, options}) — deliberately NOT invented here (ADR-015).
 *  `unknown` keeps call sites honest until the export pins the body. */
export type CreateTaskRequest = unknown;

/** Success response of POST /mesh/v1/tasks (200).
 *  Untyped in the OpenAPI export; shape sourced from LM-ARCH-001 §13.9.
 *  Narrow type declared in the §13 section above — this alias names it for call sites. */
export type CreateTaskResponse = TaskCreateResponse;

/** Request body of GET /mesh/v1/tasks/{task_id}.
 *  NOT declared in docs/openapi/mesh-v1.json (the export has no requestBody for this
 *  operation). Normative shape: LM-ARCH-001 §13 — deliberately NOT invented here (ADR-015).
 *  `unknown` keeps call sites honest until the export pins the body. */
export type GetTaskRequest = unknown;

/** Success response of GET /mesh/v1/tasks/{task_id} (200).
 *  Untyped in the OpenAPI export; shape sourced from LM-ARCH-001 §13.9 pins {status, progress, result?, error?}; task_id/type/created_at/expires_at come from the Agent implementation (core/tasks.py task_view) — not yet §-pinned.
 *  Narrow type declared in the §13 section above — this alias names it for call sites. */
export type GetTaskResponse = TaskStatusResponse;

/** Request body of DELETE /mesh/v1/tasks/{task_id}.
 *  NOT declared in docs/openapi/mesh-v1.json (the export has no requestBody for this
 *  operation). Normative shape: LM-ARCH-001 §13 — deliberately NOT invented here (ADR-015).
 *  `unknown` keeps call sites honest until the export pins the body. */
export type DeleteTaskRequest = unknown;

/** Success response of DELETE /mesh/v1/tasks/{task_id} (200).
 *  untyped in the OpenAPI export (no schema / title only). Normative shape: LM-ARCH-001 §13.2/§13.7/§13.9 — not invented here.
 */
export type DeleteTaskResponse = unknown;

/** Request body of PUT /mesh/v1/tasks/{task_id}/attachments/{name}.
 *  NOT declared in docs/openapi/mesh-v1.json (the export has no requestBody for this
 *  operation). Normative shape: LM-ARCH-001 §13 — deliberately NOT invented here (ADR-015).
 *  `unknown` keeps call sites honest until the export pins the body. */
export type PutAttachmentRequest = unknown;

/** Success response of PUT /mesh/v1/tasks/{task_id}/attachments/{name} (200).
 *  untyped in the OpenAPI export (no schema / title only). Normative shape: LM-ARCH-001 §13.2/§13.7/§13.9 — not invented here.
 */
export type PutAttachmentResponse = unknown;

/** Request body of GET /mesh/v1/tasks/{task_id}/events.
 *  NOT declared in docs/openapi/mesh-v1.json (the export has no requestBody for this
 *  operation). Normative shape: LM-ARCH-001 §13 — deliberately NOT invented here (ADR-015).
 *  `unknown` keeps call sites honest until the export pins the body. */
export type TaskEventsRequest = unknown;

/** Success response of GET /mesh/v1/tasks/{task_id}/events (200).
 *  untyped in the OpenAPI export (no schema / title only). Normative shape: LM-ARCH-001 §13.2/§13.7/§13.9 — not invented here.
 */
export type TaskEventsResponse = unknown;

// ---------------------------------------------------------------------------
// Paths map (operation per method+path; `response` is the success alias,
// `responses` lists every status declared in the OpenAPI export)
// ---------------------------------------------------------------------------

export interface Paths {
  "/mesh/v1/auth/challenge": {
    post: {
      request: AuthChallengeRequest;
      response: AuthChallengeResponse;
      responses: { 200: AuthChallengeResponse };
    };
  };
  "/mesh/v1/auth/token": {
    post: {
      request: AuthTokenRequest;
      response: AuthTokenResponse;
      responses: { 200: AuthTokenResponse };
    };
  };
  "/mesh/v1/chat/completions": {
    post: {
      request: ChatCompletionsRequest;
      response: ChatCompletionsResponse;
      responses: { 200: ChatCompletionsResponse };
    };
  };
  "/mesh/v1/device": {
    get: {
      request: GetDeviceRequest;
      response: GetDeviceResponse;
      responses: { 200: GetDeviceResponse };
    };
  };
  "/mesh/v1/health": {
    get: {
      request: HealthRequest;
      response: HealthResponse;
      responses: { 200: HealthResponse };
    };
  };
  "/mesh/v1/info": {
    get: {
      request: GetInfoRequest;
      response: GetInfoResponse;
      responses: { 200: GetInfoResponse };
    };
  };
  "/mesh/v1/models": {
    get: {
      request: ListModelsRequest;
      response: ListModelsResponse;
      responses: { 200: ListModelsResponse };
    };
  };
  "/mesh/v1/models/load": {
    post: {
      request: LoadModelRequest;
      response: LoadModelResponse;
      responses: { 200: LoadModelResponse };
    };
  };
  "/mesh/v1/models/unload": {
    post: {
      request: UnloadModelRequest;
      response: UnloadModelResponse;
      responses: { 200: UnloadModelResponse };
    };
  };
  "/mesh/v1/pair/complete": {
    post: {
      request: PairCompleteRequest;
      response: PairCompleteResponse;
      responses: { 202: PairCompleteResponse };
    };
  };
  "/mesh/v1/pair/status": {
    post: {
      request: PairStatusRequest;
      response: PairStatusResponse;
      responses: { 200: PairStatusResponse };
    };
  };
  "/mesh/v1/requests/{request_id}": {
    delete: {
      params: { request_id: string };
      request: CancelRequestRequest;
      response: CancelRequestResponse;
      responses: { 202: CancelRequestResponse; 422: HTTPValidationError };
    };
  };
  "/mesh/v1/tasks": {
    post: {
      request: CreateTaskRequest;
      response: CreateTaskResponse;
      responses: { 200: CreateTaskResponse };
    };
  };
  "/mesh/v1/tasks/{task_id}": {
    get: {
      params: { task_id: string };
      request: GetTaskRequest;
      response: GetTaskResponse;
      responses: { 200: GetTaskResponse; 422: HTTPValidationError };
    };
    delete: {
      params: { task_id: string };
      request: DeleteTaskRequest;
      response: DeleteTaskResponse;
      responses: { 200: DeleteTaskResponse; 422: HTTPValidationError };
    };
  };
  "/mesh/v1/tasks/{task_id}/attachments/{name}": {
    put: {
      params: { name: string; task_id: string };
      request: PutAttachmentRequest;
      response: PutAttachmentResponse;
      responses: { 200: PutAttachmentResponse; 422: HTTPValidationError };
    };
  };
  "/mesh/v1/tasks/{task_id}/events": {
    get: {
      params: { task_id: string };
      request: TaskEventsRequest;
      response: TaskEventsResponse;
      responses: { 200: TaskEventsResponse; 422: HTTPValidationError };
    };
  };
}

// ---------------------------------------------------------------------------
// HTTP method + path literals (from the OpenAPI export, sorted)
// ---------------------------------------------------------------------------

export type MeshApiMethod = "DELETE" | "GET" | "POST" | "PUT";

export type MeshApiPath =
  | "/mesh/v1/auth/challenge"
  | "/mesh/v1/auth/token"
  | "/mesh/v1/chat/completions"
  | "/mesh/v1/device"
  | "/mesh/v1/health"
  | "/mesh/v1/info"
  | "/mesh/v1/models"
  | "/mesh/v1/models/load"
  | "/mesh/v1/models/unload"
  | "/mesh/v1/pair/complete"
  | "/mesh/v1/pair/status"
  | "/mesh/v1/requests/{request_id}"
  | "/mesh/v1/tasks"
  | "/mesh/v1/tasks/{task_id}"
  | "/mesh/v1/tasks/{task_id}/attachments/{name}"
  | "/mesh/v1/tasks/{task_id}/events";

export type MeshApiEndpoint =
  | "DELETE /mesh/v1/requests/{request_id}"
  | "DELETE /mesh/v1/tasks/{task_id}"
  | "GET /mesh/v1/device"
  | "GET /mesh/v1/health"
  | "GET /mesh/v1/info"
  | "GET /mesh/v1/models"
  | "GET /mesh/v1/tasks/{task_id}"
  | "GET /mesh/v1/tasks/{task_id}/events"
  | "POST /mesh/v1/auth/challenge"
  | "POST /mesh/v1/auth/token"
  | "POST /mesh/v1/chat/completions"
  | "POST /mesh/v1/models/load"
  | "POST /mesh/v1/models/unload"
  | "POST /mesh/v1/pair/complete"
  | "POST /mesh/v1/pair/status"
  | "POST /mesh/v1/tasks"
  | "PUT /mesh/v1/tasks/{task_id}/attachments/{name}";

export const MESH_API_PATHS = ["/mesh/v1/auth/challenge", "/mesh/v1/auth/token", "/mesh/v1/chat/completions", "/mesh/v1/device", "/mesh/v1/health", "/mesh/v1/info", "/mesh/v1/models", "/mesh/v1/models/load", "/mesh/v1/models/unload", "/mesh/v1/pair/complete", "/mesh/v1/pair/status", "/mesh/v1/requests/{request_id}", "/mesh/v1/tasks", "/mesh/v1/tasks/{task_id}", "/mesh/v1/tasks/{task_id}/attachments/{name}", "/mesh/v1/tasks/{task_id}/events"] as const;

export const MESH_API_ENDPOINTS = ["DELETE /mesh/v1/requests/{request_id}", "DELETE /mesh/v1/tasks/{task_id}", "GET /mesh/v1/device", "GET /mesh/v1/health", "GET /mesh/v1/info", "GET /mesh/v1/models", "GET /mesh/v1/tasks/{task_id}", "GET /mesh/v1/tasks/{task_id}/events", "POST /mesh/v1/auth/challenge", "POST /mesh/v1/auth/token", "POST /mesh/v1/chat/completions", "POST /mesh/v1/models/load", "POST /mesh/v1/models/unload", "POST /mesh/v1/pair/complete", "POST /mesh/v1/pair/status", "POST /mesh/v1/tasks", "PUT /mesh/v1/tasks/{task_id}/attachments/{name}"] as const;
