/**
 * §14.2 — App store (SQLite, encrypted at rest per §11.5; key wrapping lives in
 * the native layer). This file carries the schema VERBATIM from the spec so any
 * drift is a visible one-line diff, plus a tiny migration runner interface.
 *
 * No table may contain Content beyond the `messages.content` column the spec
 * itself defines; metadata-only discipline mirrors SEC-N3 (agent side).
 */

/** §14.2 DDL, byte-for-byte (modulo this comment block). */
export const APP_STORE_SCHEMA_SQL = `
CREATE TABLE agents (
  agent_id       TEXT PRIMARY KEY,
  display_name   TEXT NOT NULL,
  spki_pin       TEXT NOT NULL,            -- b64url(no padding) SHA-256 of Agent TLS SPKI
  device_id      TEXT NOT NULL,            -- our id at this Agent
  key_alias      TEXT NOT NULL,            -- Keystore alias (key itself never stored here)
  endpoints_json TEXT NOT NULL,            -- ordered Endpoint[] with tier + last_ok_at
  last_tier      TEXT,
  last_connected_at INTEGER,
  paired_at      INTEGER NOT NULL
);

CREATE TABLE conversations (
  id TEXT PRIMARY KEY, title TEXT NOT NULL,
  agent_id TEXT,                            -- last used; nullable (history is portable)
  model_ref TEXT,                           -- last mesh_model_id (hint)
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('system','user','assistant')),
  content TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('complete','streaming','interrupted','error')),
  model_ref TEXT, stats_json TEXT,
  created_at INTEGER NOT NULL
);
CREATE INDEX messages_conv ON messages(conversation_id, created_at);

CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
`.trim();

/** Message status surface enforced by the §14.2 CHECK — mirrored as TS. */
export const MESSAGE_STATUSES = ['complete', 'streaming', 'interrupted', 'error'] as const;
export const MESSAGE_ROLES = ['system', 'user', 'assistant'] as const;

export interface Migration {
  id: number;
  name: string;
  sql: string;
}

export const MIGRATIONS: readonly Migration[] = [
  { id: 1, name: 'init_app_store_14_2', sql: APP_STORE_SCHEMA_SQL },
];

/** Minimal async executor so tests can plug bun:sqlite (or an in-memory fake). */
export type SqlValue = string | number | bigint | Uint8Array | null;

export interface SqliteExecutor {
  run(sql: string, params?: readonly SqlValue[]): Promise<void>;
  all<T = Record<string, SqlValue>>(sql: string, params?: readonly SqlValue[]): Promise<T[]>;
}

/**
 * Migration runner keyed on `PRAGMA user_version` (works on real SQLite and on
 * a fake that implements the two statements).
 */
export async function runMigrations(db: SqliteExecutor, migrations: readonly Migration[] = MIGRATIONS): Promise<number> {
  const rows = await db.all<{ user_version: number }>('PRAGMA user_version');
  let current = Number(rows[0]?.['user_version'] ?? 0);
  for (const m of migrations) {
    if (m.id <= current) continue;
    await db.run(m.sql);
    await db.run(`PRAGMA user_version = ${m.id}`);
    current = m.id;
  }
  return current;
}

/** TS-level guard mirroring the CHECK surface (defense in depth, §16.1 style). */
export function assertMessageStatus(s: string): asserts s is (typeof MESSAGE_STATUSES)[number] {
  if (!(MESSAGE_STATUSES as readonly string[]).includes(s)) {
    throw new Error(`INVALID_MESSAGE_STATUS: ${s}`);
  }
}
