<!--
LocalMesh AI is spec-driven. Reference the requirement/section IDs your
change implements (e.g. FR-CHAT-01, §15.3, SEC-N4, ADR-015). Contract
changes need a §1.5 change proposal and a green OpenAPI drift check.
-->

## Summary

<!-- What does this PR do, in 2–4 sentences? -->

## Spec references

<!-- Requirement / section / ADR IDs, e.g. [M5, §16.1, FR-CONN-02] -->

## Change type

- [ ] feat (new capability)
- [ ] fix (bug)
- [ ] contract change (API/DB/state — requires §1.5 proposal + regenerated OpenAPI/types)
- [ ] docs
- [ ] tests / QA
- [ ] chore / CI

## How was it tested?

<!-- Paste the gate-chain commands you ran and their results. -->

- [ ] `bash scripts/pytest_layer.sh agent/tests/unit`
- [ ] `bash scripts/pytest_layer.sh agent/tests/contract`
- [ ] `bash scripts/pytest_layer.sh tools/fake-backends/tests agent/tests/integration`
- [ ] `bash scripts/pytest_layer.sh agent/tests/security`
- [ ] `python scripts/check_openapi_drift.py` (ADR-015)
- [ ] Security scanners: cleartext (SEC-N1) / content-columns (SEC-N3) / secrets (SEC-N5)
- [ ] `bun test apps/mobile packages/mesh-protocol`
- [ ] Kotlin: `./gradlew assembleDebug` (+ `connectedDebugAndroidTest` if mesh-core changed)

## Security checklist (SEC-N1…N6, merge-blocking)

- [ ] No cleartext outside loopback/debug source sets
- [ ] No Content in logs, crash reports, fixtures, or Control Plane
- [ ] No secrets in code (scanners must pass); keys stay in their store
- [ ] No new dependency without an ADR + pinned lockfile (§17.11)
- [ ] Dev-insecure mode stays opt-in (SEC-N6)

## Docs

- [ ] Spec/ADR/README updated where the change alters behavior or contracts
