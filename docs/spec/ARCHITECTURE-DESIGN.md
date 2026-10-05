# LocalMesh AI — Architecture Design Document
**Version:** 1.0  
**Status:** Feasibility-Validated Design  
**Audience:** Coding agents, implementers, reviewers  
**Constraint set:** Zero recurring cost, privacy-first, self-hosted, Android-primary, open-source stack only  

---

## 0. Document Purpose & Contextual Engineering Rules

This document is the **single source of truth** for LocalMesh AI.

### Rules for any coding agent or model using this document
1. Treat every section as authoritative. Do not invent components, endpoints, protocols, or cloud services not listed here.
2. Prefer the **recommended path** over alternatives unless the user explicitly overrides.
3. All inference traffic (prompts, responses, files, images, audio) **must remain on user-owned devices**. No central server may ever see plaintext content.
4. Free-tier / open-source only. No paid cloud services, no commercial VPN subscriptions, no proprietary SDKs that require payment.
5. Android is the primary mobile target. Desktop agent runs on the user’s PC.
6. When implementing, stay inside the phased roadmap. Do not implement Phase N+1 features while building Phase N.
7. If a decision is marked “MVP”, implement the simple version first.
8. Hallucination guard: if a required detail is missing, stop and ask; do not invent.

---

## 1. Project Vision & Positioning

**One-sentence vision**  
LocalMesh AI is a privacy-first personal AI mesh that lets any authorized mobile device securely discover, connect to, and orchestrate local AI services (LLMs, vision, speech, RAG, agents) running on the user’s own computers — over LAN or remotely — without ever sending prompts or model outputs to a third-party cloud.

**What it is not**
- Not another LM Studio / Ollama chat client.
- Not a public multi-tenant AI service.
- Not a system that routes prompts through a central server.

**Differentiation from existing solutions**
| Existing solution              | Limitation                                      | LocalMesh AI response                          |
|--------------------------------|-------------------------------------------------|------------------------------------------------|
| LM Studio Locally + LM Link    | iOS-only mobile client                          | Android-first + Desktop Agent abstraction      |
| LMSA / Maid / Echo / Reins     | Mostly LAN or single-backend                    | Multi-backend + intelligent routing + remote   |
| Open-WebUI / browser clients   | Requires browser + often tunneling              | Native Android UX + automatic path selection   |
| Direct IP + API key            | Manual, insecure for remote, no discovery       | Auto discovery + pairing + E2EE mesh           |

---

## 2. High-Level Architecture

### 2.1 Logical Layers

```
┌─────────────────────────────────────────────────────────────┐
│                    Android Client (Kotlin)                   │
│  Chat UI · Device/Model picker · Streaming · Pairing · Cache │
└──────────────────────────┬──────────────────────────────────┘
                           │  HTTPS / SSE / WebSocket
                           │  (LAN or Tailscale IP)
┌──────────────────────────▼──────────────────────────────────┐
│              Connection & Discovery Layer                    │
│  mDNS · Manual IP · Tailscale (100.x.x.x) · Fallback logic  │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                 Desktop Agent (PC-side)                      │
│  FastAPI (MVP) → later Go/Rust                               │
│  Unified /mesh API · Model registry · Health · Routing       │
└────────┬─────────────────┬─────────────────┬────────────────┘
         │                 │                 │
         ▼                 ▼                 ▼
   LM Studio          Ollama            Other backends
   :1234/v1           :11434/v1         (llama.cpp, Whisper…)
```

### 2.2 Physical Deployment (User-Owned)

- **PC / Workstation**: Desktop Agent + one or more inference engines (LM Studio, Ollama, …).
- **Android phone / tablet**: Native app.
- **Optional lightweight backend** (Supabase free tier or self-hosted PocketBase): only identity, device registry, pairing tokens. **Never** sees prompts.
- **Tailscale**: free Personal plan (user devices unlimited; up to 6 users). Provides the remote encrypted overlay. No public ports are opened.

### 2.3 Data Flow Principles

1. **LAN path** (preferred when available): Phone → direct HTTP/SSE → Desktop Agent → inference engine. No external hop.
2. **Remote path**: Phone → Tailscale WireGuard tunnel → Desktop Agent → inference engine. End-to-end encrypted by WireGuard; Tailscale and any coordination service see only ciphertext / metadata.
3. **Identity path** (orthogonal): Google Sign-In → short-lived ID token → backend verifies → issues local session / device certificate. Used only for “who owns this device”, never for transporting AI traffic.

