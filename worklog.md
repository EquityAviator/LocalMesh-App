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

---
Task ID: 10 — webDevReview round 1 (WP-07)
Agent: Z.ai Code (cron webDevReview)
Task: 状态判断 + QA + 自选开发重点（WP-07 TLS identity）。

项目状态判断:
- M0/M1 完成且全绿（回归 88 passed / 2 announced skips）；仪表盘正常（console 无错误、200）。当前阶段稳定 → 按规范推进 M2 入口 WP-07（无 fixtures 依赖、可独立测试）。

本轮完成:
- QA: dev server 200s；agent-browser 仪表盘复验（全部 section 渲染、console 干净）；完整回归通过。
- WP-07（分支 wp-07-tls-identity，merge af2d0dc）:
  - `security/tls.py`：ECDSA P-256 自签 X.509（10y [DESIGN §17.3]、SAN=localmesh-agent+配置项、SHA-256 签名）；pin = SHA-256(DER SPKI) base64url 无填充（§17.3 编码规则、Appendix C trap）；`load_or_create_identity`（§10.6 step 3、§17.5 Create）；`renew_identity` 同 key 换证 ⇒ pin 不变 ⇒ 免重配对（§17.5 Renew，拒绝无关 key）；`rotate_identity` 仅显式调用（§17.5 Rotate）；key.pem 0600（§17.6）；损坏/过期/半套文件 → TlsIdentityError 拒绝启动、绝不静默重建（§10.7）。
  - 14 个单元测试（pin 格式/DER 手工对拍、生命周期、权限、腐坏拒绝、过期检测与同 key 续期）。
  - app.py 启动接线（§10.6 step 3），spki_pin 挂 app.state 供 M2 QR `fp` 使用。
  - 发现规范冲突并按流程处理：§10.6 step 7 要求 ready 日志带指纹前缀，但 §17.10 allow-list 无对应键且 NFR-SEC-02 (P0) 优先 → pin 不写日志，登记 QUESTION-102（docs/OPEN_QUESTIONS.md）。
- 仪表盘：WP-07 done（af2d0dc）、M2 in-progress（琥珀脉冲徽章，motion-reduce 友好）、QUESTION-102、gate 面板新增 TLS 行；样式细节：卡片/行 hover 过渡、tabular-nums、按钮 hover 间距过渡与 focus-visible ring、milestone chip hover。agent-browser 桌面截图复验通过。
- Gate 全绿: ruff / mypy --strict / pytest 102 passed + 2 announced skips / import-linter 3/3 / drift OK / 3 security scans。

验证结果:
- merged main: af2d0dc（WP-07）+ f4c885d（dashboard）。lint（Next 侧）clean。

未解决问题/风险，下一阶段建议:
1. WP-08（下一个 WP，M2 主体）：SM-PAIR 配对状态机 + auth challenge/token + admin listener + QR 渲染；context bundle §13.2/§14.1/§15.2/§15.4/§17.3–17.7；WP-07 pin 将作为 QR `fp`。
2. TLS 1.3 uvicorn 公网监听集成（与 WP-08 一起做才有意义——无 token 时公网端点全部 401）。
3. Owner actions 不变：fixtures 采集（阻塞 contract tests）、ADR-017、QUESTION-101/102 确认。
4. cryptography 50.x API 备注：`get_values_for_type` 直接返回原始值；NameAttribute.value 可为 bytes（mypy strict 下需收窄）。

---
Task ID: 11 — webDevReview round 2 (WP-08)
Agent: Z.ai Code (cron webDevReview)
Task: 状态判断 + agent-browser QA + 自选开发重点（WP-08 配对/认证/管理面）。

项目状态判断:
- QA 全绿：Python gate（ruff / ruff format / mypy --strict 14 files / pytest 102 passed + 2 announced skips / import-linter 3/3 KEPT / OpenAPI drift OK / 3 security scans / fake backends 27/27）；agent-browser 仪表盘复验（桌面 1280px + 移动 390px 渲染正常、console 零错误、dev.log 200s）。无 bug → 按稳定阶段推进新需求：M2 主体 WP-08。

本轮完成 (WP-08, commit d74f25f, 分支指针 wp-08-pairing-auth=d74f25f):
- security/crypto.py：LP() 4B-BE 长度成帧、pairing/status proof、SAS 推导（mod 1e6 零填充 6 位）、ECDSA P-256/SHA-256/DER 验签（拒绝非 P-256）、hmac.compare_digest 恒时比较、b64url 无填充编解码（拒绝标准 Base64，Appendix C trap）。
- security/pairing.py：SM-PAIR 状态机（CLOSED/OPEN/CLAIMED/APPROVED/DENIED/EXPIRED/LOCKED, §15.2 verbatim）；QR payload（§17.4 localmesh://pair?v=1&aid&n&fp&pid&sec&ep）；5 次坏 proof → LOCKED + 15min 冷却（§13.8）；TTL 300s（配置 ≤600, FR-PAIR-02）+ 过期墓碑 → 410（FR-PAIR-02 AC）；CLAIMED 120s 超时（FR-PAIR-04）；require_confirmation=false 自动批准；单一活跃会话；secret 仅内存、绝不落盘/日志（§17.6）。
- security/tokens.py：32B CSPRNG → b64url token（43 字符），只存 SHA-256 hash（§14.1/§10.4），TTL 900s；verify 三态区分 TOKEN_EXPIRED（401 可重试）vs AUTH_FAILED（401 统一，吊销删 hash 后不可区分，§17.8）。
- security/devices.py：DeviceService（create dv_+UUIDv7、scopes "models:read chat"）；revoke 风暴 = 删 token hash → set revoked_at（行保留, §14.1）→ Scheduler.cancel_by_device（§10.4/§15.6）→ audit device_revoked；内存 live-revoked 集合供 SSE 每块检查（FR-PAIR-06 ≤5s）。
- security/ratelimit.py：滑动窗口限流器；/info 30/min/IP、/auth/challenge 10/min per IP AND per device_id（§13.8）。
- api/v1/pair.py：API-PAIR-01（202 awaiting_confirmation；409/403/410/429 按 Appendix D）+ API-PAIR-02（approved 时才带 device_id/endpoints, §13.2）。
- api/v1/auth.py：API-AUTH-01（未知 device_id 也返回挑战 — anti-enumeration；挑战单次使用 30s）+ API-AUTH-02（消息 "localmesh-auth-v1\n..."（nonce 为 b64url 字符串, QUESTION-103）；401 统一 AUTH_FAILED；DEVICE_REVOKED 仅在有效签名之后（§13.2）；成功 → touch last_seen + audit auth_ok）。
- api/v1/info.py：API-INFO-01 正式上线（schema-only → 服务；pairing_open 反映"可接受新 claim"）。
- deps.py：Bearer token 认证路径（fail-closed SEC-N4；缺头 AUTH_REQUIRED / 未知 AUTH_FAILED / 过期 TOKEN_EXPIRED）；dev-insecure 路径保留（M1 测试兼容）。
- admin_app.py（ADR-014）：127.0.0.1:8444 HTTP；per-install admin.token（0600, §17.6）；严格 Host 检查（anti DNS-rebinding, TC-SEC-06）；无 CORS；token 仅 Authorization 头 + 恒时比较（拒绝 query string）；路由：POST /admin/pair/open|approve|deny|close、GET /admin/pair/pending（CLAIMED 时回 SAS）、GET /admin/devices（不暴露 DER 公钥）、POST /admin/devices/{id}/revoke（返回 cancelled_requests）、POST /admin/tls/rotate（§17.5 显式轮换）。
- app.py：装配 PairingService/TokenService/DeviceService/ChallengeStore/limiter；include info/pair/auth 路由；advertised_endpoints（QR ep = https://hostname:port [DESIGN, QUESTION-103]，dev 模式 loopback http）。
- chat.py：revoke-during-stream → SSE mesh.error DEVICE_REVOKED（两条路径都覆盖：循环间检查 job.cancel_reason + 上游 abort 抛 CANCELLED 分支, §15.6 best effort）。
- cli.py：run = 单进程双监听（公网 TLS 1.3-only via uvicorn ssl_context_factory + admin HTTP loopback, §10.5/§10.6 step 6）+ 信号处理双服务器优雅退出；pair（打开配对 + 打印 QR + 轮询 pending + 交互式 SAS 确认, --approve/--deny/--no-wait）/ devices / revoke = admin HTTP 客户端（§15.4/§15.6；AdminUnreachable 提示先启动 agent）；doctor 仍 M3。
- 测试 +53：unit 34（crypto 11 / pairing 13 / tokens 7 / ratelimit 3+2；共享 FakeStore/FakeClock 端口替身 tests/unit/fake_store.py）+ integration 19（完整配对→token→/models 流、409/403/410/429、anti-enumeration、单次挑战、吊销 403/401、TC-SEC-04 revoke-kills-stream <5s、admin Host/token 负路径、TLS rotate pin 变化）。
- OpenAPI：export 脚本改为 include 真实路由（9 paths: info/pair×2/auth×2/models/health/chat/requests）；重新生成 mesh-v1.json。
- 端到端冒烟（真实 uvicorn 进程, download/wp08-smoke/wp08_smoke.py）：12/12 — TLS 1.3 协商成功、TLS 1.2 被拒、admin.token 0600、CLI QR、pair/complete 202、admin SAS+approve、pair/status approved、challenge→token→Bearer /models+/health、无 token 401 fail-closed、agent 日志无 sec= 泄漏。
- 仪表盘：WP-08 done (d74f25f)、新增"Pairing/auth E2E smoke"gate 行、pytest 155 passed、QUESTION-103、next steps 更新（WP-11 mDNS 可沙箱实现；WP-09/10 需 Android 构建环境）；修复 route.ts readdirSync 类型错误；agent-browser 桌面+移动复验通过、console 零错误。

验证结果:
- merged main = ffbf7fc（WP-08 d74f25f + dashboard ffbf7fc）。gate 全绿：ruff/format PASS、mypy --strict PASS、pytest 155 passed + 2 announced skips、import-linter 3/3 KEPT、OpenAPI drift OK、3 security scans PASS、fake backends 27/27、真实进程冒烟 12/12。lint（Next 侧）clean。

未解决问题/风险，下一阶段建议:
1. QUESTION-103 已登记（docs/OPEN_QUESTIONS.md）：HMAC 成帧/nonce 编码等 WIRE FORMAT 决定需 owner 确认——若与规范意图不符，修改是局部小 diff（crypto.py + 测试向量）。
2. WP-09/WP-10（mesh-core Kotlin + RN App）需要 Android/Gradle 构建环境，沙箱不可行 → M2 收尾依赖 owner 环境；Agent 侧 M2 已完整。
3. 下一 Agent 侧增量（沙箱可做）：WP-11 mDNS advertise（python-zeroconf 已在 lockfile，LGPL 已标注）；以及把 pairing/auth 的安全测试扩展为 §17.13 TC-SEC-03（重放）/TC-SEC-09（限流）正式条目。
4. Owner actions 不变：fixtures 采集（阻塞 contract tests 硬门）、ADR-017、QUESTION-101/102/103。
5. 注：本沙箱会在会话间把 HEAD 切回 main，WP-08 提交直接落在 main（d74f25f），wp-08-pairing-auth 分支指针已对齐到同一提交以保留引用。

---
Task ID: 12 — webDevReview round 3 (WP-11 + TC-SEC-03/09)
Agent: Z.ai Code (cron webDevReview)
Task: 状态判断 + agent-browser QA + 自选开发重点（WP-11 Agent 侧 mDNS + 正式安全测试条目 + 仪表盘增强）。

项目状态判断:
- QA 全绿：Python gate（ruff/format PASS、mypy --strict PASS、pytest 181 passed + 2 announced skips、import-linter 3/3 KEPT、OpenAPI drift OK、3 security scans PASS）；agent-browser 仪表盘复验（桌面 1280px + 移动 390px、console 零错误、交互功能实测通过）；dev.log 全 200。无 bug → 稳定阶段推进新需求：WP-11（Agent 侧）+ §17.13 正式安全条目。

本轮完成:
- WP-11（commit 5d6812b）：
  - `adapters/discovery/mdns.py`：MdnsAdvertiser（zeroconf.asyncio.AsyncZeroconf，端口协议 DiscoveryAdvertiser 的实现）。§16.2 服务契约逐字：type `_localmesh._tcp.local.`、instance `"<display_name> (<first 6 of agent uuid>)"`、TXT `v=1/aid/n/fp(前16字符 pin 提示)/api=v1/po=0|1`（每个值 ≤255B，`n` 截断保护）；`po` 解释为 API-INFO-01 的 pairing_open 镜像（T-21 提示字段，60s 看门狗同步 [DESIGN]）。
  - 接口选择（FR-AGT-04/CI-24）：`[mdns] interfaces` 非空 → 名称/字面 IP 解析（未知名跳过+告警）；空 → 默认路由接口私网 IPv4（UDP-connect 无包技巧）+ 离线回退全部非虚拟接口 [DESIGN]；虚拟适配器（docker/WSL/Hyper-V/tailscale/VPN…）默认排除；IPv6 不广播（v1）；VPN/公网出口地址一律不广播（宁可不广播也不发错地址）。
  - §16.2 变更重播：60s [DESIGN] 看门狗重解析地址+同步 po，地址/TXT 未变则 no-op；重播复用同一 AsyncZeroconf 实例（避免 socket 抖动）。
  - 降级不阻塞启动（T-21）：地址不可解析 → 记日志不注册；start 异常被 app 吞掉降级。§10.6 step 5 接线 + shutdown 对称停止。
  - QR `ep` 升级：`advertised_endpoints()` 现以解析出的 LAN IPv4 领衔（QUESTION-103 item 5 实现侧完成，hostname 作后备；QUESTION-103 已附实现注记，wire-format 项仍 OPEN）。
  - 19 个单元测试（TXT 契约/实例名/接口选择/桩 zeroconf 生命周期/po 翻转与地址变更重播/看门狗/降级安全）。
