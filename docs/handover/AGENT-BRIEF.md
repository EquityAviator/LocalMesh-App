# AGENT-BRIEF — LocalMesh AI (contextual engineering handover)

> **Purpose:** hand this file (plus `RUN-BOOK.md` in the same folder) to ANY
> coding agent and have it productive in <10 minutes without guessing.
> Written in contextual-engineering style: role → mission → constraints →
> map → state → commands → traps → definition-of-done.

---

## 1. Role & mission

You are an implementation engineer on **LocalMesh AI** — a privacy-first,
zero-cost, cross-device AI mesh:

- **Agent** (Python 3.12, FastAPI): runs next to local LLM backends
  (LM Studio, Ollama), exposes the Mesh API (`/mesh/v1/*`) over **TLS 1.3
  with SPKI pinning**, discovers via mDNS, optionally joins a Tailnet.
- **App** (Android via Expo/React Native + native Kotlin module
  `mesh-core`): the phone client. Talks to the Agent with pinned TLS,
  mDNS discovery, QR pairing, chat over SSE.
- **Control plane** (optional, Supabase/Postgres): fleet registry.
- **Dashboard** (Next.js, sandbox-only surface): progress + QA panels; NOT
  part of the product contract.

## 2. Governing documents (precedence order)

1. `docs/LocalMesh_AI_Architecture_and_Requirements.md` (**LM-ARCH-001**) —
   the spec. §-references in code/comments point here. It wins on conflict.
2. `AGENTS.md` (repo root) — process governance (branching, commits, gates).
3. `docs/adr/0NN-*.md` — decided exceptions; follow them.
4. `docs/OPEN_QUESTIONS.md` — open decisions; **never guess one silently**,
   add a `QUESTION-1NN` entry instead.

Hard rules (violations = failed DoD):
- Logs and metadata NEVER contain Content (user prompt/model output) — §17.10
  allow-list logging; `scan_content_columns.py` enforces.
- No cleartext config, no dev-mode defaults in committed config — §17.9/SEC-N6
  (`scripts/security/check_dev_default.py`).
- No secrets in the repo — `scan_secrets.py`.
- Architecture layering Agent: `api → core → ports/adapters` (import-linter +
  `agent/tests/unit/test_dependency_rule.py`); App: domain pure, native only
  via `src/data/mesh/client.ts`, SQL only in `src/data/db/`
  (`apps/mobile/test/purity.test.ts`).
- Commit subjects cite spec IDs: `[WP-xx, §-ref, FR-xxx]`.

## 3. Repo map (what lives where)