---

## 3. Requirements

### 3.1 Functional Requirements (FR)

| ID     | Requirement                                                                 | Priority |
|--------|-----------------------------------------------------------------------------|----------|
| FR-01  | Android app can discover Desktop Agent on same LAN via mDNS or manual IP    | Must     |
| FR-02  | Android app can list models exposed by the Desktop Agent                    | Must     |
| FR-03  | Streaming chat (SSE) against OpenAI-compatible `/v1/chat/completions`       | Must     |
| FR-04  | Chat history stored encrypted on device                                     | Must     |
| FR-05  | Secure remote access via Tailscale without port forwarding                  | Must     |
| FR-06  | Device pairing (QR + PAKE) so only authorized phones can connect            | Must     |
| FR-07  | Desktop Agent abstracts multiple backends (LM Studio + Ollama minimum)      | Must     |
| FR-08  | Model capability metadata (modalities, VRAM, context, capabilities)         | Should   |
| FR-09  | Intelligent routing (content + hardware aware)                              | Should   |
| FR-10  | Image / voice / document upload for multimodal backends                     | Could    |
| FR-11  | Agent / tool-calling runtime on PC controlled from phone                    | Could    |
| FR-12  | Multi-device mesh (multiple PCs visible in one app)                         | Should   |

### 3.2 Non-Functional Requirements (NFR)

| ID      | Requirement                                                                 | Priority |
|---------|-----------------------------------------------------------------------------|----------|
| NFR-01  | Zero recurring monetary cost for personal use                               | Must     |
| NFR-02  | No plaintext prompt/response ever leaves user devices                       | Must     |
| NFR-03  | Time-to-first-token < 1 s on LAN for 7B 4-bit model                         | Should   |
| NFR-04  | Graceful degradation when PC offline or overloaded                          | Must     |
| NFR-05  | Android 12+ support, Kotlin + Jetpack Compose                              | Must     |
| NFR-06  | Desktop Agent runnable as background service / systemd / Windows service    | Must     |
| NFR-07  | Cleartext HTTP allowed only on trusted LAN; remote always encrypted         | Must     |
| NFR-08  | All secrets stored in Android Keystore / OS keyring                         | Must     |

### 3.3 Explicit Non-Goals (do not implement)

- Public multi-tenant SaaS with cloud GPU.
- Running large models on the phone itself (except optional tiny offline fallback).
- Replacing Tailscale with a fully custom ICE/TURN mesh in MVP.
- Storing chat history or prompts on any server.
- Supporting iOS as a primary target in the first releases (Android-first).

---

## 4. Component Design

### 4.1 Desktop Agent (Core Abstraction Layer)

**Responsibility**  
Single stable endpoint that the Android app talks to. Hides the concrete inference engines.

**Recommended MVP stack**  
- Language: Python 3.11+  
- Framework: FastAPI  
- ASGI server: Uvicorn  
- Later migration path: Go (single binary, better for long-running service)

**Listening address**  
- `0.0.0.0:8443` (or configurable).  
- On LAN the phone reaches it via `http://<lan-ip>:8443`.  
- On Tailscale the phone reaches it via `http://100.x.x.x:8443`.

**Core endpoints (contract)**

```
GET  /mesh/health
GET  /mesh/models
GET  /mesh/devices/self
POST /mesh/chat                 # streaming SSE or JSON
POST /mesh/tasks                # future generic task (vision, whisper…)
GET  /mesh/metrics
```

**Model registry shape (example)**

```json
{
  "id": "qwen2.5-7b-instruct-q4_k_m",
  "name": "Qwen2.5 7B Instruct",
  "backend": "ollama",
  "modalities": ["text"],
  "capabilities": ["chat", "code", "reasoning"],
  "context_length": 32768,
  "quantization": "q4_k_m",
  "vram_gb_approx": 5.5,
  "status": "loaded" | "available" | "unloaded"
}
```

**Backend adapters**  
- Ollama: `http://127.0.0.1:11434/v1`  
- LM Studio: `http://127.0.0.1:1234/v1`  
- Future: llama.cpp server, vLLM, Whisper HTTP, etc.

The agent polls `/v1/models` (or native equivalents) on a short interval and normalizes the list.

