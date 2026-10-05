/**
 * mesh-protocol package tests (bun test).
 *
 * Three layers of assurance:
 *  1. Structure — the generated files pin all 16 path literals, the OpenAPI
 *     schema names, the §13.7 SSE vocabulary and the validator exports.
 *  2. Round-trip — validators accept real fixture objects copied from this
 *     repo's own integration tests / §13 wire examples (Metadata ONLY — never
 *     any Content-like payload text, per the FR-CP-04 / §20 governance), and
 *     reject malformed values on the fields the App must trust.
 *  3. Determinism — running scripts/generate.ts twice produces byte-identical
 *     output, and the committed src/ files match a fresh run (generated-output
 *     drift check, mirroring scripts/check_openapi_drift.py for the spec).
 *
 * Run: bun test packages/mesh-protocol
 */

import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import path from "node:path";

import {
  MESH_API_ENDPOINTS,
  MESH_API_PATHS,
  MESH_SSE_EVENT_NAMES,
  CHAT_DONE_SENTINEL,
  assertAuthChallengeResponse,
  assertAuthTokenResponse,
  assertChatSseEvent,
  assertDeviceResponse,
  assertErrorEnvelope,
  assertHealthResponse,
  assertInfoResponse,
  assertModelsResponse,
  assertPairCompleteResponse,
  assertPairStatusResponse,
  assertTaskStatusResponse,
  isAuthChallengeResponse,
  isAuthTokenResponse,
  isChatCompletionChunk,
  isChatSseEvent,
  isDeviceResponse,
  isErrorEnvelope,
  isHealthResponse,
  isInfoResponse,
  isModelsResponse,
  isPairCompleteResponse,
  isPairStatusResponse,
  isTaskStatusResponse,
  MeshProtocolValidationError,
} from "../src/index";

const PKG_DIR = path.resolve(import.meta.dir, "..");
const REPO_ROOT = path.resolve(PKG_DIR, "..", "..");
const SRC = (name: string) => path.join(PKG_DIR, "src", name);
const read = (name: string) => readFileSync(SRC(name), "utf8");

// ---------------------------------------------------------------------------
// Fixtures — Metadata only. Sources: §13 wire examples and this repo's real
// integration tests (agent/tests/integration/*). No prompts, no completions,
// no secrets (placeholder tokens are obviously fake).
// ---------------------------------------------------------------------------

const AGENT_ID = "ag_0192f0c1-7d4b-7c6e-9a2b-3e5f6a7b8c9d";
const DEVICE_ID = "dv_0192f0c1-1111-7c6e-9a2b-3e5f6a7b8c9d";
const REQUEST_ID = "rq_01J8Z0V5A1D6M9KQ2X7YB4N8WC";
const MESH_MODEL = "lmstudio::qwen3.5-9b";

const INFO_RESPONSE = {
  agent_id: AGENT_ID,
  display_name: "Gaming PC",
  api: { versions: ["v1"], agent_version: "0.1.0" },
  pairing_open: false,
};

const PAIR_COMPLETE_RESPONSE = { status: "awaiting_confirmation" };

const PAIR_STATUS_AWAITING = {
  status: "awaiting_confirmation",
  agent_id: AGENT_ID,
  scopes: ["models:read", "chat"],
  endpoints: { lan: ["192.168.1.100"], tailnet: null },
};

// Approved case mirrors test_pair_status_reports_tailnet_endpoints_block.
const PAIR_STATUS_APPROVED = {
  status: "approved",
  agent_id: AGENT_ID,
  scopes: ["models:read", "chat"],
  endpoints: {
    lan: ["192.168.1.100"],
    tailnet: { dns: "gaming-pc.tail1234.ts.net", ips: ["100.101.102.103"] },
  },
  device_id: DEVICE_ID,
};

const AUTH_CHALLENGE_RESPONSE = {
  challenge_id: "ch_AAAAAAAAAAAAAAAAAAAAAQ",
  nonce: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", // b64url 32B placeholder
  expires_in: 30,
};