- TC-SEC-03/TC-SEC-09 正式条目（commit e3f01fc）：
  - `tests/security/test_tc_sec_03_09.py` 7 条命名测试：proof 重放 403、LOCKED 后合法 proof 仍 429、捕获签名打新挑战 401（nonce 绑定）、挑战单次使用、吊销后 token 重放 401、/info 30/min→429、/auth/challenge 10/min→429（含跨桶隔离验证）。
  - `tests/security/README.md` 改为 TC-SEC 追溯表（delivered vs pending 及原因）。
- 仪表盘（commits 5501bc7 + 67e2123）：
  - 数据：WP-11 done 行、M3 in-progress（琥珀）、mDNS §16.2 gate 行 + §17.13 gate 行、securityTests 区（10 条 TC-SEC 状态）、pytest 数字修正为 183 collected（181+2）、next steps → Doctor v1。
  - 新功能：WP 列表状态过滤 chips（aria-pressed + 计数）、WP 行展开交付注记（aria-expanded + AnimatePresence 高度动画）、HEAD 哈希点击复制（check 反馈 + sr-only status）、"checked Ns ago" 活跃时间戳、§17.13 安全态势面板、route 增加实时 test-function 计数。
  - 样式细节：渐变进度条 + 活跃端琥珀脉冲（motion-safe）、WP 行状态左色条 + 选中高亮、gate 行 hover 显示 §ref chip、统计卡 hover 上浮、开问卡 2 列网格 + BLOCKING 强化边框、next steps 序号 hover 变绿、tabular-nums 全量化。
  - agent-browser 实测：行展开渲染注记、planned 过滤 → 恰好 3 行、桌面+移动截图、console 零错误。

验证结果:
- merged main = 67e2123（WP-11 5d6812b + security e3f01fc + dashboard 5501bc7/67e2123）。gate 全绿：ruff/format PASS、mypy --strict PASS、pytest 183 collected（181 passed + 2 announced skips）、import-linter 3/3 KEPT、OpenAPI drift OK、3 security scans PASS、fake backends 27/27（未回归）。lint（Next 侧）clean。

未解决问题/风险，下一阶段建议:
1. **下一沙箱增量 = Doctor v1**（M3, §18.1）：`localmesh-agent doctor` 按 §18.1 连接阶梯自检（config → 数据目录权限 → TLS/证书/pin 前缀打印 → 端口占用 → Backends loopback 可达 → mDNS 广播可见 → 防火墙 best effort → Tailnet CLI → 时钟），findings 以 CI-ID 为键输出——全部 agent 侧、沙箱可测；WP-11 的 resolve/advertise 函数可直接复用。
2. WP-09/WP-10 + WP-11 App 侧（mesh-core Kotlin、NSD、权限）需 Android/Gradle 环境 → M2/M3 收尾依赖 owner 环境。
3. Owner actions 不变：fixtures 采集（阻塞 contract tests 硬门）、ADR-017、QUESTION-101/102/103（103 的 wire-format 项 1-4 仍 OPEN）。
4. mDNS 实机验证待真实 LAN（沙箱多播环境未验证 [Not verified]）；`po` 语义与 QUESTION-103 一起等 owner 确认。
5. 沙箱注：WP-11 提交落在 main（5d6812b、e3f01fc），wp-11-mdns 分支指针已对齐 e3f01fc。

---
Task ID: 13 — webDevReview round 4 (QA fixes + WP-13 Doctor v1)
Agent: Z.ai Code (cron webDevReview)
Task: 状态判断 + agent-browser QA + 自选开发重点（本轮：QA 修复 + Doctor v1）。

项目状态判断:
- 发现并修复 3 个真实问题：(1) pytest CI 调用方式收集失败（`bash scripts/pytest_layer.sh agent/tests/unit` 从仓库根运行时 `from tests.unit.fake_store import ...` 因 sys.path 缺 agent/ 报 ModuleNotFoundError——此前各轮仅以 `cd agent && python -m pytest` 通过，CI workflow 原样跑会挂）；(2) scripts/export_openapi.py ruff I001 import 排序；(3) **admin token 传输头不符规格**——LM-ARCH-001 §13.1 与 §17.13 T-11 两次明文命名 `X-Admin-Token`，而 WP-08 实现用了 `Authorization: Bearer`（QUESTION-103 item 4 当时的"§17.6 未命名 header"读法漏掉了该证据）。规格优先（§1.1），已对齐实现并回改 QUESTION-103。
- agent-browser QA：桌面 1280 + 移动 390 渲染正常、console/errors 零、过滤 chips/行展开/复制按钮实测通过、/api/localmesh/status 200。修复后无遗留 bug → 推进新需求 WP-13。

本轮完成 (commits 3cf64bc, f1a8873, 8e86f56, d1c7f86 — 均落 main):
- agent/conftest.py：pytest prepend 模式借 conftest 目录把 agent/ 锚进 sys.path，两种调用方式（CI 风格 / python -m）等价；单元层 fixture 仍留在 tests/unit/conftest.py。
- X-Admin-Token 对齐：admin_app 守卫只收 `X-Admin-Token`（恒时比较；Bearer 显式 401 负路径测试）；cli._admin_request、wp08_smoke.py 同步；QUESTION-103 item 4 附证据更正（operator 路由命名仍 OPEN，loopback-only 可改名）。
- Doctor v1（WP-13 Agent 侧, FR-CONN-06, §18.1-18.4）：
  - `doctor.py`：§18.4 十项有序检查（config → data_dir §14.1/tls key 0600 → tls pin 仅打 12 字符前缀 §10.6 → port free/listening/occupied（loopback /info 自识别）→ backends loopback 探测（§6 原生路径 /v1/models、/api/tags）→ backend_bind CI-06/CI-07 LAN 暴露审计（§18.2 Det 列原文）→ mdns（复用 WP-11 接口选择，T-21 hint 语义）→ firewall（ufw/netsh/socketfilterfw best effort）→ tailscale CLI [ASSUMPTION §6.3] → clock（CI-23 单调钟免疫注记）。Finding = {check, level, ci_ids, summary, detail, fix}；探针全部可注入（DoctorProbes），降级为 unknown-info，Agent 未运行也能跑完整个梯子。
  - CLI：`doctor [--config] [--json] [--rotate-tls]`；--rotate-tls 执行 §17.5 显式轮换并提示同时吊销设备/重启；退出码 0/1/2 按 level [DESIGN]。
  - `GET /admin/doctor`（§13.1 spec-named）：doctor_fn 注入 + asyncio.to_thread，admin 层不 import doctor。
  - 测试：28 unit（每个 CI 一条 golden 输出断言 + 梯序 + 无密钥断言：全 pin/admin token 不出现在输出）+ admin doctor endpoint 集成测试；替换过期的 doctor-stub 测试。
- 仪表盘（d1c7f86）：新增 "Connection ladder & doctor (§18.1 · §18.4)" 面板——L0-L10 梯子（渐变连线 + 覆盖率图例 agent/shared/app + emerald 脉冲点）、§18.4 十项检查（序号圆点 + CI chips + 模块路径 hover + delivered 勾）、CLI 命令复制按钮、admin endpoint + 退出码徽章；数据层 WP-13 done 行、M3 详情更新、pytest 212 collected、Doctor/X-Admin-Token 两条新 gate、QUESTION-103 item 4 状态更新、next steps → WP-14/owner actions。

验证结果:
- merged main = d1c7f86（3cf64bc → f1a8873 → 8e86f56 → d1c7f86）。gate 全绿：ruff/format PASS、mypy --strict PASS（14 files）、pytest 210 passed + 2 announced skips、import-linter 3/3 KEPT、OpenAPI drift OK、3 security scans PASS、fake backends 27/27、bun lint clean、agent-browser 桌面+移动+交互复验通过（console 零错误、copy 反馈实测）。

未解决问题/风险，下一阶段建议:
1. QUESTION-103 剩余 OPEN 项：wire-format items 1-2（HMAC 成帧/nonce 编码）+ operator 路由命名——等 owner 确认；若变更均为局部小 diff。
2. WP-09/WP-10 + WP-11 App 侧 + WP-13 App Diagnostics screen 需要 Android/Gradle 环境，沙箱不可行 → M2/M3 收尾依赖 owner 环境。
3. 下一沙箱增量建议 = WP-14 Tailscale 探测适配器（M4, §6.3/§18.6）：doctor 的 CLI 探针可直接升级为正式 TailnetProbe 端口实现（含 [ASSUMPTION] 字段的防御性解析），加 T2 endpoint 发现。
4. Owner actions 不变：fixtures 采集（阻塞 contract tests 硬门）、ADR-017、QUESTION-101/102/103。
5. mDNS/doctor 的 LAN 行为（多播可见性、CI-06/07 LAN 探测、防火墙规则）在真实局域网验证——沙箱多播未验证 [Not verified]。
6. 注：本沙箱会在会话间把 HEAD 切回 main，本轮提交直接落在 main。

---
Task ID: 14 — webDevReview round 5 (WP-14 Tailnet probe, M4)
Agent: Z.ai Code (cron webDevReview)
Task: 状态判断 + agent-browser QA + 自选开发重点（本轮：QA 全绿无 bug → WP-14 Tailscale 探测适配器）。

项目状态判断:
- QA 全绿：dev server 200s；agent-browser 桌面 1280 + 移动 390 渲染正常、console 零错误、过滤 chips（planned=3）/行展开/Refresh 交互实测通过、/api/localmesh/status 200；Python 回归全绿。无 bug → 按上轮建议推进 M4：WP-14（Agent 侧）。

本轮完成 (WP-14, commit a5ae930, 落 main；dashboard 为后续 commit):
- `adapters/tailscale.py`（替换 M0 stub）：
  - `TailscaleCliProbe` 实现 §10.2 `TailnetProbe` 端口：binary 缺失 → None（§10.2 "None if tailscale absent"）；timeout/nonzero exit/OSError/坏 JSON → state="unknown"（区分"缺失"与"在但读不懂"，doctor 语义沿用）；subprocess 走 asyncio.to_thread + §10.5 规定的 2s 超时；binary_resolver 可注入。
  - `parse_tailscale_status_json`：total/防御式（§10.3 rule 2，永不 raise）；字段名按 §6.3 [ASSUMPTION]（BackendState/Self.TailscaleIPs/Self.DNSName）；IP 过滤到 100.64.0.0/10 CGNAT（§6.3 addressing）、IPv6 丢弃（§16.2/CI-25）、去重+上限防垃圾；DNSName 去尾点。
  - `t2_endpoint_candidates`：§16.1 step-4 顺序（MagicDNS 名 → 100.x IP），仅 running 状态产出（§17.4 QR `[&ep=…]`、§18.5 playbook 2 "QR carries Tailnet name/IP if detected"）。
- `security/pairing.py`：PairingService 新增 `tailnet: TailnetInfo | None` + `listen_port` 字段；`status()` 的 `endpoints.tailnet` 从硬编码 null 升级为 §13.2 形状 `{dns, ips}|null`（running 且有可用地址才非 null，绝不填默认值）；QR ep 列表 LAN 在前 + T2 候选在后。
- `app.py`：startup（§10.6 step 7）探测 tailnet → 注入 app.state + pairing，作为 ready 报告的一部分；`tailscale_status` 日志事件仅用 allow-list 键（component/status），DNS/IP 不落日志（QUESTION-102 立场延续）；探测失败降级 None 绝不阻塞启动。
- `doctor.py`：check 9 的默认探针委托共享 parser —— doctor 与在线 Agent 对真实安装的解读保证一致（§18.4/§22.3）；doctor 保留同步 subprocess（需在 Agent 未运行时独立工作）。
- 测试 +29：unit 21（adapter：协议符合性/§10.5 2s 超时常量/assumed shape/防御退化参数化/CGNAT 过滤去重/探测语义/T2 顺序与门控）+ pairing 5（status block 三态 + QR ep 顺序 + 无 tailnet 时 QR 不含 T2）+ doctor 2（默认探针委托共享 parser/absent）+ integration 1（HTTP 全流程 tailnet block）。
- Contract 测试：`tests/contract/test_tailscale_vs_fixtures.py` announced skip（§22.3 "Probe parse tests with recorded tailscale output"；Appendix G：UNVERIFIED → QUESTION-104 登记）。CAPTURE.md 新增 §3 tailscale 采集命令 + checklist 两条。
- QUESTION-104 登记（docs/OPEN_QUESTIONS.md）：tailscale status --json 字段名未对真实安装验证（沙箱无 tailscale binary）；若真实 JSON 有差异 → 局部小 diff（parser + 测试向量），符合 §22.3 stop-and-ask 条件。
- 仪表盘：WP-14 done (a5ae930)、M4 in-progress（3 active）、新增 "Tailnet probe (§6.3 · §18.6)" gate 行、pytest 242 collected、QUESTION-104 卡片、next steps → WP-15 /device、"Delivered this round" 文案更新；agent-browser 桌面+移动+行展开复验通过、console 零错误。

验证结果:
- merged main = <dashboard commit>（WP-14 a5ae930 + dashboard）。gate 全绿：ruff/format PASS、mypy --strict PASS（14 files）、pytest 239 passed + 3 announced skips、import-linter 3/3 KEPT、OpenAPI drift OK、3 security scans PASS、fake backends 27/27、bun lint clean。

未解决问题/风险，下一阶段建议:
1. QUESTION-104（新）：tailscale JSON 字段名 [ASSUMPTION §6.3] 等 owner 采集确认——CAPTURE.md §3；contract test 随 fixtures 落地自动翻硬门。
2. QUESTION-103 剩余 OPEN 项：wire-format items 1-2 + operator 路由命名。
3. WP-09/WP-10/WP-12(App)/WP-13(App) 需 Android/Gradle 环境 → M2-M4 的 App 侧收尾依赖 owner 环境；Agent 侧 M2/M3/M4 已完整。
4. 下一沙箱增量建议 = WP-15（M5, §13.2 API-DEV-01）：HardwareProbe 端口（psutil/pynvml 已 lockfile）+ `/device` 端点——tailnet block 已通过 app.state 预铺好管线（network.tailnet 形状 §13.2 已定），沙箱可完整实现+测试（探针可注入）。
5. Owner actions 不变：fixtures 采集（LM Studio/Ollama/tailscale 三类）、ADR-017、QUESTION-101/102/103/104。
6. tailscale 实机行为（CLI 输出形状、DERP path 字段 CI-16）待真实安装验证 [Not verified]。
7. 注：本沙箱会在会间把 HEAD 切回 main，本轮提交直接落在 main。

