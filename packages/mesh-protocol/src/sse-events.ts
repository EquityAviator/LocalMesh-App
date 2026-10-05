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
 * Chat SSE event-name vocabulary derived from: LM-ARCH-001 §13.7 (docs/LocalMesh_AI_Architecture_and_Requirements.md) — the OpenAPI chat operation is undocumented
 * Discovered names: mesh.meta, mesh.stats, mesh.error; terminal sentinel [DONE]; keepalive comment ": ping".
 * Event data shapes are the §13.7 wire format (normative) — see types.ts for the
 * §13-derived payload types; guards live in validators.ts.
 */


import type { ErrorEnvelope, ModelLifecycleState } from "./types";

/** Named SSE events on the API-CHAT-01 stream (§13.7): meta first, stats last
 *  (before [DONE]), error terminal (no [DONE] follows). */
export const MESH_SSE_EVENT_NAMES = ["mesh.meta","mesh.stats","mesh.error"] as const;

export type MeshSseEventName = (typeof MESH_SSE_EVENT_NAMES)[number];

/** Literal data frame that terminates a successful stream (§13.7). */
export const CHAT_DONE_SENTINEL = "[DONE]" as const;
export type ChatDoneData = typeof CHAT_DONE_SENTINEL;

/** mesh.meta data (§13.7, first event): routing facts, Metadata only.
 *  routing is the M8 additive field (§16.6/§13.10) — may be absent. */
export interface ChatMeta {
  request_id: string;
  model: string;
  backend: string;
  queued_ms: number;
  model_state: ModelLifecycleState;
  routing?: Record<string, unknown>;
}

export interface ChatMetaEvent {
  event: "mesh.meta";
  data: ChatMeta;
}

/** One unnamed (default) SSE event: an OpenAI chat.completion.chunk (§13.7).
 *  delta carries at most one of role/content per chunk in practice; finish_reason
 *  is null until the terminal chunk. (ChatChunk-equivalent.) */
export interface ChatCompletionChunkChoice {
  index: number;
  delta: { role?: string; content?: string };
  finish_reason: string | null;
}

export interface ChatCompletionChunk {
  id: string;
  object: "chat.completion.chunk";
  created: number;
  model: string;
  choices: ChatCompletionChunkChoice[];
}

/** Unnamed SSE frame. The parse layer MUST normalize "no event: line" to null. */
export interface ChatChunkEvent {
  event: null;
  data: ChatCompletionChunk;
}

/** mesh.stats data (§13.7, last named event before [DONE]): per-request stats
 *  (FR-STAT-02 shape). finish_reason is null when the stream was interrupted. */
export interface ChatStats {
  ttft_ms: number;
  tokens_out: number;
  tokens_per_sec: number;
  duration_ms: number;
  finish_reason: string | null;
  token_count_source: "backend" | "estimated";
}

export interface ChatStatsEvent {
  event: "mesh.stats";
  data: ChatStats;
}

/** mesh.error is terminal (§13.7): no [DONE] follows. Payload = §13.4 envelope. */
export interface ChatErrorEvent {
  event: "mesh.error";
  data: ErrorEnvelope;
}

/** The [DONE] sentinel frame (§13.7). */
export interface ChatDoneEvent {
  event: null;
  data: ChatDoneData;
}

/** Discriminated union for every frame the App must handle on the chat stream
 *  (§13.7). Keepalive comment lines (": ping") are SSE comments, not events, and
 *  never appear here. */
export type ChatSseEvent =
  | ChatMetaEvent
  | ChatChunkEvent
  | ChatStatsEvent
  | ChatErrorEvent
  | ChatDoneEvent;