const AUTH_TOKEN_RESPONSE = {
  access_token: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", // placeholder — never a real token
  token_type: "Bearer",
  expires_in: 900,
  scopes: ["models:read", "chat"],
};

const MODELS_RESPONSE = {
  agent_id: AGENT_ID,
  generated_at: "2026-10-03T10:00:00Z",
  backends: [
    { id: "lmstudio", kind: "lmstudio", status: "up", caps: { load_unload: true, keep_warm: false } },
  ],
  models: [
    {
      mesh_model_id: MESH_MODEL,
      backend_id: "lmstudio",
      backend_model_id: "qwen3.5-9b",
      display_name: "Qwen3.5 9B",
      state: "unloaded",
      modalities: { input: ["text"], output: ["text"], source: "backend" },
      capabilities: { values: ["chat"], source: "backend" },
      context_length: { value: null, source: "unknown" },
      quantization: { value: null, source: "unknown" },
      parameter_size: { value: null, source: "unknown" },
      size_bytes: null,
      vram_estimate_bytes: null,
      tags: [],
    },
  ],
};

const HEALTH_RESPONSE = {
  status: "ok",
  uptime_s: 12345,
  backends: [{ id: "lmstudio", status: "up" }],
  queue: { active: 1, queued: 0, max_queued: 8 },
};

// §13.2 API-DEV-01 example — best-effort, all hardware fields nullable.
const DEVICE_RESPONSE = {
  agent_id: AGENT_ID,
  display_name: "Gaming PC",
  agent_version: "0.1.0",
  os: { family: "windows", version: null },
  cpu: { model: null, logical_cores: 16 },
  ram: { total_bytes: 34359738368, available_bytes: 12000000000 },
  gpus: [
    { name: null, vram_total_bytes: null, vram_used_bytes: null, utilization_pct: null, temperature_c: null },
  ],
  network: {
    lan_addresses: ["192.168.1.100"],
    tailnet: { state: "running", dns_name: null, ips: ["100.x.y.z"] },
  },
};

const CHAT_META = {
  request_id: REQUEST_ID,
  model: MESH_MODEL,
  backend: "lmstudio",
  queued_ms: 0,
  model_state: "loaded",
};

// §13.7 FIRST chunk — delta carries role only, so the fixture stays Metadata-only.
const CHAT_CHUNK = {
  id: `chatcmpl-${REQUEST_ID}`,
  object: "chat.completion.chunk",
  created: 1760000000,
  model: MESH_MODEL,
  choices: [{ index: 0, delta: { role: "assistant" }, finish_reason: null }],
};

const CHAT_STATS = {
  ttft_ms: 412,
  tokens_out: 128,
  tokens_per_sec: 17.8,
  duration_ms: 7650,
  finish_reason: "stop",
  token_count_source: "backend",
};

const ERROR_ENVELOPE = {
  error: {
    code: "MODEL_NOT_LOADED",
    message: "Model is not loaded on LM Studio.",
    retryable: true,
    request_id: REQUEST_ID,
    details: { hint: "load_model" },
  },
};

const TASK_STATUS_QUEUED = {
  task_id: "tk_0192f0c1-2222-7c6e-9a2b-3e5f6a7b8c9d",
  type: "chat",
  status: "queued",
  progress: 0,
  created_at: 1760000000,
};

// ---------------------------------------------------------------------------
// 1. Structure of the generated artifacts
// ---------------------------------------------------------------------------

const ALL_16_PATHS = [
  "/mesh/v1/auth/challenge",
  "/mesh/v1/auth/token",
  "/mesh/v1/chat/completions",
  "/mesh/v1/device",
  "/mesh/v1/health",
  "/mesh/v1/info",
  "/mesh/v1/models",
  "/mesh/v1/models/load",
  "/mesh/v1/models/unload",
  "/mesh/v1/pair/complete",
  "/mesh/v1/pair/status",
  "/mesh/v1/requests/{request_id}",
  "/mesh/v1/tasks",
  "/mesh/v1/tasks/{task_id}",
  "/mesh/v1/tasks/{task_id}/attachments/{name}",
  "/mesh/v1/tasks/{task_id}/events",
];