---
Task ID: 15 — webDevReview round 6 (WP-15 part 1: HardwareProbe + /device, M5)
Agent: Z.ai Code (cron webDevReview)
Task: 状态判断 + agent-browser QA + 自选开发重点（本轮：QA 全绿无 bug → WP-15 part 1 Agent 侧）。

项目状态判断:
- QA 全绿：dev.log 全 200；Python gate（ruff/format PASS、mypy --strict PASS、pytest 239 passed + 3 skips、import-linter 3/3、drift OK、3 scans、fake backends 27/27）；agent-browser 桌面 1280 + 移动 390 渲染正常、console 零错误、过滤 chips（planned=3）/行展开/Refresh 实测通过。无 bug → 按上轮建议推进 M5：WP-15 part 1（Agent 侧）。

本轮完成 (WP-15 part 1, commit 3576fdf, 落 main；dashboard 为 d7b752a):
- `adapters/hardware/psutil_probe.py`：
  - `PsutilHardwareProbe` 实现 §10.2 `HardwareProbe` 端口：OS family/version（platform，小写映射 §13.2 例 "windows"）、CPU model（platform.processor() + Linux /proc/cpuinfo "model name" 回退——读 OS 上报值而非猜测；全部来源缺失 → None）、logical_cores/RAM total/available（psutil）。
  - FR-STAT-01 逐字段防御：每个属性读独立 try → 该字段 None（§13.2 "MUST NOT fill unknowns with defaults"）；整个 snapshot 永不 raise。
  - §10.5 真超时语义：`asyncio.wait(..., timeout=2s)` 包 `run_in_executor`——worker 线程不可取消，超时即放弃（迟到结果丢弃），调用方等待被硬性限界（`wait_for`+`to_thread` 做不到：await 会一直骑到线程结束，已用测试证实并记录）。psutil/platform/cpuinfo_reader 全部可注入（§10.2 tests intent）。
  - `CompositeHardwareProbe`：base + GPU lister 合成，各部分独立降级（GPU 探针挂了 OS/CPU/RAM 字段存活）。
- `adapters/hardware/nvidia_probe.py`：`NvmlGpuProbe`（§21.2 optional pynvml）——import/init 失败 → `()`（绝不编造 GPU 条目）；逐字段 NVMLError 降级（NotSupported → 该字段 None 其余存活）；pynvml ≥11 str 名与旧版 bytes 名都接受；init 成功才配对 shutdown；2s wait 超时 → ()。
- `api/v1/device.py` — API-DEV-01 正式上线（§13.2 verbatim 形状）：
  - Bearer + `models:read` scope（§13.2 API 表）；OS/CPU/RAM/GPU pydantic 模型全 nullable。
  - `network.lan_addresses` 复用 §16.2 接口选择（与 mDNS 广播同一地址源，to_thread 包阻塞解析）；`network.tailnet` 镜像 WP-14 startup 探针（absent → null）。
  - `gpus` 无检测时为 `[]`——全 null 的 GPU 条目等于编造 GPU 存在（模块 docstring 记录该读法）。
  - 无限流：§13.8 穷举列出限额且无 /device 行，不自行加（docstring 说明）。
- app.py 装配：`app.state.hardware = Composite(Psutil, (Nvml,))`；device router 注册（§13.1 第 10 条公网路由）。
- OpenAPI：export 脚本 include device router → mesh-v1.json 10 paths；drift OK。
- 测试 +26：unit 19（/proc/cpuinfo 解析、全映射、unknown→null、逐字段降级、psutil/platform 全爆→全 None、真超时（量 caller 侧等待，非 asyncio.run teardown 的 executor join——测试曾据此误报已修）、NVML 双卡+bytes 名+NotSupported、init 失败/ import 失败/0 卡/枚举错、超时→()、Composite 合成/独立降级/协议符合性）+ integration 7（真实 app token 模式：200 全键集断言（§13.2 verbatim）+ 私网地址 + 无 tailnet null、401 AUTH_REQUIRED/垃圾 token AUTH_FAILED、窄 scope 403 FORBIDDEN_SCOPE（直接 store.upsert_device 建行——upsert 不改 scopes，DeviceService.create 恒默认 scope，测试先踩坑后修正）、吊销 401、tailnet block 直通、探针爆炸仍 200 全 null（FR-STAT-01））。
- 真实进程冒烟：dev-insecure loopback 起 uvicorn，curl /mesh/v1/device 实体 = §13.2 精确形状（linux/5.10.134、Xeon、2 cores、4GB RAM、gpus []、tailnet null）。
- **QUESTION-105 登记**（docs/OPEN_QUESTIONS.md）：冒烟发现 CLI dev 横幅写 "token auth ON" 但 deps.py 在 dev-insecure 下绕过 token（M1 兼容 per-process Device）——§17.9 只规定 loopback+cleartext，未说 token 豁免。规格未明 → 不猜：横幅改为如实描述（"token auth BYPASSED — QUESTION-105"），行为不动等 owner 裁决；生产 TLS 监听不受影响（恒 token 强制）。
- 仪表盘（d7b752a）：WP-15 part 1 done 行（3576fdf）、M5 in-progress（第 4 个 active 里程碑）、新增 "Hardware probe + /device" gate 行、pytest 268 collected、QUESTION-105 卡片置顶、next steps → WP-15 part 2（/models/load|unload + keep-warm，FR-MOD-04/05，fake backends 需扩展 load/unload/keep_warm 行为——沙箱可做）；**新面板 "Mesh API surface (§13.1 · §13.2)"**：10 条端点行（GET/POST/DELETE 彩色方法 chip + hover scale、mono 路径、token/no-auth 徽章 + KeyRound 图标、scope chip、API-ID 徽章、/device 行 emerald 高亮 + Sparkles "new" 徽章、注记右对齐 truncate、底部 auth 注记）——桌面/移动均复验渲染正常（移动端 flex-wrap 堆叠）；"Next milestone" 标题更新为 M5/M2-M4；lint clean。

验证结果:
- merged main = d7b752a（WP-15 3576fdf + dashboard）。gate 全绿：ruff/format PASS、mypy --strict PASS（14 files）、pytest 265 passed + 3 announced skips、import-linter 3/3 KEPT、OpenAPI drift OK（10 paths）、3 security scans PASS、fake backends 27/27、bun lint clean、agent-browser 桌面+移动+新面板复验通过（console 零错误）。

未解决问题/风险，下一阶段建议:
1. **下一沙箱增量 = WP-15 part 2（M5, FR-MOD-04/05）**：`POST /models/load|unload`（202 loading；501 UNSUPPORTED_CAPABILITY——LM Studio 原生 [VERIFIED]；404 MODEL_NOT_FOUND）+ keep-warm（Ollama keep_alive）。需要先给 fake backends 扩展 load/unload/keep_warm 能力位与行为（fake_core caps 补 load_unload/keep_warm），沙箱可完整实现+测试。
2. QUESTION-105（新）：dev-insecure 是否豁免 Device Token——owner 确认；若要求 token 强制，改动局部（deps.py dev 分支 + M1 测试适配）。
3. QUESTION-103 剩余 OPEN 项：wire-format items 1-2 + operator 路由命名；QUESTION-104 等 tailscale 采集。
4. WP-09/WP-10/WP-12(App)/WP-13(App) 需 Android/Gradle 环境 → M2-M4 的 App 侧收尾依赖 owner 环境；Agent 侧 M2/M3/M4 + M5 part 1 已完整。
5. Owner actions 不变：fixtures 采集（LM Studio/Ollama/tailscale 三类，阻塞 contract tests 硬门）、ADR-017、QUESTION-101..105。
6. 真实 GPU 主机上的 NvmlGpuProbe 行为（VRAM/util/temp）未验证 [Not verified]——沙箱无 NVIDIA 驱动，探针按 §21.2 optional 设计降级为 []。
7. 注：本沙箱会在会间把 HEAD 切回 main，本轮提交直接落在 main。

---
Task ID: 16 — webDevReview round 7 (3 QA fixes + WP-15 part 2: load/unload + keep-warm, M5 收官)
Agent: Z.ai Code (cron webDevReview)
Task: 状态判断 + agent-browser QA + 自选开发重点（本轮：修 3 个真 bug + WP-15 part 2）。

项目状态判断:
- QA 发现并修复 3 个真实问题（commits 731393a + 61156fe）：
  1. **pytest_layer.sh 解释器解析**：从仓库根以 CI 风格运行 `bash scripts/pytest_layer.sh` 时 PATH 解析到沙箱全局 venv 的 pytest（缺 zeroconf 等 Agent 依赖）→ test_mdns.py 6 errors（Task 13 的 sys.path 修复只解决了 import 锚定，没锁解释器）。修复：脚本优先用 `agent/.venv/bin/pytest`（存在时），CI 无此 venv 行为不变。修复后四层全绿（unit 209 / contract 3 announced skips / integration 48 / security 8）。
  2. **pynvml 上游弃用**：运行时 FutureWarning "The pynvml package is deprecated. Please install nvidia-ml-py instead." —— 正好触发 WP-02 报告预登记的 M5 决策规则（"If M5 finds nvidia-ml-py is the better-supported distribution, switching = new dependency → ADR at that time"）。按治理流程：**ADR-018**（Proposed）+ nvidia extra 切换到 nvidia-ml-py==13.615.71（WP-02 采证的同一版本；两个包都提供 `pynvml` 模块 → 运行时/测试代码零改动）+ 锁文件最小 diff（-pynvml、nvidia-ml-py via 改为 pyproject；版本集经无约束 uv 重编译验证完全一致 + hash dry-run 校验）+ ADR 索引 + WP-02 报告补状态注记。19/19 探针测试通过、FutureWarning 消失。
  3. **仪表盘移动端横向溢出**：agent-browser 390px 视口实测 `document.scrollWidth=549`（应 390）。根因：页面响应式网格只有 `lg:grid-cols-5`/`md:grid-cols-2` 类，移动端隐式 auto 轨道被内容 min-content 撑爆（TC-SEC-10 行的 truncate nowrap `where` 文本实测 min-content 531px）。修复：5 处网格补 `grid-cols-1`（Tailwind = minmax(0,1fr)，轨道封顶容器宽，既有 min-w-0+truncate 链正确省略号）。实测 390px sw=390、1280px 五列布局不变。
- 其余 QA 全绿：dev.log 全 200、console 零错误、过滤 chips/行展开/Refresh 实测通过、Python 全量 gate 绿。→ 修复后推进 WP-15 part 2。

本轮完成 (WP-15 part 2, commit 649cd8f + dashboard 21b08f9, 均落 main):
- **API-MODEL-02/03**（§13.2, FR-MOD-04）`POST /mesh/v1/models/load|unload`：
  - Bearer + `models:manage`（§13.2 API 表；集成测试含窄 scope 403 FORBIDDEN_SCOPE、无 token 401）。
  - 体 `{mesh_model_id}` 经 `validate_model_ref_payload`（core/policy.py，allow-list 拒未知字段 → 422 INVALID_REQUEST §13.4 envelope；JSON 解析失败同样 422 而非 500）。
  - 202 `{"state":"loading"}`（逐字）；unload 返回镜像 `{"state":"unloaded"}` —— **QUESTION-106 登记**（规格单行只给了 load 状态；§13.5 封闭词表存在即为此用；若 owner 推翻是一行 diff）。
  - 404 MODEL_NOT_FOUND（复用 Router.resolve 的 §14.3 first-"::" 解析）；501 UNSUPPORTED_CAPABILITY（§10.2 基类契约 —— Ollama 无显式 load，§10.3 表）；适配器的 BACKEND_* 错误照 §10.3 rule 3 映射，绝不透传 raw body。
  - 不加限流（§13.8 穷举且无此二路由行，与 /device 同一读法，docstring 记录）。
- **KeepWarmScheduler**（`core/warm.py`，§16.5, FR-MOD-05）：
  - 暖集**仅**来自 `models.overrides[].keep_warm = true`（Appendix E 默认 false；调度器收解析好的 id 集，不 import config 类型，§10.1）。
  - interval = min(backend_idle_unload/2, 240 s)（§16.5 逐字公式；[DESIGN] idle=300s 按 §6.2 [SRC] Ollama 默认 idle-unload ≈5min，常量非 Appendix E 键）。
  - 只 ping 声明 keep_warm cap 的 Backend（§10.3 表：仅 Ollama 原生 /api/chat 空 messages ping；LM Studio keep-warm n/a 永不 ping —— 即使 override=true，防"静默保温"）。
  - **设备活动门**：≥1 个非吊销设备 last_seen_at 在 60 分钟内（§14.1，app.py 谓词过滤 revoked 行）→ 否则整轮 no-op（"Never keeps models warm silently otherwise"）。
  - ping 失败（BACKEND_UNAVAILABLE 等 MeshError）→ allow-list 键日志降级、pass 继续（CI-21 缓解项，非正确性路径）；Clock 可注入；[DESIGN] 启动即首轮 ping（冷 Agent 不该让活跃设备吃冷启动 TTFT）；§10.6 顺序：registry warm 后 start，shutdown 对称 stop。
