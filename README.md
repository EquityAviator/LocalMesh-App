# Local Mesh AI

**Your AI, your hardware.** Local Mesh AI lets an Android app drive the large
models already running on *your own* PC — LM Studio, Ollama, or any
OpenAI-compatible backend — over your LAN or Tailnet, with an architecture
that is designed so that **your conversation content never leaves your
devices.**

| | |
| --- | --- |
| Status | **v1.0.0-rc.1** — milestones M0–M9 complete, release gate 14/14 PASS |
| License | Apache-2.0 (see [LICENSE](LICENSE); third-party notices in [docs/THIRD-PARTY-NOTICES.md](docs/THIRD-PARTY-NOTICES.md)) |
| Platform | Android app (React Native/Expo + Kotlin `mesh-core`) · Desktop Agent (Python 3.12 + FastAPI) · Control Plane (SQL, metadata-only) |
| CI | Full gate chain defined in [docs/ci/PR-GATE.yml](docs/ci/PR-GATE.yml) — see [restore note](docs/ci/README.md) |
| Governance | Spec-driven: [AGENTS.md](AGENTS.md) → `docs/LocalMesh_AI_Architecture_and_Requirements.md` (**LM-ARCH-001**) + ADRs + open questions |

---

## Why

Typical "local AI" setups still leak: prompts get proxied through cloud
relays, logs capture content, and the phone talks to the PC over unauthenticated
HTTP. Local Mesh AI is a from-scratch, spec-first design where the privacy
properties are **structural**, not aspirational:

- **Backends stay on loopback.** LM Studio / Ollama are never exposed; the
  Agent is the only network-facing process (SEC-N2).
- **Content never touches the cloud.** The optional Control Plane stores
  *metadata only* — a database column that could hold conversation content is
  a CI-blocking failure (SEC-N3, CON-02, ADR-011).
- **Every call is authenticated.** LAN/Tailnet position is never
  authorization; each device holds a revocable Device Token (SEC-N4).
- **Transport is pinned.** TLS 1.3-only with SPKI pinning against the Agent's
  P-256 identity; the identity key lives in the Android Keystore and never
  leaves it (SEC-N5).

## Architecture

```
┌─────────────────────────┐   mDNS discovery (§16.2)   ┌──────────────────────────────┐
│  Android App            │◄──────────────────────────►│  Desktop Agent (Python)      │
│  (React Native + Expo)  │   TLS 1.3 + SPKI pinning   │  FastAPI · Mesh API /mesh/v1 │
│                         │   Device-token auth        │                              │
│  domain layer (TS)      │                            │  ┌────────────────────────┐  │
│  SM-CONN · SM-STREAM    │                            │  │ Backend adapters       │  │
│  mesh-core (Kotlin)     │                            │  │ LM Studio │ Ollama │...│  │
│  Keystore · PinnedHttp  │                            │  └───────────┬────────────┘  │
│  NSD · SSE · NetMonitor │                            │         loopback only        │
└─────────────────────────┘                            └──────────────┬───────────────┘
       │    ▲                                                    │
       │    │ optional remote access (Tier T2)                   ▼
       │    │                                        LM Studio / Ollama / OpenAI-compatible
┌──────┴────┴──────────┐   metadata only, never   (the user's own inference engines)
│  Control Plane (SQL) │◄══ Content
│  registry · revocation│
└──────────────────────┘
```

**Vocabulary** (used consistently across code and docs): *Mesh · Device ·
App · Agent · Backend · Mesh API (`/mesh/v1`) · Content vs Metadata · Pairing
Secret · Device Token · Transport Tier T0–T3 · Capability Registry ·
`mesh_model_id = <backend_id>::<backend_model_id>` · Request vs Task · SAS ·
Connection Manager · Doctor.*

## What works today (M0–M9)

| Milestone | Delivered |
| --- | --- |
| M0 Foundations | Monorepo, tooling, §21.4 CI gate chain (staged — see docs/ci), fake backends |
| M1 Contracts | OpenAPI-first Mesh API (`docs/openapi/mesh-v1.json`), generated TS types/validators (`packages/mesh-protocol`), ADR-015 drift check |
| M2 Backends & registry | LM Studio / Ollama / OpenAI-compatible adapters, Capability Registry, `model:auto` ground truth |
| M3 Pairing & identity | QR pairing with one-time secret, P-256 device identity in Android Keystore, Device Tokens + revocation |
| M4 Transport security | TLS 1.3-only + SPKI pinning (`PinnedHttp`), FR-PAIR-03 zero-body trust binding, loopback enforcement |
| M5 Discovery & chat | mDNS `_localmesh._tcp` (§16.2), SSE chat streaming, §15.1/§15.3 state machines, §16.1 staggered-race connection planner |
| M6 Control Plane | §12.2 schema, agent heartbeat/register/revocation-mirror (ADR-019) — metadata only |
| M7 Multimodal & Tasks | Vision/audio parts, Whisper adapter, local RAG, durable Tasks API (AES-GCM at rest, 1 h retention, ADR-011) |
| M8 Routing & runtime | `model:auto` rule engine (§16.6) with explainability, tool calling behind ADR-020 default-deny sandbox |
| M9 Hardening & release | Release gate (14 checks), wheel/sdist/SHA256SUMS, TC-SEC-07 artifact scan, v1.0.0-rc.1 (ADR-021 closed the Go/Rust gate) |