const KEY_SCHEMA_NAMES = [
  "AgentApiInfo",
  "AgentInfo", // the MeshInfo-equivalent
  "CpuInfo",
  "DeviceResponse",
  "ErrorEnvelope",
  "GpuEntry",
  "HealthResponse",
  "HTTPValidationError",
  "ModelEntry",
  "ModelsResponse",
  "NetworkInfo",
  "OsInfo",
  "PairStatusResponse",
  "RamInfo",
  "TailnetBlock",
  "TaskStatusResponse",
  "ValidationError",
  "AuthTokenResponse",
];

describe("generated artifacts exist and pin the contract", () => {
  const types = read("types.ts");
  const validators = read("validators.ts");
  const sse = read("sse-events.ts");

  test("all 16 path literals appear in types.ts", () => {
    for (const p of ALL_16_PATHS) {
      expect(types).toContain(`"${p}"`);
    }
  });

  test("method+path endpoint literals cover all 17 operations", () => {
    expect(MESH_API_PATHS).toHaveLength(16);
    expect(MESH_API_ENDPOINTS).toHaveLength(17);
    expect(MESH_API_ENDPOINTS).toContain("GET /mesh/v1/info");
    expect(MESH_API_ENDPOINTS).toContain("POST /mesh/v1/chat/completions");
    expect(MESH_API_ENDPOINTS).toContain("DELETE /mesh/v1/requests/{request_id}");
    expect(MESH_API_ENDPOINTS).toContain("PUT /mesh/v1/tasks/{task_id}/attachments/{name}");
  });

  test("key schema names appear in types.ts", () => {
    for (const name of KEY_SCHEMA_NAMES) {
      expect(types).toContain(`export interface ${name}`);
    }
    expect(types).toContain("export type MeshApiEndpoint");
    expect(types).toContain("export interface Paths");
  });

  test("§13.7 SSE vocabulary + ChatChunk-equivalent live in sse-events.ts", () => {
    expect(MESH_SSE_EVENT_NAMES).toEqual(["mesh.meta", "mesh.stats", "mesh.error"]);
    expect(CHAT_DONE_SENTINEL).toBe("[DONE]");
    expect(sse).toContain("export interface ChatCompletionChunk");
    expect(sse).toContain("chat.completion.chunk");
    expect(sse).toContain("export type ChatSseEvent =");
    expect(sse).toContain("13.7");
  });

  test("validators.ts exports the safety-critical guards", () => {
    const guards = [
      ["isInfoResponse", "assertInfoResponse"],
      ["isPairCompleteResponse", "assertPairCompleteResponse"],
      ["isPairStatusResponse", "assertPairStatusResponse"],
      ["isAuthChallengeResponse", "assertAuthChallengeResponse"],
      ["isAuthTokenResponse", "assertAuthTokenResponse"],
      ["isModelsResponse", "assertModelsResponse"],
      ["isHealthResponse", "assertHealthResponse"],
      ["isDeviceResponse", "assertDeviceResponse"],
      ["isChatCompletionChunk", null], // chunk guard: asserted via assertChatSseEvent
      ["isChatSseEvent", "assertChatSseEvent"],
      ["isTaskStatusResponse", "assertTaskStatusResponse"],
      ["isErrorEnvelope", "assertErrorEnvelope"],
    ] as const;
    for (const [isName, assertName] of guards) {
      expect(validators).toContain(`export function ${isName}`);
      if (assertName) expect(validators).toContain(`export function ${assertName}`);
    }
    expect(validators).toContain("class MeshProtocolValidationError");
  });
});

// ---------------------------------------------------------------------------
// 2. Validator round-trips against real repo shapes
// ---------------------------------------------------------------------------