- **Fake Ollama 动态内存状态**（tools/fake-backends）：`in_memory` 服务器级实例状态 —— 空 messages 的 /api/chat 判定为 keep-warm ping（模型入内存集 + `warm_pings` 计数，/api/ps 可观察）；chat demand-load（镜像真实行为；keep_alive on /v1 仍 [UNVERIFIED] §6.2 按安全假设忽略）；每实例独立状态。Fake LM Studio 已有 load/unload + loaded_models（WP-03 预铺）未动。
- 测试 +33：unit 12（调度器：interval 公式/候选门（无 override、无 cap、无 backend）/活动窗 60min 边界/吊销设备不保温/失败降级继续/start-stop 幂等 + [DESIGN] 首轮 ping 钉住）+ policy 6（model_ref 校验全分支）+ integration 11（真实 app + 双 fake + lifespan：202/404/501/422/401/403、§13.3 头、fake 状态翻转、**LM Studio registry state 停留 unknown**（§6.1 loaded 标志 UNVERIFIED —— 不猜，钉住该契约直到 fixtures）、keep-warm 经 app 装配真实 tick 打到 fake 并经 /api/ps 观察）+ fake-backends 4（16/16 ollama 文件级）。
- OpenAPI 12 paths（+load/unload），drift OK。
- **真实进程 TLS token 路径冒烟**（dev-insecure 绕过 token 不算数 —— QUESTION-105 行为再次确认）：store 直插 manage-scope 设备 + TokenService 签发 → curl -k https：202 loading / fake 状态翻转 / 404 / 501 / 422 / 202 unloaded / 401 全分支符合规格；keep-warm 在无活跃设备时 0 ping（真实进程验证"静默"约束）。
- 仪表盘（21b08f9）：WP-15 (part 2) 行、新 gate 行（Model load/unload + keep-warm）、Mesh API surface 10→12 行（load/unload 带 models:manage chip + QUESTION-106 徽记）、QUESTION-106 + ADR-018 卡片、M5 详情改"Agent side COMPLETE"、pytest 297 collected、next steps 重写（Agent 侧 M2–M5 完结 → M6+ 需 owner 重规划）。
- agent-browser 复验：all16/done13 chips、行展开（649cd8f 注记）、/models/load 面板行、QUESTION-106/ADR-018 卡、桌面+移动零 console 错误、390px 无横向溢出（回归通过）。

验证结果:
- merged main = 21b08f9（731393a → 61156fe → 649cd8f → 21b08f9）。gate 全绿：ruff/format PASS（88 files）、mypy --strict PASS（15 files, CI scope core+security）、pytest 294 passed + 3 announced skips、fake backends 31/31、import-linter 3/3 KEPT、OpenAPI drift OK（12 paths）、3 security scans PASS、bun lint clean、agent-browser 桌面 1280 + 移动 390 + 交互复验通过（console 零错误、无横向溢出）。
- 已知非阻塞项：全 src 范围 mypy 2.4.0 在 CI 范围外文件报 26 处（库版本签名变化 + 类型收窄；§21.2 只要求 core/security；运行时有 pydantic 校验兜底，非真实 bug）——建议未来作为 owner 决策扩范围或加 per-module overrides，未自行扩（避免擅自改 CI 契约）。

未解决问题/风险，下一阶段建议:
1. **Agent 侧 M2–M5 全部完成**。剩余 WP（09/10/11-App/12/13-App）需 Android/Gradle 环境；WP-16+ 按 §22.2 "M6–M9 packages are defined when each milestone starts" 等 owner 重规划；M6 Control Plane 可选、门在 Q-05。
2. 沙箱可做的硬化候选：TC-SEC-10 pytest 化（TLS 1.3-only 自动化条目，替代 smoke 状态）；§19.1 benchmark 骨架（数字需真实 Backends）；keep-warm 与 chat mesh.meta 的 CI-21 e2e 串联；全 src mypy 范围决策落地。
3. QUESTION-106（新）：unload 响应体状态；ADR-018（新）：nvidia-ml-py 审批；QUESTION-103 剩余 wire-format items 1-2 + operator 路由命名；QUESTION-104 等 tailscale 采集；QUESTION-105 dev token 豁免。
4. Owner actions 不变：fixtures 采集（LM Studio/Ollama/tailscale，阻塞 contract tests 硬门）、ADR-017/018 审批、QUESTION-101..106。
5. 沙箱注：本沙箱会在会间把 HEAD 切回 main，本轮提交直接落在 main；`agent/.venv` 与新锁文件已同步（nvidia-ml-py 13.615.71）。

---
Task ID: 17 — webDevReview round 8 (1 QA fix + 3 spec-anchored hardening items + dashboard round-8, sandbox)
Agent: Z.ai Code (main agent)
Task: 状态判断 + agent-browser QA + 自选开发重点（本轮：修 228 个弃用警告 + TC-SEC-10/CI-21/§19.1 三项加固 + 仪表盘新面板）。

项目状态判断:
- QA round 8 全绿后开发：pytest 301 passed + 3 announced skips、agent-browser 桌面 1280 + 移动 390（无横向溢出）、console 零错误、dev.log 全 200、过滤 chips/行展开/Refresh 交互正常。项目处于 Agent 侧 M2–M5 完结后的加固期。
- QA 期间发现的唯一真实问题：**全量 pytest 输出 228 个 DeprecationWarning**，全部源自 app.py 的 `@app.on_event("startup"/"shutdown")`（FastAPI ≥0.103 弃用；每个 TestClient 建两处注册 → 全套件放大）。

本轮完成 (commits: agent 加固 + fcacafc dashboard，均落 main):
1. **App 生命周期迁移（修复）**：app.py 的 §10.6 startup/shutdown 改为单一 FastAPI **lifespan** handler（`@asynccontextmanager`，闭包捕获工厂局部服务，注册于 `FastAPI(lifespan=...)`；shutdown 严格逆序）。app.state 全部键保持不变（集成测试 `app.state.*` 零改动，`app.router.lifespan_context` 用法继续成立）。新增 tests/unit/test_app_lifespan.py 钉住：工厂构建期 DeprecationWarning ⇒ error（fail-closed）。结果：**套件警告 228 → 0**。
2. **TC-SEC-10 pytest 化（§17.13/§17.3）**：`build_tls13_server_context` 落位 security/tls.py（§10.1 归属，CLI 委托之——生产 context 与被测 context 同源）；tests/security/test_tc_sec_10_tls13.py 用**真实 TLS 握手**：TLS 1.3 客户端协商 TLSv1.3 + 三大 1.3 cipher 之一；TLS 1.2-only 客户端双侧 fail-closed 拒绝（服务器线程 bounded-wait 防竞态，3 次复跑稳定）；`minimum_version` 钉在 TLSv1_3。tests/security/README.md 矩阵更新：10 条中 6 条 delivered。
3. **CI-21 e2e 链（§21.4 × §16.5 × §13.7）**：tests/integration/test_ci21_keepwarm_chain.py 三条——冷路径 chat 在 mesh.meta 时刻钉住 `model_state="unloaded"`（meta 先于 demand-load 发出，CI-21 问题陈述上线）且生成仍完成；保温路径（override + 活跃设备 + 一轮 §16.5 tick + registry.refresh）后同 chat 发 `model_state="loaded"`（fake /api/ps → §10.3 状态推导，零编造）；基线：DEFAULT_IN_MEMORY 模型免保温读 loaded。
4. **§19.1 benchmark 骨架**：scripts/bench_agent_latency.py（§21.1 scripts/=dev helpers，不动 monorepo 布局）——经真实 ASGI app + fake Ollama 测客户端观测 TTFT/chunk 间隔 p50/p95/max/mean，对比 §19.1 逐字预算；输出明示 "sandbox-relative, NOT Agent-added" + 进程内 transport 会合并流 chunk 的已知局限；诚实数字等真实 Backends（CAPTURE.md owner action）。已实跑验证（20 iterations + JSON 输出）。
5. **仪表盘 round-8（fcacafc）**：新面板 "Performance budgets (§19.1)"（8 行逐字 target + [DESIGN]/[SRC] basis + 诚实测量状态 chips + harness 注脚）；Mesh API surface 12 行全部可**点击展开**（request body / §13.8 rate-limit / response codes chips，AnimatePresence + aria-expanded/controls）；planned WP 行新增 "blocked · <原因>" chip（不再藏在展开里）；"Delivered this round" 改为数据驱动 data.round（替换遗留 WP-14 硬编码陈旧文案）；Next-steps 标题更新为 §22.2 措辞；status JSON 更新（4 条新 gate 行、TC-SEC-10 → delivered、304 collected、nextSteps 重写）。
6. **移动端溢出修复（本轮 QA 抓到的回归）**：新 §19.1 chip（shadcn Badge 自带 whitespace-nowrap+shrink-0）在 390px 把 scrollWidth 撑到 429——chip 改 whitespace-normal/break-words/shrink，行改始终 flex-wrap（metric 独占一行 sm:w-auto sm:flex-1）；复测 390=390（含展开态）。

验证结果:
- main = fcacafc（agent 加固 commit + dashboard fcacafc）。gate 全绿：ruff check/format PASS（91 files）、mypy --strict PASS（CI scope 15 files）、pytest **301 passed + 3 announced skips、0 warnings**、fake backends 31/31、四层 pytest_layer（repo root 调用）228 unit / 3 announced skips / 62 integration / 11 security 全绿、import-linter 3/3 KEPT、OpenAPI drift OK（12 paths）、3 security scans PASS、bun lint clean、agent-browser 桌面 1280 + 移动 390 + 新面板/展开/过滤复验通过（console 零错误、390px 无横向溢出）。
- 基准骨架实跑样本（sandbox-relative）：TTFT p50≈57ms / p95≈58ms（含 fake 后端自身行为；进程内 transport 合并 chunk → per-chunk gaps ≈0，已如实标注）。

未解决问题/风险，下一阶段建议:
1. **沙箱可做候选**：TC-SEC-05 unauth fuzz harness（Agent 侧端点可重复条目）；全 src mypy --strict 范围决策（2.4.0 在 CI 范围外报 26 处——owner call）；CI-17..20 流鲁棒性条目（proxy 缓冲/断流）。均未开工。
2. **pytest_layer.sh 调用姿势**：必须在 **repo root** 调用（脚本从 CWD 解析 `agent/.venv`）；在 agent/ 目录内调用会静默回退到 PATH 全局 venv 的 pytest → test_mdns 6 errors（本轮实测踩坑，脚本 docstring 已有说明，勿改脚本）。
3. QUESTION-105/106、QUESTION-103 wire-format items 1-2 + operator 路由命名、QUESTION-104 等 tailscale 采集；ADR-017/018 待 owner 审批。
4. Owner actions 不变：fixtures 采集（LM Studio/Ollama/tailscale，硬门）、真实 LAN/GPU/Android 环境验证（mDNS 多播、NvmlGpuProbe 真实 GPU、§19.1 Agent-added 数字、WP-09/10/12/13 App 侧）。
5. WP-16+ 按 §22.2 "M6–M9 packages are defined when each milestone starts" 等 owner 重规划。
6. 沙箱注：HEAD 会间会被切回 main，本轮提交直接落 main；`agent/.venv` 已同步。

---
Task ID: 18 — webDevReview round 9 (3 spec-conformance bug fixes + TC-SEC-05 fuzz harness + dashboard stream-lifecycle panel)
Agent: Z.ai Code (main agent)
Task: 状态判断 + agent-browser QA + 自选开发重点（本轮：修复 3 个规格符合性 bug + TC-SEC-05 模糊测试 + 仪表盘新面板）。

项目状态判断:
- QA round 9 基线全绿：pytest 301 passed + 3 announced skips、agent-browser 桌面 1280 + 移动 390（无横向溢出）、console 零错误、dev.log 全 200、交互（过滤 chips）复验正常。项目处于 Agent 侧 M2–M5 完结后的加固期。
- 代码审查（CI-17..20 候选清单驱动）发现 **3 个真实规格符合性 bug**（详见下），全部修复。

本轮完成 (agent: 99610ef, dashboard: 7088cee, 均落 main):
1. **流鲁棒性 bug 簇修复（CI-18/CI-21, §13.7, §10.3 rule 4, NFR-REL-02）**：
   - `api/v1/chat.py`：首 token 等待改为与 `: ping`（每 15 s）竞速（§13.7 "pings until first token" + CI-21 mitigation "Pings"）。**原代码 `asyncio.wait_for(upstream.__anext__(), timeout=30.0)` 是三重违规**：(a) 30 s ≠ 规格的 120 s 冷加载预算；(b) TimeoutError 未捕获 → 生成器裸崩 → 流无 terminal `mesh.error` 即死（NFR-REL-02 违规）；(c) 冷加载期间零 ping → 手机 45 s idle 检测（CI-18）误杀活流。finally 中补 pending task 取消，防泄漏。
   - `adapters/backends/openai_compat.py`：`_consume` 首个已解析 chunk 前的静默缺口用 `first_token_timeout_s`（120 s），之后才用 60 s idle 预算（原 60 s 一刀切会杀掉 60–120 s 的静默冷加载，先于 API 层触发）；idle 超时参数化以便测试。
   - `app.py build_adapters`：**Appendix E 的 `first_token_timeout_seconds`/`max_stream_seconds` 是死配置**——存在但从未传入适配器；现已接线（§10.3 rule 4 "configurable" 落实）。
