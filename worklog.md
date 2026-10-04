# LocalMesh AI — Worklog (M0)

Handover document for coding agents working on the LocalMesh AI monorepo
(governing docs: repo-root `AGENTS.md` + `docs/LocalMesh_AI_Architecture_and_Requirements.md`
= LM-ARCH-001; LM-ARCH-001 wins on conflict).

- Repo root: `/home/z/my-project` (git). Branches merged this milestone:
  `wp-01-scaffold` → `wp-02-spike` → `wp-03-fakes` → `main` (all `--no-ff`).
- Note: the Next.js scaffolding pre-existing at the repo root (src/, package.json,
  prisma/, upload/, …) is sandbox infrastructure. It is NOT part of the LocalMesh
  monorepo contract; do not touch it while doing LocalMesh work, and never let
  LocalMesh code import from it.

---

## Task ID: 0 — Environment reconnaissance
Agent: Z.ai Code (main agent; no subagents — see rationale in Task 1)
Task: verify toolchain + whether real Backends are capturable.

Work Log:
- Confirmed Python 3.12.14, uv 0.12.17, pip 25.0.1, curl 8.14.1, git 2.47.3.
- Registry network access OK (pypi.org, registry.npmjs.org).
- LM Studio (1234) / Ollama (11434) NOT present → real fixtures NOT capturable here → CAPTURE.md path (per FIXTURE RULE).

Stage Summary:
- Pinning via uv; fixture fallback documented; sandbox venv for checks at `agent/.venv` (gitignored).

---
Task ID: 1 (WP-01)
Agent: Z.ai Code (main agent)
Task: Repo scaffold, CI, lint, import-linter [NFR-MAINT-01] — branch `wp-01-scaffold`.

Work Log:
- Read governing sections of LM-ARCH-001 (§1, §2.3, §3, §4.4, §5, §6, §8, §10.1, §13.1/13.2/13.10, §17.9/17.10/17.11, §21, §22, Appendix C/F/G).
- Created §21.1 monorepo layout: docs/{spec copy, OPEN_QUESTIONS.md, adr/, openapi/, fixtures/}, agent/ (pyproject, .importlinter, §10.1 src skeleton with docstring stubs), apps/mobile + packages/mesh-protocol + control-plane README placeholders, tools/fake-backends, scripts/, .github/workflows/ci.yml.
- Copy of `AGENTS.md` to repo root (per Appendix A / user instruction).
- `agent/.importlinter`: 3 contracts — layers `api > core > adapters.ports`; core forbidden {fastapi, httpx, sqlite3, psutil}; core forbidden {api, store, adapter implementation subpackages}. Enforced by CI stage AND pytest (`agent/tests/unit/test_dependency_rule.py`).
- `scripts/export_openapi.py` + `scripts/check_openapi_drift.py` (§21.3/NFR-MAINT-01); generated `docs/openapi/mesh-v1.json` with ONLY `GET /mesh/v1/info` (API-INFO-01 schema, §13.2; route serving is M2 — schema-only Pydantic models in `agent/src/localmesh_agent/api/v1/info.py`).
- §21.4 security gates as scripts: `scan_cleartext_manifest.py` (VACUOUS PASS while no Android project; activates automatically; release-vs-debug refinement deferred to WP-09), `scan_content_columns.py` (Content-stem deny-list + allow-marker), `scan_secrets.py` (tripwire heuristics, self-exclusion).
- CI workflow (M0 staging): §21.4 stage order; layers without content yet (contract/security tests, npm audit, Android APK) are announced transparent skips that flip to hard gates when their inputs appear; release job scaffold (full gates at M9).
- Docs: OPEN_QUESTIONS.md template (QUESTION-101+ numbering), `docs/adr/_template.md` (Appendix F), ADR-017 Proposed (setuptools build backend — needed because §21.2 names none; flagged for approval), `docs/fixtures/README.md` (layout + evidence rules), empty-package README stubs.
- 6 commits on `wp-01-scaffold`, merged `--no-ff` to main.
- Decision (documented): monorepo root = git root `/home/z/my-project` (required so `.github/workflows` is where GitHub reads it); pre-existing Next.js files are out-of-contract sandbox artifacts.

Stage Summary:
- Full local gate green: ruff check+format, mypy --strict (14 files, core+security), pytest unit 4/4 (incl. import-linter), lint-imports 3/3 KEPT, OpenAPI drift OK, all 3 security gates pass, workflow YAML validated.

