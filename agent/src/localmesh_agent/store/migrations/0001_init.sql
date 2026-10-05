-- LM-ARCH-001 §14.1 — Agent store migration 0001_init.sql (SQLite, WAL mode).
-- The DDL below is the normative §14.1 schema, verbatim. Do not edit without a
-- spec change (§1.5 change protocol).
--
-- NOTE: the Content-column schema scan (scripts/security/scan_content_columns.py)
-- gates every future migration (SEC-N3, ADR-011: the Agent stores no Content).
-- Retention (§14.1): audit_events ≤ 90 days / 10 000 rows (rolling); tokens are
-- pruned on expiry (see localmesh_agent.store.sqlite.Store.prune).

PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;

CREATE TABLE agent_identity (
  id            INTEGER PRIMARY KEY CHECK (id = 1),
  agent_id      TEXT NOT NULL,
  display_name  TEXT NOT NULL,
  created_at    INTEGER NOT NULL           -- unix seconds
);

CREATE TABLE devices (
  device_id        TEXT PRIMARY KEY,       -- 'dv_' + UUIDv7
  name             TEXT NOT NULL,
  platform         TEXT NOT NULL,
  public_key_spki  BLOB NOT NULL,          -- DER, P-256
  scopes           TEXT NOT NULL,          -- space-separated
  created_at       INTEGER NOT NULL,
  last_seen_at     INTEGER,
  revoked_at       INTEGER                 -- non-NULL = revoked (row kept; see API-AUTH-02)
);

CREATE TABLE tokens (
  token_hash  BLOB PRIMARY KEY,            -- SHA-256(token)
  device_id   TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
  issued_at   INTEGER NOT NULL,
  expires_at  INTEGER NOT NULL
);
CREATE INDEX tokens_device ON tokens(device_id);

CREATE TABLE audit_events (                -- Metadata only. NEVER Content.
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         INTEGER NOT NULL,
  device_id  TEXT,
  event      TEXT NOT NULL,                -- pair_opened|pair_approved|auth_ok|auth_fail|revoked|chat_started|chat_finished|…
  meta_json  TEXT                          -- allow-listed keys only (§20.2)
);

CREATE TABLE backends (
  backend_id  TEXT PRIMARY KEY, kind TEXT NOT NULL, base_url TEXT NOT NULL,
  enabled     INTEGER NOT NULL DEFAULT 1,
  auth_ref    TEXT                          -- keyring entry name, NOT the secret
);

CREATE TABLE model_cache (
  mesh_model_id TEXT PRIMARY KEY, entry_json TEXT NOT NULL, refreshed_at INTEGER NOT NULL
);

CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
