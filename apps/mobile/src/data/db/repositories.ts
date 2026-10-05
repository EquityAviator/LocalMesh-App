/**
 * §14.2 repositories — AgentsRepo / ConversationsRepo / MessagesRepo /
 * SettingsRepo over the minimal SqliteExecutor interface (src/data/db/schema).
 * The UI never touches SQL (§11.3); tests plug an executor around bun:sqlite.
 */

import type { Conversation, Endpoint, Message, MessageRole, MessageStatus, PairedAgent } from '../../domain/entities';
import {
  assertMessageStatus,
  type SqliteExecutor,
  type SqlValue,
} from './schema';

// ---------------------------------------------------------------------------
// Row ↔ entity mapping
// ---------------------------------------------------------------------------

interface AgentRow extends Record<string, SqlValue> {
  agent_id: string;
  display_name: string;
  spki_pin: string;
  device_id: string;
  key_alias: string;
  endpoints_json: string;
  last_tier: string | null;
  last_connected_at: number | null;
  paired_at: number;
}

function parseEndpoints(json: string): Endpoint[] {
  let raw: unknown;
  try {
    raw = JSON.parse(json);
  } catch {
    return [];
  }
  if (!Array.isArray(raw)) return [];
  return raw.filter((e): e is Endpoint => {
    if (typeof e !== 'object' || e === null) return false;
    const r = e as Record<string, unknown>;
    return typeof r['url'] === 'string' && typeof r['tier'] === 'string' && typeof r['origin'] === 'string';
  });
}

function toAgent(row: AgentRow): PairedAgent {
  return {
    agentId: row.agent_id,
    displayName: row.display_name,
    spkiPin: row.spki_pin,
    deviceId: row.device_id,
    keyAlias: row.key_alias,
    endpoints: parseEndpoints(row.endpoints_json),
    lastTier: (row.last_tier ?? undefined) as PairedAgent['lastTier'],
    lastConnectedAt: row.last_connected_at ?? undefined,
    pairedAt: row.paired_at,
  };
}

interface ConversationRow extends Record<string, SqlValue> {
  id: string;
  title: string;
  agent_id: string | null;
  model_ref: string | null;
  created_at: number;
  updated_at: number;
  archived: number;
}

function toConversation(row: ConversationRow): Conversation {
  return {
    id: row.id,
    title: row.title,
    agentId: row.agent_id ?? undefined,
    modelRef: row.model_ref ?? undefined,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    archived: row.archived !== 0,
  };
}

interface MessageRow extends Record<string, SqlValue> {
  id: string;
  conversation_id: string;
  role: string;
  content: string;
  status: string;
  model_ref: string | null;
  stats_json: string | null;
  created_at: number;
}

function toMessage(row: MessageRow): Message {
  assertMessageStatus(row.status);
  let stats: Record<string, number | string> | undefined;
  if (row.stats_json) {
    try {
      const parsed: unknown = JSON.parse(row.stats_json);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        stats = parsed as Record<string, number | string>;
      }
    } catch {
      stats = undefined;
    }
  }
  return {
    id: row.id,
    conversationId: row.conversation_id,
    role: row.role as MessageRole,
    content: row.content,
    status: row.status,
    modelRef: row.model_ref ?? undefined,
    stats,
    createdAt: row.created_at,
  };
}

// ---------------------------------------------------------------------------
// Repos
// ---------------------------------------------------------------------------

export class AgentsRepo {
  constructor(private readonly db: SqliteExecutor) {}

  async upsert(agent: PairedAgent): Promise<void> {
    await this.db.run(
      `INSERT INTO agents (agent_id, display_name, spki_pin, device_id, key_alias, endpoints_json, last_tier, last_connected_at, paired_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(agent_id) DO UPDATE SET
         display_name=excluded.display_name, spki_pin=excluded.spki_pin, device_id=excluded.device_id,
         key_alias=excluded.key_alias, endpoints_json=excluded.endpoints_json, last_tier=excluded.last_tier,
         last_connected_at=excluded.last_connected_at`,
      [
        agent.agentId,
        agent.displayName,
        agent.spkiPin,
        agent.deviceId,
        agent.keyAlias,
        JSON.stringify(agent.endpoints),
        agent.lastTier ?? null,
        agent.lastConnectedAt ?? null,
        agent.pairedAt,
      ],
    );
  }