2. **TC-SEC-05 unauth fuzz harness（§17.13 L5）**：`tests/security/test_tc_sec_05_fuzz.py`——确定性固定语料（无随机）。公开路由从**应用自身 OpenAPI schema** 枚举（FastAPI 惰性 `_IncludedRouter` 隐藏 APIRoute，app.routes 枚举为空——改为 openapi() 权威面）：12 条公开路由 × 4 种 auth 变体 × 7 种 body 变体 + admin listener（伪造 Host → 403、缺/错 X-Admin-Token → 401，fail-closed stub 证明 handler 永不可达）。断言：永不 5xx、§13.4 envelope 键集精确、攻击者输入零反射、无 Traceback、X-Mesh-Request-Id 恒在；路由集 containment 钉死防新端点漏网。
3. **OpenAPI 脚本解释器修复（QA 中抓到的假阳性）**：`python3 scripts/check_openapi_drift.py`（系统 pydantic 2.12.5）与 lockfile venv（2.13.5）生成的 ValidationError schema 不同 → drift 假失败。仿 round-7 pytest_layer.sh 模式：两脚本在 `agent/.venv` 存在时 re-exec（CI 无该 venv 不受影响）。**两个实现教训**：venv python 是 base 解释器的符号链接 → 比较解析路径恒等 → 必须用 `sys.prefix != venv_dir` 判定；shim 用 `__file__` 会把 checker re-exec 成 exporter（shim 活在 export 模块里）→ 必须用 `sys.argv[0]`。
4. **测试 +11**：unit 5（首 token 缺口 > idle 预算存活 / 首 chunk 后缺口用 idle 预算超时 / 全静默在 first_token 预算处 BACKEND_TIMEOUT(504, retryable) / §10.3 rule 4 默认值钉住 / build_adapters 接线 77s/321s 端到端）+ integration 3（真实 app + fake 2.5 s 冷加载 + 预算 1 s + PING_INTERVAL_S 收缩：≥3 ping + terminal mesh.error BACKEND_TIMEOUT + 无 [DONE]；快流零杂散 ping（保生产 15 s 间隔防竞速不稳）；冷加载在预算内（4 s）→ ping 保活且正常完成）+ security 3（fuzz 全电池 / 路由集 containment / admin listener 全矩阵）。
5. **仪表盘 round-9（7088cee）**：新面板 "SSE stream lifecycle (§13.7 · §10.3 rule 4)"——6 阶段线框契约时间线（queued → mesh.meta → cold load → deltas → stats → terminal error），色环节点（琥珀=等待/翠绿=正常/红=终态）、mono emit chips、每阶段预算行、琥珀 "fixed this round" 条说明 30 s abort 修复、页脚引用新测试文件；CI gate 面板 +2 行（SSE stream robustness、TC-SEC-05）、pytest 行更新 315 collected；TC-SEC-05 → delivered（7/10）；/chat/completions API 行补冷加载 ping + BACKEND_TIMEOUT 响应行；nextSteps 重写；round 9 数据。
6. agent-browser 复验：新面板桌面 1280 渲染正常（分色节点/chips/what-changed 条全部到位）、移动 390 无横向溢出（sw=390，chips 正确换行）、console 零错误。

验证结果:
- main = 7088cee（agent 99610ef + dashboard 7088cee）。gate 全绿：ruff check/format PASS（94 files）、mypy --strict PASS（CI scope 15 files）、pytest **312 passed + 3 announced skips、0 warnings**、四层 pytest_layer（CI 式 repo-root 调用，须带层目录参数）233 unit / 3 announced skips / 65 integration / 14 security 全绿、fake backends 31/31、import-linter 3/3 KEPT、OpenAPI drift OK（12 paths，双解释器验证）、3 security scans PASS、bun lint clean、agent-browser 桌面+移动复验通过（console 零错误、390px 无横向溢出）。

未解决问题/风险，下一阶段建议:
1. **剩余沙箱可做候选**：全 src mypy --strict 范围决策（2.4.0 在 CI 范围外报 26 处——owner call，未动）；CI-19/20 属客户端条目（SM-CONN re-plan / app 后台），随 Android 工作包落地；§19.1 数字需真实 Backends。
2. **pytest_layer.sh 调用姿势**：repo root 调用且**必须带层目录参数**（`bash scripts/pytest_layer.sh agent/tests/unit` 等，CI 四步原样）——裸调用只会打印 "no test directories" 通知（本轮实测踩坑后核对 ci.yml）。
3. QUESTION-105/106、QUESTION-103 wire-format items 1-2 + operator 路由命名、QUESTION-104 等 tailscale 采集；ADR-017/018 待 owner 审批——全部不变。
4. Owner actions 不变：fixtures 采集（LM Studio/Ollama/tailscale，硬门）、真实 LAN/GPU/Android 环境验证、WP-16+ 等 owner 重规划（§22.2）。
5. 冷加载长流（120 s 预算 + 15 s ping）的**真实 LM Studio/Ollama 行为**待 fixtures/实机验证——fake 的冷加载是 sleep-before-headers，真实后端可能先发头再静默（两条超时路径已分别覆盖：send 阶段 httpx read 预算 + _consume 首解析 chunk 缺口）。
6. 沙箱注：HEAD 会间会被切回 main，本轮提交直接落 main；`agent/.venv` 未变（无新依赖）。

---
Task ID: 19 — webDevReview round 10 (Admin API conformance pass §13.1 + §20.1 metrics + 2 dashboard QA fixes)
Agent: Z.ai Code (main agent)
Task: 状态判断 + agent-browser QA + 自选开发重点（本轮：QA 全绿无 bug → §13.1 Admin API 一致性 + §20.1 可观测性）。

项目状态判断:
- QA 基线全绿：Python gate（unit 233 / integration+security 79 / contract 3 announced skips、ruff/format clean、mypy --strict CI scope clean、CI 式 pytest_layer 全绿）；agent-browser 桌面 1280 + 移动 390（无溢出）、console 零错误、过滤 chips（planned=3）/行展开/Refresh 实测通过、/api/localmesh/status 200。→ 按上轮候选推进：本轮主题 = Admin API 一致性 + §20.1 指标。

本轮完成 (agent commit e4bf129 + dashboard commit e4bf129，均落 main):
1. **§13.1 Admin API 一致性 pass（重大发现）**：QUESTION-103 item 4 原读法"§15.4/§15.6 只命名动作不命名路径"再次漏证据——§13.1 正文（line 893）明确枚举全部 admin 路由（与 WP-13 X-Admin-Token 同类失误）。规格优先对齐：
   - **PATCH /admin/devices/{id}**（scopes, name）— 规格命名的 operator 授权机制（"models:manage and tasks are granted per Device by the operator"）。DeviceService.update()：scope 宇宙白名单（§17.7 矩阵：models:read/chat/models:manage/tasks）、canonical 排序去重、name strip+128 上限 [DESIGN]、吊销行可编辑但鉴权仍封锁 [DESIGN]（token 已删 + revoked_at 门，无法复活）；Store.update_device 新增（ports + sqlite 动态 SET（固定列字面量，绑定参数）+ fake_store）。
   - **GET /admin/status** — 规格命名、形状 [DESIGN]：Metadata-only（identity/uptime/pairing state/device 计数/backends/queue/listen/pin 前 12 字符/tailnet block），经 status_fn 注入（admin 层零 core 依赖）。
   - **DELETE /admin/devices/{id}** + **POST /admin/pairing/open|approve|deny|close** + **GET /admin/pairing** — 规格命名路由升为主路由；WP-08 [DESIGN] 名保留为 loopback-only 别名（owner 可一行 diff 移除）。QUESTION-103 item 4 → **RESOLVED by implementation**。
   - 审计：AUDIT_EVENTS 扩展 device_updated（§14.1 schema 注释以"…"收尾 = 开放词表钩子 [DESIGN]；meta 不含变更字段名——§17.10 allow-list 无该键，扩 allow-list 留 owner）。
2. **§20.1 指标（observability/metrics.py 替换 M0 stub）**：MetricsRegistry 十个 verbatim family（requests_total{status,backend} / ttft_ms histogram / tokens_out_total / tokens_per_sec / queue_depth / active_generations / backend_up{backend} / auth_failures_total / pairing_attempts_total / cancel_latency_ms）；线程安全 push + scrape 时 pull 刷新（scheduler.queue_stats + registry.snapshot）；Prometheus text 0.0.4 渲染（label 转义、直方图 bucket/_sum/_count、无标签空 family 预置 0）。**GET /admin/metrics** [DESIGN path]——§20.1 "optional Prometheus text endpoint on loopback admin only"，ADR-014 守卫全覆盖。
   - 埋点：deps.get_principal 401 类 → auth_failures_total（NoReturn helper）；pair.py claim → pairing_attempts_total；chat.py 流式 + **非流式**（smoke 实测抓到非流式漏埋）→ requests_total(ok|error|cancelled)/tokens_out_total/ttft_ms/tokens_per_sec；scheduler cancel()/cancel_by_device() 打戳 → _finish 观测 cancel_latency_ms（cancel 请求→job 完成，§13.7 ≤1s 带宽可解析；构造器注入，core 零直接依赖）。
3. **测试 +45**：unit +31（metrics 16：counter/gauge/histogram 语义、bucket 常量钉 §19.1 200ms + §13.7 1s、渲染转义/空 family/全 10 family、pull 刷新 + 降级；device update 13；scheduler cancel-latency 2 含"流退出路径不重复计数"）+ integration 12（admin conformance：**授权 e2e**——operator PATCH 授 models:manage → 同设备新 token 过 scope 门打到 /models/load 404 而非 403；PATCH 校验矩阵（unknown scope/empty/blank name/unknown field/garbage JSON→422）；DELETE=规格化 revoke + 别名行为一致；pairing 规格路由↔别名 parity；status Metadata-only 断言（全 pin/ admin token 不出现在 body）；metrics 10 family + 真实事件计数 + Host/token 负路径）。
4. **QA 修复**：agent/tests/security/README.md 陈旧 Pending 行移除 TC-SEC-05（round 9 已交付）；真实进程 smoke（dev-insecure + fake LM Studio + admin token）全链路验证：pairing open(规格路由) → claim → approve(别名) → PATCH 授权 → chat 流式+非流式 → scrape 显示 requests_total=2/tokens_out_total=6/ttft 直方图/backend_up=1 → DELETE → 再 DELETE 404。
5. **仪表盘 round 10**：新面板 "Admin API surface (§13.1 loopback · ADR-014)"——operator 条（loopback listener + X-Admin-Token(§13.1·T-11) + operator-only 徽章）、12 端点行（PATCH 紫/POST 琥珀/DELETE 红/GET 翠方法 chip、spec-named vs [DESIGN] path 徽章、行展开 responses chips）、§20.1 metrics families 网格（10 卡片：counter/histogram/gauge 类型 chip + push/pull 来源注记、可折叠）、WP-08 别名→规格名映射卡（QUESTION-103 item 4 resolved）、§17.6 auth 注脚；status JSON：Round 10、+2 gate 行（27 总）、QUESTION-103 注记、nextSteps 重写。
   - **agent-browser QA 抓到 2 个真 bug 并修复**：(1) PATCH/DELETE 共享路径 `/admin/devices/{id}` → React duplicate key error（rowKey 改 method+path）；(2) metrics 切换行 390px 溢出 5px（sw=395，flex 无 wrap）→ flex-wrap 后 390=390。

验证结果:
- main = e4bf129（agent + dashboard）。gate 全绿：ruff check/format PASS（97 files）、mypy --strict PASS（CI scope 15 files）、pytest **356 passed + 3 announced skips**（265 unit / 77 integration / 14 security）、import-linter 3/3 KEPT、OpenAPI drift OK（12 paths）、fake backends 31/31、bun lint clean、agent-browser 桌面 1280 + 移动 390（sw=390 无溢出）、console 零错误、行展开 + metrics 网格交互实测通过、截图存档 download/round10-admin-panel-{desktop,mobile}.png。

未解决问题/风险，下一阶段建议:
1. **沙箱侧增量已尽**：Agent 侧 M2–M5 + admin API 全量 + §20.1 指标完成。剩余 WP（09/10/11-App/12/13-App）全部依赖 Android/Gradle 环境；WP-16+ 按 §22.2 等 owner 重规划（M6 Control Plane 门在 Q-05）。
2. QUESTION-103 item 4 已 RESOLVED（若 owner 反对别名保留 = 一行 diff）；剩余 OPEN：QUESTION-101/102/104/105/106 + ADR-017/018 审批。
3. Owner actions 不变：fixtures 采集（LM Studio/Ollama/tailscale 三类，contract tests 硬门）、真实 LAN/GPU/Android 验证、/admin/metrics 在真实 Prometheus 抓取器下的 scrape 行为 [Not verified]（格式按 text/plain 0.0.4 渲染并有单测）。
4. 全 src mypy --strict 范围决策（26 处 CI 范围外）仍待 owner call，未动。
5. device_updated 审计扩展（AUDIT_EVENTS + device_updated）与 §17.10 "fields" 键扩展均为 [DESIGN] 标注——若 owner 收紧词表，移除是一处小 diff。
6. 沙箱注：HEAD 会间会被切回 main，本轮提交直接落 main。

---
Task ID: 20 — M6 Control Plane full implementation (§12, FR-CP-01..04)
Agent: Z.ai Code (main agent)
Task: User directive "complete M0–M9 one by one with full-fledged implementation". This round: M6.

Work Log:
- Owner authorization recorded: the milestone-review session directive closes the Q-05 gate; ADR-019 written (docs/adr/019-control-plane-activation.md).
- control-plane/ built: migrations/0001_init.sql (§12.2 devices table + RLS **verbatim**), README.md (deployment + flows + §17.6 keyring wiring), scripts/schema_content_scan.py (TC-SEC-08 — build fails on any column matching /prompt|message|content|completion|attachment/i per FR-CP-04; comments stripped before matching).
- Agent side: ControlPlaneClient port (adapters/ports.py); SupabaseControlPlaneClient adapter (PostgREST + Edge-Function shapes, [UNVERIFIED] → QUESTION-107; bytea \x… hex; Content-Range count parsing; 5 s bounded timeout; errors carry no URL/key echoes); ControlPlaneService in core/ (state machine disabled/unregistered/ok/offline, §12.3 failure mode "continue with local data", register via one-time link code, 60 s heartbeat loop, best-effort revocation mirror by public_key); config gates ([control_plane] enabled requires https url + auth_ref; keyring lookup, §17.6); app factory wiring (lifespan start/stop, fire-and-forget mirror task set drained at shutdown, DeviceService revoke fan-out); admin endpoints POST /admin/control-plane/register + GET /admin/control-plane/status (loopback, X-Admin-Token); /admin/status gains control_plane block; audit vocabulary + control_plane_registered [DESIGN open-vocabulary hook]; import-linter forbidden list + adapters.controlplane.
- QUESTION-107 opened (Supabase call shapes [UNVERIFIED]); activation itself APPROVED (ADR-019).
- Tests +31: unit 19 (client shapes/state machine/codec/config gates; metadata-only status asserts no key/URL), security 6 (TC-SEC-08: shipped schema green, forbidden columns detected, comment false-positive guard, CLI exit codes), integration 6 (admin register e2e w/ fake CP MockTransport, 503 envelope on CP down, revocation mirror URL/body assertions, audit event, disabled → 422).