---
Task ID: 2 (WP-02)
Agent: Z.ai Code (main agent)
Task: Dependency & API spike — replace §6.5, pin versions from registry, fixture plan — branch `wp-02-spike`.

Work Log:
- Registry capture (2026-10-04, live HTTP): PyPI JSON API ×18 packages, npm registry ×6 packages; raw JSON archived + committed under `docs/spikes/evidence/` (condensed `wp02-registry-capture-2026-10-04.json` + `raw-2026-10-04/` snapshot).
- GitHub REST API returned HTTP 403 (rate limit) for every repo → repo-activity stats NOT captured (recorded honestly as a limitation; registry publish dates used as maintenance signals).
- README evidence via raw.githubusercontent.com: op-sqlite "SQLCipher is supported as a compilation target"; no Android-16/17 claims found in ANY candidate README (recorded as absence-of-evidence, not invented); expo/fetch present in current SDK docs (8 mentions); react-native-quick-sqlite DEPRECATED per npm; react-native-sqlcipher-storage stale (2019); react-native-sse stale (2024-03).
- Key license finding: `zeroconf` 0.151.5 is LGPL-2.1-or-later (only non-permissive Agent dep) — flagged under CON-03/Q-08.
- pynvml 13.0.1 kept per §21.2; nvidia-ml-py 13.615.71 (newer, NVIDIA) recorded as alternative requiring ADR if adopted.
- Lockfile: `agent/requirements.txt` via `uv pip compile pyproject.toml --all-extras --generate-hashes` (§17.11 "requirements.txt with hashes"); verified by clean-venv install; `pip-audit -r requirements.txt` → "No known vulnerabilities found".
- `docs/spikes/WP-02-report.md` written (replaces §6.5 per §22.1 M0 exit): verdicts adopt/avoid/needs-verification per candidate, every claim URL-cited, "Not verified" list, owner-attention items (ADR-017; zeroconf LGPL).
- `docs/fixtures/CAPTURE.md`: copy-paste capture commands for LM Studio (native + OpenAI lists; streaming chat; token-auth variants) and Ollama (tags/ps/show; streaming + non-stream chat; keep_alive probe answering §6.2 [UNVERIFIED]); per-directory README requirements; checklist of files blocking M1 (WP-05).
- Subagent usage: considered, deliberately NOT used for registry research — R-10 (hallucinated versions) is the top-rated risk; direct registry capture with raw-JSON evidence is verifiable in a way delegated summarization is not.
- 3 commits, merged `--no-ff` to main.

Stage Summary:
- §6.5 replaced with evidence-cited report; all Agent deps pinned with hashes from registry; fixture blocker list for M1 explicit; ADR-017 (Proposed) awaiting owner.

---
Task ID: 3 (WP-03)
Agent: Z.ai Code (main agent)
Task: Fake backends (§21.5) — branch `wp-03-fakes`.

