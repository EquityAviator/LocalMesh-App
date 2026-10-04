-- LM-ARCH-001 M7 — migration 0002_tasks.sql (SQLite, §13.9 / FR-MM-01..04).
--
-- Durable Tasks + attachments + local RAG storage. Content-at-rest rules:
--   - task results and attachment/section text are stored ENCRYPTED
--     (AES-256-GCM ciphertext BLOBs) — §13.9 "encrypted at rest" + ADR-011;
--   - results carry expires_at (§13.9: retained ≤ 1 h) and are purged on
--     fetch-ack (DELETE) or expiry sweep;
--   - column names avoid the Content deny-list stems (scripts/security/
--     scan_content_columns.py gates every migration — SEC-N3).

CREATE TABLE tasks (
  task_id      TEXT PRIMARY KEY,        -- 'tk_' + UUIDv7
  device_id    TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
  type         TEXT NOT NULL CHECK (type IN ('chat','vision','transcribe','doc_qa')),
  status       TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
  progress     INTEGER NOT NULL DEFAULT 0,
  enc_input    BLOB NOT NULL,           -- task definition, AES-256-GCM (Content)
  input_nonce  BLOB NOT NULL,
  enc_options  BLOB,                    -- options may carry Content refs
  options_nonce BLOB,
  error_code   TEXT,
  error_text   TEXT,
  created_at   INTEGER NOT NULL,
  started_at   INTEGER,
  finished_at  INTEGER,
  expires_at   INTEGER,                 -- finished_at + retention (§13.9 ≤ 1 h)
  enc_result   BLOB,                    -- AES-256-GCM ciphertext (Content)
  result_nonce BLOB                     -- GCM nonce for enc_result
);
CREATE INDEX tasks_expiry ON tasks(expires_at);
CREATE INDEX tasks_device ON tasks(device_id);

CREATE TABLE task_files (                -- §13.9 attachments (encrypted at rest)
  task_id    TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
  name       TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  enc_data   BLOB NOT NULL,
  file_nonce BLOB NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (task_id, name)
);

CREATE TABLE rag_sources (               -- FR-MM-03: uploaded documents (metadata)
  source_id  TEXT PRIMARY KEY,           -- 'doc_' + UUIDv7
  name       TEXT NOT NULL,
  sha256     BLOB NOT NULL,
  size_bytes INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE TABLE rag_sections (              -- document body, encrypted at rest
  row_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL REFERENCES rag_sources(source_id) ON DELETE CASCADE,
  seq       INTEGER NOT NULL,
  enc_text  BLOB NOT NULL,
  text_nonce BLOB NOT NULL,
  UNIQUE (source_id, seq)
);

CREATE TABLE rag_vectors (               -- section embeddings (not reversible text)
  row_id    INTEGER PRIMARY KEY REFERENCES rag_sections(row_id) ON DELETE CASCADE,
  model     TEXT NOT NULL,
  dim       INTEGER NOT NULL,
  vector    BLOB NOT NULL               -- float32 little-endian packed
);
