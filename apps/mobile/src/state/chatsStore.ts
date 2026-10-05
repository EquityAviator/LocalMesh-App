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
