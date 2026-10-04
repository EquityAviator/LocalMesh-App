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
