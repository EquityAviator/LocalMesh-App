/**
 * §18.4 Doctor ladder wired to the web demo transport (§11.3: screens →
 * features → MeshApiClient / data-layer probes). On the web transport there
 * is no TCP/DNS granularity and no mDNS — the probe reports reachability
 * through the proxy honestly (the pin assertion runs inside the client on
 * every call) and discovery stays "not seen". Every dep catches internally so
 * runDoctor never rejects.
 */

import { getMeshApiClient, meshCoreProbes } from '../../data/mesh/client';
import type { Clock } from '../../domain/connection/clock';
import type { PairedAgent } from '../../domain/entities';
import { runDoctor, type DoctorDeps } from './doctor';

export function buildWebDoctorDeps(clock: Clock, agent: PairedAgent | undefined): DoctorDeps {
  const client = getMeshApiClient();
  const probes = meshCoreProbes();
  return {
    clock,
    getNetwork: () => probes.getNetworkState(),
    getPermission: () => probes.getLocalNetworkPermission(),
    isTailscaleInstalled: () => probes.isPackageInstalled('com.tailscale.ipn'),
    // mDNS discovery is native-only (§16.2) — honest "not seen" on the web demo.
    discoverySawAgent: () => false,
    candidates: agent?.endpoints ?? [],
    probeCandidate: async () => {
      try {
        const info = await client.info();
        return {
          dns: true, // implied: the request reached the Agent through the proxy
          tcp: true, // implied by reachability (no socket granularity on web)
          tlsPin: true, // MeshApiClient asserts the pin on every response
          info: true,
          agentIdOk: !agent || info.agent_id === agent.agentId,
        };
      } catch {
        return { dns: false, tcp: false, tlsPin: false, info: false, agentIdOk: false };
      }
    },
    authCheck: async () => {
      try {
        await client.device();
        return { ok: true };
      } catch {
        return { ok: false };
      }
    },
    healthCheck: async () => {
      try {
        await client.health();
        return { ok: true };
      } catch {
        return { ok: false };
      }
    },
    backendStatus: async () => {
      try {
        const health = await client.health();
        const backends = health.backends ?? [];
        const up = backends.filter((b) => b.status === 'up').length;
        return {
          ok: backends.length > 0 && up === backends.length,
          summary: `${up}/${backends.length} backends up · status ${String(health.status ?? 'unknown')}`,
        };
      } catch {
        return { ok: false, summary: 'health unavailable' };
      }
    },
  };
}

export { runDoctor };