Stage Summary:
- M6 COMPLETE (sandbox surface): main = ff21f12. Gates: ruff clean (104 files), mypy --strict (core+security 16 files) PASS, import-linter 3/3 KEPT, pytest 284 unit + 83 integration + 20 security = 387 passed, 0 failures. TC-SEC-08 delivered (8/10 per security README). Residual owner actions: Supabase deployment + real call-shape verification (QUESTION-107), Google Sign-In config (FR-CP-01 App side).

---
Task ID: 21 — M7 Multimodal & Tasks full implementation (§13.9, FR-MM-01..04)
Agent: Z.ai Code (main agent)
Task: Complete M7 one-by-one per user directive.

Work Log:
- FR-MM-01 vision: §13.6 content now string OR OpenAI-style parts (text/image_url/input_audio); parts pass through to OpenAI-compat backends; capability gate AFTER model resolution — image parts need `vision` (§13.5), audio parts in chat → 501 UNSUPPORTED_CAPABILITY with transcribe hint (S-13: STT is a separate service).
- FR-MM-02 whisper: new `whisper` backend kind [DESIGN per FR-MM-02/S-13] + WhisperBackend adapter (multipart /v1/audio/transcriptions, /v1/models listing, chat explicitly UNSUPPORTED; 300 s bound).
- FR-MM-03 RAG: embed() on OpenAICompatBackend (/v1/embeddings — §6 documents it for both real backends); core/rag.py (sliding-window chunking, float32-packed vectors, cosine top-k, .txt/.md-only honest scope, ciphertext section text); migration 0002_tables (tasks/task_files/rag_sources/rag_sections/rag_vectors — Content columns ONLY as AES-256-GCM ciphertext; repo content-column scanner green).
- FR-MM-04 tasks: §13.9 wire contract delivered — POST /tasks 202 {task_id,status:queued}; GET /tasks/{id} {status,progress,result?,error?}; GET /tasks/{id}/events SSE (15 s pings, snapshot-then-live, terminal [DONE]); DELETE (cancel running / fetch-ack delete); PUT /tasks/{id}/attachments/{name} (size caps via tasks.max_attachment_bytes, middleware exception path). Task INPUT and RESULT both encrypted at rest (AAD-bound to task_id; canary rule TC-SEC-01 stays green — diag3 showed plaintext input would have leaked). chat/vision tasks run through the SAME §16 Scheduler; transcribe direct; doc_qa = retrieval + scheduler chat. Retention ≤ 1 h (config capped at 3600) + 60 s sweeper in lifespan.
- Fakes: /v1/embeddings on fake LM Studio + fake Ollama (deterministic hash vectors, UNVERIFIED-marked); NEW fake_whisper.py (models + multipart transcriptions, scenario-driven); +6 fake self-tests.
- Exporter updated: tasks router in schema app → 16 paths; drift OK.
- QA bug cluster fixed during round: (1) encrypt() returns (nonce, ct) — create_task unpacked reversed → InvalidTag → zombie queued rows (also moved decode into try→failed mapping); (2) httpx 0.28 rejects list-of-tuples data= with files= (sync IteratorByteStream) → dict form fields; (3) fake whisper missing do_GET/do_POST dispatch → 501; (4) store drift test extended to EXPECTED_TABLES_M7; (5) test_policy v1 string-only test superseded by M7 parts test.

Stage Summary:
- M7 COMPLETE (sandbox surface): 310 unit + 37 fake + 96 integration + 20 security = 463 tests green; ruff clean; mypy --strict 19 files clean; import-linter 3/3; OpenAPI 16 paths drift OK; content-column scan OK. Residual owner actions: real Whisper service fixtures (CAPTURE.md), real backend /v1/embeddings contract tests (fixture gate), Android attachment UI (WP-12/13).

---
Task ID: 22 — M8 Routing & agent runtime full implementation (§16.6, FR-RTE-01..03, FR-AGENT-RT)
Agent: Z.ai Code (main agent)
Task: Complete M8 per user directive.

Work Log:
- FR-RTE-01/02: §16.6 auto-routing rule engine in core/router.py — VERBATIM scoring (0.40*quality/5 + 0.25*warm + 0.20*speed_norm + 0.15*(1-queue_load), ×fit; candidates filtered by state/known-backend + modality/capability subset; unknown context → fit 0.5; ties → lexicographic; est_tokens=ceil(chars/4)); quality_rank default 3 + Appendix E override; speed_norm provider (per-model recent tokens/s, null→0.5, 100 tok/s normalisation [DESIGN]); queue_load provider (scheduler.backend_load); weights in config (RoutingConfig, must sum to 1).
- §16.6 gate "Routing decisions explained in mesh.meta": mesh.meta.routing (mode/mesh_model_id/backend_id/reason/est_tokens/top-5 per-candidate score breakdown; pinned requests report mode=pinned) — additive field per §13.10.
- FR-RTE-03: classifier hook wired ONLY when [routing] classifier_enabled=true + classifier_model set; scheduled through the §16 Scheduler; can only REFINE the required set; failures degrade silently; OFF by default (S-21).
- FR-AGENT-RT: ADR-020 written (default-deny; allow-listed no-I/O built-ins time_now/uuid_v4/list_models; forbidden categories shell/fs/network/browser; bounded loop ≤5 iterations (config ≤10); 4096 B output cap; non-stream-only v1; audit without arguments). core/tools.py + core/agent_loop.py; ChatChunk gains defensive tool_calls parse; ChatRequest carries pass-through tools; tools gate 422s when disabled / stream+tools; tool_calls turn e2e over the fake (SSE delta form per ADR-009 single-parser rule); trace is Metadata-only (arguments never echoed).
- Fake ollama: deterministic tool_calls turn (SSE + JSON) behind the CALL_TOOL scaffold marker; ordering bug fixed (tool marker check must precede the stream branch).
- Tests +40: unit 21 (router_auto 11 + tools_runtime 10) + integration 8 (auto routing meta/pinned/404-no-candidate + tools disabled/stream-reject/e2e-loop/unknown-tool-denied/shape-422) + policy adjustments (tools now allow-listed per §13.6 M8 arrival; response_format still rejected).
- Gate notes: append_audit audit event unchanged; §20.1 untouched; OpenAPI unchanged paths (chat body schema unchanged — tools validated in code, schema additive doc stays code-level).

Stage Summary:
- M8 COMPLETE (sandbox surface): 331 unit + 104 fake+integration + 20 security = 455 tests green; ruff clean; mypy --strict (21 files) clean; import-linter 3/3; drift OK. Residual owner actions: real Backend tool-calling contract tests (fixtures), §16.6 tunables acceptance (speed scale 100 tok/s is [DESIGN]), classifier model selection.

---
Task ID: 23 — M9 Hardening & release full implementation (§21.4/§21.6, §17.13, §22.1 M9)
Agent: Z.ai Code (main agent)
Task: User directive "complete M0–M9 one by one with full-fledged implementation" — M9 was the last remaining milestone (M0–M8 verified complete via git log + worklog).

项目状态判断:
- Verified actual repo state first: 65 commits, M6/M7/M8 milestone commits present (ff21f12 / 1c9066a / 3c99be7), worklog Tasks 20-22. The continuation-summary claim of "zero output" was wrong; M9 was the only open milestone.
- QA/gate inspection exposed that the FINAL M8 commit (e76c45da + 3527196) had NEVER been gate-checked: ruff 20 errors, 14 files with format drift, mypy --strict 3 errors including a REAL runtime bug.

本轮完成 (agent commit <M9> + dashboard round-11, 均落 main):
1. **Release engineering**:
   - `scripts/release_gate.sh` — one-command runner of all 9 RELEASE.md gates in §21.4 order (ruff/mypy/4 pytest layers/lint-imports/drift/3 security scans/pip-audit) + SEC-N6 dev-default check; `--release` additionally requires `docs/security/pentest-signoff.md` (manual §17.13 pen-pass gate).
   - `scripts/release_build.sh` — uv build (PEP 517, ADR-017 setuptools) → wheel+sdist → SHA256SUMS → TC-SEC-07 artifact scan over the exact bytes to be signed; signing documented as manual (minisign, key outside repo).
   - `scripts/security/scan_artifacts.py` — scans BUILT wheel/sdist/tar with the SAME PATTERNS as scan_secrets (import-shared); explicit empty target FAILS (never sign an empty bundle); tarfile filter="data" (3.14 warning clean).
   - `scripts/security/check_dev_default.py` — SEC-N6: `run` parses dev_insecure=False + Settings has NO dev field (env can't enable dev mode).
   - CI `.github/workflows/ci.yml`: release-gate scaffold → real M9 job (on tags): pip install → release_gate.sh --release → release_build.sh → upload-artifact → signing notice.
   - `docs/security/pentest-signoff.md` — TEMPLATE (never pre-signed; unit test pins it).
2. **v1.0.0-rc.1**: pyproject `1.0.0rc1` (PEP 440) ↔ `AGENT_VERSION "1.0.0-rc.1"` (SemVer) + `tests/unit/test_release_engineering.py` pinning SemVer validity, the two-spelling sync, gate-script completeness, SEC-N6 defaults, signoff-template honesty. docs/CHANGELOG.md created (M0→M9 history, Keep-a-Changelog).
3. **ADR-021 (Accepted)** — Go/Rust single-binary decision gate CLOSED: Python kept for v1.0; re-open only via measured-need criteria (installer defect evidence / measured footprint over budget / distribution channel need). ADR index updated (017-021).
4. **M9 decision register** (docs/RELEASE.md): Q-08 license (zeroconf LGPL-2.1-or-later is the only non-permissive dep per WP-02 evidence; recommendation Apache-2.0 + notices — owner legal review; pyproject intentionally has NO license field) + Q-09 distribution (sideload for v1.0 = spec default). QUESTION-108 opened (OPEN, owner).
5. **QA fixes (real bugs from the unverified final M8 commit)**:
   - `security/manual_pairing.py`: `hmac` used at line 138 WITHOUT import → runtime NameError killed every FR-PAIR-07 verify_attempt → added import; `(str, Enum)` → `StrEnum` (UP042).
   - `security/spake2.py` compute_transcript: `_uncompress_encode(_M_POINT)` with `_M_POINT: tuple|None` → fail-closed None guard (mypy --strict + defensive).
   - Lint/format drift: 20 ruff errors + 14 format-diffed files fixed (E402 noqa on sys.path-setup scripts, isort order, E501 wraps, unused imports).
6. **Dashboard round-11**: new "Release engineering (M9 · §21.6)" panel — 9-gate checklist with live badges (pass/announced-skip/pending), built-artifacts card, M9 decision register; milestones M6-M9 → done with honest "agent side / residual owner" details; WP-17..20 rows; gates +5 (release gate, artifact scan, SEC-N6, build+checksums, manual sign-off=pending); securityTests TC-SEC-07/08 → delivered; QUESTION-108; round-11 data; nextSteps rewritten to the owner release path. GateBadge gained a proper "pending" branch.
   - **QA caught a real dashboard bug mid-round**: my new WP rows shipped `reqs` as a STRING while page.tsx maps `wp.reqs` (array) → whole-page client crash ("Application error") → fixed to arrays. Caught by agent-browser, fixed, re-verified.

验证结果:
- `bash scripts/release_gate.sh` → **ALL 14 automated steps PASS**: ruff check+format clean, mypy --strict 23 files clean, unit 345 / contract 3 announced skips / integration 141 / security 33 (519 total, 0 failures), import-linter 3/3 KEPT, drift OK, cleartext VACUOUS PASS / content-column / secret scans OK, pip-audit clean, SEC-N6 OK. Verdict banner honestly states manual pen-test sign-off still pending.
- `bash scripts/release_build.sh` → localmesh_agent-1.0.0rc1 wheel + sdist + SHA256SUMS + artifact scan OK (142+72 files). DeprecationWarning fixed and re-verified under -W error.
- agent-browser: desktop 1280 (sw=1280) + mobile 390 (sw=390, no overflow), zero console errors, footer gap=0 (sticky), WP filter interaction verified, screenshots download/round11-m9-{release-panel,mobile}.png. bun lint clean.

未解决问题/风险，下一阶段建议:
1. **M0–M9 all COMPLETE on the agent/sandbox side.** Owner release path: manual pentest checklist on real hardware → commit pentest-signoff.md → tag v1.0.0-rc.1 (CI builds+scans) → minisign SHA256SUMS → publish.
2. Owner decisions due: Q-08/Q-09 (RELEASE.md register + QUESTION-108), ADR-017/018 approvals, QUESTION-101..107.
3. Environment-gated items unchanged: fixtures capture (flips contract tests to hard gates), real-GPU/LAN/Tailnet validation, Supabase deployment (QUESTION-107), Android WPs 09/10/11-App/12/13.
4. Sandbox note: HEAD reset to main between sessions; commits land on main. agent/dist is gitignored.

---
Task ID: 2-a
Agent: general-purpose sub-agent (mesh-protocol typegen)
Task: Fully implement packages/mesh-protocol so the App data layer can import real generated TS types — a real generator (bun scripts/generate.ts) parsing docs/openapi/mesh-v1.json, emitting types.ts / validators.ts / sse-events.ts / index.ts, plus package.json + strict tsconfig + bun tests + README, all deterministic and drift-checked (§21.3, ADR-015).

Work Log:
- Read worklog tail, LM-ARCH-001 §13 (lines 838-1130, incl. §13.7 SSE wire format), docs/openapi/mesh-v1.json in full (16 paths / 17 operations, 11 components.schemas — AgentInfo/AgentApiInfo/DeviceResponse + sub-blocks, HTTPValidationError/ValidationError), agent/src/localmesh_agent/api/v1/*.py and agent/tests/integration/* for the REAL wire shapes (pairing status tailnet block, task_view, queue_stats, MeshStats.to_api_json, ModelEntry serialization).
- Wrote packages/mesh-protocol/scripts/generate.ts (bun-runnable): parses the OpenAPI export and emits, byte-deterministically — types.ts (components.schemas → sorted interfaces; per-op <Op>Request/<Op>Response; Paths map; MeshApiMethod/MeshApiPath/MeshApiEndpoint literals + MESH_API_PATHS/MESH_API_ENDPOINTS consts; §13.4 ErrorEnvelope; §13-normative narrow response shapes each with source comment), validators.ts (hand-rolled ZERO-dep guards is*/assert* for InfoResponse, pair complete/status, auth challenge/token, ModelsResponse, HealthResponse, DeviceResponse, chat SSE chunk/event union, TaskStatusResponse, ErrorEnvelope + MeshProtocolValidationError), sse-events.ts (MESH_SSE_EVENT_NAMES derived from the OpenAPI chat op docs if present, else §13.7 — incl. a mesh.* token scan because mesh.error never appears as an `event:` line; ChatCompletionChunk + discriminated ChatSseEvent union + [DONE] sentinel), index.ts barrel. Header carries the mandated GENERATED marker + spec sha256; "generation timestamp" = source spec mtime (UTC) so two runs are byte-identical.
- Added package.json (@localmesh/mesh-protocol, type module, main/exports → src/index.ts, scripts gen/test, zero dependencies — zod exists at repo root but hand-rolled guards keep the package importable by Expo without a validator runtime), strict tsconfig.json (types: bun-types), rewrote README.md (regen instructions, export map, honest gap inventory), and packages/mesh-protocol/.gitignore (!test/ — the root .gitignore's bare `test` rule at line 49 silently ignored the package's test dir; root file out of scope so fixed in-package).
- Added test/generated.test.ts (bun test): (1) structure — all 16 path literals, 17 method+path endpoint literals via imported consts, key schema names (AgentInfo/DeviceResponse/ModelEntry/ErrorEnvelope/…), §13.7 vocabulary, guard exports; (2) round-trips of Metadata-only fixtures copied from the repo's real tests/§13 examples (info, pair awaiting + approved-with-tailnet, auth challenge/token, §13.5 models envelope, health+queue, all-nullable device, mesh.meta, role-only chat chunk [NO content text], mesh.stats, §13.4 error envelope, queued task) plus negative cases on ids/enums/state fields; (3) determinism — spawns the generator twice via Bun.spawnSync and asserts committed == run1 == run2 byte-for-byte.
- Fixed during bring-up: narrow-type lookup keyed by op base name (full operationId → duplicate declarations); mesh.error missing from derived vocabulary; TailnetBlock.dns_name now strict-required (nullable) per components.schemas; double-asterisk header cosmetic; unquoted identifier-safe interface keys.

