# agent/tests/security

Security tests per §17.13 (TC-SEC-*, "must exist before M9").

| Entry | File | Scope |
| --- | --- | --- |
| TC-SEC-01 canary | `test_canary.py` | Unique canary prompt → no Content at rest / in logs / stdout |
| TC-SEC-03 replay | `test_tc_sec_03_09.py` | Pairing proof replay 403; valid proof while LOCKED → 429; captured signature vs fresh challenge → 401; challenge reuse → 401; token replay after revoke → 401 |
| TC-SEC-04 revoke | `../integration/test_pairing_auth.py` (`test_revocation_during_stream_*`) | Revoked device blocked + stream killed ≤ 5 s |
| TC-SEC-05 unauth fuzz | `test_tc_sec_05_fuzz.py` | Deterministic corpus over every public route (from the app's own OpenAPI schema): 4 auth variants × 7 body variants → never 5xx, exact §13.4 envelope, zero attacker-input reflection, no Traceback; admin listener fail-closed matrix (fake Host → 403, missing/wrong `X-Admin-Token` → 401); route-set containment pinned |
| TC-SEC-06 admin Host | `../integration/test_pairing_auth.py` (`test_admin_requires_token_and_rejects_bad_host`) | Host-header/DNS-rebinding + token negative paths |
| TC-SEC-07 release manifest | `test_tc_sec_07_release_manifest.py` | Secret/cleartext/Content-column scans over the tracked release surface + release-bundle compilability; M9 addition: `scripts/security/scan_artifacts.py` scans the BUILT wheel/sdist (release_build.sh) — detection/clean/empty-bundle behaviour covered here |
| TC-SEC-08 CP schema | `test_tc_sec_08_cp_schema.py` | Content-column scan of the shipped Control-Plane schema (delivered M6, ADR-019) |
| TC-SEC-09 rate-limit/lockout | `test_tc_sec_03_09.py` | /info 30/min → 429; /auth/challenge 10/min → 429; PAIRING_LOCKED after 5 bad proofs |
| TC-SEC-10 TLS 1.3-only | `test_tc_sec_10_tls13.py` | Real handshakes against the production context (`security.tls.build_tls13_server_context`): TLS 1.3 client negotiates TLSv1.3 + 1.3 cipher suite; TLS 1.2-only client rejected closed on BOTH sides; `minimum_version` pinned to TLSv1_3 |

Pending (needs non-sandbox inputs): TC-SEC-02 (pin-mismatch on-device, mesh-core —
the AGENT side of §17.5 rotation exists: `POST /admin/tls/backup-pin` stages the
next pin, `/auth/token` pre-announces `pin_backup`). TC-SEC-07's Android
release-manifest leg activates when apps/mobile exists (agent-side artifact
scan is delivered above). The M9 release gate (`scripts/release_gate.sh
--release`) additionally enforces the manual pen-pass sign-off.
