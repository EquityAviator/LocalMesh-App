# Changelog

All notable changes to the LocalMesh AI Agent are documented here.
Format: Keep a Changelog 1.1; versioning: SemVer (NFR-COMP-02). The Mesh API
(`/mesh/v1`) is stable within a major version (§13.10).

## [1.0.0-rc.1] — 2026-10-04 (M9: Hardening & release)

First release candidate. Exit criteria (§22.1 M9): §17.13 security-test
matrix green on every surface that exists in this environment; all nine
RELEASE.md gates automated in `scripts/release_gate.sh`; build/checksum
pipeline in `scripts/release_build.sh`; CI `release-gate` job active on tags.

### Added
- Release engineering: `scripts/release_gate.sh` (the 9 RELEASE.md gates in
  §21.4 order, `--release` enforces the manual pentest sign-off),
  `scripts/release_build.sh` (PEP 517 wheel+sdist → SHA256SUMS → TC-SEC-07
  artifact scan), `scripts/security/scan_artifacts.py` (scans the BUILT
  bundle with the repo tripwire patterns), `scripts/security/check_dev_default.py`
  (SEC-N6: dev-mode unreachable by default), pentest sign-off template
  (`docs/security/pentest-signoff.md`).
- CI `release-gate` (tags): full gate chain → build → checksums → artifact
  upload; signing remains a documented manual step (key outside the repo).
- Version discipline tests: SemVer validity + pyproject↔`AGENT_VERSION`
  sync (`1.0.0rc1` ↔ `1.0.0-rc.1`).
- ADR-021 — Go/Rust single-binary rewrite: decision gate closed, Python kept
  for v1.0 (re-open criteria recorded).

### Security (§17.13 matrix status at rc.1)
- Automated: TC-SEC-01/03/04/05/06/07/08/09/10 + FR-PAIR-07 (RFC 9383
  vectors) green in the security layer on every run.
- Manual/on-device (owner): TC-SEC-02 pin-mismatch UX on device; the pen-pass
  manual checklist (`docs/security/pentest-checklist.md`).

## [Unreleased milestone history — 0.1.0 line, M0–M8]

Per-milestone summaries; full detail in `worklog.md` (agent handover log)
and the git log (every commit cites its spec IDs).

### M8 — Routing & agent runtime (§16.6, FR-RTE-01..03, FR-AGENT-RT)
- `model:auto` rule engine: verbatim §16.6 scoring (quality/warm/speed/queue
  weights × fit), candidates filtered by state/backend/modality/capability;
  decision + top-5 breakdown exposed in `mesh.meta.routing`.
- Optional classifier hook (off by default, S-21); tool calling via ADR-020
  default-deny sandbox (bounded loop, 4 KB output cap, audit without args).

### M7 — Multimodal & Tasks (§13.6/§13.9, FR-MM-01..04)
- Vision parts (image_url) gated on `vision` capability; audio in chat → 501
  with transcribe hint (S-13); Whisper adapter (`whisper` backend kind).
- Local RAG: chunking + embeddings + cosine top-k; `doc_qa` tasks.
- Durable Tasks API (202 queued → progress → result) with AES-256-GCM
  at-rest input AND result, 1 h retention sweeper, SSE task events.

### M6 — Control Plane (§12, FR-CP-01..04, ADR-019)
- Activation approved in-session (Q-05 gate closed); Supabase REST client,
  heartbeat loop, revocation mirror, §12.2 schema + TC-SEC-08 Content-column
  scan; CP outage never affects chat (§12.3).

### M5 — Multi-backend & metrics (FR-MOD-04/05, §20.1)
- `POST /mesh/v1/models/load|unload` (202/404/501 semantics); KeepWarmScheduler
  (§16.5, Ollama-native pings, device-activity gate); §20.1 metrics registry
  (10 verbatim families) + `GET /admin/metrics` (Prometheus text 0.0.4,
  loopback admin only, ADR-014); nvidia-ml-py swap (ADR-018).

### M4 — Remote (Tailnet) (§11)
- TailnetProbe adapter + fixtures-gated contract tests; `tailscale` backend
  reachability class surfaced in registry/status.

### M3 — Discovery & connection manager (§10.2/§15)
- mDNS advertiser + browser (python-zeroconf), TXT record limited to
  Metadata (§13.2); connection ladder inputs for the doctor (§18.4).

### M2 — Secure LAN MVP (§13/§15/§16/§17)
- Pairing (SPAKE2+ manual-code + QR, §15), ECDSA device identity, Device
  Tokens (hash-only at rest, 15 min TTL), scoped authorization (§17.7),
  TLS 1.3-only listeners, scheduler + chat SSE (§13.7/§16.4), admin API
  (§13.1, loopback + X-Admin-Token, ADR-014).

### M1 — Agent core (loopback) (§10, §14, §16)
- Config (Appendix E, fail-closed), allow-list logging (§17.10), SQLite store
  (§14.1 + migrations + retention), backend adapters (LM Studio / Ollama,
  §6), CapabilityRegistry (§16.3 merge), router, OpenAPI export + drift gate.

### M0 — Foundations (§21)
- Monorepo scaffold (§21.1), import-linter contracts (§10.1), CI pipeline
  (§21.4), dependency spike with registry evidence (§6.5 → WP-02 report),
  hash-pinned lockfile (§17.11), fake LM Studio / Ollama / Whisper backends
  with scenario injection (§21.5), fixture capture procedure (CAPTURE.md).

[1.0.0-rc.1]: https://example.invalid/localmesh/releases/tag/v1.0.0-rc.1
