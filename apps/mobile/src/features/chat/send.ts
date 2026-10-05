/**
 * Chat send flow (web demo): the glue between the composer and the §13.7
 * stream, integrating the §11.2 StreamHandle into SM-STREAM (§15.3) and the
 * §16.7 render pipeline (StreamBatcher, 80 ms).
 *
 * Frame routing (§13.7 wire format):
 *  - `: ping`            → SM-STREAM 'ping' (re-arms the 45 s window, CI-21);
 *  - default chunk (OpenAI `chat.completion.chunk`) → `choices[0].delta.content`
 *    is appended to the transcript via SM-STREAM (deltas only — never raw JSON);
 *  - `mesh.meta`         → labels the conversation with the resolved
 *    mesh_model_id/backend (Metadata, §13.10);
 *  - `mesh.stats`        → retained on the final message (Metadata only);
 *  - `mesh.error`        → SM-STREAM error path (retryable from §13.4 envelope);
 *  - `[DONE]`            → SM-STREAM complete; transport close afterwards.
 * Transport-level failures (network/HTTP ≥ 400/IDLE_TIMEOUT) are fed to
 * SM-STREAM as synthetic §13.4 `mesh.error` envelopes so the terminal surface
 * stays uniform.
 */

import { getMeshApiClient, type StreamHandle } from '../../data/mesh/client';
import { firstChatModelId } from '../machines/live';
import {
  appendMessages,
  patchStreaming,
  setConversationModelRef,
  setDraft,
  setStreaming,
  chatsStore,
} from '../../state/chatsStore';
import { SystemClock } from '../../domain/connection/clock';
import { StreamMachine, type StreamStatus } from '../../domain/sm-stream';
import type { Message } from '../../domain/entities';
import { StreamBatcher } from './pipeline';

interface ActiveStream {
  sm: StreamMachine;
  batcher: StreamBatcher;
  handle: StreamHandle | null;
}

const active = new Map<string, ActiveStream>();
let idSeq = 0;

function newId(prefix: string): string {
  return `${prefix}${Date.now().toString(36)}-${(idSeq++).toString(36)}`;
}

function tryParse(data: string): unknown {
  try {
    return JSON.parse(data) as unknown;
  } catch {
    return undefined;
  }
}

/** Extract `choices[0].delta.content` from a §13.7 default chunk. */
function chunkDeltaText(parsed: unknown): string {
  if (!parsed || typeof parsed !== 'object') return '';
  const choices = (parsed as Record<string, unknown>)['choices'];
  if (!Array.isArray(choices) || choices.length === 0) return '';
  const first = choices[0] as Record<string, unknown> | undefined;
  const delta = first?.['delta'];
  if (!delta || typeof delta !== 'object') return '';
  const content = (delta as Record<string, unknown>)['content'];
  return typeof content === 'string' ? content : '';
}

