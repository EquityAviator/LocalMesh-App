/**
 * Settings store — appearance and behaviour toggles persisted through
 * SettingsRepo (§14.2 settings kv table; UI spec 6.10 sections).
 */

import { createStore, type TinyStore } from './store';

export type ThemeMode = 'system' | 'light' | 'dark';

export interface SettingsState {
  theme: ThemeMode;
  dynamicColour: boolean;
  autoSwitchPaths: boolean;
  allowRelayFallback: boolean;
  enterSends: boolean;
  textSizeSp: number;
  showTokensPerSecond: boolean;
  autoDeleteDays: 0 | 30 | 365;
}

export type SettingsStore = TinyStore<SettingsState>;

export const SETTINGS_DEFAULTS: SettingsState = {
  theme: 'system',
  dynamicColour: false,
  autoSwitchPaths: true,
  allowRelayFallback: false,
  enterSends: false,
  textSizeSp: 16,
  showTokensPerSecond: true,
  autoDeleteDays: 0,
};

export const settingsStore: TinyStore<SettingsState> = createStore<SettingsState>({ ...SETTINGS_DEFAULTS });

/** Persistable keys → settings table rows (key/value strings, §14.2). */
export function settingsToRows(s: SettingsState): Array<[string, string]> {
  return Object.entries(s).map(([k, v]) => [k, String(v)]);
}
