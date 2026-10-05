/**
 * Design tokens from the UI spec §3.1 (light + dark) — the four path colours
 * carry meaning wherever they appear and are FIXED across themes:
 *   Wi-Fi #0E7A4F · Secure tunnel #2563D8 · Relay #A86412 · Offline #6B7186
 * (dark: #3DD598 / #7AAEFF / #F2B84B / #8A90A6).
 */

export type ThemeMode = 'system' | 'light' | 'dark';

export interface Palette {
  background: string;
  surface: string;
  surfaceRaised: string;
  outline: string;
  text: string;
  textSecondary: string;
  primary: string;
  primaryContainer: string;
  pathWifi: string;
  pathTunnel: string;
  pathRelay: string;
  pathOffline: string;
  error: string;
}

export const LIGHT: Palette = {
  background: '#F7F7FB',
  surface: '#FFFFFF',
  surfaceRaised: '#EEF0F6',
  outline: '#D6D9E4',
  text: '#151826',
  textSecondary: '#5A6075',
  primary: '#3F3FD9',
  primaryContainer: '#E3E3FF',
  pathWifi: '#0E7A4F',
  pathTunnel: '#2563D8',
  pathRelay: '#A86412',
  pathOffline: '#6B7186',
  error: '#C62F3E',
};

export const DARK: Palette = {
  background: '#0E1018',
  surface: '#171A25',
  surfaceRaised: '#1F2332',
  outline: '#2E3347',
  text: '#E8EAF3',
  textSecondary: '#9AA0B6',
  primary: '#9A9AFF',
  primaryContainer: '#2A2A6B',
  pathWifi: '#3DD598',
  pathTunnel: '#7AAEFF',
  pathRelay: '#F2B84B',
  pathOffline: '#8A90A6',
  error: '#FF7A88',
};

export function paletteFor(mode: ThemeMode): Palette {
  if (mode === 'light') return LIGHT;
  if (mode === 'dark') return DARK;
  return LIGHT; // 'system' resolution happens in the root layout hook
}

/** §3.3 spacing grid: all spacing is a multiple of 4. */
export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
  screenMargin: 16,
} as const;

/** §3.2 type scale. */
export const type = {
  titleLarge: { fontSize: 22, lineHeight: 28, fontWeight: '500' as const },
  titleMedium: { fontSize: 16, lineHeight: 24, fontWeight: '500' as const },
  bodyLarge: { fontSize: 16, lineHeight: 24, fontWeight: '400' as const },
  bodyMedium: { fontSize: 14, lineHeight: 20, fontWeight: '400' as const },
  labelLarge: { fontSize: 14, lineHeight: 20, fontWeight: '500' as const },
  labelMedium: { fontSize: 12, lineHeight: 16, fontWeight: '500' as const },
  code: { fontSize: 13, lineHeight: 18, fontWeight: '400' as const },
} as const;

/** §3.3 shape. */
export const shape = {
  cardRadius: 16,
  chipRadius: 12,
  chipHeight: 24,
  buttonHeight: 40,
  composerMinHeight: 52,
  composerRadius: 28,
  sheetRadius: 28,
} as const;