Stage Summary:
- packages/mesh-protocol is a real generated package: regen via `bun packages/mesh-protocol/scripts/generate.ts` (repo root) or `bun run gen` in-package; `bun test packages/mesh-protocol` → 17 pass / 0 fail / 134 expects; `bunx tsc --noEmit -p packages/mesh-protocol/tsconfig.json` → clean (strict). Committed src/ is byte-identical to a fresh generator run (generated-output drift check mirrors scripts/check_openapi_drift.py).
- Types honesty rule held: OpenAPI-typed where the export types, §13-sourced narrow types (each commented with its §) where it doesn't, `unknown` where nothing pins it. App data layer imports one barrel: @localmesh/mesh-protocol.
- Spec gaps noticed (report only, no QUESTION-xxx opened): (1) the OpenAPI export declares NO requestBody for ANY operation — request shapes exist only in §13.2/§13.6/§13.9, so all <Op>Request = unknown; (2) no 4xx/5xx responses / error schema in the export — ErrorEnvelope comes from §13.4; (3) most 2xx untyped (additionalProperties:true) — narrow §13 types cover the safety-critical subset; (4) status-code drift candidates: models/load|unload + POST /tasks declared 200 in export but 202 per §13.2/§13.9 + implementation, PUT attachments declared 200 but Agent returns 204; (5) no securitySchemes — Bearer token + X-Mesh-* headers (§13.3) untyped; (6) tasks SSE event vocabulary not §-pinned (impl emits `event: task`) — deliberately not invented; (7) Agent sends pair/status `endpoints` pre-approval while §13.2 gates device_id/endpoints on `approved` — validator accepts additively (§13.10); (8) root .gitignore bare `test` rule hides any packages/*/test dir (worked around in-package; consider renaming to `tests/` or scoping the rule).
- Governance: fixtures Metadata-only (chat chunk fixture uses delta {role:"assistant"} — never any Content-like payload text); placeholder token strings only, no secrets; nothing outside packages/mesh-protocol/** touched.

---
Task ID: 2-b
Agent: general-purpose sub-agent (timed out; completed & fixed by main agent)
Task: apps/mobile Expo app — §11.1 layout, pure-TS domain (SM-CONN §15.1, race planner §16.1, reasons §18.3, SM-STREAM §15.3, tokens), data layer (§14.2 DB, mesh client, §13.7 SSE), screens, bun-runnable domain tests.

Work Log:
- Agent delivered the full source tree before its context deadline: app/ screens (machines/chats/settings tabs, pair scan+confirm, machine detail, chat, doctor), src/domain (entities, connection/{clock,sm-conn,race-planner,reasons}, sm-stream, tokens), src/data (db/{schema,repositories} §14.2 verbatim, mesh/{client,sse}), src/features (pairing/machines/models/chat/diagnostics/settings), src/state (external stores), src/infra/meshCore.ts (lazy native require + mock), src/ui (theme with UI-spec §3.1 tokens, components), modules/mesh-core/{index.ts,src/MeshCore.types.ts} (normative §11.2 contract). Only 2 of 9 planned test files were written.
- Main agent verified + fixed: (1) test/race-planner.test.ts had 6 failing expectations — 4 test bugs (probe never pushed to startedAt; ordering test used vpnActive:false yet expected the T2 candidate to survive pruning; cellular hint expected CI-09 where §18.2 CI-02 is the exact detection row; r.at expected the 8000 ms deadline although all probes fail at 4250 — deadline is a ceiling, §16.1 "all probes failed ⇒ aggregate") and 2 real impl bugs (paired T2 endpoints with .ts.net hostnames were never generated — §16.1 rule 4 now takes the whole stored T2 pool; wonAt now reports the winner's own first-success time, §16.1 "first := first successful probe at time t").
- Wrote the 7 missing suites: reasons (rank table + verbatim CI map + precedence), sm-stream (§15.3 machine + 401 refresh-once + idle), tokens (80 % refresh, single-flight, memory-only surface introspection), sse (frames/multi-line/CRLF/pings/[DONE]/split chunks + feed idle), qr (§17.4 payload validation + §17.8 confirmation + SAS format), db (REAL SQLite via bun:sqlite: §14.2 CHECK constraints live, FK cascade, PRAGMA user_version migrations, repos), doctor-report (§18.4 ladder order + CI keys + no-Content/no-secrets report), purity (§11.3 layering enforced by scan: domain RN-free, mesh-core only via data/mesh, SQL only in data/db).

Stage Summary:
- apps/mobile source-complete; `bun test apps/mobile` → 141 pass / 0 fail / 418 expects; `bunx tsc --noEmit` clean apart from expected expo*/react-native module resolution (deps install on the build machine). Impl fixes vs spec: §13.7 idle window corrected to "45 s without ANY bytes" (pings are bytes — keeps CI-21 cold loads alive; previously would interrupt healthy streams), mesh.error retryable now read from the §13.4 error envelope, doctor checks TCP before TLS pin (a refused connection can never present a certificate — was mislabelled CI-12), sanitizer preserves separators + consumes scheme+value for authorization/bearer + double-redaction safe.

---
Task ID: 2-c
Agent: general-purpose sub-agent (timed out; completed by main agent)
Task: modules/mesh-core Kotlin — Keystore/PinnedHttp/SseStream/Nsd/NetMonitor/Permissions per §11.2/§17.3/§17.9/§6.4 + tests.

Work Log:
- Agent delivered the 10 main Kotlin sources + build.gradle + manifest + expo-module.config.json + 2 JVM unit tests (B64UrlTest, QrPayloadTest) before its deadline. MeshCoreModule.kt exposes the full §11.2 surface as Expo Functions + Events; typed MeshCoreException codes (PIN_REQUIRED, PIN_MISMATCH, HTTP_REJECTED_CLEARTEXT, TLS_HANDSHAKE_FAILED, IDLE_TIMEOUT, CANCELLED, NSD_ERROR, PERMISSION_REQUIRED + documented [DESIGN] additions); §17.10 discipline in messages (no keys/secrets/content, 12-char pin prefix max).
- Main agent completed the deliverable: instrumented tests (PinnedHttpInstrumentedTest — pin mandatory fail-closed before any socket, cleartext rejected release AND debug-off-host, §17.9 emulator carve-out, TLS 1.3-only server handshake, THE pin-mismatch test asserting PIN_MISMATCH with ZERO request-body bytes on the wire per FR-PAIR-03; NsdInstrumentedTest — fake _localmesh._tcp advertiser with §16.2 TXT, agentFound parse assertions, service-type normalization matrix, aligned to the real NsdDiscovery(emit) API) + README.md with the full §11.2→Kotlin mapping table, OkHttp decision rationale, build/test commands, cert fixture generation, and an honest VERIFICATION STATUS section (no Gradle/SDK in sandbox: compile + instrumented runs = owner).

Stage Summary:
- modules/mesh-core source-complete (10 main + 2 unit + 2 instrumented + README). Kotlin SseStream verified to already implement the correct §13.7 semantics ("any bytes incl. pings reset the watchdog") — the TS side was the deviating one and was fixed.

---
Task ID: 24 — Round 12: M2–M5 App side implemented → ALL milestones M0–M9 GREEN
Agent: Z.ai Code (main agent)
Task: User flagged M2/M3/M4/M5 still yellow on the roadmap = not completed. Completed the App-side scope (WP-09/10/11/12/13 App halves + M4 racing/failover + M5 metrics screen) per §22.1 with full-fledged implementation.

