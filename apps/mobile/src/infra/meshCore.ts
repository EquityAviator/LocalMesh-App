/**
 * Typed wrapper of the native mesh-core module (§11.1 src/infra/meshCore.ts).
 *
 * - `getMeshCore()` lazily requires the native module (expo-modules-core style)
 *   so bundlers/tests never touch native code unless the wrapper is used.
 * - `MeshCoreMock` implements the §11.2 contract for previews/tests.
 *
 * Screens never import this file — only src/data/mesh/client.ts does (§11.3).
 */

import type {
  MeshCore,
  MeshCoreRequest,
  MeshCoreResponse,
  MeshCoreStreamRequest,
  NetworkStateNative,
  StreamHandle,
} from '../modules/mesh-core/src/MeshCore.types';

export type { MeshCore } from '../modules/mesh-core/src/MeshCore.types';

let cached: MeshCore | null = null;

/** Lazy native resolution; throws a clear error when the native build is absent. */
export function getMeshCore(): MeshCore {
  if (cached) return cached;
  // Lazy require keeps the native module out of every non-app entry point.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const native = require('expo-modules-core');
  const mod = (native.requireNativeModule ?? native.NativeModulesProxy?.['MeshCore'])?.('MeshCore');
  if (!mod) throw new Error('mesh-core native module not available (is the app built?)');
  cached = mod as MeshCore;
  return cached;
}

// ---------------------------------------------------------------------------
// Mock — scripted responses for tests/previews. Never performs I/O.
// ---------------------------------------------------------------------------

export interface MockRoute {
  /** Matched against `${method} ${path-with-query}`. */
  match: string | RegExp;
  respond: (req: MeshCoreRequest) => { status: number; bodyJson?: unknown };
}

export class MeshCoreMock implements MeshCore {
  readonly calls: MeshCoreRequest[] = [];
  routes: MockRoute[] = [];
  network: NetworkStateNative = { transport: 'wifi', vpnActive: false, metered: false };
  permission: 'granted' | 'denied' | 'not_required' | 'unknown' = 'granted';
  /** Simulated observed SPKI — flip to test PIN_MISMATCH (§15.1). */
  servedSpki: string;

  constructor(servedSpki = 'pin-mock') {
    this.servedSpki = servedSpki;
  }

  async createDeviceKey(alias: string): Promise<{ publicKeySpkiB64Url: string; hardwareBacked: boolean }> {
    return { publicKeySpkiB64Url: `pub-${alias}`, hardwareBacked: false };
  }
  async signWithDeviceKey(_alias: string, dataB64Url: string): Promise<string> {
    return `sig(${dataB64Url})`;
  }
  async deleteDeviceKey(_alias: string): Promise<void> {}

  async request(req: MeshCoreRequest): Promise<MeshCoreResponse> {
    this.calls.push(req);
    const key = `${req.method} ${new URL(req.url).pathname}`;
    for (const r of this.routes) {
      if (typeof r.match === 'string' ? r.match === key : r.match.test(key)) {
        const out = r.respond(req);
        return {
          status: out.status,
          headers: { 'content-type': 'application/json' },
          bodyJson: out.bodyJson,
          tlsSpkiSha256B64Url: this.servedSpki,
        };
      }
    }
    return { status: 404, headers: {}, bodyJson: { error: { code: 'NOT_FOUND', message: 'no mock route' } }, tlsSpkiSha256B64Url: this.servedSpki };
  }

  async openStream(_req: MeshCoreStreamRequest): Promise<StreamHandle> {
    throw new Error('MeshCoreMock.openStream: attach a fake StreamHandle in the test');
  }

  async startDiscovery(_serviceType: '_localmesh._tcp'): Promise<void> {}
  async stopDiscovery(): Promise<void> {}
  async getNetworkState(): Promise<NetworkStateNative> {
    return this.network;
  }
  async getLocalNetworkPermission(): Promise<'granted' | 'denied' | 'not_required' | 'unknown'> {
    return this.permission;
  }
  async requestLocalNetworkPermission(): Promise<'granted' | 'denied'> {
    return this.permission === 'denied' ? 'denied' : 'granted';
  }
  async isPackageInstalled(_pkg: string): Promise<boolean> {
    return false;
  }
}