**Health & metrics**  
- GPU name, VRAM used/total, tokens/s (when available), queue depth, temperature (optional).

### 4.2 Android Client

**Stack (mandatory for MVP)**  
- Kotlin  
- Jetpack Compose  
- OkHttp + SSE / WebSocket  
- Room (encrypted with SQLCipher or Jetpack Security) for local history  
- Android Keystore for secrets  
- CameraX / MediaRecorder for later multimodal

**Key screens**
1. Onboarding / Pairing (QR scan or code entry)
2. My AI Machines (device list + online/offline + connection type)
3. Device detail (models, metrics, services)
4. Chat (streaming bubbles, stop generation, model selector)
5. Settings (Tailscale status, cleartext toggle for LAN only, revoke devices)

**Networking policy**
- Try order (strict):  
  1. Direct LAN IP / mDNS hostname  
  2. Tailscale IP (`100.x.x.x`)  
  3. (Future) custom P2P / relay  
- `android:usesCleartextTraffic="true"` **only** for development and trusted LAN; production remote traffic must be over Tailscale (already encrypted).

### 4.3 Identity & Device Registry (Minimal Backend)

**Purpose only**  
- Verify Google Sign-In ID token  
- Store device public keys / pairing records  
- Issue short-lived session tokens or certificates  
- Support device revocation

**Allowed free options**
- Supabase free tier  
- Firebase Auth + Firestore free tier  
- Self-hosted PocketBase / Supabase on a free VPS (optional)

**Never store**  
- Prompts, responses, files, embeddings, chat history.

### 4.4 Inference Engines (User-Controlled)

Supported at MVP:
- LM Studio (OpenAI-compatible server on port 1234)
- Ollama (OpenAI-compatible on port 11434)

Both already expose `/v1/chat/completions` with streaming (SSE). The Desktop Agent simply proxies and normalizes.

---

## 5. Connection Architecture & Path Selection

### 5.1 Discovery

| Method          | When used                  | Implementation notes                          |
|-----------------|----------------------------|-----------------------------------------------|
| mDNS / Bonjour  | Same LAN                   | Advertise `_localmesh._tcp.local` or reuse existing |
| Manual IP:port  | Fallback / first setup     | Always available                              |
| Tailscale IP    | Remote or when LAN fails   | Stable 100.x.x.x address                      |

### 5.2 Recommended Remote Solution: Tailscale

**Why Tailscale is the chosen remote path**
- Free Personal plan: unlimited user devices, up to 6 users (more than enough for personal/family).
- WireGuard encryption, peer-to-peer preferred, DERP relay only as fallback.
- No public ports opened on the home router.
- LM Studio’s own LM Link uses the same technology (tsnet), proving the approach is production-viable.
- Zero configuration for the end user beyond installing the Tailscale client and logging in with the same account.

**How the app uses it**
1. User installs Tailscale on PC and phone and logs into the same account.
2. Desktop Agent binds to `0.0.0.0:8443`.
3. Android app, when LAN discovery fails, reads the PC’s Tailscale IP (can be stored after pairing or looked up via Tailscale status) and connects to `http://100.x.x.x:8443`.

**Important constraint**  
Do **not** rely on LM Studio’s proprietary LM Link network for the Android client. LocalMesh AI builds its own mesh using the public Tailscale free tier so the Desktop Agent remains backend-agnostic.

### 5.3 Connection State Machine (Android)

```
IDLE
  → try_mDNS / try_manual_IP
      → SUCCESS → CONNECTED_LAN
      → FAIL → try_Tailscale_IP
          → SUCCESS → CONNECTED_REMOTE
          → FAIL → DISCONNECTED (show offline UI + retry)
```

Keep-alive / health check every 15–30 s while the chat screen is open.

### 5.4 Explicitly Rejected for MVP
- Public port forwarding / ngrok / Cloudflare Tunnel (privacy violation or TLS termination at third party).
- Full custom WebRTC ICE/TURN stack (complexity + TURN hosting cost).
- SSH reverse tunnels (manual, brittle).

---

## 6. Security Design

### 6.1 Threat Model (Summary)
- Honest-but-curious network (Wi-Fi or Internet).
- Malicious apps on the same device (mitigated by Android sandbox + Keystore).
- Compromised phone or PC (inherent; mitigate by revocation).
- Relay / Tailscale coordination servers must never see plaintext.