/** Keep only primitive values — Message.stats is Metadata (§14.2). */
function pickStats(parsed: unknown): Record<string, number | string> | undefined {
  if (!parsed || typeof parsed !== 'object') return undefined;
  const out: Record<string, number | string> = {};
  for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
    if (typeof v === 'number' || typeof v === 'string') out[k] = v;
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

export function isStreaming(conversationId: string): boolean {
  return active.has(conversationId);
}

export function sendMessage(conversationId: string, text: string): void {
  const trimmed = text.trim();
  if (trimmed === '' || active.has(conversationId)) return;
  const conversation = chatsStore.getState().conversations.find((c) => c.id === conversationId);
  if (!conversation) return;

  appendMessages(conversationId, [
    { id: newId('m'), conversationId, role: 'user', content: trimmed, status: 'complete', createdAt: Date.now() },
  ]);
  setDraft(conversationId, '');

  const model = conversation.modelRef ?? firstChatModelId(conversation.agentId ?? '');
  if (!model) {
    appendMessages(conversationId, [
      {
        id: newId('m'),
        conversationId,
        role: 'assistant',
        content: 'No model is available on this machine yet.',
        status: 'error',
        createdAt: Date.now(),
      },
    ]);
    return;
  }

  const history = (chatsStore.getState().messages[conversationId] ?? [])
    .filter((m) => m.role !== 'system' && m.status === 'complete')
    .map((m) => ({ role: m.role, content: m.content }));

  const clock = new SystemClock();
  const assistantId = newId('m');
  let stats: Record<string, number | string> | undefined;
  let resolvedModel: string | undefined;

  const batcher = new StreamBatcher({
    clock,
    onFlush: (visible) => patchStreaming(conversationId, { visible }),
  });

  const finalize = (): void => {
    batcher.end();
    active.delete(conversationId);
    const content = sm.text;
    if (content !== '' || sm.persistedStatus() === 'error') {
      const final: Message = {
        id: assistantId,
        conversationId,
        role: 'assistant',
        content: content !== '' ? content : 'No reply — the machine could not complete the response.',
        status: sm.persistedStatus(),
        modelRef: resolvedModel ?? model,
        ...(stats ? { stats } : {}),
        createdAt: Date.now(),
      };
      appendMessages(conversationId, [final]);
    }
    setStreaming(conversationId, null);
  };

  const sm = new StreamMachine(clock, {
    onStatus: (status: StreamStatus) => {
      patchStreaming(conversationId, { status });
      if (status === 'complete' || status === 'error' || status === 'interrupted' || status === 'cancelled') {
        finalize();
      }
    },
    onDelta: (delta) => batcher.push(delta),
  });

  setStreaming(conversationId, { status: 'submitting', visible: '', messageId: assistantId });
  sm.begin();

  const entry: ActiveStream = { sm, batcher, handle: null };
  active.set(conversationId, entry);

  void (async () => {
    try {
      const handle = await getMeshApiClient().openChatStream({ model, messages: history, stream: true });
      if (active.get(conversationId) !== entry) {
        handle.cancel(); // user stopped while the request was opening
        return;
      }
      entry.handle = handle;
      handle.on('event', (p) => {
        if (p.event === 'ping') {
          sm.onEvent('ping', '');
          return;
        }
        if (p.event === 'mesh.error') {
          sm.onEvent('mesh.error', p.data);
          return;
        }
        if (p.event === 'mesh.meta') {
          const meta = tryParse(p.data);
          if (meta && typeof meta === 'object') {
            const m = meta as Record<string, unknown>;
            if (typeof m['model'] === 'string') {
              resolvedModel = m['model'];
              setConversationModelRef(conversationId, m['model']);
              patchStreaming(conversationId, {
                meta: { model: m['model'], backend: typeof m['backend'] === 'string' ? m['backend'] : undefined },
              });
            }
          }
          return;
        }
        if (p.event === 'mesh.stats') {
          stats = pickStats(tryParse(p.data)) ?? stats;
          return;
        }
        if (p.event === undefined || p.event === '') {
          const content = chunkDeltaText(tryParse(p.data));
          if (content !== '') sm.onEvent(undefined, content);
        }
        // Unknown named events are additive (§13.10) — ignored.
      });
      handle.on('error', (p) => {
        // Uniform terminal surface: transport failure → §13.4 envelope.
        sm.onEvent('mesh.error', JSON.stringify({ error: { code: p.code, message: p.message, retryable: false } }));
      });
      handle.on('closed', (p) => {
        sm.onClosed(p.reason);
      });
    } catch (e) {
      sm.onEvent(
        'mesh.error',
        JSON.stringify({
          error: { code: 'NETWORK', message: e instanceof Error ? e.message : String(e), retryable: false },
        }),
      );
    }
  })();
}

/** User pressed Stop → cancelled; partial is retained (§15.3, UI spec 6.5). */
export function cancelStream(conversationId: string): void {
  const entry = active.get(conversationId);
  if (!entry) return;
  entry.sm.cancel(); // terminal transition → finalize via onStatus
  entry.handle?.cancel(); // abort the socket; the late 'closed' is ignored
}
