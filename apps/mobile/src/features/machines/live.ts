/**
 * Web demo live-data flows (§11.3): screens → features → MeshApiClient.
 * Fetches /info + /health + /models and projects them into the stores; every
 * failure degrades to the existing empty/offline states (never throws, never
 * crashes a screen). Metadata only — no Content, no secrets (§13.10/§17.10).
 */

import { DEMO_AGENT_BASE_URL, DEMO_AGENT_PIN, getMeshApiClient, type AgentInfo, type ModelListResponse } from '../../data/mesh/client';
import type { ModelEntry, PairedAgent } from '../../domain/entities';
import { agentDataStore, emptyAgentLive, setAgentData, type AgentLive } from '../../state/agentDataStore';
import { setAgents, setConnState, machinesStore } from '../../state/machinesStore';

export interface DemoRefreshResult {
  ok: boolean;
  agentId?: string;
  /** Machine-readable failure detail (no Content/secrets, §17.10). */
  error?: string;
}

/** §13.5 ModelEntry JSON → domain row (`state` → the `loaded` boolean). */
export function toDomainModels(models: ModelListResponse['models']): ModelEntry[] {
  return (models ?? [])
    .map((m): ModelEntry => {
      const id = typeof m.mesh_model_id === 'string' && m.mesh_model_id !== '' ? m.mesh_model_id : String(m.id ?? '');
      const caps = Array.isArray(m.capabilities) ? m.capabilities : (m.capabilities?.values ?? []);
      return {
        meshModelId: id,
        displayName: m.display_name ?? m.backend_model_id ?? id,
        loaded: m.state === 'loaded' || m.loaded === true,
        capabilities: caps.filter((c): c is string => typeof c === 'string'),
      };
    })
    .filter((m) => m.meshModelId !== '');
}

/** "2 backends · 2 up · ok" (§6.3 card line, live from /health). */
export function backendLine(live: AgentLive): string | undefined {
  const overall = live.status;
  if (live.backends.length === 0 && !overall) return undefined;
  const up = live.backends.filter((b) => b.status === 'up').length;
  const n = live.backends.length;
  const head = n === 0 ? 'no backends' : `${n} backend${n === 1 ? '' : 's'} · ${up} up`;
  return overall ? `${head} · ${overall}` : head;
}

/** "3 models · <first>" (§6.3 card line, live from /models). */
export function modelLine(live: AgentLive): string | undefined {
  const first = live.models[0];
  if (live.models.length === 0 || !first) return undefined;
  const n = live.models.length;
  return `${n} model${n === 1 ? '' : 's'} · ${first.displayName}`;
}

function upsertDemoAgent(info: AgentInfo): void {
  const prev = machinesStore.getState().agents;
  const existing = prev.find((a) => a.agentId === info.agent_id);
  const agent: PairedAgent = {
    agentId: info.agent_id,
    displayName: info.display_name,
    spkiPin: DEMO_AGENT_PIN,
    deviceId: 'web-demo-device',
    keyAlias: 'web-demo',
    endpoints: [{ url: DEMO_AGENT_BASE_URL, tier: 'T0', origin: 'manual' }],
    pairedAt: existing?.pairedAt ?? Date.now(),
    lastConnectedAt: Date.now(),
  };
  setAgents(existing ? prev.map((a) => (a.agentId === agent.agentId ? agent : a)) : [...prev, agent]);
}

/**
 * One live refresh round: /info (pre-auth probe, §13.2) → SM-CONN CONNECTED
 * (T0; the web transport has no race planner — reachability through the proxy
 * IS the connection), then /health + /models recorded best-effort.
 */
export async function refreshAgentData(): Promise<DemoRefreshResult> {
  const client = getMeshApiClient();
  try {
    const info = await client.info();
    const agentId = info.agent_id;
    upsertDemoAgent(info);
    setConnState(agentId, {
      s: 'CONNECTED',
      tier: 'T0',
      endpoint: { url: DEMO_AGENT_BASE_URL, tier: 'T0', origin: 'manual' },
    });

    const prevLive = agentDataStore.getState()[agentId] ?? emptyAgentLive();
    let live: AgentLive = { ...prevLive, error: undefined };
    try {
      const health = await client.health();
      live = {
        ...live,
        status: health.status,
        backends: (health.backends ?? []).map((b) => ({ id: String(b.id ?? ''), status: String(b.status ?? '') })),
        fetchedAt: Date.now(),
      };
    } catch (e) {
      live = { ...live, error: e instanceof Error ? e.message : String(e) };
    }
    try {
      const models = await client.listModels();
      live = { ...live, models: toDomainModels(models.models), fetchedAt: Date.now() };
    } catch (e) {
      live = { ...live, error: e instanceof Error ? e.message : String(e) };
    }
    setAgentData(agentId, live);
    return { ok: true, agentId };
  } catch (e) {
    // /info failed → the Agent is unreachable; screens keep their stored rows
    // (a previously-fetched agent simply stays/turns UNREACHABLE below) or
    // show the existing empty state on first run.
    const agents = machinesStore.getState().agents;
    for (const a of agents) {
      if (machinesStore.getState().conn[a.agentId]?.s === 'CONNECTED') {
        setConnState(a.agentId, { s: 'UNREACHABLE', reason: 'TIMEOUT_LAN' });
      }
    }
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

/** First usable chat model: a loaded one, else the first known (§13.6 model ref). */
export function firstChatModelId(agentId: string): string | null {
  const live = agentDataStore.getState()[agentId];
  if (!live || live.models.length === 0) return null;
  const loaded = live.models.find((m) => m.loaded);
  const pick = loaded ?? live.models[0];
  return pick ? pick.meshModelId : null;
}
