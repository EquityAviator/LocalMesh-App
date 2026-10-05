# Security Policy

Local Mesh AI exists to keep user content on the user's devices. Security
reports are treated as the highest-priority work in this repository.

## Supported versions

| Version | Supported |
| --- | --- |
| 1.0.0-rc.1 (main) | ✅ active development |
| < 1.0.0-rc.1 | ❌ no backports; upgrade |

## Reporting a vulnerability

**Do not open a public issue for security problems.**

1. Preferred: open a **GitHub Security Advisory** (private) on
   `EquityAviator/LocalMesh-App` — *Security → Report a vulnerability*.
2. Include: affected component (`agent/`, `apps/mobile/`,
   `packages/mesh-protocol/`, `control-plane/`), spec section IDs if known
   (e.g. FR-PAIR-03, SEC-N4), reproduction steps, and **redacted** logs.

Never attach real device tokens, pairing secrets, private keys, or
conversation content to a report. The four CI scanners (SEC-N1 cleartext,
SEC-N3 content-columns, SEC-N5 secrets, pip-audit) run on every change; a
report that trips them will still be handled privately.

## What is in scope

- Bypass of Device Token authentication or pairing (§13.5, FR-PAIR-*).
- Cleartext exposure in release builds (SEC-N1), loopback violations (SEC-N2).
- Content leakage into logs, crash reports, or the Control Plane (SEC-N3).
- Keystore / key material handling in `apps/mobile/modules/mesh-core` (SEC-N5).
- TLS/pinning weaknesses in `PinnedHttp` (FR-TRANS-*, TLS 1.3-only, SPKI pin).
- Control Plane storing anything beyond metadata (CON-02, ADR-011).
- Supply-chain issues in pinned dependencies (§17.11, TC-SEC-07).

## What is explicitly out of scope

- The `--dev-insecure-loopback` mode (§17.9): plain-HTTP **loopback-only**
  developer mode, off by default (SEC-N6). Reports must include a proof it is
  reachable beyond `127.0.0.1` to qualify.
- The committed `apps/mobile/android/app/debug.keystore`: standard Android
  debug credential used for local/CI debug builds only; release signing keys
  live outside the repository by design (docs/RELEASE.md).
- Social-engineering of end users, or attacks requiring local malware on the
  user's PC/phone.

## Hardening references

- Security non-negotiables: [AGENTS.md](AGENTS.md) (SEC-N1…N6).
- Threat model & requirements: LM-ARCH-001 §7, §13, §17
  ([docs/LocalMesh_AI_Architecture_and_Requirements.md](docs/LocalMesh_AI_Architecture_and_Requirements.md)).
- Pentest checklist: [docs/security/pentest-checklist.md](docs/security/pentest-checklist.md).
- Release gates: [docs/RELEASE.md](docs/RELEASE.md) +
  `scripts/release_gate.sh`.

## Disclosure timeline

- **48 h** — acknowledgement.
- **7 days** — triage decision and severity estimate.
- Fixes ship on `main` first; coordinated public disclosure after the fix
  lands (or a documented why-not).