**Still open before 1.0 final:** on-device pentest sign-off (§18.8 real
network matrix), owner Android-environment test runs, ADR-017/018 approvals,
PR #1 CI restore — tracked in [docs/OPEN_QUESTIONS.md](docs/OPEN_QUESTIONS.md)
and [docs/RELEASE.md](docs/RELEASE.md).

## Repository layout

```
agent/                    Desktop Agent — Python 3.12, FastAPI, Mesh API /mesh/v1
  src/localmesh_agent/    core · adapters · api · security · store · observability
  tests/                  unit → contract → integration → security (§21.5 layers)
apps/mobile/              Android app (Expo / React Native, TypeScript)
  src/                    domain layer: SM-CONN, SM-STREAM, planner, §18.3 reasons
  modules/mesh-core/      Kotlin module: Keystore, PinnedHttp (TLS 1.3 + SPKI pin),
                          SseStream, NSD, NetMonitor, Permissions + instrumented tests
  android/                committed prebuild output (ai.localmesh.app, debug builds)
packages/mesh-protocol/   OpenAPI-generated TS types/validators/SSE events (ADR-015)
control-plane/            metadata-only schema + migrations (ADR-011, §12.2)
tools/fake-backends/      stdlib-only fake LM Studio / Ollama / Whisper for tests
docs/                     LM-ARCH-001 spec, ADRs, run-book, release, security, CI
scripts/                  pytest layers, OpenAPI drift, security scanners, release gate
src/                      local dashboard (Next.js) used as the development cockpit
```

## Quickstart

### 1. Desktop Agent + fake backends (no GPU needed)

```bash
# Fake LM Studio + Ollama (stdlib Python, no dependencies)
cd tools/fake-backends
python3 fake_lmstudio.py --port 1234 &
python3 fake_ollama.py  --port 11434 &

# Agent — dev loopback mode (§17.9: HTTP on 127.0.0.1 ONLY, off by default, SEC-N6)
cd agent
python3 -m pip install -r requirements.txt          # pinned, hashed (§17.11)
PYTHONPATH=src python3 -m localmesh_agent run --dev-insecure-loopback

curl -s http://127.0.0.1:8443/mesh/v1/health         # → backends up
```

> `--dev-insecure-loopback` is for development only. The default mode is
> TLS 1.3 (§17.3); production deployment is described in
> [docs/RELEASE.md](docs/RELEASE.md) and governed by SEC-N6.

### 2. Android app

```bash
cd apps/mobile
bun install                # or npm install
npx expo start             # dev server; or:
npx expo prebuild --platform android --no-install   # (re)generate android/
cd android && ./gradlew assembleDebug               # JDK 17, Android SDK required
```

The debug APK installs directly (package `ai.localmesh.app`, display name
**Local Mesh AI**). Release signing keys live **outside** the repository by
design ([docs/RELEASE.md](docs/RELEASE.md)).

### 3. Dashboard (development cockpit)

```bash
bun install
bun run dev                # http://localhost:3000 — incl. /virtual-device/ preview
```

## Testing & quality gates

Every PR is expected to keep this chain green (mirrors §21.4 / [docs/ci/PR-GATE.yml](docs/ci/PR-GATE.yml)):

```bash
bash scripts/pytest_layer.sh agent/tests/unit         # unit layer
bash scripts/pytest_layer.sh agent/tests/contract     # contract vs recorded fixtures
bash scripts/pytest_layer.sh tools/fake-backends/tests agent/tests/integration
bash scripts/pytest_layer.sh agent/tests/security     # §17.13 security layer
python scripts/check_openapi_drift.py                 # ADR-015 contract drift
python scripts/security/scan_cleartext_manifest.py    # SEC-N1
python scripts/security/scan_content_columns.py       # SEC-N3 / CON-02
python scripts/security/scan_secrets.py               # SEC-N5
bun test apps/mobile packages/mesh-protocol           # 158 TS domain/protocol tests
```

The mobile domain layer runs on a deterministic simulated clock (§11.3
purity-tested, ≥80 % coverage) — no sleeps, no flakes.

## Contributing

Contributions welcome! Start with [CONTRIBUTING.md](CONTRIBUTING.md) — it
covers environment setup, the spec-driven workflow (LM-ARCH-001 precedence,
ADR process, anti-hallucination rules), commit message conventions (spec-ID
references), and the PR checklist. Good first issues are typically docs,
test coverage, and UI polish; contract changes require a §1.5 change proposal.

## Security

Please report vulnerabilities privately — see
[SECURITY.md](SECURITY.md). Do **not** open public issues for anything that
could expose a device token, pairing secret, or content. The security
non-negotiables (SEC-N1…N6) live in [AGENTS.md](AGENTS.md) and are enforced
by CI.

## License

Apache-2.0 — [LICENSE](LICENSE). The Agent's mDNS dependency
(`python-zeroconf`, LGPL-2.1-or-later) carries redistribution obligations
documented in [docs/THIRD-PARTY-NOTICES.md](docs/THIRD-PARTY-NOTICES.md).

## Acknowledgments

Designed against the LM-ARCH-001 architecture and requirements specification
([docs/LocalMesh_AI_Architecture_and_Requirements.md](docs/LocalMesh_AI_Architecture_and_Requirements.md)),
with the founding feasibility studies preserved under
[docs/research/](docs/research) and the original design documents under
[docs/spec/](docs/spec).