Work Log:
- Verified repo state first: worklog Tasks 20-23 confirmed M6-M9 done; the yellow M2-M5 rows were exactly the App-side residuals (WP-09/10/11-App/12/13-App blocked on "Android build env"). apps/mobile was a placeholder README.
- packages/mesh-protocol (sub-agent 2-a): real generator (bun) parsing docs/openapi/mesh-v1.json → types.ts/validators.ts/sse-events.ts (zero-dep guards, §13.4 ErrorEnvelope, §13.7 SSE vocabulary), deterministic byte-checked regen, 17 tests + strict tsc clean. Spec gaps recorded in its worklog entry (OpenAPI export has no requestBody/4xx5xx/securitySchemes — types sourced from §13 with per-type comments; no QUESTION opened).
- apps/mobile + modules/mesh-core (sub-agents 2-b/2-c, completed + fixed by main): see Task 2-b/2-c entries above.
- Dashboard round 12: status JSON — milestones M2-M5 → done with honest agent+App detail and owner residuals; WP rows merged into spec numbering (WP-09/10/11/12/13/14 all done, zero dupes); new mobileApp section + "Mobile app (M2–M5 App side · §11)" panel (10 module rows, test-suite card, screens, amber device-verification card); stale pytest gate row updated to the round-11 release-gate numbers; nextSteps rewritten to owner release path.
- agent-browser QA: desktop 1280 (sw=1280) + mobile 390 (sw=390 — fixed a real 3px overflow from the Round-12 card: min-w-0 break-words), footer gap=0 at bottom, zero console errors, WP-12 row expand interaction verified, roadmap shows M0-M9 all green with 10/10 complete. Screenshots: download/round12-{desktop-top-green,mobile-panel-desktop,mobile-390,mobile-bottom}.png.
- Gates: bun run lint clean; bun test apps/mobile 141/0; bun test packages/mesh-protocol 17/0; tsc clean (both packages); agent/** untouched → agent gates unchanged (release gate 14/14 PASS from round 11 still stands).

Stage Summary:
- M0-M9 ALL GREEN on the roadmap (agent side M0-M9 + App side M2-M5 source-complete with sandbox-verified domain suite). Remaining = owner/real-env actions only: pentest sign-off → tag v1.0.0-rc.1 → sign/publish; Android device verification (expo prebuild + Gradle + connectedDebugAndroidTest + §18.8 matrix); fixtures capture; Supabase deployment (QUESTION-107); Q-08/Q-09 + ADR-017/018 approvals.

---
Task ID: 25-a
Agent: general-purpose sub-agent
Task: Wire web demo transport — §11.2 MeshCore contract over fetch() (WebMeshCore → /api/localmesh/demo proxy → real Agent, §17.9 dev-insecure loopback) + minimal LIVE data wiring in the exported web app.

Work Log:
- Read worklog tail (Tasks 23/2-a/2-b/2-c/24 conventions), §11.2 MeshCore.types.ts contract, infra/meshCore.ts + MeshCoreMock, data/mesh/client.ts + sse.ts (SseParser REUSED, not duplicated), sm-stream/pipeline machines, stores, screens, purity.test.ts rules (R1–R5), the Next.js proxy route, and the REAL agent wire shapes (api/v1/{info,health,models,chat}.py) + live curl probes of 127.0.0.1:8443 (info/health/models/SSE chat all up).
- NEW src/infra/webMeshCore.ts — WebMeshCore implements the full §11.2 MeshCore surface over fetch(): request() maps logical `…/mesh/v1/X` URLs to `${proxyBase}/X` (query preserved, proxyPathFor exported), JSON body tolerant of empty, timeoutMs via AbortController (TIMEOUT vs NETWORK codes); openStream() fetches the stream, pumps response.body bytes through the pure SseParser (§13.7: mesh.* named events, default OpenAI chunks, `: ping` comments, [DONE]) and emits 'event'/'error'/'closed' — idle watchdog re-arms on EVERY raw read (any bytes incl. partial lines/pings, mirroring the Kotlin SseStream semantics), IDLE_TIMEOUT on byte silence; HTTP ≥ 400 parsed as §13.4 envelope → error code/message; cancel() → AbortController + closed('cancelled'); tlsSpkiSha256B64Url = demo pin (header comment documents sandbox-demo-only: NO TLS/pinning — production keeps native PinnedHttp §17.3); demo key API = documented stubs with no crypto claims; discovery no-op; network wifi/granted/false fixed answers.
- infra/meshCore.ts: added MESH_DEMO_CONFIG {proxyBase '/api/localmesh/demo', logicalBase 'https://demo.agent.local', pin 'demo-pin-loopback'} + getMeshCoreForPlatform() (web → cached WebMeshCore, else native getMeshCore(); MeshCoreMock untouched). Also FIXED a pre-existing tsc error: the type-only import used `../modules/…` (resolves to nonexistent src/modules) → corrected to `../../modules/…` (type-only, so Metro bundling was never affected).
- data/mesh/client.ts: added getMeshApiClient() (§11.3 singleton gateway bound to the demo transport), meshCoreProbes() (§11.2 transport probes for the §18.4 Doctor ladder), DEMO_AGENT_BASE_URL/PIN re-exports, StreamHandle type re-export; refined HealthReport/ModelListResponse to the real §13.2/§13.5 wire shapes (state, capabilities.values, nullable display_name).
- NEW state/agentDataStore.ts (per-agent live status/backends/models + patchAgentModel) and chatsStore helpers (createConversation/appendMessages/setConversationModelRef/patchStreaming + optional StreamingState.meta from mesh.meta).
- NEW features/machines/live.ts — refreshAgentData(): /info → upsert PairedAgent + SM-CONN CONNECTED(T0) (web transport has no race planner; reachability IS the connection), /health + /models best-effort into the store; /info failure → existing empty/offline states (UNREACHABLE/TIMEOUT_LAN on stale rows); toDomainModels (§13.5 state→loaded), backendLine/modelLine card lines, firstChatModelId.
- NEW features/chat/send.ts — sendMessage()/cancelStream(): SM-STREAM (§15.3) + StreamBatcher (§16.7 80 ms) over MeshApiClient.openChatStream (first/loaded model from /models, model:auto honored by agent routing); frame routing: ping→SM idle re-arm, chunk delta.content→transcript via SM deltas, mesh.meta→model/backend labels (conversation.modelRef + streaming meta), mesh.stats→Message.stats (Metadata only), mesh.error→SM error path, transport failures→synthetic §13.4 envelopes; Stop→cancelled with partial retained.
- NEW features/diagnostics/live.ts — buildWebDoctorDeps(): network/permission/Tailscale-hint probes + candidate probe via client /info (dns/tcp reported as implied-by-reachability, pin asserted client-side; discovery honestly false — mDNS is native-only), auth/health/backend checks, all internally caught.
- Screens (web-gated, graceful): machines.tsx (mount + pull-to-refresh refresh; live hardware/model card lines); machine/[agentId].tsx (live models with Load/Unload buttons — optimistic flag + applyModelOpResponse/modelOpNotice error surface; live backend status chips; Start chat → createConversation + router.push); chat/[conversationId].tsx (Composer onSend/onStop wired to send.ts; mesh.meta labels on the streaming bubble; refresh for direct navigation; existing error Banner/Retry reused); doctor.tsx (web → buildWebDoctorDeps, native → previous honest-static ladder).
- NEW test/web-mesh-core.test.ts (bun, 8 tests): URL mapping (query/base-slash variants), request round-trip + POST body + empty-204 tolerance + pin echo, full SSE framing against a local Bun.serve byte stream (mesh.meta/chunks/ping/mesh.stats/[DONE] → closed('done')), HTTP 404 §13.4 envelope → MODEL_NOT_FOUND error event, IDLE_TIMEOUT watchdog, cancel → closed('cancelled') with no error, fixed demo answers. Governance: no new deps, no logging, no Content/secrets (§17.10); purity rules R1–R5 verified green.

Stage Summary:
- bun test apps/mobile → 149 pass / 0 fail / 449 expects (141 pre-existing + 8 new; purity suite green). bunx tsc --noEmit (apps/mobile) → CLEAN (zero errors; the two pre-existing TS2307 module-resolution errors in infra/meshCore.ts were the broken `../modules` type-import path and are now fixed).
- Verified end-to-end against the REAL agent (one-off Bun.serve mimic of the Next proxy → WebMeshCore): /info 200 "WP15 Smoke PC", /health 200 ok (lmstudio:up, ollama:up), /models 200 (4 models), chat SSE → mesh.meta(model=ollama::qwen-fake:7b, backend=ollama) → deltas "Hello from fake Ollama." → mesh.stats → [DONE] → closed(done).
- What works on the web virtual device after re-export: one live machine card (name from /info, backend count/status from /health, model count from /models, Wi-Fi/online chip); machine detail with live model rows + load/unload and backend status chips; Start chat → conversation → send → REAL streamed reply with model/backend labels, Stop (partial kept), error surfaces; Doctor ladder with live results. Web-only by Platform.OS==='web' gates; native paths and MeshCoreMock untouched.
- Deliberately skipped: expo export (main agent), DB persistence of conversations/messages (in-memory stores, repos = later WP), pairing/auth-token flows (dev-insecure loopback bypasses auth per QUESTION-105), tasks/attachments UI, mDNS discovery on web (native-only), tokens/s display in chat bubbles (stats retained on the Message only).

---
Task ID: 25
Agent: Z.ai Code (main agent + general-purpose sub-agent 25-a)
Task: User directives — (1) attempt real SDK build of the Android app, (2) create a virtual emulator, (3) full real-scenario sandbox, (4) app name "Local Mesh AI" approved, (5) contextual-engineering MD handovers, (6) enhance + code QA without mess.

Work Log:
- Recon: Java 21 present, no /dev/kvm, dl.google.com/maven/npm reachable, 4GB RAM, 10GB disk (the binding constraint).
- Android SDK installed (platform-tools, android-35, build-tools 35.0.0; android-37.0 via cmdline-tools 13114758 — SDK 37 ships as minor-version packages AGP<9 cannot register; symlink proved insufficient, mesh-core compileSdk falls back to root's 35 with string-constant + SDK_INT guards, behaviour identical §6.4).
- expo deps installed; web export initially failed → real source bugs fixed: app/doctor.tsx wrong relative depth (../../src → ../src), undeclared expo-status-bar, missing peer query-string. RN/React aligned to SDK 52 pairing (0.76.9 / 18.3.1) after expo-modules-core Kotlin failed against RN 0.77.
- APK attempts: 7 builds. Blockers solved then final: NDK 26.1 (~2GB) installed via a NEW streaming HTTP-range zip extractor (scripts/stream_unzip.py, resume + retry); disk hit 0 repeatedly (transforms ~1.6GB). Result: `:mesh-core:assembleDebug` BUILD SUCCESSFUL (48s) after fixing 6 real Kotlin bugs: KeyGenerator wrong package + JDK initialize→Android init, hardwareBackedOf expression-body return, 9× promise.reject 2-arg→3-arg, requestPermission→askForPermissions PermissionsResponseListener mapping, PinnedHttp javax.net→javax.net.ssl.HostnameVerifier, Nsd getHostAddress removed-in-34 → reflection fallback, missing brace. Full :app assembleDebug remains physically impossible in-sandbox (needs ~1GB beyond ceiling) — owner recipe in RUN-BOOK §2b.
- Virtual emulator (no KVM possible): react-native-web export of the REAL app + Next route src/app/virtual-device/[[...path]]/route.ts serving apps/mobile/dist (public/ rejected: dev server prunes _expo dirs) + <head> bootstrap replaceState to /machines (no index route; router base path). Fixed query-string@9 ESM→7.1.1 CJS (o.stringify TypeError).
- Live demo bridge: Next catch-all /api/localmesh/demo/* → 127.0.0.1:8443 (agent run --dev-insecure-loopback §17.9) with SSE passthrough; fake LM Studio :1234 + fake Ollama :11434; full chain verified (chat SSE via curl + browser).
- Sub-agent 25-a: WebMeshCore (§11.2 over fetch, SSE parser reuse, idle watchdog), getMeshCoreForPlatform, agentDataStore, features live.ts (machines/chat/doctor), screens wiring; 149 tests pass (8 new), tsc clean.
- Dashboard: VirtualDevicePanel (phone frame iframe, live agent badge, reload/full-screen), package ai.localmesh.app, app name "Local Mesh AI" (app.json; closes Q-02 name half).
- QA via agent-browser: dashboard 10/10 green + panel live (agent badge, machine card, detail with live model Load/Unload states + backend chips, chat screen with real streamed reply "Hello from fake Ollama." via bridge→agent→fake backend); fixed SM-STREAM onClosed (reason 'done' → complete, §15.3) after observing 'interrupted'; re-tested to clean completion.
- Code QA: jscpd 0.12% (1 clone in GENERATED validators.ts — determinism forbids hand edits); ruff F401/F811/F841 clean; tsc noUnusedLocals scan → 8 dead-code items fixed (2 screens, confirm.tsx, race-planner hostOf/t0, useThemeMode React, 2 test helpers); 149/149 re-verified.
- Handovers: docs/handover/AGENT-BRIEF.md (role→mission→constraints→map→state→commands→traps→DoD) + docs/handover/RUN-BOOK.md (sandbox scenario, APK recipes sandbox+owner, virtual device rebuild, fixtures, release path).
- Disk saga (documented for future agents): bun global agent-browser lives in .bun/install/global — deleting .bun/install breaks it; gradle modules-2 (1.1GB) deleted = sandbox APK rebuilds off the table; venv/@mermaid-js are image-layer (deletion frees nothing).

Stage Summary:
- M0–M9 all green AND now: real toolchain-verified Kotlin (AAR builds), interactive virtual device running the real app against the real agent, full QA'd dashboard panel, named app (Local Mesh AI / ai.localmesh.app), 149+17+agent gates green, contextual handover docs ready for the owner's local coding agent. Owner residuals unchanged: device matrix §18.8, fixtures, pentest+release, ADR approvals.

---
Task ID: R14-OSS-PUBLISH
Agent: Z.ai Code (main agent, session web-70b12970)
Task: Publish the repository to https://github.com/EquityAviator/LocalMesh-App as a fully adjusted open-source project (README, license, contributing/conduct/security docs, PR + issue templates, repo metadata), per owner directive ("push that on main and adjust it accordingly as a whole open source project").

Work Log:
- Analyzed the repo before publishing: 599 tracked files; verified git history never contained real secrets (.env only ever held a local DATABASE_URL line).
- Fixed SEC-N5 scanner false positive: added the missing `secrets-scan: allow(pem-private-key)` annotation on the instrumented-test PEM-header literal (fixture parser; no key material committed).
- Fixed SEC-N1 scanner: implemented the documented §17.9 debug-only exception by Android source set — cleartext under `src/debug/` is a NOTICE (debug-variant-only), main/release remains a hard FAIL.
- Resolved Q-08 (owner directive): license = Apache-2.0 (M9 decision-brief recommendation). Added LICENSE (full text), `agent/pyproject.toml` `license = "Apache-2.0"`, `docs/THIRD-PARTY-NOTICES.md` (zeroconf LGPL-2.1-or-later obligations, CON-03), updated QUESTION-108 + RELEASE.md decision register.
- Wired the two CI placeholder gates that activate now that the projects exist: npm audit (apps/mobile) + Android debug APK build (JDK 17 + bun frozen lockfile + gradlew assembleDebug).
- OSS hygiene: untracked sandbox artifacts (.env, tool-results/, .zscripts/, research/ duplicate of docs/spikes evidence, upload/, download/, qa-*.png, --width); moved founding docs to docs/spec/ (ARCHITECTURE-DESIGN, ANDROID-UI-SPECIFICATION) and docs/research/ (feasibility + deep-research reports); extended .gitignore.
- DISCOVERY: the publishing fine-grained PAT lacks the "Workflows" permission — GitHub rejects any push whose ref-diff creates .github/workflows/*.yml. Mitigation: relocated the fully wired pipeline to docs/ci/PR-GATE.yml with a one-command restore path in docs/ci/README.md (restore as PR once the token includes the Workflows permission).
- Pushed full history to main (replaced the GitHub auto-init MIT placeholder per Q-08 Apache-2.0 decision; force-with-lease pinned to the auto-init SHA).
- OSS surface delivered via PROPER PR FLOW: branch `docs/open-source` → PR #1 → merged (merge commit a10cd65). README (pitch, architecture diagram, M0–M9 table, quickstart, gate chain), CONTRIBUTING (spec-driven workflow, gate commands, commit style), SECURITY (private advisories, scope), CODE_OF_CONDUCT (Covenant 2.1), .github PR/issue templates (SEC-N checklist, Content-redaction rule).
- Repo metadata set via API: description, topics (local-llm, privacy, android, fastapi, ollama, tailscale, mdns, ...), merged-branch auto-delete enabled.
- Local gates re-run and green before each commit: OpenAPI drift (required pinning sandbox pydantic/fastapi to 2.13.5/0.142.2 — sandbox venv was stale), cleartext, content-columns, secrets scans.

Stage Summary:
- github.com/EquityAviator/LocalMesh-App is PUBLIC: main = a10cd65 (PR #1 merged), Apache-2.0, full OSS onboarding surface, topics set.
- Commits: a4f762e (publish readiness), 9553cda (CI staging under docs/ci), 885ed52 (OSS docs, merged via PR #1).
- OPEN: CI workflow restoration needs a token with the Workflows permission (docs/ci/README.md has the exact commands); pentest sign-off + §18.8 real-device matrix unchanged; owner should ROTATE the fine-grained PAT since it was shared in chat.
- Security note: the PAT was used inline in push URLs only (never persisted to .git/config, never committed).
