# Contributing to Local Mesh AI

Thanks for your interest! This is a **spec-driven** project: the architecture
specification is the source of truth, and both code and process exist to keep
it enforceable. Reading this file top-to-bottom is the fastest way to become
productive.

## 0. Ground rules (read once, save hours)

1. **The spec wins.** Precedence when sources conflict:
   ADRs → API/DB/state contracts (§13–15) → Requirements (§7) →
   component designs (§10–12, §16) → narrative → your prior knowledge.
   See [AGENTS.md](AGENTS.md) (the always-loaded digest).
2. **Never invent.** Endpoints, fields, flags, package names/versions: if you
   don't know, look it up in official docs, or open a `QUESTION-xxx` entry in
   [docs/OPEN_QUESTIONS.md](docs/OPEN_QUESTIONS.md) and stop that sub-task.
   Model metadata is **never guessed** from names — emit `null` +
   `source:"unknown"`.
3. **No new dependency without an ADR.** Exact versions are pinned from the
   registry lockfiles (`agent/requirements.txt`, `bun.lock`) — never typed
   from memory (§17.11).
4. **Contracts change via proposal (§1.5):** edit doc → regenerate OpenAPI →
   update types → update tests. `scripts/check_openapi_drift.py` must stay
   green.
5. **Security non-negotiables (SEC-N1…N6)** in [AGENTS.md](AGENTS.md) are
   merge-blocking. Highlights: no cleartext outside loopback/debug, backends
   loopback-only, no Content in logs/Control-Plane, LAN position is never
   authorization, secrets stay in their store, no dev mode by default.

## 1. Environment setup

Prerequisites: **Python 3.12**, **bun** (or Node ≥ 20 for the mobile app),
**JDK 17** + Android SDK (only for the APK), **GNU make-like shell**.

```bash
git clone https://github.com/EquityAviator/LocalMesh-App.git
cd LocalMesh-App

# Agent (pinned + hashed lockfile, §17.11)
python3.12 -m venv .venv && source .venv/bin/activate
python -m pip install -r agent/requirements.txt
python -m pip install -e 'agent/[dev]'      # ruff, mypy, pytest, import-linter, pip-audit

# Mobile app
cd apps/mobile && bun install && cd ..

# Dashboard (dev cockpit)
bun install
```

## 2. Run it locally

Follow the verified recipes in [docs/handover/RUN-BOOK.md](docs/handover/RUN-BOOK.md).
Short version:

```bash
# fake backends (no GPU needed)
(cd tools/fake-backends && python3 fake_lmstudio.py --port 1234 &)
(cd tools/fake-backends && python3 fake_ollama.py  --port 11434 &)

# agent in dev-loopback mode (§17.9; default mode is TLS 1.3)
(cd agent && PYTHONPATH=src python3 -m localmesh_agent run --dev-insecure-loopback &)
curl -s http://127.0.0.1:8443/mesh/v1/health
```

## 3. Branches & commits

- Branch names: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`, `spike/<topic>`.
- Commit message style (spec-ID references are mandatory):

  ```
  feat(agent): SSE chat stream [FR-CHAT-01, API-CHAT-01]
  fix(mobile): rebind SSE on stale Token 401s [§15.3, FR-SEC-05]
  ```

  Reference the requirement/section IDs your change implements or touches.
  Sandbox/UI-only work may tag `[sandbox-surface]`.
- One logical change per PR. Contract changes deserve their own PR.

## 4. Before you open a PR — the gate chain

All of these must pass locally (CI runs the same chain — [docs/ci/PR-GATE.yml](docs/ci/PR-GATE.yml)):

```bash
ruff check --config agent/pyproject.toml agent tools scripts
ruff format --check --config agent/pyproject.toml agent tools scripts
cd agent && mypy --strict src/localmesh_agent/core src/localmesh_agent/security && cd ..
bash scripts/pytest_layer.sh agent/tests/unit
bash scripts/pytest_layer.sh agent/tests/contract
bash scripts/pytest_layer.sh tools/fake-backends/tests agent/tests/integration
bash scripts/pytest_layer.sh agent/tests/security
PYTHONPATH=agent/src lint-imports --config .importlinter   # §10.1 dependency rule
python scripts/check_openapi_drift.py
python scripts/security/scan_cleartext_manifest.py          # SEC-N1
python scripts/security/scan_content_columns.py             # SEC-N3 / CON-02
python scripts/security/scan_secrets.py                     # SEC-N5
bun test apps/mobile packages/mesh-protocol
```

Mobile (JS/Kotlin) changes additionally:

```bash
cd apps/mobile && bunx tsc --noEmit          # strict TS
cd android && ./gradlew assembleDebug        # JDK 17 (Kotlin compiles in CI too)
./gradlew --no-daemon connectedDebugAndroidTest   # when touching mesh-core (device/emulator)
```

## 5. PR checklist

- [ ] Scope matches the milestone/WP you claim; no unrelated reformatting.
- [ ] Tests cover the behavior (layer per §21.5); deterministic (simulated clock, no sleeps).
- [ ] Spec IDs in title/commits; docs updated (spec → ADR → README when applicable).
- [ ] No Content in logs, fixtures, or test data (SEC-N3).
- [ ] New dependency ⇒ new ADR + pinned lockfile update (§17.11).
- [ ] Gate chain (above) green.

PR template: [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md).

## 6. Where things live

| Need | Go to |
| --- | --- |
| Architecture / requirements | [docs/LocalMesh_AI_Architecture_and_Requirements.md](docs/LocalMesh_AI_Architecture_and_Requirements.md) |
| One-page rules digest | [AGENTS.md](AGENTS.md) |
| Decisions (ADRs) | [docs/adr/](docs/adr) (template included) |
| Open questions | [docs/OPEN_QUESTIONS.md](docs/OPEN_QUESTIONS.md) |
| Run / build recipes | [docs/handover/RUN-BOOK.md](docs/handover/RUN-BOOK.md) |
| Release engineering | [docs/RELEASE.md](docs/RELEASE.md) |
| Original design docs | [docs/spec/](docs/spec), [docs/research/](docs/research) |

## 7. License

By contributing you agree your contributions are licensed under the
Apache-2.0 license of this repository ([LICENSE](LICENSE)).