```
agent/                      Python package (src/localmesh_agent/)
  api/v1/                   FastAPI routers: info, health, models, chat, pair,
                            auth, device, tasks      ← §13 endpoints
  core/                     scheduler, registry, router (model:auto §16.6),
                            agent_loop, tools (ADR-020 sandbox), rag, tasks,
                            control_plane, policy, warm, entities, errors
  adapters/                 backends (lmstudio/ollama/openai_compat/whisper),
                            discovery/mdns, hardware (psutil/nvidia), tailscale,
                            keyring_store, controlplane
  security/                 tls, pairing, manual_pairing, spake2, tokens,
                            crypto, task_crypto, devices, ratelimit
  store/                    SQLite store + migrations (0001_init, 0002_tasks)
  observability/            allow-list logging, redact, metrics (§20.1)
  admin_app.py              loopback admin API (§13.1, ADR-014)
  tests/{unit,integration,contract,security}/
apps/mobile/                THE ANDROID APP (Expo SDK 52, RN 0.77)
  app/                      expo-router screens (UI only): (tabs)/machines,
                            chats, settings; pair/scan+confirm; machine/[agentId];
                            chat/[conversationId]; doctor
  src/domain/               PURE TS: SM-CONN (§15.1), race planner (§16.1),
                            reasons (§18.3), SM-STREAM (§15.3), tokens
  src/data/                 db/ (§14.2 SQLite schema+repos), mesh/ (client, sse)
  src/features/             pairing, machines, models, chat, diagnostics, settings
  src/state/                hand-rolled external stores (useSyncExternalStore)
  src/infra/                meshCore.ts (native wrapper + platform factory),
                            webMeshCore.ts (sandbox web demo transport)
  src/ui/                   theme (UI-spec §3.1 tokens), components
  modules/mesh-core/        NORMATIVE §11.2 contract (src/MeshCore.types.ts) +
                            Kotlin impl: Keystore, PinnedHttp, SseStream, Nsd,
                            NetMonitor, Permissions, PairPayload, B64Url
  test/                     bun tests (149): domain machines, DB, QR, doctor,
                            purity, web transport
packages/mesh-protocol/     GENERATED TS types/validators/SSE events from
  src/                      docs/openapi/mesh-v1.json (ADR-015, byte-deterministic)
control-plane/              §12.2 SQL schema + content scan script
tools/fake-backends/        fake LM Studio (:1234) / Ollama (:11434) / Whisper
docs/                       spec, OPEN_QUESTIONS.md, adr/, openapi/mesh-v1.json,
                            fixtures/ (CAPTURE.md), spikes/WP-02-report.md,
                            handover/ (THIS folder)
scripts/                    release_gate.sh, release_build.sh, security scans,
                            OpenAPI export/drift, bench
.github/workflows/ci.yml    §21.4 stage-ordered CI
src/ (repo root) + public/  sandbox Next.js dashboard + virtual-device bundle
                            (OUT of product contract; see §2 of worklog Task 1)
```

## 4. Verified state (what is DONE and how it is proven)

| Area | State | Proof |
|---|---|---|
| M0–M9 Agent side | complete | release gate 14/14 PASS, `v1.0.0-rc.1` (worklog Tasks 1–23) |
| Fake backends | complete | 27 self-tests; live in sandbox |
| App domain logic | complete | 149 bun tests, purity green |
| mesh-protocol pkg | complete | 17 tests, deterministic regen |
| Kotlin module source | complete | strict contract vs §11.2; **compile = see RUN-BOOK** |
| App ↔ Agent wiring | complete (web) | virtual device panel: live /info, /models, load/unload, SSE chat, doctor |
| Web bundle build | **passing** | `expo export --platform web` (705 modules) |
| APK build | **passing in sandbox** | `gradlew assembleDebug` (see RUN-BOOK §2) |
| Real-scenario sandbox | running | fake backends + real agent + demo bridge; chat SSE verified end-to-end |

Authoritative progress JSON: `src/data/localmesh-status.json` (dashboard reads it).

## 5. Owner residuals (NOT done — do not claim them)

1. **On-device verification**: install the APK, run §18.8 matrix (mDNS,
   pairing, LAN chat, Tailnet, SQLCipher-at-rest), `connectedDebugAndroidTest`
   (pin-mismatch FR-PAIR-03 zero-body, NSD TXT §16.2).
2. **Real fixtures**: run `docs/fixtures/CAPTURE.md` on a PC with real
   LM Studio/Ollama; commit fixtures; contract tests already prefer them.
3. **Release path**: pentest sign-off (docs/security/pentest-checklist.md)
   → tag v1.0.0-rc.1 → `scripts/release_build.sh` → publish.
4. **Decisions**: ADR-017/018 approvals; Q-08 (zeroconf LGPL) ack; Supabase
   control-plane deployment (QUESTION-107).

## 6. Commands (all verified)

