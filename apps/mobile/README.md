# apps/mobile — LocalMesh AI App (WP-09/10/11-App/12/13-App, M2–M5)

React Native (Expo + expo-router) app + `modules/mesh-core` (Kotlin native
module) per LM-ARCH-001 §11, §14.2, §15.1, §15.3, §16.1, §16.7, §18.3–18.4 and
the Android UI Design Specification.

## Layout (§11.1, verbatim)

```
app/                        # expo-router screens (UI only)
  (tabs)/ machines.tsx chats.tsx settings.tsx
  pair/scan.tsx pair/confirm.tsx
  machine/[agentId].tsx  chat/[conversationId].tsx  doctor.tsx
src/
  domain/                   # PURE TS: entities, use-cases, no RN imports
    entities.ts             # §16.1 Endpoint, §14.2 rows, §11.2 NetState/PermState
    connection/             # SM-CONN reducer (§15.1) + race planner (§16.1) +
      ...                   #   §18.3 reason aggregation, simulated Clock
    sm-stream.ts            # §15.3 one-generation status machine
    tokens.ts               # §16.1 in-memory token, refresh at 80 % of expires_in
  data/
    db/ schema.ts repositories.ts     # §14.2 DDL verbatim + repos over SqliteExecutor
    mesh/ client.ts sse.ts            # typed Mesh API client over mesh-core; §13.7 SSE
  features/ pairing/ machines/ models/ chat/ diagnostics/ settings/
  state/                    # hand-rolled external stores (useSyncExternalStore)
  infra/ meshCore.ts        # typed wrapper of the native module; lazy require; mockable
  ui/ theme.ts components.tsx         # UI-spec §3 colour tokens, one-status-language
modules/mesh-core/          # Expo module — Kotlin: Keystore / PinnedHttp / SseStream /
  ...                       #   Nsd / NetMonitor / Permissions (see its README)
```

Layering is **enforced by tests** (`test/purity.test.ts`), the App-side mirror
of the agent's import-linter: domain is pure; only `data/mesh/client.ts`
touches the native wrapper; SQL lives only in `data/db/`.

## What is machine-verified here (bun test)

`bun test apps/mobile` → **141 tests, 0 failures**. All timing/logic machines
run on a deterministic `SimulatedClock` — the spec's own acceptance criterion
("Simulated-clock race tests", WP-11/12):

- **SM-CONN (§15.1)** — every state + edge of the normative diagram; invariants
  1–4 (single endpoint, PIN_MISMATCH never falls through, no mid-stream
  endpoint switch, state+reason exposed, UI never infers).
- **Race planner (§16.1)** — candidate generation (mdnsFresh → lanKnown →
  lanName → tailnet → manual classification), pruning (permission/cellular/VPN
  + CI-02/09/13 hints), staggered race on the simulated clock (stagger 250 ms,
  tier timeouts 1500/2500/4000, preempt grace 400 ms, overall deadline 8000 ms
  as a ceiling), PIN_MISMATCH aborts globally, learning (lastOkAt promotion,
  learned add/drop 5-failures-≥2-days), backoff 2/5/10/30/60 s ±20 % jitter.
- **Reasons (§18.3)** — rank table 1..10, verbatim CI mapping, precedence.
- **SM-STREAM (§15.3)** — submitting→streaming→complete/interrupted/error/
  cancelled; 401 → refresh once → retry once → AUTH_FAIL; §13.7 idle rule
  (45 s without ANY bytes — 15 s pings keep CI-21 cold loads alive).
- **SSE (§13.7)** — frames, multi-line data, CRLF, pings, [DONE], split chunks.
- **Tokens (§16.1)** — refresh at 80 % of expires_in, single-flight,
  memory-only surface.
- **QR (§17.4/§17.8)** — `localmesh://pair` parse + validation, HTTPS-only ep,
  confirmation always required, SAS formatting.
- **DB (§14.2)** — schema verbatim against REAL SQLite (bun:sqlite): CHECK
  constraints live, FK cascade, repositories round-trip, migration runner on
  `PRAGMA user_version`.
- **Doctor (§18.4)** — ordered ladder with CI keys and timings; shareable
  report with no Content and no secrets (pin truncated to 12 chars, deny-list
  redaction).

## Not verifiable in this sandbox (honest, per governance)

- Expo/RN bundle + screens on a device (deps not installed here; source is
  strict-tsc-clean apart from `expo*`/`react-native` module resolution, which
  resolves on the build machine).
- `modules/mesh-core` Kotlin: Gradle build, JVM unit tests, and the
  instrumented pin-mismatch/NSD tests — needs the Android SDK
  (see `modules/mesh-core/README.md` for commands + fixture generation).
- §18.8 network matrix on real hardware; SQLCipher-at-rest check on device.

## Open decisions carried from M0

Q-02 (app name/package id — provisionally `ai.localmesh.app`), Q-06 (minSdk 29
per §6.4 floor), Q-10 (E2E tool — none wired; Maestro recommended at WP-13-App
time). Q-04 (RN vs native Kotlin) was settled by §11.1: Expo/React Native UI
over a Kotlin native module.
