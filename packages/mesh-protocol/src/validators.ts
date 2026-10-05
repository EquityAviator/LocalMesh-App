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
 * Runtime guards for the safety-critical shapes (InfoResponse, pair/auth responses,
 * ModelsResponse, HealthResponse, DeviceResponse, chat SSE chunk/event union,
 * TaskStatusResponse, §13.4 ErrorEnvelope).
 */

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
 * Guard for one parsed chat SSE event (§13.7): named `mesh.meta` /
 * `mesh.stats` / `mesh.error` events, unnamed OpenAI
 * `chat.completion.chunk` events, and the literal `[DONE]` sentinel.
 * Unnamed events must be normalized to `event: null` by the parse layer.
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

