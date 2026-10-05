# ADR-019 — Control Plane activation for M6 (Supabase REST, Metadata-only)

Status: Accepted (owner approval recorded in-session; Q-05 gate)

Context: §12 marks the Control Plane OPTIONAL and gated on explicit owner
approval (Q-05, §22.1 M6 gate: "Owner approval (Q-05); Content-column scan
green"). The M0–M9 milestone review session delivered that approval with the
directive to complete M6–M9 with full-fledged implementations. §12.3 leaves
the exact Supabase call shapes `[UNVERIFIED — verify at M6]`; §12.2 fixes the
data model verbatim (devices table + RLS by `auth.uid()`).

Decision:

1. Build the CP surface exactly to §12: `control-plane/migrations/0001_init.sql`
   verbatim (devices + RLS), FR-CP-02 device registry + heartbeat,
   FR-CP-03 revocation mirror (Agent authoritative), FR-CP-01 Google identity
   via Supabase Auth (deployment-side; the Agent never sees the Google token).
2. The Agent talks to the CP over PostgREST conventions
   (`rest/v1/devices`) plus one Edge Function (`functions/v1/register-agent`)
   for the one-time-link registration — shapes marked `[UNVERIFIED]`
   (QUESTION-107). All calls are Metadata-only and bounded (5 s timeout).
3. Zero-Content is enforced, not promised: `control-plane/scripts/
   schema_content_scan.py` (TC-SEC-08) fails the build on any column matching
   `/prompt|message|content|completion|attachment/i` (§12.2 pattern).
4. The CP key is read from the OS keyring via `auth_ref` (§17.6); config
   validation REQUIRES `url` (https) + `auth_ref` when `enabled = true`.
5. Failure semantics: every CP error degrades to `state = offline`
   (§12.3 "continue with local data"); nothing in the CP path can block
   chat, pairing, or revocation (the mirror is fire-and-forget).

Consequences: the Agent gains an optional account-sync capability without any
content-path risk; operators must deploy Supabase (or equivalent) and the
`register-agent` function to use it. The unverified call shapes are isolated
in one adapter (`adapters/controlplane.py`) so a deployment-time correction is
a one-file diff.

Alternatives rejected: building the CP as part of the Agent (violates §12.1
separation/ADR-001); pulling Google Sign-In server-side into the Agent (the
Agent never authenticates users — FR-CP-01 "as identity only"); replacing the
local revocation path with the CP (§12.1 explicitly forbids).

Requirements affected: FR-CP-01..04, FR-PAIR-* (unchanged), NFR-SEC-03
(loopback backends untouched)   Contracts affected: §12.1–§12.3, §17.6,
§17.13 (TC-SEC-08), §22.1 M6 gate
