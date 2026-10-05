import { useColorScheme } from 'react-native';
import type { ThemeMode } from './theme';

/** Theme resolution shared by screens ('system' follows the OS setting). */
export function useThemeMode(): { mode: ThemeMode } {
  const scheme = useColorScheme();
  return { mode: scheme === 'dark' ? 'dark' : 'light' };
}