describe("validators round-trip real Metadata-only fixtures", () => {
  test("InfoResponse (§13.2 API-INFO-01)", () => {
    expect(isInfoResponse(INFO_RESPONSE)).toBe(true);
    expect(assertInfoResponse(INFO_RESPONSE).api.versions).toEqual(["v1"]);
    expect(isInfoResponse({})).toBe(false);
    expect(isInfoResponse({ ...INFO_RESPONSE, pairing_open: "no" })).toBe(false);
    expect(() => assertInfoResponse({ ...INFO_RESPONSE, api: {} })).toThrow(MeshProtocolValidationError);
  });

  test("PairCompleteResponse (§13.2 API-PAIR-01, 202 verbatim)", () => {
    expect(isPairCompleteResponse(PAIR_COMPLETE_RESPONSE)).toBe(true);
    expect(assertPairCompleteResponse(PAIR_COMPLETE_RESPONSE).status).toBe("awaiting_confirmation");
    expect(isPairCompleteResponse({ status: "approved" })).toBe(false);
  });

  test("PairStatusResponse (§13.2 API-PAIR-02, awaiting + approved w/ Tailnet)", () => {
    expect(isPairStatusResponse(PAIR_STATUS_AWAITING)).toBe(true);
    expect(isPairStatusResponse(PAIR_STATUS_APPROVED)).toBe(true);
    expect(assertPairStatusResponse(PAIR_STATUS_APPROVED).device_id).toBe(DEVICE_ID);
    expect(isPairStatusResponse({ ...PAIR_STATUS_AWAITING, status: "claimed" })).toBe(false);
    expect(
      isPairStatusResponse({ ...PAIR_STATUS_APPROVED, endpoints: { lan: "not-an-array", tailnet: null } }),
    ).toBe(false);
  });

  test("AuthChallengeResponse / AuthTokenResponse (§13.2 API-AUTH-01/02)", () => {
    expect(assertAuthChallengeResponse(AUTH_CHALLENGE_RESPONSE).expires_in).toBe(30);
    expect(assertAuthTokenResponse(AUTH_TOKEN_RESPONSE).scopes).toEqual(["models:read", "chat"]);
    expect(isAuthChallengeResponse({ challenge_id: "ch_x", nonce: "n" })).toBe(false);
    expect(isAuthTokenResponse({ ...AUTH_TOKEN_RESPONSE, token_type: "Basic" })).toBe(false);
    // §17.5 M9: pin_backup is additive/optional.
    expect(isAuthTokenResponse({ ...AUTH_TOKEN_RESPONSE, pin_backup: "sha256-..." })).toBe(true);
  });

  test("ModelsResponse (§13.5 Capability Registry envelope)", () => {
    expect(isModelsResponse(MODELS_RESPONSE)).toBe(true);
    expect(assertModelsResponse(MODELS_RESPONSE).models[0]!.mesh_model_id).toBe(MESH_MODEL);
    expect(
      isModelsResponse({
        ...MODELS_RESPONSE,
        models: [{ ...MODELS_RESPONSE.models[0]!, state: "banana" }],
      }),
    ).toBe(false);
    expect(isModelsResponse({ ...MODELS_RESPONSE, backends: [{ id: 1 }] })).toBe(false);
  });

  test("HealthResponse (§13.2 API-HEALTH-01)", () => {
    expect(isHealthResponse(HEALTH_RESPONSE)).toBe(true);
    expect(assertHealthResponse(HEALTH_RESPONSE).queue.max_queued).toBe(8);
    expect(isHealthResponse({ ...HEALTH_RESPONSE, status: "fine" })).toBe(false);
    expect(isHealthResponse({ ...HEALTH_RESPONSE, backends: [{ id: "lmstudio", status: "warm" }] })).toBe(false);
  });

  test("DeviceResponse (§13.2 API-DEV-01, all-nullable hardware blocks)", () => {
    expect(isDeviceResponse(DEVICE_RESPONSE)).toBe(true);
    expect(assertDeviceResponse(DEVICE_RESPONSE).network.tailnet!.state).toBe("running");
    expect(isDeviceResponse({ ...DEVICE_RESPONSE, network: { lan_addresses: [42], tailnet: null } })).toBe(false);
    expect(
      isDeviceResponse({
        ...DEVICE_RESPONSE,
        network: { lan_addresses: [], tailnet: { state: "running", ips: [] } },
      }),
    ).toBe(false);
  });

  test("chat SSE event union (§13.7: meta → chunks → stats → [DONE])", () => {
    expect(isChatSseEvent({ event: "mesh.meta", data: CHAT_META })).toBe(true);
    expect(isChatSseEvent({ event: null, data: CHAT_CHUNK })).toBe(true);
    expect(isChatSseEvent({ event: "mesh.stats", data: CHAT_STATS })).toBe(true);
    expect(isChatSseEvent({ event: "mesh.error", data: ERROR_ENVELOPE })).toBe(true);
    expect(isChatSseEvent({ event: null, data: "[DONE]" })).toBe(true);
    expect(isChatSseEvent({ event: "mesh.noop", data: {} })).toBe(false);
    expect(isChatSseEvent({ event: "mesh.meta", data: { ...CHAT_META, model_state: "banana" } })).toBe(false);
    expect(isChatSseEvent({ event: "mesh.stats", data: { ...CHAT_STATS, token_count_source: "guessed" } })).toBe(
      false,
    );
    // The parse layer normalizes unnamed events to event: null — a raw chunk
    // without the wrapper is still recognized as a chunk (not as an event).
    expect(isChatCompletionChunk(CHAT_CHUNK)).toBe(true);
    expect(() => assertChatSseEvent({ event: "mesh.error", data: { error: {} } })).toThrow(
      MeshProtocolValidationError,
    );
  });

  test("TaskStatusResponse (§13.9 stub shape)", () => {
    expect(isTaskStatusResponse(TASK_STATUS_QUEUED)).toBe(true);
    expect(assertTaskStatusResponse(TASK_STATUS_QUEUED).progress).toBe(0);
    expect(isTaskStatusResponse({ ...TASK_STATUS_QUEUED, progress: "0%" })).toBe(false);
    expect(isTaskStatusResponse({ ...TASK_STATUS_QUEUED, error: { code: "X" } })).toBe(false);
  });

  test("ErrorEnvelope (§13.4, all non-2xx + mesh.error payload)", () => {
    expect(isErrorEnvelope(ERROR_ENVELOPE)).toBe(true);
    expect(assertErrorEnvelope(ERROR_ENVELOPE).error.code).toBe("MODEL_NOT_LOADED");
    expect(isErrorEnvelope({})).toBe(false);
    expect(isErrorEnvelope({ error: { code: "X" } })).toBe(false);
    expect(isErrorEnvelope({ error: { code: "X", message: "m", retryable: "yes" } })).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 3. Determinism: the generator is a pure function of the spec files
// ---------------------------------------------------------------------------

const GENERATED_FILES = ["types.ts", "validators.ts", "sse-events.ts", "index.ts"];

function snapshotGenerated(): Map<string, string> {
  const snap = new Map<string, string>();
  for (const name of GENERATED_FILES) snap.set(name, read(name));
  return snap;
}

function runGenerator(): void {
  const result = Bun.spawnSync(["bun", path.join(PKG_DIR, "scripts", "generate.ts")], {
    cwd: REPO_ROOT,
    stdout: "pipe",
    stderr: "pipe",
  });
  if (result.exitCode !== 0) {
    throw new Error(`generator failed (${result.exitCode}):\n${result.stderr.toString()}`);
  }
}

describe("regeneration is deterministic (ADR-015)", () => {
  test("two consecutive runs produce byte-identical files", () => {
    const committed = snapshotGenerated();
    runGenerator();
    const run1 = snapshotGenerated();
    runGenerator();
    const run2 = snapshotGenerated();
    for (const name of GENERATED_FILES) {
      expect(run1.get(name)).toBe(committed.get(name)); // committed == regenerated (no drift)
      expect(run2.get(name)).toBe(run1.get(name)); // run 2 == run 1 (pure function)
    }
  });

  test("generated header carries the mandated marker + spec provenance", () => {
    const types = read("types.ts");
    expect(types).toContain("GENERATED — do not edit; regenerate via bun run gen:types (mesh-protocol)");
    expect(types).toContain("docs/openapi/mesh-v1.json");
    expect(types).toContain("LM-ARCH-001");
    expect(types).toContain("Spec file sha256: ");
    expect(types).toContain("Generated at (source spec mtime, UTC): ");
  });
});