  async get(agentId: string): Promise<PairedAgent | null> {
    const rows = await this.db.all<AgentRow>('SELECT * FROM agents WHERE agent_id = ?', [agentId]);
    const row = rows[0];
    return row ? toAgent(row) : null;
  }

  async list(): Promise<PairedAgent[]> {
    const rows = await this.db.all<AgentRow>('SELECT * FROM agents ORDER BY paired_at ASC');
    return rows.map(toAgent);
  }

  async delete(agentId: string): Promise<void> {
    await this.db.run('DELETE FROM agents WHERE agent_id = ?', [agentId]);
  }
}

export class ConversationsRepo {
  constructor(private readonly db: SqliteExecutor) {}

  async create(conv: Conversation): Promise<void> {
    await this.db.run(
      `INSERT INTO conversations (id, title, agent_id, model_ref, created_at, updated_at, archived)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [conv.id, conv.title, conv.agentId ?? null, conv.modelRef ?? null, conv.createdAt, conv.updatedAt, conv.archived ? 1 : 0],
    );
  }

  async get(id: string): Promise<Conversation | null> {
    const rows = await this.db.all<ConversationRow>('SELECT * FROM conversations WHERE id = ?', [id]);
    const row = rows[0];
    return row ? toConversation(row) : null;
  }

  async list(): Promise<Conversation[]> {
    const rows = await this.db.all<ConversationRow>(
      'SELECT * FROM conversations WHERE archived = 0 ORDER BY updated_at DESC',
    );
    return rows.map(toConversation);
  }

  async touch(id: string, at: number): Promise<void> {
    await this.db.run('UPDATE conversations SET updated_at = ? WHERE id = ?', [at, id]);
  }

  async setModelRef(id: string, modelRef: string | null, at: number): Promise<void> {
    await this.db.run('UPDATE conversations SET model_ref = ?, updated_at = ? WHERE id = ?', [modelRef, at, id]);
  }

  async setArchived(id: string, archived: boolean): Promise<void> {
    await this.db.run('UPDATE conversations SET archived = ? WHERE id = ?', [archived ? 1 : 0, id]);
  }
}

export class MessagesRepo {
  constructor(private readonly db: SqliteExecutor) {}

  async insert(msg: Message): Promise<void> {
    assertMessageStatus(msg.status);
    await this.db.run(
      `INSERT INTO messages (id, conversation_id, role, content, status, model_ref, stats_json, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        msg.id,
        msg.conversationId,
        msg.role,
        msg.content,
        msg.status,
        msg.modelRef ?? null,
        msg.stats ? JSON.stringify(msg.stats) : null,
        msg.createdAt,
      ],
    );
  }

  async listByConversation(conversationId: string): Promise<Message[]> {
    const rows = await this.db.all<MessageRow>(
      'SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC, id ASC',
      [conversationId],
    );
    return rows.map(toMessage);
  }

  /** Streaming flush: replace content wholesale (caller owns batching, §16.7). */
  async updateContent(id: string, content: string): Promise<void> {
    await this.db.run('UPDATE messages SET content = ? WHERE id = ?', [content, id]);
  }

  async updateStatus(id: string, status: MessageStatus, stats?: Record<string, number | string>): Promise<void> {
    assertMessageStatus(status);
    await this.db.run('UPDATE messages SET status = ?, stats_json = ? WHERE id = ?', [
      status,
      stats ? JSON.stringify(stats) : null,
      id,
    ]);
  }
}

export class SettingsRepo {
  constructor(private readonly db: SqliteExecutor) {}

  async get(key: string): Promise<string | null> {
    const rows = await this.db.all<{ value: string }>('SELECT value FROM settings WHERE key = ?', [key]);
    return rows[0]?.['value'] ?? null;
  }

  async set(key: string, value: string): Promise<void> {
    await this.db.run(
      'INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
      [key, value],
    );
  }

  async delete(key: string): Promise<void> {
    await this.db.run('DELETE FROM settings WHERE key = ?', [key]);
  }
}
