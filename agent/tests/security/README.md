# agent/tests/security

Security tests per §17.13 (TC-SEC-*, "must exist before M9").

| Entry | File | Scope |
| --- | --- | --- |
| TC-SEC-01 canary | `test_canary.py` | Unique canary prompt → no Content at rest / in logs / stdout |
| TC-SEC-03 replay | `test_tc_sec_03_09.py` | Pairing proof replay 403; valid proof while LOCKED → 429; captured signature vs fresh challenge → 401; challenge reuse → 401; token replay after revoke → 401 |
| TC-SEC-04 revoke | `../integration/test_pairing_auth.py` (`test_revocation_during_stream_*`) | Revoked device blocked + stream killed ≤ 5 s |
| TC-SEC-06 admin Host | `../integration/test_pairing_auth.py` (`test_admin_requires_token_and_rejects_bad_host`) | Host-header/DNS-rebinding + token negative paths |
| TC-SEC-09 rate-limit/lockout | `test_tc_sec_03_09.py` | /info 30/min → 429; /auth/challenge 10/min → 429; PAIRING_LOCKED after 5 bad proofs |

Pending (needs non-sandbox inputs): TC-SEC-02 (pin-mismatch on-device, mesh-core),
TC-SEC-05 (unauth fuzz matrix), TC-SEC-07/08 (release manifest scans activate at
Android/Control-Plane inputs), TC-SEC-10 (TLS 1.3-only asserted in the WP-08
real-process smoke; a repeatable pytest entry follows the TLS serving work).
