import React from 'react';
import { ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { Link, Stack } from 'expo-router';
import { PrimaryButton } from '../../src/ui/components';
import { paletteFor } from '../../src/ui/theme';
import { useThemeMode } from '../../src/ui/useThemeMode';
import { settingsStore } from '../../src/state/settingsStore';
import { useStore } from '../../src/state/useStore';
import type { SettingsState } from '../../src/state/settingsStore';

/** §6.10 Settings root — every row has a title and a live summary. */
export default function SettingsScreen(): React.ReactElement {
  const { mode } = useThemeMode();
  const palette = paletteFor(mode);
  const settings = useStore(settingsStore);

  const set = (patch: Partial<SettingsState>) => settingsStore.setState((prev) => ({ ...prev, ...patch }));

  const rows: Array<{ title: string; summary: string }> = [
    { title: 'Connection', summary: settings.autoSwitchPaths ? 'Switch automatically' : 'Manual' },
    { title: 'Models and routing', summary: 'Auto routing on' },
    { title: 'Chat', summary: `Text size ${settings.textSizeSp} sp` },
    { title: 'Devices and security', summary: 'App lock off' },
    { title: 'Storage and history', summary: settings.autoDeleteDays === 0 ? 'Auto-delete: never' : `Auto-delete: ${settings.autoDeleteDays} days` },
    { title: 'Appearance', summary: settings.theme === 'system' ? 'Theme: System' : `Theme: ${settings.theme}` },
  ];

  return (
    <>
      <Stack.Screen options={{ title: 'Settings' }} />
      <ScrollView contentContainerStyle={styles.container}>
        <View style={[styles.card, { backgroundColor: palette.surface, borderColor: palette.outline }]}>
          {rows.map((r) => (
            <View key={r.title} style={styles.row}>
              <Text style={{ color: palette.text, flex: 1, fontSize: 16 }}>{r.title}</Text>
              <Text style={{ color: palette.textSecondary }}>{r.summary}</Text>
            </View>
          ))}
        </View>

        <View style={[styles.card, { backgroundColor: palette.surface, borderColor: palette.outline }]}>
          <View style={styles.row}>
            <Text style={{ color: palette.text, flex: 1 }}>Switch paths automatically</Text>
            <Switch value={settings.autoSwitchPaths} onValueChange={(v) => set({ autoSwitchPaths: v })} />
          </View>
          <View style={styles.row}>
            <Text style={{ color: palette.text, flex: 1 }}>Allow relay fallback</Text>
            <Switch value={settings.allowRelayFallback} onValueChange={(v) => set({ allowRelayFallback: v })} />
          </View>
          <View style={styles.row}>
            <Text style={{ color: palette.text, flex: 1 }}>Dynamic colour</Text>
            <Switch value={settings.dynamicColour} onValueChange={(v) => set({ dynamicColour: v })} />
          </View>
        </View>

        <Link href="/doctor" asChild>
          <PrimaryButton label="Diagnostics" palette={palette} />
        </Link>
        <View style={{ height: 12 }} />
        <Link href="/pair/scan" asChild>
          <PrimaryButton label="Pair a machine" palette={palette} />
        </Link>
        <Text style={{ color: palette.textSecondary, marginTop: 24, fontSize: 12 }}>
          LocalMesh · version 1.0.0-rc.1 · Share diagnostics exports connection events with no prompts or replies.
        </Text>
      </ScrollView>
    </>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, paddingBottom: 48 },
  card: {
    borderRadius: 16,
    borderWidth: 1,
    padding: 16,
    marginBottom: 12,
  },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 10 },
});
