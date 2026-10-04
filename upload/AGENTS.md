# AGENTS.md — LocalMesh AI (always loaded)

Digest of `docs/LocalMesh_AI_Architecture_and_Requirements.md` (LM-ARCH-001). **If this file and LM-ARCH-001 disagree, LM-ARCH-001 wins.** Load the full document sections named in §22.3 for your work package; do not load the whole document into one task.

## What this project is
LocalMesh AI lets an Android **App** (React Native + Kotlin module `mesh-core`) use models on the user's own PC through a **Desktop Agent** (Python 3.12 + FastAPI). Remote access = Tailscale (Tier T2). The optional cloud **Control Plane** holds Metadata only. No Content ever goes through a cloud component.

## Vocabulary (use exactly)
Mesh · Device · Phone · App · **Agent** (never "server") · **Backend** (LM Studio / Ollama / OpenAI-compatible, loopback only) · Mesh API (`/mesh/v1`) · Control Plane · Content vs Metadata · Pairing / Pairing Secret · Device Token · Transport Tier T0–T3 · Endpoint · Capability Registry · `mesh_model_id` = `<backend_id>::<backend_model_id>` · Request vs Task · SAS · Connection Manager · Doctor.

## Precedence when sources conflict
1. ADRs (§8) → 2. API/DB/state contracts (§13–15) → 3. Requirements (§7) → 4. Component designs/algorithms (§10–12, §16) → 5. Narrative → 6. Your own prior knowledge (lowest).

## Anti-hallucination rules
- Do **not** invent endpoints, fields, flags, CLI options, package names or versions. Unknown = look up in official docs at implementation time, or write `QUESTION-xxx` in `docs/OPEN_QUESTIONS.md` and stop that sub-task.
- Evidence tags: `[VERIFIED]` ok · `[SRC]`, `[ASSUMPTION]`, `[UNVERIFIED]` = confirm with a test before relying.
- Never guess model metadata (context length, quantization, capabilities) from names: emit `null` + `source:"unknown"`.
- Pin exact dependency versions from the registry at M0; never type versions from memory. No new dependency without an ADR.
- Never silently change a contract. Propose a change (§1.5): edit doc → regenerate OpenAPI/types → update tests.
- Stay inside the current milestone's scope (§22.1) and the non-goals (§4.4).

## Security non-negotiables (violation = block the merge)
- **SEC-N1** No cleartext HTTP on non-loopback or in release builds; never `usesCleartextTraffic=true` in release.
- **SEC-N2** Backends reached only via loopback; the Agent is the only network-exposed process.
- **SEC-N3** No Content in logs, crash reports, analytics, or the Control Plane. Log with the allow-list only (§17.10).
- **SEC-N4** LAN/Tailnet position is never authorization; every non-pairing call needs a valid Device Token.
- **SEC-N5** Secrets stay in their store (Keystore / OS keyring / owner-only files); never logged. Only exception: the one-time Pairing Secret in the QR.
- **SEC-N6** No dev/insecure mode on by default; CI fails a release if dev paths are reachable.

## Fixed technical decisions (do not re-litigate)
SSE streaming + `DELETE /requests/{id}` cancel (ADR-004) · pinned self-signed TLS 1.3 (ADR-006) · QR one-time secret + SAS approval (ADR-007) · ECDSA P-256 device key in Android Keystore + opaque 15-min Device Tokens (ADR-008) · inference via OpenAI-compatible `POST /v1/chat/completions` on every Backend; native endpoints for metadata/load/unload only (ADR-009) · stateless Agent, history on Phone only (ADR-011) · loopback-only admin listener (ADR-014) · all binary-in-JSON = **base64url, no padding**.

## Architecture rules
- Agent dependency rule: `api → core → ports`; `adapters → ports/core`; `core` imports no fastapi/httpx/sqlite/psutil (import-linter enforces).
- App: screens never call `mesh-core` directly; only `data/mesh/client.ts` does. `domain/connection` is pure.
- A `PIN_MISMATCH` never auto-retries or falls through to another candidate.
- Content must never move between Agents without explicit user action.

## Method for every task
1. Restate the requirement IDs. 2. List contracts touched. 3. Write tests first or alongside (use recorded real-backend fixtures; they outrank fakes). 4. Implement in a small diff, one WP per branch. 5. Run Appendix G (Definition of Done). 6. Report what you did **and a "Not verified" list**.
Commit style: `feat(agent): SSE chat stream [FR-CHAT-01, API-CHAT-01]`.

## Stop and ask (write a QUESTION-xxx, do not proceed) when
A contract is ambiguous · two sections conflict at the same precedence · a needed external API detail is `[UNVERIFIED]` and cannot be confirmed by a test against a real or recorded backend · a change would weaken a SEC-N rule · the task needs a dependency or ADR not yet approved.

## Known traps (see Appendix C for the full list)
LM Studio has no `/v1/list_models` or `/v1/load_model`; use `GET /api/v1/models`, `POST /api/v1/models/load|unload`, OpenAI `GET /v1/models` · OpenAI-compatible chat is `/v1/chat/completions`, native chat is `/api/v1/chat` · don't build on `/api/v0` · Ollama has no auth · emulator host loopback is `10.0.2.2` (debug only) · Android 17+ local-network permission can block LAN/mDNS · Tailscale free-plan limits are unverified; never hard-code them.