### 6.2 Layered Security

| Layer                | Mechanism                                      | Notes |
|----------------------|------------------------------------------------|-------|
| Transport (remote)   | WireGuard (Tailscale)                          | E2EE by default |
| Transport (LAN)      | Optional TLS or plain HTTP on trusted network  | Cleartext allowed only on LAN |
| Application          | Optional AES-GCM on top of transport (future)  | Defense in depth |
| Authentication       | Google Sign-In (identity only) + device keys   | OAuth Authorization Code flow |
| Pairing              | QR code + SPAKE2+ (or simple one-time code)    | Prevents casual joining |
| Authorization        | Device ACL on registry + local API key on agent| Revocable |
| Secrets storage      | Android Keystore / OS keyring                  | Never plaintext in SharedPreferences |

### 6.3 Pairing Flow (MVP → Target)

**MVP (simple)**  
1. Desktop Agent generates a short-lived pairing token / QR containing: `device_id`, `public_key`, `lan_endpoint`, `pairing_token`.  
2. Phone scans QR, sends token + its own public key to the registry.  
3. Registry binds the two devices under the same user.  
4. Subsequent connections use the stored public keys or a derived shared secret.

**Target (stronger)**  
Replace the simple token with SPAKE2+ (augmented PAKE). Only the phone holds the password; the agent stores a verifier. Resistant to offline dictionary attacks if the registry is compromised.

### 6.4 Encryption Guarantees
- Tailscale guarantees end-to-end encryption between phone and PC.
- Desktop Agent never logs request bodies.
- Chat history is encrypted at rest on the phone.
- Registry stores only device metadata and public keys.

### 6.5 Revocation
User can revoke a device from a settings screen or web UI. The registry marks the device as revoked; the Desktop Agent rejects connections from revoked device IDs / keys.

---

## 7. Model Orchestration & Optimization

### 7.1 Capability Registry
Populated by Desktop Agent from each backend’s `/v1/models` + static metadata files. Used by the phone (or later by the agent itself) for routing decisions.

### 7.2 Routing Strategies (Progressive)

1. **Manual** (MVP): user picks device + model.
2. **Content-based**: simple keyword / modality detection (image → vision model, code keywords → stronger model).
3. **Hardware-aware**: prefer device with free VRAM / lowest queue depth.
4. **Hybrid** (later): small always-loaded classifier model on the agent decides.

### 7.3 Inference Optimizations (PC side)
- Prefer 4-bit / 5-bit GGUF or equivalent quantized models.
- Ollama / LM Studio continuous batching where available.
- `keep_alive` / pre-load frequently used models to avoid cold-start.
- Expose `OLLAMA_NUM_PARALLEL` (or equivalent) so the user can tune concurrency vs VRAM.
- Stream tokens immediately; Android side buffers UI updates every 50–100 ms to avoid jank.

### 7.4 Latency Targets
- LAN, 7–9 B 4-bit model: time-to-first-token < 1 s, sustained > 15 tok/s on mid-range GPU.
- Remote (Tailscale, good connection): add < 100–200 ms RTT; still feel interactive.

---

## 8. API Contracts (Stable for Coding Agents)

### 8.1 Desktop Agent → Inference Engine
Standard OpenAI-compatible:

```
POST /v1/chat/completions
{
  "model": "...",
  "messages": [...],
  "stream": true
}
```

Response: SSE `data: {"choices":[{"delta":{"content":"..."}}]}`

### 8.2 Android → Desktop Agent (Mesh API)

```
GET /mesh/models
→ 200 [{id, name, backend, modalities, ...}]

POST /mesh/chat
Content-Type: application/json
{
  "model": "qwen2.5-7b-instruct-q4_k_m",
  "messages": [...],
  "stream": true
}
→ SSE stream (same shape as OpenAI) or non-stream JSON
```

All other endpoints follow the same style. Version the API under `/mesh/v1/` if breaking changes become necessary later.

---

## 9. Phased Roadmap (Strict Order)

