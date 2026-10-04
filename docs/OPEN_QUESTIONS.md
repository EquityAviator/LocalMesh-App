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
