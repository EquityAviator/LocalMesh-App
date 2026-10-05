/**
 * mesh-protocol type generator (LM-ARCH-001 §21.3, ADR-015).
 *
 * Parses docs/openapi/mesh-v1.json (the drift-checked Agent API export) and
 * emits, deterministically:
 *
 *   src/types.ts        — per-schema TS interfaces, per-operation request/
 *                         response types, the Paths map, method+path literal
 *                         unions, the §13.4 error envelope.
 *   src/validators.ts   — hand-rolled, dependency-free runtime guards for the
 *                         safety-critical wire shapes.
 *   src/sse-events.ts   — the chat SSE event-name vocabulary + typed event
 *                         union (§13.7; the OpenAPI export does not document
 *                         the event names, so they are derived from the
 *                         governing spec).
 *   src/index.ts        — barrel.
 *
 * Determinism: output depends ONLY on the input files. The "generated at"
 * timestamp is the source spec's mtime (UTC), and the spec sha256 is pinned,
 * so two runs on the same inputs are byte-identical (asserted by
 * test/generated.test.ts).
 *
 * Honesty rule (ADR-015): anything the OpenAPI export does not pin down is
 * NOT invented here. Where a wire shape is normative in LM-ARCH-001 §13 but
 * absent from the OpenAPI export, the type carries an explicit source
 * comment; where nothing pins it, the type is `unknown` and the gap is
 * noted — never guessed.
 *
 * Usage: bun packages/mesh-protocol/scripts/generate.ts
 * (or `bun run gen` inside packages/mesh-protocol)
 */

import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

const PKG_DIR = path.resolve(import.meta.dir, "..");
const REPO_ROOT = path.resolve(PKG_DIR, "..", "..");
const SPEC_PATH = path.join(REPO_ROOT, "docs", "openapi", "mesh-v1.json");
const ARCH_PATH = path.join(REPO_ROOT, "docs", "LocalMesh_AI_Architecture_and_Requirements.md");
const OUT_DIR = path.join(PKG_DIR, "src");

