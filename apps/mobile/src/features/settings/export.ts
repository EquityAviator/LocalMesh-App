/**
 * Settings feature — export of conversations (JSON / Markdown, user-initiated
 * only per §11.5) + appearance/about helpers (UI spec 6.10).
 */

import type { Conversation, Message } from '../../domain/entities';

export interface ExportPayload {
  format: 'json' | 'markdown';
  generatedAt: number;
  conversations: Array<{
    id: string;
    title: string;
    agentId?: string;
    createdAt: number;
    messages: Array<{ role: string; content: string; status: string; modelRef?: string; createdAt: number }>;
  }>;
}

export function buildJsonExport(conversations: readonly Conversation[], messagesByConv: Record<string, Message[]>, now: number): string {
  const payload: ExportPayload = {
    format: 'json',
    generatedAt: now,
    conversations: conversations.map((c) => ({
      id: c.id,
      title: c.title,
      ...(c.agentId ? { agentId: c.agentId } : {}),
      createdAt: c.createdAt,
      messages: (messagesByConv[c.id] ?? []).map((m) => ({
        role: m.role,
        content: m.content,
        status: m.status,
        ...(m.modelRef ? { modelRef: m.modelRef } : {}),
        createdAt: m.createdAt,
      })),
    })),
  };
  return JSON.stringify(payload, null, 2);
}

export function buildMarkdownExport(conversations: readonly Conversation[], messagesByConv: Record<string, Message[]>, now: number): string {
  const out: string[] = [];
  out.push('# LocalMesh export');
  out.push('');
  out.push(`Generated: ${new Date(now).toISOString()}`);
  for (const c of conversations) {
    out.push('');
    out.push(`## ${c.title}`);
    for (const m of messagesByConv[c.id] ?? []) {
      const who = m.role === 'user' ? 'You' : m.role === 'assistant' ? m.modelRef ?? 'Assistant' : 'System';
      out.push('');
      out.push(`**${who}** (${m.status})`);
      out.push('');
      out.push(m.content);
    }
  }
  return out.join('\n');
}

/** Auto-delete options (UI spec 6.10 Storage and history). */
export const AUTO_DELETE_OPTIONS: ReadonlyArray<{ value: 0 | 30 | 365; label: string }> = [
  { value: 0, label: 'Never' },
  { value: 30, label: '30 days' },
  { value: 365, label: '1 year' },
];
