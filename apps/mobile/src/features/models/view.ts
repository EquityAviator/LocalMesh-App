/**
 * Model list / load / unload view-models (§6.4 Machine detail, §6.6 sheet).
 * Uses POST /models/load|unload (§13.2 API-MODEL-02/03): 202
 * `{"state":"loading"}` / `{"state":"unloaded"}`.
 */

import type { ModelEntry } from '../../domain/entities';

export interface ModelRowVM {
  meshModelId: string;
  name: string;
  /** "Q4_K_M · 32k context · loaded" (§6.4). */
  detail: string;
  loaded: boolean;
  capability?: string;
}

export function toModelRows(models: readonly ModelEntry[]): ModelRowVM[] {
  return models.map((m) => ({
    meshModelId: m.meshModelId,
    name: m.displayName,
    detail: [
      m.quantisation,
      m.contextLength ? `${m.contextLength} context` : undefined,
      m.loaded ? 'loaded' : 'on disk',
    ]
      .filter(Boolean)
      .join(' · '),
    loaded: m.loaded,
    capability: m.capabilities[0],
  }));
}

export type ModelOpState = 'idle' | 'loading' | 'unloading' | 'error';

/** Map a 202 response body to the row state (§13.2 closed vocabulary). */
export function applyModelOpResponse(
  current: ModelOpState,
  body: { state?: unknown },
): ModelOpState {
  if (body && body['state'] === 'loading') return 'loading';
  if (body && body['state'] === 'unloaded') return 'idle';
  return current === 'idle' ? 'error' : current;
}

/** "Loading Qwen 3.5 9B. The first reply can take up to a minute." (§6.5). */
export function modelOpNotice(name: string, state: ModelOpState): string | null {
  if (state === 'loading') return `Loading ${name}. The first reply can take up to a minute.`;
  if (state === 'unloading') return `Unloading ${name}.`;
  if (state === 'error') return `Couldn't change ${name} on the machine.`;
  return null;
}
