-- LocalMesh Control Plane — initial schema (M6, §12.2).
--
-- VERBATIM from LM-ARCH-001 §12.2 "Data model (Postgres)" — the spec SQL is
-- the contract; the only additions here are the comment blocks (comments are
-- not schema). No `messages`, `prompts` or file tables may exist; the CI
-- schema check (TC-SEC-08, control-plane/scripts/schema_content_scan.py)
-- fails the build if any column name matches
--   /prompt|message|content|completion|attachment/i
-- (FR-CP-04 "Control Plane stores zero Content, enforced by schema and
-- review").

create table public.devices (
  id          uuid primary key,
  user_id     uuid not null references auth.users(id) on delete cascade,
  kind        text not null check (kind in ('agent','phone')),
  name        text not null,
  public_key  bytea not null,            -- SPKI DER
  tailnet_dns text,                       -- optional hint, metadata
  created_at  timestamptz not null default now(),
  last_seen   timestamptz,
  revoked_at  timestamptz
);
alter table public.devices enable row level security;
create policy devices_owner on public.devices
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());