/* eslint-disable @typescript-eslint/no-explicit-any */
type Json = any;

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function pascal(name: string): string {
  return name
    .split(/[^A-Za-z0-9]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join("");
}

/** operationId `get_info_mesh_v1_info_get` → base `get_info` (FastAPI suffix stripped). */
function baseOpName(operationId: string): string {
  const idx = operationId.indexOf("_mesh_v1_");
  return idx >= 0 ? operationId.slice(0, idx) : operationId;
}

/** JSON string literal, safely quoted for TS output. */
function q(s: string): string {
  return JSON.stringify(s);
}

/** Turn a schema `description` into JSDoc lines (escaped). */
function jsdoc(description: string | undefined, extra?: string[]): string[] {
  const lines: string[] = [];
  const body = (description ?? "").trim();
  if (body) {
    for (const raw of body.split("\n")) {
      lines.push(" * " + raw.replace(/\*\//g, "*\\/").trimEnd());
    }
  }
  for (const line of extra ?? []) lines.push(" * " + line.replace(/\*\//g, "*\\/"));
  if (lines.length === 0) return [];
  return ["/**", ...lines, " */"];
}

function refName(schema: Json): string | null {
  if (schema && typeof schema.$ref === "string") {
    const tail = schema.$ref.split("/").pop() ?? "";
    return pascal(tail);
  }
  return null;
}

function uniq(values: string[]): string[] {
  return [...new Set(values)];
}

// ---------------------------------------------------------------------------
// Schema → TS
// ---------------------------------------------------------------------------

function tsType(schema: Json): string {
  if (schema === true || schema === undefined || schema === null) return "unknown";
  if (typeof schema !== "object") return "unknown";
  const ref = refName(schema);
  if (ref) return ref;
  if (Array.isArray(schema.anyOf)) {
    const parts = uniq(schema.anyOf.map((s: Json) => tsType(s)));
    return parts.length > 0 ? parts.join(" | ") : "unknown";
  }
  if (Array.isArray(schema.oneOf)) {
    const parts = uniq(schema.oneOf.map((s: Json) => tsType(s)));
    return parts.length > 0 ? parts.join(" | ") : "unknown";
  }
  if (Array.isArray(schema.enum)) {
    return uniq(schema.enum.map((v: Json) => (typeof v === "string" ? q(v) : String(v)))).join(" | ");
  }
  const t = schema.type;
  if (t === "string") return "string";
  if (t === "integer" || t === "number") return "number";
  if (t === "boolean") return "boolean";
  if (t === "null") return "null";
  if (t === "array") return `${tsType(schema.items ?? {})}[]`;
  if (t === "object") {
    const props = schema.properties as Record<string, Json> | undefined;
    if (props && Object.keys(props).length > 0) {
      // Inline object literal (not used by the current export, but kept for
      // robustness so a future export never silently degrades).
      const required: string[] = Array.isArray(schema.required) ? schema.required : [];
      const fields = Object.entries(props).map(([key, pschema]) => {
        const opt = required.includes(key) ? "" : "?";
        return `${q(key)}${opt}: ${tsType(pschema)}`;
      });
      return `{ ${fields.join("; ")} }`;
    }
    const ap = schema.additionalProperties;
    if (ap && typeof ap === "object") return `Record<string, ${tsType(ap)}>`;
    return "Record<string, unknown>";
  }
  return "unknown";
}

function tsFieldName(key: string): string {
  return /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(key) ? key : q(key);
}

function schemaInterface(name: string, schema: Json): string {
  const out: string[] = [];
  out.push(...jsdoc(schema.description, [`OpenAPI schema: components.schemas.${name}.`]));
  out.push(`export interface ${name} {`);
  const props = (schema.properties ?? {}) as Record<string, Json>;
  const required: string[] = Array.isArray(schema.required) ? schema.required : [];
  for (const [key, pschema] of Object.entries(props)) {
    for (const line of jsdoc(pschema?.description)) out.push("  " + line);
    const opt = required.includes(key) ? "" : "?";
    out.push(`  ${tsFieldName(key)}${opt}: ${tsType(pschema)};`);
  }
  out.push("}");
  return out.join("\n");
}

// ---------------------------------------------------------------------------
// §13-narrow response shapes (normative in LM-ARCH-001, untyped in the export)
// ---------------------------------------------------------------------------

const NARROW_RESPONSES: Record<string, { type: string; source: string }> = {
  pair_complete: { type: "PairCompleteResponse", source: "LM-ARCH-001 §13.2 (verbatim 202 body)" },
  pair_status: { type: "PairStatusResponse", source: "LM-ARCH-001 §13.2" },
  auth_challenge: { type: "AuthChallengeResponse", source: "LM-ARCH-001 §13.2" },
  auth_token: { type: "AuthTokenResponse", source: "LM-ARCH-001 §13.2 (pin_backup: §17.5 M9)" },
  list_models: { type: "ModelsResponse", source: "LM-ARCH-001 §13.5 (Capability Registry envelope)" },
  health: { type: "HealthResponse", source: "LM-ARCH-001 §13.2" },
  load_model: { type: "LoadModelResponse", source: "LM-ARCH-001 §13.2 (verbatim 202 body)" },
  unload_model: {
    type: "UnloadModelResponse",
    source: "LM-ARCH-001 §13.5 closed vocabulary (mirror state; see QUESTION-106)",
  },
  cancel_request: { type: "CancelRequestResponse", source: "LM-ARCH-001 §13.2 API-REQ-01" },
  create_task: { type: "TaskCreateResponse", source: "LM-ARCH-001 §13.9" },
  get_task: {
    type: "TaskStatusResponse",
    source:
      "LM-ARCH-001 §13.9 pins {status, progress, result?, error?}; task_id/type/created_at/expires_at come from the Agent implementation (core/tasks.py task_view) — not yet §-pinned",
  },
};

/** §-reference for the (undeclared) request bodies, for the honest note per op. */
const REQUEST_BODY_NOTES: Record<string, string> = {
  pair_complete: "LM-ARCH-001 §13.2 API-PAIR-01",
  pair_status: "LM-ARCH-001 §13.2 API-PAIR-02",
  auth_challenge: "LM-ARCH-001 §13.2 API-AUTH-01",
  auth_token: "LM-ARCH-001 §13.2 API-AUTH-02",
  load_model: "LM-ARCH-001 §13.2 API-MODEL-02 ({mesh_model_id})",
  unload_model: "LM-ARCH-001 §13.2 API-MODEL-03 ({mesh_model_id})",
  chat_completions: "LM-ARCH-001 §13.6 chat parameter allow-list",
  create_task: "LM-ARCH-001 §13.9 ({type, input, options})",
};

const NARROW_SECTION = `
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
 * API-PAIR-02 200 body (§13.2). \`device_id\` is present only when
 * \`approved\` (§13.2); the Agent additionally sends \`endpoints\` before
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

/** §13.5 Capability Registry \`models[]\` entry (normalized, provenance-carrying). */
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

/** API-MODEL-02 202 body (§13.2, verbatim \`{"state":"loading"}\`). */
export type LoadModelResponse = { state: "loading" };

/** API-MODEL-03 202 body (§13.5 vocabulary mirror; owner note in QUESTION-106). */
export type UnloadModelResponse = { state: "unloaded" };

/** API-REQ-01 202 body (§13.2). */
export type CancelRequestResponse = { status: "cancelling" };

/** POST /tasks 202 body (§13.9). Status enum is not §-pinned; kept \`string\`. */
export type TaskCreateResponse = { task_id: string; status: string };

/** Terminal-task error block (§13.9 \`error?\`). */
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
`.trimStart();

// ---------------------------------------------------------------------------
// Error envelope (§13.4 — not declared in the OpenAPI export)
// ---------------------------------------------------------------------------

const ERROR_ENVELOPE_SECTION = `
// ---------------------------------------------------------------------------
// Error envelope — LM-ARCH-001 §13.4 (all non-2xx JSON responses, and the
// \`mesh.error\` SSE payload).
//
// NOT declared in docs/openapi/mesh-v1.json (the export carries no 4xx/5xx
// responses and no error schema). Emitted here from §13.4 so the App has one
// import; \`message\` is human-readable and never contains Content or raw
// backend bodies (§13.4). Code vocabulary: Appendix D.
// ---------------------------------------------------------------------------

/** Optional details object (§13.4 example: {"hint": "load_model"}). */
export type ErrorDetails = Record<string, unknown>;

/** §13.4 \`error\` block. \`retryable\`/\`request_id\`/\`details\` are optional
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
`.trimStart();

// ---------------------------------------------------------------------------
// validators.ts (emitted verbatim; dependency-free hand-rolled guards)
// ---------------------------------------------------------------------------

const VALIDATORS_SECTION = `
import type {
  AgentInfo,
  AuthChallengeResponse,
  AuthTokenResponse,
  DeviceResponse,
  ErrorEnvelope,
  HealthResponse,
  ModelsResponse,
  PairCompleteResponse,
  PairStatusResponse,
  TaskStatusResponse,
} from "./types";
import type { ChatCompletionChunk, ChatMeta, ChatSseEvent, ChatStats } from "./sse-events";

/**
 * Hand-rolled, ZERO-dependency runtime guards for the safety-critical wire
 * shapes (no zod: keeps the package importable by the Expo App data layer
 * without pulling a validator runtime into the bundle; ADR-015 keeps these
 * regenerated with the types, not hand-maintained elsewhere).
 *
 * Sources: OpenAPI-typed schemas (AgentInfo, DeviceResponse) and LM-ARCH-001
 * §13.2 / §13.4 / §13.5 / §13.7 / §13.9 for shapes the OpenAPI export leaves
 * open. Guards are LENIENT about additive unknown fields (§13.10: the App
 * MUST ignore unknown fields) but STRICT about the fields the App must trust
 * (ids, tokens, enums, state machines).
 */

export class MeshProtocolValidationError extends Error {
  readonly expected: string;

  constructor(expected: string) {
    super('mesh-protocol: value does not match ' + expected + ' (packages/mesh-protocol/src/validators.ts)');
    this.name = 'MeshProtocolValidationError';
    this.expected = expected;
  }
}

// -- primitive helpers ------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === 'string';
}

function isStringOrNull(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isInt(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value);
}

function isNumberOrNull(value: unknown): value is number | null {
  return value === null || isNumber(value);
}

function isIntOrNull(value: unknown): value is number | null {
  return value === null || isInt(value);
}

function isBool(value: unknown): value is boolean {
  return typeof value === 'boolean';
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString);
}

function isIn(value: unknown, set: readonly string[]): value is string {
  return isString(value) && (set as readonly string[]).includes(value);
}

function assertGuard<T>(expected: string, guard: (v: unknown) => v is T, value: unknown): T {
  if (!guard(value)) throw new MeshProtocolValidationError(expected);
  return value;
}

// -- API-INFO-01: InfoResponse (OpenAPI-typed: components.schemas.AgentInfo, §13.2)

export function isInfoResponse(value: unknown): value is AgentInfo {
  if (!isRecord(value)) return false;
  const api = value['api'];
  return (
    isString(value['agent_id']) &&
    isString(value['display_name']) &&
    isRecord(api) &&
    isStringArray(api['versions']) &&
    api['versions'].length > 0 &&
    isString(api['agent_version']) &&
    isBool(value['pairing_open'])
  );
}

export function assertInfoResponse(value: unknown): AgentInfo {
  return assertGuard('InfoResponse (AgentInfo, §13.2)', isInfoResponse, value);
}

// -- API-PAIR-01: PairCompleteResponse (§13.2)

export function isPairCompleteResponse(value: unknown): value is PairCompleteResponse {
  return isRecord(value) && value['status'] === 'awaiting_confirmation';
}

export function assertPairCompleteResponse(value: unknown): PairCompleteResponse {
  return assertGuard('PairCompleteResponse (§13.2)', isPairCompleteResponse, value);
}

// -- API-PAIR-02: PairStatusResponse (§13.2)

const PAIRING_STATUSES = ['awaiting_confirmation', 'approved', 'denied', 'expired'] as const;

export function isPairStatusResponse(value: unknown): value is PairStatusResponse {
  if (!isRecord(value)) return false;
  if (!isIn(value['status'], PAIRING_STATUSES)) return false;
  if (!isString(value['agent_id'])) return false;
  if (!isStringArray(value['scopes'])) return false;
  if (value['device_id'] !== undefined && !isString(value['device_id'])) return false;
  const endpoints = value['endpoints'];
  if (endpoints === undefined) return true; // §13.2 gates device_id/endpoints on approval
  if (!isRecord(endpoints)) return false;
  if (!isStringArray(endpoints['lan'])) return false;
  const tailnet = endpoints['tailnet'];
  if (tailnet === null) return true;
  if (!isRecord(tailnet)) return false;
  if (tailnet['dns'] !== undefined && !isStringOrNull(tailnet['dns'])) return false;
  if (tailnet['ips'] !== undefined && !isStringArray(tailnet['ips'])) return false;
  return true;
}

export function assertPairStatusResponse(value: unknown): PairStatusResponse {
  return assertGuard('PairStatusResponse (§13.2)', isPairStatusResponse, value);
}

// -- API-AUTH-01: AuthChallengeResponse (§13.2)

export function isAuthChallengeResponse(value: unknown): value is AuthChallengeResponse {
  return (
    isRecord(value) &&
    isString(value['challenge_id']) &&
    isString(value['nonce']) &&
    isInt(value['expires_in'])
  );
}

export function assertAuthChallengeResponse(value: unknown): AuthChallengeResponse {
  return assertGuard('AuthChallengeResponse (§13.2)', isAuthChallengeResponse, value);
}

// -- API-AUTH-02: AuthTokenResponse (§13.2)

export function isAuthTokenResponse(value: unknown): value is AuthTokenResponse {
  return (
    isRecord(value) &&
    isString(value['access_token']) &&
    value['token_type'] === 'Bearer' &&
    isInt(value['expires_in']) &&
    isStringArray(value['scopes']) &&
    (value['pin_backup'] === undefined || isString(value['pin_backup']))
  );
}

export function assertAuthTokenResponse(value: unknown): AuthTokenResponse {
  return assertGuard('AuthTokenResponse (§13.2)', isAuthTokenResponse, value);
}

// -- API-MODEL-01: ModelsResponse (§13.5 envelope; entries guarded on the
//    fields the App must trust — ids + closed state vocabulary)

const MODEL_STATES = ['loaded', 'unloaded', 'loading', 'unknown'] as const;

export function isModelsResponse(value: unknown): value is ModelsResponse {
  if (!isRecord(value)) return false;
  if (!isString(value['agent_id']) || !isString(value['generated_at'])) return false;
  const backends = value['backends'];
  if (!Array.isArray(backends)) return false;
  for (const backend of backends) {
    if (
      !isRecord(backend) ||
      !isString(backend['id']) ||
      !isString(backend['kind']) ||
      !isString(backend['status'])
    ) {
      return false;
    }
    const caps = backend['caps'];
    if (!isRecord(caps) || !isBool(caps['load_unload']) || !isBool(caps['keep_warm'])) return false;
  }
  const models = value['models'];
  if (!Array.isArray(models)) return false;
  for (const model of models) {
    if (!isRecord(model)) return false;
    if (!isString(model['mesh_model_id']) || !isString(model['backend_id'])) return false;
    if (!isIn(model['state'], MODEL_STATES)) return false;
  }
  return true;
}

export function assertModelsResponse(value: unknown): ModelsResponse {
  return assertGuard('ModelsResponse (§13.5)', isModelsResponse, value);
}

// -- API-HEALTH-01: HealthResponse (§13.2)

const HEALTH_STATES = ['ok', 'degraded', 'down'] as const;
const BACKEND_STATES = ['up', 'down', 'unknown'] as const;

export function isHealthResponse(value: unknown): value is HealthResponse {
  if (!isRecord(value)) return false;
  if (!isIn(value['status'], HEALTH_STATES)) return false;
  if (!isInt(value['uptime_s'])) return false;
  const backends = value['backends'];
  if (!Array.isArray(backends)) return false;
  for (const backend of backends) {
    if (!isRecord(backend) || !isString(backend['id']) || !isIn(backend['status'], BACKEND_STATES)) {
      return false;
    }
  }
  const queue = value['queue'];
  return (
    isRecord(queue) && isInt(queue['active']) && isInt(queue['queued']) && isInt(queue['max_queued'])
  );
}

export function assertHealthResponse(value: unknown): HealthResponse {
  return assertGuard('HealthResponse (§13.2)', isHealthResponse, value);
}

// -- API-DEV-01: DeviceResponse (OpenAPI-typed: components.schemas.DeviceResponse, §13.2;
//    every hardware value is nullable — the Agent MUST NOT fill unknowns with defaults)

function isGpuEntry(value: unknown): boolean {
  return (
    isRecord(value) &&
    isStringOrNull(value['name']) &&
    isIntOrNull(value['vram_total_bytes']) &&
    isIntOrNull(value['vram_used_bytes']) &&
    isNumberOrNull(value['utilization_pct']) &&
    isNumberOrNull(value['temperature_c'])
  );
}

export function isDeviceResponse(value: unknown): value is DeviceResponse {
  if (!isRecord(value)) return false;
  if (!isString(value['agent_id']) || !isString(value['display_name']) || !isString(value['agent_version'])) {
    return false;
  }
  const os = value['os'];
  if (!isRecord(os) || !isStringOrNull(os['family']) || !isStringOrNull(os['version'])) return false;
  const cpu = value['cpu'];
  if (!isRecord(cpu) || !isStringOrNull(cpu['model']) || !isIntOrNull(cpu['logical_cores'])) return false;
  const ram = value['ram'];
  if (!isRecord(ram) || !isIntOrNull(ram['total_bytes']) || !isIntOrNull(ram['available_bytes'])) return false;
  if (!Array.isArray(value['gpus']) || !value['gpus'].every(isGpuEntry)) return false;
  const network = value['network'];
  if (!isRecord(network) || !isStringArray(network['lan_addresses'])) return false;
  const tailnet = network['tailnet'];
  if (tailnet === null) return true;
  if (!isRecord(tailnet) || !isString(tailnet['state']) || !isStringArray(tailnet['ips'])) return false;
  // dns_name is REQUIRED by components.schemas.TailnetBlock (nullable, §13.2 example
  // shows null) — a missing key is a contract violation, not an additive field.
  return isStringOrNull(tailnet['dns_name']);
}

export function assertDeviceResponse(value: unknown): DeviceResponse {
  return assertGuard('DeviceResponse (§13.2 / components.schemas)', isDeviceResponse, value);
}

// -- API-CHAT-01 SSE: ChatCompletionChunk + event union (§13.7)

export function isChatCompletionChunk(value: unknown): value is ChatCompletionChunk {
  if (!isRecord(value)) return false;
  if (!isString(value['id']) || value['object'] !== 'chat.completion.chunk') return false;
  if (!isInt(value['created']) || !isString(value['model'])) return false;
  const choices = value['choices'];
  if (!Array.isArray(choices)) return false;
  for (const choice of choices) {
    if (!isRecord(choice) || !isInt(choice['index']) || !isRecord(choice['delta'])) return false;
    const delta = choice['delta'];
    if (delta['role'] !== undefined && !isString(delta['role'])) return false;
    if (delta['content'] !== undefined && !isString(delta['content'])) return false;
    if (choice['finish_reason'] !== null && !isString(choice['finish_reason'])) return false;
  }
  return true;
}

const MESH_EVENT_NAMES = ['mesh.meta', 'mesh.stats', 'mesh.error'] as const;
const TOKEN_COUNT_SOURCES = ['backend', 'estimated'] as const;

function isChatMeta(value: unknown): value is ChatMeta {
  if (!isRecord(value)) return false;
  if (
    !isString(value['request_id']) ||
    !isString(value['model']) ||
    !isString(value['backend']) ||
    !isInt(value['queued_ms']) ||
    !isIn(value['model_state'], MODEL_STATES)
  ) {
    return false;
  }
  return value['routing'] === undefined || isRecord(value['routing']);
}

function isChatStats(value: unknown): value is ChatStats {
  return (
    isRecord(value) &&
    isInt(value['ttft_ms']) &&
    isInt(value['tokens_out']) &&
    isNumber(value['tokens_per_sec']) &&
    isInt(value['duration_ms']) &&
    (value['finish_reason'] === null || isString(value['finish_reason'])) &&
    isIn(value['token_count_source'], TOKEN_COUNT_SOURCES)
  );
}

/**
 * Guard for one parsed chat SSE event (§13.7): named \`mesh.meta\` /
 * \`mesh.stats\` / \`mesh.error\` events, unnamed OpenAI
 * \`chat.completion.chunk\` events, and the literal \`[DONE]\` sentinel.
 * Unnamed events must be normalized to \`event: null\` by the parse layer.
 */
export function isChatSseEvent(value: unknown): value is ChatSseEvent {
  if (!isRecord(value)) return false;
  const name = value['event'];
  const data = value['data'];
  if (isIn(name, MESH_EVENT_NAMES)) {
    if (name === 'mesh.meta') return isChatMeta(data);
    if (name === 'mesh.stats') return isChatStats(data);
    return isErrorEnvelope(data);
  }
  if (name === null || name === undefined) {
    return data === '[DONE]' || isChatCompletionChunk(data);
  }
  return false;
}

export function assertChatSseEvent(value: unknown): ChatSseEvent {
  return assertGuard('ChatSseEvent (§13.7)', isChatSseEvent, value);
}

// -- API-TASK-xx: TaskStatusResponse (§13.9)

export function isTaskStatusResponse(value: unknown): value is TaskStatusResponse {
  if (!isRecord(value)) return false;
  if (!isString(value['task_id']) || !isString(value['type']) || !isString(value['status'])) return false;
  if (!isInt(value['progress']) || !isInt(value['created_at'])) return false;
  if (value['expires_at'] !== undefined && !isInt(value['expires_at'])) return false;
  const error = value['error'];
  if (error !== undefined) {
    if (!isRecord(error) || !isString(error['code']) || !isString(error['message'])) return false;
  }
  return true;
}

export function assertTaskStatusResponse(value: unknown): TaskStatusResponse {
  return assertGuard('TaskStatusResponse (§13.9)', isTaskStatusResponse, value);
}

// -- §13.4 MeshError envelope (all non-2xx; also the mesh.error SSE payload)

export function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (!isRecord(value)) return false;
  const error = value['error'];
  if (!isRecord(error) || !isString(error['code']) || !isString(error['message'])) return false;
  if (error['retryable'] !== undefined && !isBool(error['retryable'])) return false;
  if (error['request_id'] !== undefined && !isString(error['request_id'])) return false;
  return error['details'] === undefined || isRecord(error['details']);
}

export function assertErrorEnvelope(value: unknown): ErrorEnvelope {
  return assertGuard('ErrorEnvelope (§13.4)', isErrorEnvelope, value);
}
`.trimStart();

// ---------------------------------------------------------------------------
// index.ts barrel
// ---------------------------------------------------------------------------

const INDEX_SECTION = `
// Barrel: the App data layer imports everything from '@localmesh/mesh-protocol'.

export * from './types';
export * from './sse-events';
export * from './validators';
`.trimStart();

// ---------------------------------------------------------------------------
// SSE event-name extraction (§13.7)
// ---------------------------------------------------------------------------

interface SseVocabulary {
  names: string[];
  doneSentinel: string | null;
  pingComment: string | null;
  source: string;
}

function extractSseVocabulary(spec: Json): SseVocabulary {
  // 1) Preferred: the OpenAPI chat operation documentation (description /
  //    summary / x-sse-events extension), per the ADR-015 source-of-truth order.
  const chatOp = spec.paths?.["/mesh/v1/chat/completions"]?.post ?? {};
  const docText: string = [chatOp.description, chatOp.summary, chatOp["x-sse-events"]]
    .filter((v: unknown): v is string => typeof v === "string")
    .join("\n");
  const names: string[] = [];
  for (const match of docText.matchAll(/event:\s*([a-z][a-z0-9_.-]*)/gi)) {
    if (!names.includes(match[1]!)) names.push(match[1]!);
  }
  if (names.length >= 2) {
    return {
      names,
      doneSentinel: docText.includes("[DONE]") ? "[DONE]" : null,
      pingComment: docText.includes(": ping") ? "ping" : null,
      source: "docs/openapi/mesh-v1.json POST /mesh/v1/chat/completions documentation",
    };
  }

  // 2) Fallback: §13.7 of the governing spec (LM-ARCH-001), normative wire format.
  const arch = readFileSync(ARCH_PATH, "utf8");
  const start = arch.indexOf("### 13.7");
  const end = arch.indexOf("### 13.8");
  if (start < 0 || end < 0 || end <= start) {
    throw new Error(
      "mesh-protocol generator: cannot derive chat SSE event names — the OpenAPI chat " +
        "operation has no documentation and §13.7 was not found in " +
        path.relative(REPO_ROOT, ARCH_PATH),
    );
  }
  const section = arch.slice(start, end);
  for (const match of section.matchAll(/^event:\s*([a-z][a-z0-9_.-]*)/gim)) {
    if (!names.includes(match[1]!)) names.push(match[1]!);
  }
  // mesh.error never appears as an `event:` line in §13.7 — only in the rule
  // table ("Named events: mesh.meta (first), mesh.stats (last…), mesh.error
  // (terminal failure…)"). Scan every `mesh.*` token in the section so the
  // vocabulary stays complete (order = first appearance in §13.7).
  for (const match of section.matchAll(/`?(mesh\.[a-z_][a-z_]*)`?/g)) {
    if (!names.includes(match[1]!)) names.push(match[1]!);
  }
  if (names.length === 0) {
    throw new Error(
      'mesh-protocol generator: §13.7 contains no "event: <name>" lines — refusing to guess the vocabulary',
    );
  }
  const doneMatch = section.match(/^data:\s*(\[DONE\])\s*$/m);
  const pingMatch = section.match(/^:\s*(ping)\s*$/m);
  return {
    names,
    doneSentinel: doneMatch ? doneMatch[1]! : null,
    pingComment: pingMatch ? pingMatch[1]! : null,
    source:
      "LM-ARCH-001 §13.7 (docs/LocalMesh_AI_Architecture_and_Requirements.md) — the OpenAPI chat operation is undocumented",
  };
}

// ---------------------------------------------------------------------------
// Operation model
// ---------------------------------------------------------------------------

const HTTP_METHOD_ORDER = ["get", "post", "put", "delete", "patch", "head", "options"] as const;

interface OpRecord {
  path: string;
  method: string;
  operationId: string;
  base: string;
  typeName: string;
  pathParams: { name: string; type: string; required: boolean }[];
  responses: { code: string; type: string; note: string | null }[];
  success: { code: string; type: string; note: string | null } | null;
  description: string;
}

/** Classify an OpenAPI response schema for the honest note. */
function classifyResponse(schema: Json): { type: string; note: string | null } {
  if (schema === undefined || schema === null) {
    return { type: "unknown", note: "no schema declared in the OpenAPI export" };
  }
  const ref = refName(schema);
  if (ref) return { type: ref, note: null };
  if (typeof schema !== "object") return { type: "unknown", note: "no schema declared in the OpenAPI export" };
  const titleOnly =
    typeof schema.title === "string" && schema.type === undefined && schema.properties === undefined;
  if (schema.type === "object") {
    const ap = schema.additionalProperties;
    if (ap && typeof ap === "object" && ap.type === "string") {
      return { type: "Record<string, string>", note: null };
    }
    if (ap === true) {
      return {
        type: "Record<string, unknown>",
        note: "untyped in the OpenAPI export (additionalProperties: true)",
      };
    }
  }
  if (titleOnly || Object.keys(schema).length === 0) {
    return { type: "unknown", note: "untyped in the OpenAPI export (no schema / title only)" };
  }
  return { type: tsType(schema), note: null };
}

function buildOps(spec: Json): OpRecord[] {
  const ops: OpRecord[] = [];
  const paths = spec.paths as Record<string, Json>;
  for (const route of Object.keys(paths).sort()) {
    const pathItem = paths[route]!;
    for (const method of HTTP_METHOD_ORDER) {
      const op = pathItem[method];
      if (!op) continue;
      const operationId = String(op.operationId ?? `${method}_${route}`);
      const base = baseOpName(operationId);
      const typeName = pascal(base);
      const pathParams = ((op.parameters ?? []) as Json[])
        .filter((p: Json) => p?.in === "path")
        .map((p: Json) => ({
          name: String(p.name),
          type: tsType(p.schema ?? {}),
          required: Boolean(p.required),
        }));
      const responses: OpRecord["responses"] = [];
      const responseEntries = Object.entries(op.responses ?? {}) as [string, Json][];
      for (const [code, resp] of responseEntries) {
        const media = resp?.content?.["application/json"];
        const classified = classifyResponse(media?.schema);
        responses.push({ code, type: classified.type, note: classified.note });
      }
      let success: OpRecord["success"] = null;
      const successCode = responseEntries
        .map(([code]) => code)
        .filter((code) => /^2/.test(code))
        .sort()[0];
      if (successCode !== undefined) {
        const found = responses.find((r) => r.code === successCode);
        if (found) success = { ...found };
      }
      ops.push({
        path: route,
        method,
        operationId,
        base,
        typeName,
        pathParams,
        responses,
        success,
        description: String(op.description ?? ""),
      });
    }
  }
  return ops;
}

// ---------------------------------------------------------------------------
// Emitters
// ---------------------------------------------------------------------------

function headerComment(extra: string[], spec: Json, specSha: string, specMtime: string): string {
  const lines = [
    "/**",
    " * GENERATED — do not edit; regenerate via bun run gen:types (mesh-protocol).",
    " *",
    ` * Source: docs/openapi/mesh-v1.json (LM-ARCH-001 §13; OpenAPI ${spec.openapi}; info.version ${q(String(spec.info?.version ?? ""))})`,
    " *         ADR-015 / §21.3: this package is generated from the drift-checked export — nothing hand-written.",
    ` * Spec file sha256: ${specSha}`,
    ` * Generated at (source spec mtime, UTC): ${specMtime}`,
    " *         Deterministic by design: derived from the spec file, not the wall clock, so two",
    " *         runs on the same inputs are byte-identical (asserted by test/generated.test.ts).",
    ...extra.map((l) => ` * ${l.replace(/^\s*\*\s?/, "")}`),
    " */",
    "",
  ];
  return lines.join("\n");
}

function emitTypes(spec: Json, ops: OpRecord[], specSha: string, specMtime: string): string {
  const schemas = spec.components?.schemas as Record<string, Json> | undefined;
  const schemaNames = Object.keys(schemas ?? {}).sort();

  const parts: string[] = [];
  parts.push(
    headerComment(
      [
        " *",
        " * Contains: components.schemas → interfaces; per-operation Request/Response types;",
        " * Paths map; MeshApiMethod/MeshApiPath/MeshApiEndpoint literals; §13.4 ErrorEnvelope;",
        " * §13-normative narrow response shapes for endpoints the export leaves untyped",
        " * (each carries its own source comment — nothing is invented).",
      ],
      spec,
      specSha,
      specMtime,
    ),
  );

  parts.push("// ---------------------------------------------------------------------------");
  parts.push("// Schema interfaces (docs/openapi/mesh-v1.json → components.schemas, sorted by name)");
  parts.push("// ---------------------------------------------------------------------------");
  parts.push("");
  for (const name of schemaNames) {
    parts.push(schemaInterface(name, schemas![name]!));
    parts.push("");
  }

  parts.push(ERROR_ENVELOPE_SECTION);
  parts.push("");
  parts.push(NARROW_SECTION);
  parts.push("");

  parts.push("// ---------------------------------------------------------------------------");
  parts.push("// Per-operation types (sorted by path, then HTTP method)");
  parts.push("// ---------------------------------------------------------------------------");
  for (const op of ops) {
    const label = `${op.method.toUpperCase()} ${op.path}`;
    const reqNote = REQUEST_BODY_NOTES[op.base] ?? "LM-ARCH-001 §13";
    parts.push("");
    parts.push(
      [
        `/** Request body of ${label}.`,
        " *  NOT declared in docs/openapi/mesh-v1.json (the export has no requestBody for this",
        ` *  operation). Normative shape: ${reqNote} — deliberately NOT invented here (ADR-015).`,
        " *  `unknown` keeps call sites honest until the export pins the body. */",
      ].join("\n"),
    );
    parts.push(`export type ${op.typeName}Request = unknown;`);

    const narrow = NARROW_RESPONSES[op.base];
    parts.push("");
    if (narrow) {
      if (narrow.type === `${op.typeName}Response`) {
        // The narrow §13 declaration above IS this operation's response type
        // (e.g. HealthResponse) — emitting an alias would redeclare the name.
        continue;
      }
      parts.push(
        [
          `/** Success response of ${label} (${op.success?.code ?? "2xx"}).`,
          " *  Untyped in the OpenAPI export; shape sourced from " + narrow.source + ".",
          " *  Narrow type declared in the §13 section above — this alias names it for call sites. */",
        ].join("\n"),
      );
      parts.push(`export type ${op.typeName}Response = ${narrow.type};`);
    } else {
      const note = op.success?.note ?? null;
      const lines = [`/** Success response of ${label} (${op.success?.code ?? "2xx"}).`];
      if (note) {
        lines.push(` *  ${note}. Normative shape: LM-ARCH-001 §13.2/§13.7/§13.9 — not invented here.`);
        if (op.operationId === "chat_completions") {
          lines.push(" *  stream=true returns text/event-stream per §13.7 — typed events live in sse-events.ts.");
        }
      }
      lines.push(" */");
      parts.push(lines.join("\n"));
      parts.push(`export type ${op.typeName}Response = ${op.success?.type ?? "unknown"};`);
    }
  }

  // Paths map
  parts.push("");
  parts.push("// ---------------------------------------------------------------------------");
  parts.push("// Paths map (operation per method+path; `response` is the success alias,");
  parts.push("// `responses` lists every status declared in the OpenAPI export)");
  parts.push("// ---------------------------------------------------------------------------");
  parts.push("");
  parts.push("export interface Paths {");
  const byPath = new Map<string, OpRecord[]>();
  for (const op of ops) {
    const list = byPath.get(op.path) ?? [];
    list.push(op);
    byPath.set(op.path, list);
  }
  for (const [route, routeOps] of [...byPath.entries()].sort(([a], [b]) => (a < b ? -1 : 1))) {
    parts.push(`  ${q(route)}: {`);
    for (const op of routeOps) {
      parts.push(`    ${op.method}: {`);
      if (op.pathParams.length > 0) {
        parts.push(
          `      params: { ${op.pathParams.map((p) => `${tsFieldName(p.name)}: ${p.type}`).join("; ")} };`,
        );
      }
      parts.push(`      request: ${op.typeName}Request;`);
      parts.push(`      response: ${op.typeName}Response;`);
      // 2xx entry points at the same (narrow-aware) response type as `response`;
      // non-2xx statuses (422 validation) keep their OpenAPI-derived types.
      parts.push(
        `      responses: { ${op.responses
          .map((r) => `${r.code}: ${r.code === op.success?.code ? op.typeName + "Response" : r.type}`)
          .join("; ")} };`,
      );
      parts.push("    };");
    }
    parts.push("  };");
  }
  parts.push("}");
  parts.push("");

  // Method + path literals
  const methods = uniq(ops.map((o) => o.method.toUpperCase())).sort();
  const pathsList = [...byPath.keys()].sort();
  const endpoints = ops.map((o) => `${o.method.toUpperCase()} ${o.path}`).sort();

  parts.push("// ---------------------------------------------------------------------------");
  parts.push("// HTTP method + path literals (from the OpenAPI export, sorted)");
  parts.push("// ---------------------------------------------------------------------------");
  parts.push("");
  parts.push(`export type MeshApiMethod = ${methods.map(q).join(" | ")};`);
  parts.push("");
  parts.push("export type MeshApiPath =");
  parts.push(pathsList.map((p) => `  | ${q(p)}`).join("\n") + ";");
  parts.push("");
  parts.push("export type MeshApiEndpoint =");
  parts.push(endpoints.map((e) => `  | ${q(e)}`).join("\n") + ";");
  parts.push("");
  parts.push(`export const MESH_API_PATHS = [${pathsList.map(q).join(", ")}] as const;`);
  parts.push("");
  parts.push(`export const MESH_API_ENDPOINTS = [${endpoints.map(q).join(", ")}] as const;`);
  parts.push("");

  return parts.join("\n");
}

function emitSseEvents(vocab: SseVocabulary, spec: Json, specSha: string, specMtime: string): string {
  const has = (name: string) => vocab.names.includes(name);
  const lines: string[] = [];
  lines.push(
    headerComment(
      [
        " *",
        ` * Chat SSE event-name vocabulary derived from: ${vocab.source}`,
        ` * Discovered names: ${vocab.names.join(", ")}${vocab.doneSentinel ? `; terminal sentinel ${vocab.doneSentinel}` : ""}${vocab.pingComment ? `; keepalive comment ": ${vocab.pingComment}"` : ""}.`,
        " * Event data shapes are the §13.7 wire format (normative) — see types.ts for the",
        " * §13-derived payload types; guards live in validators.ts.",
      ],
      spec,
      specSha,
      specMtime,
    ),
  );
  lines.push("");
  lines.push('import type { ErrorEnvelope, ModelLifecycleState } from "./types";');
  lines.push("");
  lines.push("/** Named SSE events on the API-CHAT-01 stream (§13.7): meta first, stats last");
  lines.push(" *  (before [DONE]), error terminal (no [DONE] follows). */");
  lines.push(`export const MESH_SSE_EVENT_NAMES = ${JSON.stringify(vocab.names)} as const;`);
  lines.push("");
  lines.push("export type MeshSseEventName = (typeof MESH_SSE_EVENT_NAMES)[number];");
  if (vocab.doneSentinel) {
    lines.push("");
    lines.push("/** Literal data frame that terminates a successful stream (§13.7). */");
    lines.push(`export const CHAT_DONE_SENTINEL = ${q(vocab.doneSentinel)} as const;`);
    lines.push("export type ChatDoneData = typeof CHAT_DONE_SENTINEL;");
  }
  if (has("mesh.meta")) {
    lines.push("");
    lines.push("/** mesh.meta data (§13.7, first event): routing facts, Metadata only.");
    lines.push(" *  routing is the M8 additive field (§16.6/§13.10) — may be absent. */");
    lines.push("export interface ChatMeta {");
    lines.push("  request_id: string;");
    lines.push("  model: string;");
    lines.push("  backend: string;");
    lines.push("  queued_ms: number;");
    lines.push("  model_state: ModelLifecycleState;");
    lines.push("  routing?: Record<string, unknown>;");
    lines.push("}");
    lines.push("");
    lines.push("export interface ChatMetaEvent {");
    lines.push(`  event: ${q("mesh.meta")};`);
    lines.push("  data: ChatMeta;");
    lines.push("}");
  }
  lines.push("");
  lines.push("/** One unnamed (default) SSE event: an OpenAI chat.completion.chunk (§13.7).");
  lines.push(" *  delta carries at most one of role/content per chunk in practice; finish_reason");
  lines.push(" *  is null until the terminal chunk. (ChatChunk-equivalent.) */");
  lines.push("export interface ChatCompletionChunkChoice {");
  lines.push("  index: number;");
  lines.push("  delta: { role?: string; content?: string };");
  lines.push("  finish_reason: string | null;");
  lines.push("}");
  lines.push("");
  lines.push("export interface ChatCompletionChunk {");
  lines.push('  id: string;');
  lines.push('  object: "chat.completion.chunk";');
  lines.push("  created: number;");
  lines.push("  model: string;");
  lines.push("  choices: ChatCompletionChunkChoice[];");
  lines.push("}");
  lines.push("");
  lines.push('/** Unnamed SSE frame. The parse layer MUST normalize "no event: line" to null. */');
  lines.push("export interface ChatChunkEvent {");
  lines.push("  event: null;");
  lines.push("  data: ChatCompletionChunk;");
  lines.push("}");
  if (has("mesh.stats")) {
    lines.push("");
    lines.push("/** mesh.stats data (§13.7, last named event before [DONE]): per-request stats");
    lines.push(" *  (FR-STAT-02 shape). finish_reason is null when the stream was interrupted. */");
    lines.push("export interface ChatStats {");
    lines.push("  ttft_ms: number;");
    lines.push("  tokens_out: number;");
    lines.push("  tokens_per_sec: number;");
    lines.push("  duration_ms: number;");
    lines.push("  finish_reason: string | null;");
    lines.push('  token_count_source: "backend" | "estimated";');
    lines.push("}");
    lines.push("");
    lines.push("export interface ChatStatsEvent {");
    lines.push(`  event: ${q("mesh.stats")};`);
    lines.push("  data: ChatStats;");
    lines.push("}");
  }
  if (has("mesh.error")) {
    lines.push("");
    lines.push("/** mesh.error is terminal (§13.7): no [DONE] follows. Payload = §13.4 envelope. */");
    lines.push("export interface ChatErrorEvent {");
    lines.push(`  event: ${q("mesh.error")};`);
    lines.push("  data: ErrorEnvelope;");
    lines.push("}");
  }
  if (vocab.doneSentinel) {
    lines.push("");
    lines.push("/** The [DONE] sentinel frame (§13.7). */");
    lines.push("export interface ChatDoneEvent {");
    lines.push("  event: null;");
    lines.push("  data: ChatDoneData;");
    lines.push("}");
  }
  const members: string[] = [];
  if (has("mesh.meta")) members.push("ChatMetaEvent");
  members.push("ChatChunkEvent");
  if (has("mesh.stats")) members.push("ChatStatsEvent");
  if (has("mesh.error")) members.push("ChatErrorEvent");
  if (vocab.doneSentinel) members.push("ChatDoneEvent");
  lines.push("");
  lines.push("/** Discriminated union for every frame the App must handle on the chat stream");
  lines.push(' *  (§13.7). Keepalive comment lines (": ping") are SSE comments, not events, and');
  lines.push(" *  never appear here. */");
  lines.push("export type ChatSseEvent =");
  lines.push(members.map((m) => `  | ${m}`).join("\n") + ";");
  lines.push("");
  return lines.join("\n");
}

function emitIndex(spec: Json, specSha: string, specMtime: string): string {
  return headerComment([" * Barrel re-exports."], spec, specSha, specMtime) + "\n" + INDEX_SECTION + "\n";
}

function emitValidators(spec: Json, specSha: string, specMtime: string): string {
  return (
    headerComment(
      [
        " *",
        " * Runtime guards for the safety-critical shapes (InfoResponse, pair/auth responses,",
        " * ModelsResponse, HealthResponse, DeviceResponse, chat SSE chunk/event union,",
        " * TaskStatusResponse, §13.4 ErrorEnvelope).",
      ],
      spec,
      specSha,
      specMtime,
    ) +
    "\n" +
    VALIDATORS_SECTION +
    "\n"
  );
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function main(): void {
  const specBytes = readFileSync(SPEC_PATH);
  const specSha = createHash("sha256").update(specBytes).digest("hex");
  const specMtime = statSync(SPEC_PATH).mtime.toISOString();
  const spec = JSON.parse(specBytes.toString("utf8")) as Json;

  const ops = buildOps(spec);
  if (ops.length === 0) {
    throw new Error("mesh-protocol generator: no operations found in the OpenAPI export");
  }
  const vocab = extractSseVocabulary(spec);

  mkdirSync(OUT_DIR, { recursive: true });
  const files: Record<string, string> = {
    "types.ts": emitTypes(spec, ops, specSha, specMtime),
    "validators.ts": emitValidators(spec, specSha, specMtime),
    "sse-events.ts": emitSseEvents(vocab, spec, specSha, specMtime),
    "index.ts": emitIndex(spec, specSha, specMtime),
  };
  for (const [name, content] of Object.entries(files)) {
    writeFileSync(path.join(OUT_DIR, name), content, "utf8");
  }
  const rel = (p: string) => path.relative(REPO_ROOT, p);
  process.stdout.write(
    `mesh-protocol: generated ${Object.keys(files).length} files into ${rel(OUT_DIR)} ` +
      `from ${rel(SPEC_PATH)} (sha256 ${specSha.slice(0, 12)}…, ${ops.length} operations, ` +
      `SSE events: ${vocab.names.join(", ")})\n`,
  );
}

main();