| Phase | Goal                                      | Key Deliverables                                      | Est. Effort |
|-------|-------------------------------------------|-------------------------------------------------------|-------------|
| 1     | LAN Chat MVP                              | Android chat + manual IP + streaming against one backend | 2–3 PM     |
| 2     | Desktop Agent + Discovery                 | FastAPI agent, model list, mDNS, health               | 1–2 PM     |
| 3     | Secure Remote                             | Tailscale integration, automatic path selection       | 1–2 PM     |
| 4     | Pairing & Identity                        | QR pairing, Google Sign-In, device registry, revocation | 1–2 PM   |
| 5     | Multi-backend + Metrics                   | Ollama + LM Studio adapters, GPU/VRAM display         | 1 PM       |
| 6     | Multimodal + Routing                      | Image/voice upload, simple content-based router       | 2 PM       |
| 7     | Agent Runtime (optional)                  | Tool calling, local file/browser actions              | 2+ PM      |

**MVP definition** = Phases 1–3 (or 1–4 if pairing is considered essential).

---

## 10. Technology Decisions Summary (Authoritative)

| Concern                  | Decision                                      | Rationale |
|--------------------------|-----------------------------------------------|---------|
| Mobile framework         | Kotlin + Jetpack Compose                      | Native performance, mature Android ecosystem |
| Desktop Agent (MVP)      | Python + FastAPI                              | Fast iteration, excellent AI library support |
| Desktop Agent (prod)     | Go (preferred) or Rust                        | Single binary, low resource, easy distribution |
| Remote connectivity      | Tailscale free Personal plan                  | Proven (used by LM Link), zero cost, E2EE, no ports |
| Local discovery          | mDNS + manual IP                              | Zero-config on home networks |
| Identity                 | Google Sign-In (identity only)                | Free, familiar, no prompt exposure |
| Pairing                  | QR + short-lived token → later SPAKE2+        | Usable UX + strong crypto path |
| Streaming                | SSE (Server-Sent Events)                      | Matches OpenAI / Ollama / LM Studio native style |
| Chat storage             | Room + encryption on device                   | Privacy, offline history |
| Inference backends       | LM Studio + Ollama (OpenAI-compatible)        | Largest user base, already standardized |
| Cleartext HTTP           | Allowed only on LAN / development             | Security hygiene |

---

## 11. Implementation Constraints for Coding Agents

1. **Never** add a cloud LLM provider or send prompts to any external inference service.
2. **Never** store chat content on the identity backend.
3. **Always** prefer the LAN path when the Desktop Agent is reachable on the local subnet.
4. **Always** treat Tailscale as an encrypted overlay; do not add extra application-level encryption on top unless explicitly requested later.
5. Desktop Agent must be able to run without the identity backend (pure LAN mode).
6. All new endpoints must be added under the `/mesh` prefix and documented in this file before implementation.
7. When adding a new backend adapter, keep the external Mesh API unchanged.
8. UI must remain usable offline (cached history, “PC offline” state).

---

## 12. Open Questions (Resolved for MVP)

| Question                              | Decision for MVP                          |
|---------------------------------------|-------------------------------------------|
| Custom P2P vs Tailscale               | Tailscale only                            |
| iOS support                           | Out of scope                              |
| Self-hosted coordinator (Headscale)   | Optional later; start with Tailscale cloud free tier |
| Full Noise Protocol / mTLS            | Later hardening; start with Tailscale + pairing tokens |
| Multi-user team features              | Personal / family only (≤ 6 users)        |

---

## 13. Success Metrics

- User can chat with a local model from Android on the same Wi-Fi with zero configuration beyond installing the Desktop Agent.
- User can leave home and continue the same conversation over Tailscale with no port-forwarding and no public exposure.
- No prompt or response is ever visible to Tailscale, Google, or any LocalMesh backend.
- Adding a second backend (e.g. Ollama alongside LM Studio) requires zero changes to the Android app.

---

## 14. Appendix — Reference Implementations & Prior Art

- LM Studio LM Link + Locally (iOS): proves Tailscale/tsnet approach for remote model access.
- Ollama & LM Studio OpenAI-compatible `/v1` endpoints: canonical streaming contract.
- SPAKE2+ (RFC 9383) and python-spake2: pairing cryptography path.
- Existing Android clients (LMSA, Maid, Echo, LMSMOB): confirm demand and common pain points (manual IP, limited remote, single backend).

---

**End of Architecture Design Document**

This document is intentionally self-contained. Any implementation must remain inside the boundaries defined above. When in doubt, re-read Sections 0, 3.3 (Non-Goals), 10 (Technology Decisions), and 11 (Implementation Constraints).
