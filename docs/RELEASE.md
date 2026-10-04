# Release process & gates (M9, §21.6, §22.1)

## Versioning

- Agent: `agent/src/localmesh_agent/app.py` `AGENT_VERSION` (SemVer,
  NFR-COMP-02), surfaced via `GET /info.api.agent_version`.
- Mesh API: `/mesh/v1` is stable within a major (§13.10); breaking changes
  require `/mesh/v2` alongside + `info.api.versions` listing both.

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
- Go/Rust single-binary rewrite remains an OPTIONAL later decision (ADR-002,
  §23) — revisit only with measured need (distribution size / startup time).
