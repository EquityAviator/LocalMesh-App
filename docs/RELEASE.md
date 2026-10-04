# Release process & gates (M9, §21.6, §22.1)

## Versioning

- Agent: `agent/src/localmesh_agent/app.py` `AGENT_VERSION` (SemVer,
  NFR-COMP-02), surfaced via `GET /info.api.agent_version`. The PEP 440
  spelling in `agent/pyproject.toml` must describe the SAME release
  (`1.0.0-rc.1` ↔ `1.0.0rc1` — pinned by `tests/unit/test_release_engineering.py`).
- Mesh API: `/mesh/v1` is stable within a major (§13.10); breaking changes
  require `/mesh/v2` alongside + `info.api.versions` listing both.

## One-command gate runner (M9)

```bash
bash scripts/release_gate.sh             # automated gates only (dev runs)
bash scripts/release_gate.sh --release   # + requires the pentest sign-off file
bash scripts/release_build.sh            # wheel + sdist + SHA256SUMS + artifact scan
```

`--release` fails without `docs/security/pentest-signoff.md` (template
committed; the operator fills it from the manual section of
`docs/security/pentest-checklist.md` BEFORE tagging). The tag CI job runs
exactly these two scripts (`.github/workflows/ci.yml` `release-gate`).

## Release gates (ALL must be green before signing/tagging)

1. **Unit layer:** `bash scripts/pytest_layer.sh agent/tests/unit`
2. **Contract layer:** `bash scripts/pytest_layer.sh agent/tests/contract`
   — HARD GATE: recorded real-Backend fixtures must exist (CAPTURE.md).
3. **Integration layer:** `bash scripts/pytest_layer.sh tools/fake-backends/tests agent/tests/integration`
4. **Security layer (§17.13):** `bash scripts/pytest_layer.sh agent/tests/security`
   — includes TC-SEC-05 fuzz, TC-SEC-07 release manifest scans, TC-SEC-08
   Content-column scan, TC-SEC-10 TLS 1.3 handshakes, FR-PAIR-07 RFC vectors.
5. **Import-linter (§10.1):** `cd agent && lint-imports --config .importlinter`
6. **Typecheck (§21.2):** `mypy --strict src/localmesh_agent/core src/localmesh_agent/security`
7. **Lint:** `ruff check --config agent/pyproject.toml agent tools scripts`
8. **OpenAPI drift (§21.3):** `python scripts/check_openapi_drift.py`
9. **Pen-test checklist:** `docs/security/pentest-checklist.md` manual section
   signed off by the operator.

## Build & sign

```bash
# 1. Build the wheel (the Agent is a wheel/pipx install; ADR-002, §21.6).
cd agent && python -m build

# 2. Manifest + checksums.
sha256sum dist/* > SHA256SUMS

# 3. Sign (minisign shown; cosign/sigstore acceptable — ADR-tracked swap).
minisign -Sm SHA256SUMS
# Publish dist/*, SHA256SUMS, SHA256SUMS.minisig and the minisign public key.
```

The signature key lives OUTSIDE the repository (hardware token or encrypted
keyring); TC-SEC-07 scans the manifest for accidentally committed keys.

## Install paths (packaging/)

- Windows: `packaging/windows/install-agent.ps1` — service + FR-AGT-05
  Private-profile-only firewall rule + data-dir ACL.
- Linux: `packaging/systemd/localmesh-agent.service` — hardened non-root unit.

## Post-release

- Verify the admin `GET /admin/doctor` ordered checks (§18.4) on the target
  host; keep `docs/CHANGELOG.md` current for every release.
- Go/Rust single-binary rewrite: decision gate CLOSED at M9 — Python kept for
  v1.0 (ADR-021); re-open only via ADR-021's measured-need criteria.

## M9 decision register (owner calls surfaced at M9 — still OPEN)

These are owner decisions per the LM-ARCH-001 open-questions table (§ "Q-08",
"Q-09": "decided at M9"). M9 ships the decision BRIEF and the ready-to-flip
state; the final call is recorded here by the owner.

- **Q-08 Project license (permissive vs copyleft).** Facts from the WP-02
  report (evidence-cited): the only non-permissive Agent dependency is
  `zeroconf` (LGPL-2.1-or-later, CON-03); everything else is permissive.
  Recommendation (needs owner legal review, not a decision by the dev agent):
  a permissive project license (Apache-2.0 suggested for the patent grant)
  with mandatory redistribution of the zeroconf license text and notices; a
  copyleft choice would be simpler to reason about but reduces embedding
  freedom the spec's CON-03 note implies. `agent/pyproject.toml` intentionally
  still has NO `license` field; adding it is a one-line change once decided.
- **Q-09 Distribution channel.** Spec default: sideload/F-Droid. Suggestion:
  keep sideload for v1.0 (zero fee, matches the spec default); Play Store
  ($25 one-time, owner cost) stays open as a later add-on and does not block
  rc.1. Android-side WP-09/10/12/13 remain gated on the owner's Android
  environment regardless of channel.