Work Log:
- `tools/fake-backends/fake_core.py`: stdlib-only threaded HTTP server base; scenario injection via `X-Fake-Backend-Scenario` (ok | http-500 | mid-stream-disconnect | slow-first-token | shape-variant-a/b/c) + `X-Fake-Backend-Delay-Ms`; SSE writer ending `data: [DONE]`; abrupt-disconnect path (no [DONE], socket close); UNVERIFIED_SHAPE marking (header + `_localmesh_fake` JSON object + SSE comment) and RECORDED_FIXTURE mode (fixture files served verbatim — mechanism tested with synthetic fixtures).
- `fake_lmstudio.py`: §6.1 endpoints only (GET /api/v1/models, POST /api/v1/models/load|unload, GET /v1/models, POST /v1/chat/completions stream/non-stream); auth `--auth none|token` (§6.1); demand-load cold-load simulation (`--cold-load-ms`, then model "loaded"); Appendix C traps 404 by design and asserted by tests (/v1/list_models, /v1/load_model, /api/v0/*, /api/v1/chat).
- `fake_ollama.py`: §6.2 endpoints (GET /api/tags, GET /api/ps, POST /api/show, POST /v1/chat/completions stream/non-stream, POST /api/chat NDJSON for keep-warm); NO auth by construction (§6.2); keep_alive ignored on /v1 ([UNVERIFIED] §6.2); /api/generate absent (documented).
- 27 self-tests (pytest + httpx, ephemeral loopback ports): SSE+[DONE] both fakes; disconnect w/o [DONE]; cold-load timing (cold ≥0.3s → warm <0.3s); 500s; shape variants a/b/c; token-auth (401 paths + authorized 200); fixture-override verbatim; traps absent.
- README.md rewritten (behaviour matrix, endpoint lists, UNVERIFIED_SHAPE rule, fixture mode, "fake CLI is test-tool surface, not contract").
- ruff clean (repo config); 2 commits, merged `--no-ff` to main.

Stage Summary:
- 27/27 fake-backend tests pass; fakes satisfy every §21.5 bullet; fixture-override mechanism ready for real captures (WP-05 contract tests will run against fixtures, fakes remain fallback).

---
Task ID: 4 — M0 integration verification & governance
Agent: Z.ai Code (main agent)
Task: merged-main gate run, DoD, handover.

Work Log:
- Ran the full §21.4-equivalent gate on merged `main`: lint+format PASS; mypy --strict PASS; unit 4/4; contract layer = announced skip (fixtures pending); integration layer 27/27; import-linter 3/3 KEPT; OpenAPI drift OK; cleartext scan VACUOUS PASS; content-columns scan OK; secret scan OK (1266 files); pip-audit on committed lockfile → no known vulnerabilities.
- Logged QUESTION-101 (ports-layer interpretation of the §10.1 rule; conservative interpretation adopted; not blocking).
- Appendix G DoD filled per WP (see final report in session).
- Wrote this worklog.

Stage Summary:
- M0 exit criteria status: CI-equivalent gate green locally (actual GitHub Actions run pending push — noted as Not verified); WP-02 report exists and replaces §6.5; fixtures = CAPTURE.md path with explicit M1 blocker list (permitted alternative in exit criteria); fake backends pass their own tests.

## Unresolved issues / risks / next-phase priorities
1. **Owner actions needed:** (a) run `docs/fixtures/CAPTURE.md` on a real PC and commit fixtures (blocks WP-05 contract tests); (b) approve/reject ADR-017 (setuptools); (c) confirm QUESTION-101 interpretation; (d) awareness: zeroconf is LGPL-2.1-or-later (CON-03/Q-08).
2. **Not verified (must not be assumed):** GitHub Actions actually executing (repo not pushed); repo-activity stats for candidates (API 403); Android 16/17 runtime behaviour of react-native-zeroconf / op-sqlite (M2/M3 device spikes); real Backend response shapes (fixtures pending).
3. **Next milestone (M1) entry point:** WP-04 (config, allow-list logging, store + 0001_init.sql migration) → WP-05 (adapters + registry; needs fixtures) → WP-06 (scheduler, chat SSE, cancel, /health, CLI run). Re-read §22.3 context bundles before each WP.

---
Task ID: 5 (WP-04)
Agent: Z.ai Code (main agent)
Task: M1 WP-04 — Agent config, allow-list logging, store + migrations — branch `wp-04-agent-base`.

Work Log:
- Loaded §1/§2.3/§3 + WP-04 context (Appendix E, §14.1, §17.10, §20.2) per §22.3.
- `config.py`: pydantic-settings Settings mirroring Appendix E verbatim; unknown keys rejected (extra=forbid); loopback-only backend base_url (NFR-SEC-03/SEC-N2/§10.3); pairing TTL ≤ 600 (FR-PAIR-02); per-OS default data dir [DESIGN]; `LOCALMESH_CONFIG` resolution; owner-only data dir (§14.1).
- `observability/logging.py`: §17.10 allow-list verbatim (16 keys) as JSON formatter; ComponentLogger that MERGES extras (stdlib LoggerAdapter.process on 3.12 clobbers call-site `extra` — trap found and fixed); deny-by-default.
- `store/sqlite.py` + `0001_init.sql`: §14.1 schema applied verbatim via PRAGMA user_version; WAL; devices/tokens(hash-only)/audit/settings/model_cache repositories; §20.2 closed audit vocabulary; meta keys gated by the §17.10 allow-list (StoreError otherwise); §14.1 retention (90 d / 10 000 rows rolling, token expiry) in `Store.prune`.
- Tests: 33 unit tests (config, allow-list incl. canary drop, store drift guard vs §14.1 columns, retention).
- Fixed stale testDependencyRule test to locate lint-imports in the sandbox venv.

Stage Summary:
- Gate green (ruff/mypy-strict/unit/lint-imports/drift/3 security scans); merged `--no-ff` to main.

---
Task ID: 6 (WP-05)
Agent: Z.ai Code (main agent)
Task: M1 WP-05 — Backend adapters + CapabilityRegistry — branch `wp-05-adapters-registry`.

Work Log:
- Context bundle: §6.1, §6.2, §10.2–10.4, §13.5, §16.3.
- `adapters/ports.py`: §10.2 Protocols verbatim (InferenceBackend/HardwareProbe/DiscoveryAdvertiser/TailnetProbe/Store/Clock) + shared bottom-layer types (QUESTION-101 interpretation: port-signature types live in ports, re-exported by core/entities).
- `core/errors.py`: Appendix D verbatim mapping; "maybe"-retryable rows → conservative False [DESIGN].
- `core/entities.py`: ModelEntry with §13.5 exact `to_api_json` (null + provenance; never guessed); Device; MeshStats; RFC 9562 UUIDv7 (§14.3 ids, no new dep).
- `adapters/backends/openai_compat.py`: generic adapter + §10.3-rule-5 SSE parser (data lines, [DONE], comments, partial UTF-8 across chunks, \r\n); defensive JSON helpers; schema-drift warnings (no Content); timeouts connect 3 s / first-token 120 s / idle 60 s / total 15 min.
- `lmstudio.py`: native `/api/v1/models` parsed to verified `id` only (§6.1 fields UNVERIFIED — no name-guessing), fallback `GET /v1/models`; load/unload POSTs tolerate any 2xx (shape UNVERIFIED, flagged).
- `ollama.py`: tags+ps+show(cached); loaded state from /api/ps; no-auth by construction (never sends Authorization); keep-warm native ping (§6.2 keep_alive-on-/v1 UNVERIFIED).
- `core/registry.py`: §16.3 merge algorithm verbatim (concurrent probe 3 s, down → previous entries state=unknown, user overrides source='user', sort, model_cache snapshot, generated_at); background poll 15 s.
- import-linter caught core→store.sqlite (TYPE_CHECKING import): fixed by typing registry against the `Store` port (ports refined with the two model_cache methods core consumes).
- Tests: 12 SSE-parser units; 7 registry units (never-emits-guessed AC of FR-MOD-02); contract tests as announced skips pending recorded fixtures (docs/fixtures/CAPTURE.md); 10 integration tests vs WP-03 fakes incl. FR-MOD-01 detection AC, 500→BACKEND_UNAVAILABLE, disconnect→BACKEND_PROTOCOL, cancel→CANCELLED.

Stage Summary:
- 59 passed / 2 announced skips; gate green; merged `--no-ff` to main.

---
Task ID: 7 (WP-06)
Agent: Z.ai Code (main agent)
Task: M1 WP-06 — Scheduler + chat SSE + cancel + /models + /health + CLI run — branch `wp-06-scheduler-chat`.

Work Log:
- Context bundle: §10.4, §13.2 (API-CHAT-01), §13.4, §13.7, §13.8, §15.3, §16.4.
- `core/scheduler.py`: §16.4 admission (per-device limit → backend slot → global FIFO queue → QUEUE_FULL+Retry-After est. from recent durations); cancel / cancel_by_device; queued_ms; explicit slot-holding flag (concurrency>1 release bug caught).
- `core/policy.py`: §13.6 allow-list (unknown → 422 + details.unknown_fields), roles, string content v1, 200-message limit, numeric ranges; §13.8 limits.
- `core/router.py`: pinned resolution; split on FIRST '::' (§14.3); MODEL_NOT_FOUND.
- API layer: `errors.py` (§13.4 envelope + Retry-After on QUEUE_FULL), `deps.py` (fail-closed 401 without dev mode, SEC-N4/SEC-N6; dev-loopback principal only with the flag), `v1/models.py` (API-MODEL-01), `v1/health.py` (API-HEALTH-01 incl. queue block), `v1/requests.py` (API-REQ-01: 202 cancelling / 404 unknown-or-finished via status_override [DESIGN — Appendix D gap documented] / 403 other device, ownership checked BEFORE cancelling), `v1/chat.py` (§13.7 wire format: mesh.meta → OpenAI chunks → `: ping` 15 s while queued → mesh.stats → [DONE]; mesh.error terminal without [DONE]; cancel = no further events; resolve+admit BEFORE response start so 404/429 carry envelopes; non-stream returns OpenAI completion + x_mesh.stats).
- `app.py`: factory per §10.5/§10.6 subset (config→logging→migrations→identity ag_+UUIDv7→adapters→registry refresh→polling; X-Mesh-Api-Version/X-Mesh-Request-Id/no-store middleware; 2 MiB body limit → 413; keyring auth_ref lookup, §17.6).
- `cli.py`: `run` refuses to start without `--dev-insecure-loopback` (SEC-N6; §17.9 binds 127.0.0.1 only); pair/devices/revoke/doctor report their milestones (no invented surface).
- Adapter fix: cancel ≤ 1 s also during pre-first-byte (send raced against token; root cause of a 2.5 s stall was asyncio.wait missing return_when=FIRST_COMPLETED).
- Tests: 8 policy + 8 scheduler + 2 router units; 10 chat SSE integration tests (wire format, headers, non-stream, 422/404/413 envelopes, fail-closed 401, cancel ≤ 2 s via REAL uvicorn listener — ASGITransport buffers bodies so it cannot exercise mid-stream cancel); `tests/security/test_canary.py` = TC-SEC-01 (canary prompt → grep data dir + log file + stdout: absent).
- M1 smoke test on loopback: CLI run + fake backend + curl → /models envelope, SSE token stream, /health ok — M1 exit behaviour demonstrated with fakes.

Stage Summary:
- 88 passed / 2 announced skips; full gate green; merged `--no-ff` to main.

---
Task ID: 8 — M1 integration verification & governance
Agent: Z.ai Code (main agent)
Task: M1 gate on merged main, DoD, handover.

Work Log:
- Full local gate on main: ruff check+format PASS; mypy --strict (core+security) PASS; pytest unit/contract/integration/security 88 passed, 2 announced contract skips (fixtures pending owner capture, §10.3 rule 1); import-linter 3/3 KEPT; OpenAPI drift OK; cleartext/content-columns/secret scans PASS.
- Appendix G per WP: WP-04 (FR-AGT-03 tests; no contract divergence; §17.10 allow-list; §14.1 schema verbatim) — done; WP-05 (FR-MOD-01 via fakes, FR-MOD-02 schema test; UNVERIFIED fields left null; contract tests await fixtures) — done with announced skips; WP-06 (FR-CHAT-01/02/04/05 tests incl. canary + cancel ≤ 2 s; SSE format per §13.7; error envelopes per §13.4) — done.
- M1 exit status: "curl on loopback streams tokens" demonstrated against fake Backends (real-Backend verification pending fixture capture + owner-run); contract tests flip to hard gates when recordings land.

Stage Summary:
- M1 (dev-insecure loopback core) implemented and verified within scope fence; real-backend contract coverage remains the standing M2 entry blocker (owner action: docs/fixtures/CAPTURE.md).

---
Task ID: 9 — User-visible dashboard (sandbox surface)
Agent: Z.ai Code (main agent)
Task: LocalMesh progress dashboard on `/` + live status API + browser verification.

Work Log:
- Boundary decision (documented): the Next.js app at the repo root is sandbox surface the user watches; the dashboard reads repo state ONE-WAY (curated snapshot in `src/data/localmesh-status.json` + live stats via fs/git in `/api/localmesh/status`). No LocalMesh Python code imports from the Next.js app — the worklog boundary rule stays intact.
- Dashboard sections: header (LM-ARCH-001 ref, git HEAD badge, refresh), M0–M9 roadmap strip with progress, §22.2 WP table (WP-01..10 with req IDs + commits), §21.4 CI-equivalent gate panel (10 gates incl. announced-skip transparency), §24 open questions/owner actions (QUESTION-101, ADR-017, fixtures blocker, Q-08), live repo stats (LOC/files/tests via fs walk), M2 entry next-steps.
- Styling: zinc/emerald/amber palette (no blue/indigo), responsive mobile→desktop, sticky footer (min-h-screen flex + mt-auto), framer-motion subtle reveals, shadcn components only.
- eslint.config.mjs: flat-config global ignores for the LocalMesh monorepo (agent/.venv was being linted — moved ignores to a standalone {ignores} block; `agent/**` alone does not match dotdirs).
- Verification (agent-browser): desktop 1280px + mobile 390px screenshots; all sections render with live data (hash cb008cc, 3,809 LOC / 52 files, 18 test files); Refresh re-fetches; zero console errors; footer sticks to content bottom on both viewports; dev.log shows clean 200s for `/` and `/api/localmesh/status`.

Stage Summary:
- User-visible progress surface live; `bun run lint` clean; committed 2fa76ae.