```bash
# Agent (from repo root)
cd agent && .venv/bin/python -m pytest tests/unit -q          # unit
cd agent && .venv/bin/python -m pytest tests/integration -q   # integration (fakes)
.venv/bin/python -m localmesh_agent run --dev-insecure-loopback   # sandbox agent
.venv/bin/python -m localmesh_agent doctor

# App tests (bun, from repo root)
bun test apps/mobile && bun test packages/mesh-protocol
cd apps/mobile && bunx tsc --noEmit

# Web virtual device rebuild (after editing apps/mobile source)
cd apps/mobile && CI=1 EXPO_NO_TELEMETRY=1 bunx expo export --platform web --output-dir dist
rm -rf ../public/_expo ../public/assets ../public/virtual-device
mkdir -p ../public/virtual-device
cp -r dist/_expo ../public/_expo && cp -r dist/assets ../public/assets
cp dist/index.html dist/metadata.json ../public/virtual-device/

# Dashboard lint / dev
bun run lint   # from repo root
bun run dev    # port 3000 (auto-started in sandbox)

# Android APK in this sandbox — exact recipe in RUN-BOOK §2
```

## 7. Traps found the hard way (do not rediscover)

1. **Relative-import depth in `app/` screens**: screens one level below
   `app/` need `../../src/...`; screens AT `app/` root need `../src/...`.
   `app/doctor.tsx` shipped wrong and only Metro caught it — TS did not
   (path was never type-checked against the bundler's resolution).
2. **Undeclared deps**: `expo-status-bar` was imported but missing from
   package.json (bundling caught it). After adding any import, re-run
   `expo export` before claiming green.
3. **expo-router peer dep**: `query-string` must be installed explicitly
   (bun does not auto-install peers).
4. **SDK 37 minor-version packages**: modern platform packages are
   `platforms;android-37.0` etc.; AGP < 9 cannot register them, and a
   symlink `platforms/android-37 → android-37.0` is NOT enough (package.xml
   validation). mesh-core therefore falls back to the root project's
   compileSdk (see its build.gradle comment). Runtime semantics unchanged
   (string constants + `SDK_INT` guards).
5. **Kotlin SseStream is the reference** for §13.7 idle semantics: ANY bytes
   (incl. 15 s pings) reset the watchdog — the TS side previously got this
   wrong; do not "simplify" either side into disagreement.
6. **stdlib LoggerAdapter.process clobbers call-site `extra`** (py3.12):
   use the ComponentLogger in `observability/logging.py`.
7. **Bun background jobs get killed** in this sandbox — run long installs in
   foreground or with `(nohup cmd &)` subshell pattern.
8. **`MeshApiClient` enforces https + pin** (SEC-N1, §11.2) — the sandbox web
   demo bypasses this via `WebMeshCore` (logical https base + demo pin echo).
   NEVER wire the web transport into a production path.
9. **Gradle in 4 GB sandbox**: the pinned settings at the bottom of
   `apps/mobile/android/gradle.properties` (1.4 GB heap, in-process Kotlin,
   workers=2) are REQUIRED; owner machines may remove them.
10. **Fixtures are UNVERIFIED_SHAPE-marked by design** until real captures
    land (FIXTURE RULE) — never fabricate "real" backend responses.

## 8. Definition of done (every change)

- [ ] `bun run lint` clean (dashboard/protocol changes)
- [ ] `bun test apps/mobile` + `bun test packages/mesh-protocol` green
- [ ] `cd apps/mobile && bunx tsc --noEmit` clean
- [ ] Python touched? ruff + mypy --strict + relevant pytest green
- [ ] `expo export --platform web` still succeeds (if apps/mobile touched)
- [ ] No Content/secrets/dev-defaults in the diff (three scanners green)
- [ ] Architecture layering tests green (import-linter / purity)
- [ ] Worklog entry appended (`/home/z/my-project/worklog.md`)
- [ ] Commit cites spec IDs; OPEN_QUESTIONS.md updated for anything guessed

## 9. Where the live scenario lives (sandbox)

```
fake_lmstudio :1234   fake_ollama :11434        (tools/fake-backends/*.py)
        └──────────────┬──────────────┘
        real Python Agent :8443 (dev-insecure-loopback; admin :8444)
        └── demo bridge: Next route /api/localmesh/demo/* (same origin)
              └── virtual device: /virtual-device/ (expo web export)
                    └── dashboard panel: "Virtual device" (iframe + status)
```

Reproduce from scratch: RUN-BOOK.md §1.
