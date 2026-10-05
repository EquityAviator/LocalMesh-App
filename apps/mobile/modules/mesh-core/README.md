# modules/mesh-core — Android native module (WP-09, WP-11 App half)

Kotlin implementation of the **normative §11.2 `MeshCore` TypeScript contract**
(LM-ARCH-001, `docs/LocalMesh_AI_Architecture_and_Requirements.md`). Expo
module name: **`MeshCore`**. Package: `ai.localmesh.meshcore`
(minSdk 29 / targetSdk 37 / Java 17).

`index.ts` + `src/MeshCore.types.ts` re-export the contract the JS layer codes
against; the Kotlin module implements exactly that surface. The App's data
layer only ever calls it through `apps/mobile/src/infra/meshCore.ts` (§11.3).

## §11.2 mapping (TS contract → Kotlin implementation)

| §11.2 function / event | Kotlin | Notes |
|---|---|---|
| `createDeviceKey(alias)` | `Keystore.kt` | ECDSA P-256 in AndroidKeyStore; StrongBox attempted, TEE fallback; `hardwareBacked` from `KeyInfo`. **No export path exists** (§17.6). |
| `signWithDeviceKey(alias, dataB64Url)` | `Keystore.kt` | `SHA256withECDSA`, DER signature, base64url-no-pad in/out. |
| `deleteDeviceKey(alias)` | `Keystore.kt` | Key material destroyed, never leaves the TEE. |
| `request(req)` | `PinnedHttp.kt` | Pinned HTTPS JSON. TLS 1.3 only (`ConnectionSpec.RESTRICTED_TLS` + `TLS_1_3`); TrustManager pins leaf **SPKI SHA-256, base64url-no-pad** with constant-time compare (`MessageDigest.isEqual`). Returns `tlsSpkiSha256B64Url` so the JS layer double-checks (defense in depth). |
| `openStream(req)` → `StreamHandle` | `SseStream.kt` | Pinned POST SSE. Multi-line `data:` frames, CRLF, `event:` names, `:`-comments. Idle watchdog **resets on ANY bytes incl. pings** (§13.7: "45 s without ANY bytes ⇒ dead", CI-18/CI-21). `cancel()` closes the socket (Agent cancels upstream on disconnect). |
| `startDiscovery('_localmesh._tcp')` / `stopDiscovery()` | `Nsd.kt` | `NsdManager` + `registerServiceInfoCallback` resolve path (§6.4). TXT parsed per §16.2: `v,aid,n,fp,api,po` (v≠1 ignored); IPv4 addresses only in v1. Service-type variants normalized, everything else → `NSD_ERROR`. |
| events `agentFound` / `agentLost` | `Nsd.kt` | `agentFound {aid,name,fp,api,po,addresses,port}`; `agentLost {aid}`. |
| `getNetworkState()` / event `networkChanged` | `NetMonitor.kt` | `ConnectivityManager.NetworkCallback`: transport wifi/cellular/ethernet/none, `vpnActive` via `TRANSPORT_VPN` (one-VPN slot, §6.3), `metered`. |
| `getLocalNetworkPermission()` / `requestLocalNetworkPermission()` | `Permissions.kt` | Models §6.4 exactly: target < 37 + `INTERNET` ⇒ `not_required`; A17+ checks `ACCESS_LOCAL_NETWORK` runtime state. |
| `isPackageInstalled(pkg)` | `Permissions.kt` | `<queries>`-scoped to `com.tailscale.ipn` (Tailscale hint only, CI-13). |

Dependency decision: **OkHttp** (brought by the Expo/Android ecosystem, not a
new third-party runtime dep) for HTTP/SSE + `org.json` (platform) for JSON.
Rationale: SSE over `HttpURLConnection` requires hand-rolled chunked-decoding
and reconnect handling; OkHttp gives call timeouts, ConnectionSpec control and
battle-tested TLS plumbing. NSD/Keystore/permissions are pure platform APIs.

## Error codes (JS rejection codes, verbatim)

`PIN_REQUIRED`, `PIN_MISMATCH`, `HTTP_REJECTED_CLEARTEXT`, `TLS_HANDSHAKE_FAILED`,
`IDLE_TIMEOUT`, `CANCELLED`, `NSD_ERROR`, `PERMISSION_REQUIRED` are mandated by
the module contract; the module adds `INVALID_REQUEST`, `TIMEOUT`,
`NETWORK_ERROR`, `HTTP_ERROR`, `BODY_TOO_LARGE`, `KEYSTORE_ERROR`,
`KEY_NOT_FOUND`, `UNKNOWN` ([DESIGN], documented here). §17.10 discipline:
no key material, pairing secrets, tokens, or body content ever enters an error
message; full pins never appear (12-char diagnostic prefix maximum).

## Build & test (machine with Android SDK)

```bash
cd apps/mobile
npx expo prebuild -p android          # once, to generate the android/ app shell
cd android
./gradlew :mesh-core:assembleDebug          # compile the module
./gradlew :mesh-core:testDebugUnitTest      # B64UrlTest, QrPayloadTest (JVM)
./gradlew :mesh-core:connectedDebugAndroidTest  # instrumented tests below
```

Instrumented tests (`androidTest/`):

- `PinnedHttpInstrumentedTest` — pin mandatory (fail-closed before any socket),
  malformed pin rejected, cleartext rejected (release AND debug-off-host),
  §17.9 emulator carve-out verified, TLS 1.3-only server handshake,
  **pin-mismatch test**: wrong pin ⇒ `PIN_MISMATCH` and **zero request-body
  bytes reach the wire** (FR-PAIR-03, CI-12). Needs
  `androidTest/assets/agent-cert.pem` + `agent-key.pem` (self-signed EC P-256,
  PKCS#8):
  ```bash
  openssl ecparam -name prime256v1 -genkey -noout -out agent-key.pem
  openssl req -new -x509 -key agent-key.pem -days 3650 \
    -subj "/CN=localmesh-agent" -addext "SAN=IP:127.0.0.1" -out agent-cert.pem
  ```
- `NsdInstrumentedTest` — advertises a fake `_localmesh._tcp.` service with the
  §16.2 TXT keys, asserts `agentFound` parses `aid/fp/api/po/addresses/port`;
  service-type normalization matrix (`localmesh` / `_localmesh._tcp.local.`
  accepted; foreign types → `NSD_ERROR`).

## VERIFICATION STATUS (honest, per repo governance)

Implemented and delivered as **source-complete** in this sandbox. What was
NOT verifiable here and requires a machine with the Android SDK + a device:

- Gradle compilation / lint of the Kotlin sources (no SDK in sandbox).
- The JVM unit tests (`B64UrlTest`, `QrPayloadTest`) — pure JUnit, expected to
  run on any JVM, but not executed in this sandbox.
- The instrumented tests above — require device/emulator (`connectedDebugAndroidTest`).
- Real-network matrix runs (§18.8): mDNS on/isolated LAN, cellular+Tailscale,
  permission-denied A17 device, Wi-Fi→cellular mid-stream, agent restart /
  key-rotation (`PIN_MISMATCH`) — these flip WP-09/11 contract rows from
  "source complete" to "verified" and are **owner actions**.

Everything else in the pipeline (pure-TS domain machines, SSE semantics,
SM-CONN, race planner, repositories) IS machine-verified in this sandbox via
`bun test apps/mobile` (see apps/mobile/README.md).
