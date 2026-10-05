# packages/mesh-protocol

Generated TypeScript types + lightweight runtime validators for the LocalMesh
Mesh API (`/mesh/v1`), regenerated from `docs/openapi/mesh-v1.json` per
LM-ARCH-001 §21.3 and ADR-015. **Nothing in `src/` is hand-written** — the
OpenAPI export is drift-checked by `scripts/check_openapi_drift.py`, and this
package's tests additionally assert that the committed generated output
matches a fresh run (generated-output drift check) and that two consecutive
generations are byte-identical.

## Regenerate

```bash
# from this package directory
bun run gen            # == bun scripts/generate.ts

# from the repo root
bun packages/mesh-protocol/scripts/generate.ts
```

The emitted header says `regenerate via bun run gen:types (mesh-protocol)`;
`gen:types` is the §21.3 script name. This package's own script is `gen`
(above); when the App worktree wires workspaces, alias `gen:types` to it —
the repo-root `package.json` is outside this package's scope.

Regeneration is **deterministic**: the "generated at" stamp is the source
spec's mtime (UTC) and the spec sha256 is pinned, so two runs on the same
inputs produce byte-identical files (asserted by `test/generated.test.ts`,
which also spawns the generator twice via `bun`).

## What's exported (`src/index.ts` barrel)

| Module | Contents |
|---|---|
| `types.ts` | `components.schemas` → interfaces (`AgentInfo`, `DeviceResponse`, `GpuEntry`, `TailnetBlock`, `HTTPValidationError`, …); per-operation `<Op>Request` / `<Op>Response` types; `Paths` map; `MeshApiMethod` / `MeshApiPath` / `MeshApiEndpoint` literals (+ `MESH_API_PATHS`, `MESH_API_ENDPOINTS` consts); the §13.4 `ErrorEnvelope`; §13-normative narrow response shapes (`PairStatusResponse`, `AuthTokenResponse`, `ModelsResponse`, `HealthResponse`, `TaskStatusResponse`, …) — each with its source comment. |
| `validators.ts` | Zero-dependency hand-rolled guards (`isX` / `assertX`, `MeshProtocolValidationError`) for the safety-critical shapes: InfoResponse, PairCompleteResponse / PairStatusResponse, AuthChallengeResponse / AuthTokenResponse, ModelsResponse, HealthResponse, DeviceResponse, the chat SSE chunk/event union, TaskStatusResponse, ErrorEnvelope. |
| `sse-events.ts` | Chat SSE event-name vocabulary (`MESH_SSE_EVENT_NAMES` = `mesh.meta` / `mesh.stats` / `mesh.error`, derived from §13.7 — the OpenAPI chat operation is undocumented), `ChatCompletionChunk` (the ChatChunk-equivalent) and the `ChatSseEvent` discriminated union incl. the `[DONE]` sentinel. |

Usage: `import { AgentInfo, assertHealthResponse, MESH_API_ENDPOINTS, isChatSseEvent } from "@localmesh/mesh-protocol"`.

## Sources, and what is deliberately NOT invented

Order of authority used by the generator:

1. **`docs/openapi/mesh-v1.json`** (drift-checked export) — schema interfaces,
   path/method literals, response status codes, the 422 `HTTPValidationError`
   shape.
2. **LM-ARCH-001 §13** (`docs/LocalMesh_AI_Architecture_and_Requirements.md`,
   normative) — only for shapes the export leaves open. Every such type
   carries an inline source comment (e.g. `PairCompleteResponse` ← §13.2
   verbatim 202 body; SSE names ← §13.7; `ErrorEnvelope` ← §13.4).
3. Anything pinned by **neither** → emitted as `unknown` with a comment.
   Gaps are noted, never guessed.

Known gaps in the current OpenAPI export (honest inventory, each also visible
as a comment on the affected type):

- **No `requestBody` is declared for ANY operation** (the FastAPI handlers
  read the raw request). All `<Op>Request` types are therefore `unknown`;
  the normative bodies live in §13.2 (pair/auth/model-ref), §13.6 (chat
  allow-list) and §13.9 (tasks).
- **No 4xx/5xx responses are declared** — the §13.4 `ErrorEnvelope`
  (`{error: {code, message, retryable?, request_id?, details?}}`) exists only
  in the architecture spec; it is emitted into `types.ts` from §13.4 so the
  App has one import.
- **Most 2xx responses are untyped** (`additionalProperties: true` or no
  schema): the narrow §13 types above cover the safety-critical ones; chat
  (`200` SSE per §13.7, typed in `sse-events.ts`) and the remaining task
  endpoints stay `unknown`.
- **Status-code drift candidates (for the API owner, not fixed here):**
  `POST /models/load|unload` and `POST /tasks` are declared `200` in the
  export but return **202** per §13.2/§13.9 and the Agent implementation;
  `PUT /tasks/{id}/attachments/{name}` is declared `200` while the Agent
  returns **204**. The `Paths.responses` map reproduces the export verbatim;
  the narrow §13 types describe the real bodies.
- **No `securitySchemes`** — Bearer Device Tokens and the `X-Mesh-Request-Id`
  / `X-Mesh-Api-Version` headers (§13.3) are not expressible in the current
  export and are therefore not typed here.
- **Unload response state** (`{"state":"unloaded"}`) follows §13.5's closed
  vocabulary as a mirror of the §13.2 load body — tracked upstream as
  QUESTION-106.
- **Tasks SSE event vocabulary is not §-pinned** (§13.9 says only "SSE"); the
  Agent emits `event: task` frames, but since the spec does not fix them, no
  tasks event union is generated — only the chat (§13.7) vocabulary is.

`PairStatusResponse.device_id` / `endpoints`: §13.2 gates them on
`approved`; the current Agent sends `endpoints` pre-approval too, so the
validator accepts both (additive tolerance, §13.10: the App MUST ignore
unknown fields) while strictly checking ids, tokens, enums and state
machines.

## Validators: why hand-rolled instead of zod

`zod` exists at the repo root, but this package is intentionally
**zero-dependency**: the Expo App data layer can import it without pulling a
validator runtime into the bundle, and the guards stay regenerated with the
types under ADR-015 instead of drifting as a hand-maintained schema file.

## Tests

```bash
bun test packages/mesh-protocol            # 17 tests (structure + fixtures + determinism)
bunx tsc --noEmit -p packages/mesh-protocol/tsconfig.json   # strict typecheck
```

Fixtures in the tests are copied from this repo's real integration tests /
§13 wire examples and are **Metadata-only** — no prompt/completion text, no
secrets (placeholder token strings only), per the §20 / FR-CP-04 governance.
