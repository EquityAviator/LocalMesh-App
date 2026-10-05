/**
 * Chats store — conversations, messages, drafts, streaming state (§11.1).
 */

import type { Conversation, Message } from '../domain/entities';
import type { StreamStatus } from '../domain/sm-stream';
import { createStore, type TinyStore } from './store';

export interface StreamingState {
  status: StreamStatus;
  /** Rendered text (batched, §16.7). */
  visible: string;
  messageId: string;
  /** Labels from `mesh.meta` (§13.7): resolved model + backend (Metadata). */
  meta?: { model?: string; backend?: string };
}

export interface ChatsState {
  conversations: Conversation[];
  /** conversation_id → messages (loaded lazily from MessagesRepo). */
  messages: Record<string, Message[]>;
  /** conversation_id → composer draft (kept per conversation, UI spec 6.5). */
  drafts: Record<string, string>;
  streaming: Record<string, StreamingState>;
}

export type ChatsStore = TinyStore<ChatsState>;

export const chatsStore: TinyStore<ChatsState> = createStore<ChatsState>({
  conversations: [],
  messages: {},
  drafts: {},
  streaming: {},
});

export function setConversations(conversations: Conversation[]): void {
  chatsStore.setState((prev) => ({ ...prev, conversations }));
}

export function setMessages(conversationId: string, messages: Message[]): void {
  chatsStore.setState((prev) => ({ ...prev, messages: { ...prev.messages, [conversationId]: messages } }));
}

export function setDraft(conversationId: string, text: string): void {
  chatsStore.setState((prev) => ({ ...prev, drafts: { ...prev.drafts, [conversationId]: text } }));
}

export function setStreaming(conversationId: string, streaming: StreamingState | null): void {
  chatsStore.setState((prev) => {
    const next = { ...prev.streaming };
    if (streaming === null) delete next[conversationId];
    else next[conversationId] = streaming;
    return { ...prev, streaming: next };
  });
}

// ---------------------------------------------------------------------------
// Web demo mutations (in-memory; DB repos wire through in a later WP)
// ---------------------------------------------------------------------------

let convSeq = 0;

/** Create a conversation row and put it at the top of the list (§14.2 shape). */
export function createConversation(input: { title: string; agentId?: string; modelRef?: string }): Conversation {
  const now = Date.now();
  const conv: Conversation = {
    id: `c${now.toString(36)}${(convSeq++).toString(36)}`,
    title: input.title,
    agentId: input.agentId,
    modelRef: input.modelRef,
    createdAt: now,
    updatedAt: now,
    archived: false,
  };
  chatsStore.setState((prev) => ({ ...prev, conversations: [conv, ...prev.conversations] }));
  return conv;
}

/** Append messages to a thread and bump the conversation's updatedAt. */
export function appendMessages(conversationId: string, added: Message[]): void {
  chatsStore.setState((prev) => ({
    ...prev,
    messages: { ...prev.messages, [conversationId]: [...(prev.messages[conversationId] ?? []), ...added] },
    conversations: prev.conversations.map((c) =>
      c.id === conversationId ? { ...c, updatedAt: Date.now() } : c,
    ),
  }));
}

/** mesh.meta carries the resolved mesh_model_id (§13.7) — record the hint. */
export function setConversationModelRef(conversationId: string, modelRef: string): void {
  chatsStore.setState((prev) => ({
    ...prev,
    conversations: prev.conversations.map((c) =>
      c.id === conversationId ? { ...c, modelRef, updatedAt: Date.now() } : c,
    ),
  }));
}

/** Merge-patch the live streaming view of one conversation. */
export function patchStreaming(conversationId: string, patch: Partial<StreamingState>): void {
  chatsStore.setState((prev) => {
    const current = prev.streaming[conversationId];
    if (!current) return prev;
    return { ...prev, streaming: { ...prev.streaming, [conversationId]: { ...current, ...patch } } };
  });
}
