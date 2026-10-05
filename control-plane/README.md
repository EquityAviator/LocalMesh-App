# LocalMesh Control Plane (optional, M6)

Implements LM-ARCH-001 **§12** (FR-CP-01..04). Activated for M6 by explicit
owner approval — the "complete them all" directive in the M0–M9 milestone
review session (Q-05 gate, recorded in `docs/adr/019-control-plane-activation.md`).

Holds **Metadata only**; never Content (ADR-001, FR-CP-04, CON-02). The Agent
remains authoritative for authorization and revocation (§12.1) — this service
exists so a signed-in Phone can see which of the user's Agents are online and
notice revocations.

## Contents

| Path | Purpose |
| --- | --- |
| `migrations/0001_init.sql` | §12.2 devices table + RLS policy, **verbatim** |
| `scripts/schema_content_scan.py` | TC-SEC-08: fails the build on any column matching `/prompt\|message\|content\|completion\|attachment/i` (FR-CP-04) |

## Deployment (Supabase or self-hosted Postgres + PostgREST)

1. Create a project; run `migrations/0001_init.sql` (Supabase SQL editor or
   `psql`).
2. Google Sign-In is configured at the provider (FR-CP-01: Google identity
   **as identity only** — Supabase Auth session `[UNVERIFIED call shape —
   verify at M6 deployment]`, §12.3).
3. Create an Edge Function `register-agent` implementing §12.3 "Register
   Agent": validate the one-time link code from the logged-in Phone, insert
   the `kind='agent'` row (id, name, `public_key` SPKI DER), return
   `{"device_id": <uuid>}`. The Agent's call shape is in
   `agent/src/localmesh_agent/adapters/controlplane.py`
   (`[UNVERIFIED — verify at M6 deployment]`, QUESTION-107).
4. Store a service/anon key in the Agent host's OS keyring
   (`security keyring set localmesh <auth_ref>`) and point the Agent config at
   it — the key NEVER lives in `config.toml` (§17.6):

   ```toml
   [control_plane]
   enabled = true
   url = "https://<project>.supabase.co"
   auth_ref = "cp-key"            # keyring entry name
   heartbeat_interval_s = 60      # §12.3 default
   ```

5. Operator links the Agent to the account (operator consent, §12.3):

   ```
   curl -X POST http://127.0.0.1:8444/admin/control-plane/register \
     -H "X-Admin-Token: <token>" -H "Content-Type: application/json" \
     -d '{"code": "<one-time link code from the Phone>"}'
   ```

## Flows implemented Agent-side (§12.3)

| Flow | Where |
| --- | --- |
| Register Agent (one-time link code) | `POST /admin/control-plane/register` → `core.control_plane.ControlPlaneService.register` |
| Heartbeat (upsert `last_seen`, 60 s, only when registered) | lifespan asyncio task → `ControlPlaneService.heartbeat_once` |
| Revocation mirror (Agent authoritative, best effort) | `DeviceService` revoke hook → `ControlPlaneService.mirror_device_revocation` |
| Failure mode ("account sync offline") | state machine `disabled/unregistered/ok/offline`; chat and pairing NEVER block |

## Guarantees

- **Zero Content (FR-CP-04):** payloads are ids, names, public keys,
  timestamps only; `scripts/schema_content_scan.py` gates the schema.
- **Fail-open locally:** every CP error degrades to `state=offline`
  (§12.3 "App/Agent continue with local data"); the Agent's own store
  stays the authority (§12.1 "Does NOT replace local revocation").
- **No secrets in transit config:** CP key via keyring (`auth_ref`), never
  TOML/env (§17.6).
