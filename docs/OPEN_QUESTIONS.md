# Open Questions (QUESTION-xxx)

Agents append new questions here instead of guessing (LM-ARCH-001 §1.2, AGENTS.md
"Stop and ask"). One entry per question. A QUESTION-xxx stops the sub-task that
raised it; other work continues.

Format (append below, keep reverse-chronological order — newest first):

```
## QUESTION-<next-number> — <short title>
- Date: <YYYY-MM-DD>
- Raised by: <WP/task>
- Question: <what needs a human decision?>
- Context/evidence: <spec sections, fixture or registry evidence, code paths>
- Why we must not guess: <what could go wrong>
- Default if unanswered: <safe fallback, or "none — blocks <milestone>">
- Status: OPEN | ANSWERED (<answer summary>) | SUPERSEDED (by <id>)
```

Seed numbering continues from the spec's own open questions (Q-01…Q-12, LM-ARCH-001
§24); agent-raised questions use QUESTION-101 onwards to avoid ID collisions.

## QUESTION-105 — Does `--dev-insecure-loopback` (§17.9) waive Device Token auth?
- Date: 2026-10-04
- Raised by: WP-15 smoke QA (real uvicorn process on the dev loopback)
- Question: §17.9 sanctions `--dev-insecure-loopback` (cleartext HTTP on
  127.0.0.1 only, debug builds, SEC-N6 gate) but does NOT say whether the
  loopback listener still requires Device Token auth under §17.7 ("each
  handler checks scope server-side") or may auto-authenticate as a
  per-process Device. Which is intended?
- Context/evidence: `agent/src/localmesh_agent/api/deps.py` implements the
  bypass — dev-insecure returns `Principal(dev_device_id, DEFAULT_SCOPES)`
  without a Bearer header (M1-compat reading, kept deliberately in WP-08 per
  worklog "dev-insecure 路径保留（M1 测试兼容）"). The CLI banner at
  `agent/src/localmesh_agent/cli.py` previously printed "token auth ON" for
  this mode, which contradicts the implemented behavior (banner reworded in
  the WP-15 round, behavior left untouched pending the answer). The public
  TLS listener always enforces tokens (§17.7/§17.8); production default is
  unaffected (§17.9 OFF by default, SEC-N6).
- Why we must not guess: making dev mode token-required would change M1-era
  developer workflows and tests; leaving the bypass unconfirmed risks a
  spec deviation living silently in the auth dependency.
- Default if unanswered: keep the M1-compat bypass (dev-only, loopback-only,
  OFF by default), banner now describes it accurately.
- Status: OPEN

## QUESTION-104 — `tailscale status --json` field names unverified against a real install
- Date: 2026-10-04
- Raised by: WP-14 (TailnetProbe adapter, §6.3/§18.6/§22.3)
- Question: §6.3 marks the CLI contract `[ASSUMPTION — verify against installed
  version]`: "`tailscale status --json` is expected to expose `BackendState`,
  `Self.TailscaleIPs`, `Self.DNSName`". No tailscale binary exists in the dev
  sandbox, so the recorded-output contract test
  (`agent/tests/contract/test_tailscale_vs_fixtures.py`) ships as an announced
  skip until an owner capture lands (docs/fixtures/CAPTURE.md §3). Please
  confirm the field names (and value casing, e.g. `BackendState: "Running"`)
  on a real install, or provide the capture.
- Context/evidence: LM-ARCH-001 §6.3 (CLI row), §22.3 WP-14 ("Probe parse
  tests with recorded `tailscale` output"; "Stop-and-ask if: Tailscale JSON
  differs"), Appendix G (UNVERIFIED → recorded-fixture test or QUESTION);
  parser at `agent/src/localmesh_agent/adapters/tailscale.py` implements the
  documented shape defensively (missing/renamed fields → unknown-info, never
  exception; IPs filtered to 100.64.0.0/10 per §6.3 addressing; IPv6 dropped
  per §16.2/CI-25).
- Why we must not guess: the parser output feeds the pairing QR `ep` list and
  `endpoints.tailnet` (§13.2/§18.6) — a wrong field name would silently report
  `null` (or, worse, mis-parse) on real installs; §22.3 explicitly fences this
  as a stop-and-ask condition.
- Default if unanswered: parser keeps the §6.3 documented shape; contract test
  stays an announced skip; surfaces degrade to `tailnet: null` / doctor
  "unknown" (LAN-only guidance, §18.5). Not blocking M4 Agent-side work.
- Status: OPEN

## QUESTION-103 — WP-08 underspecified protocol/admin-surface details
- Date: 2026-10-04
- Raised by: WP-08 (pairing/auth/admin implementation)
- Implementation note (2026-10-04, WP-11): item 5 is now implemented — the QR
  `ep` list leads with `https://<lan-ip>:<listen.port>` resolved via the §16.2
  interface selection (hostname form kept as fallback). The wire-format items
  1-4 remain OPEN pending owner confirmation.
- Question: LM-ARCH-001 leaves several WP-08 details open. Please confirm (or
  correct) the interpretations shipped with WP-08:
  1. **HMAC framing of string IDs** (§13.2): `agent_id`/`pair_id`/`device_id`/
     `challenge_id` are framed as their UTF-8 bytes verbatim (prefixes included);
     `client_nonce` and SPKI/DER values as raw bytes.
  2. **Auth-message nonce encoding** (§13.2 API-AUTH-02): the message is
     `"\n"`-joined UTF-8 text, so `nonce` appears as its base64url (no padding)
     STRING as issued — raw 32 bytes would break the "(UTF-8)" property.
  3. **Pair/status after terminal states** (§15.2 vs §13.2 API-PAIR-02): §15.2
     destroys the secret on DENIED/EXPIRED/LOCKED entry, but §13.2 defines
     pollable `denied`/`approved` statuses and §15.4 shows the phone polling
     after the decision. Shipped behaviour: DENIED/APPROVED keep the secret for
     a 60 s delivery window (then close); EXPIRED/LOCKED destroy immediately and
     answer 410/429; a JUST-expired session answers 410 (FR-PAIR-02 "use after
     TTL → 410") via a (pair_id, until) tombstone that never holds the secret.
  4. **Admin route names** beyond the spec-named `POST /admin/tls/rotate` (§17.5):
     §15.4/§15.6 name the operator ACTIONS but not paths. Shipped (loopback-only,
     rename-safe): `POST /admin/pair/open|approve|deny|close`, `GET
     /admin/pair/pending`, `GET /admin/devices`, `POST
     /admin/devices/{id}/revoke`, `POST /admin/tls/rotate`.
     **Corrected (WP-13 round, 2026-10-04):** the admin token header is now the
     spec-explicit **`X-Admin-Token`** — §13.1 "Loopback Admin API (separate
     listener `127.0.0.1:8444`, header `X-Admin-Token`)" and §17.13 T-11
     "custom header `X-Admin-Token`" both name it; the original WP-08 reading
     ("§17.6 names no header" → `Authorization: Bearer`) overlooked that
     evidence and the code was aligned in the same round (admin_app.py, cli.py,
     tests, smoke script). The remaining item — route NAMES for the operator
     actions — stays OPEN (loopback-only, rename-safe).
  5. **QR `ep` before WP-11 mDNS** (§17.4): the QR advertises
     `https://<hostname>:<listen.port>` as the best non-invented endpoint;
     proper LAN-IP advertisement arrives with WP-11.
- Context/evidence: §13.2, §15.2, §15.4, §17.4–§17.6; implementation under
  `agent/src/localmesh_agent/security/` and `admin_app.py`; FR-PAIR-02 ACs.
- Why we must not guess: items 1-2 change the WIRE FORMAT (a phone built
  against a different reading fails proofs); item 3 is user-visible pairing UX;
  item 4-5 are operator/app-visible surfaces.
- Default if unanswered: ship the readings above (conservative, documented
  inline); any change is a small, localized diff.
- Status: OPEN

## QUESTION-102 — Fingerprint prefix in the "ready" log vs the §17.10 allow-list
- Date: 2026-10-04
- Raised by: WP-07 (app startup integration, §10.6 step 3/7)
- Question: §10.6 step 7 says the "ready" log carries the fingerprint prefix
  (TLS SPKI pin), but the §17.10 logging allow-list has no key for it and
  NFR-SEC-02 (P0, "Content never in logs; log field allow-list") binds the
  formatter to exactly 16 keys. Which wins: add an allow-list key (e.g.
  `pin_prefix`) or omit the pin from logs?
- Context/evidence: LM-ARCH-001 §10.6 step 7 vs §17.10 + NFR-SEC-02;
  formatter drops non-allow-listed keys by construction (agent/src/
  localmesh_agent/observability/logging.py).
- Why we must not guess: weakening the allow-list is a SEC-adjacent change
  (§1.3); logging the pin under an unrelated key (e.g. `status`) would be
  contract abuse and could confuse CI-ID triage.
- Default if unanswered: pin is NOT logged (NFR-SEC-02 P0 wins per §1.1
  precedence; the pin is served to paired Devices in M2 flows instead).
  Not blocking WP-08.
- Status: OPEN

## QUESTION-101 — Ports layer representation in the §10.1 dependency rule
- Date: 2026-10-04
- Raised by: WP-01 (import-linter contracts, `agent/.importlinter`)
- Question: §10.1 states both "api → core → ports" and "core imports nothing from
  api/adapters/store **implementations**", while the layout places the protocols in
  `adapters/ports.py`. Reading "implementations" as excluding the `ports` module
  (i.e. core MAY import `adapters.ports`, but no other `adapters.*`), is that the
  intended mapping — or should a dedicated `ports/` package exist at `M1`?
- Context/evidence: LM-ARCH-001 §10.1 ("Dependency rule (enforced by an
  import-linter test)") and §10.2 ("Ports (interfaces the core depends on)");
  contracts currently enforced: layers `api > core > adapters.ports`; forbidden:
  core → {api, store, adapters.backends/.hardware/.discovery/.tailscale/.keyring_store,
  fastapi, httpx, sqlite3, psutil}.
- Why we must not guess: getting this wrong shapes every `core`/`adapters` import
  from WP-05 onwards; unwinding later is expensive.
- Default if unanswered: keep the implemented interpretation (conservative; satisfies
  both statements textually). Not blocking M0 exit; revisit before WP-05.
- Status: OPEN

