import React, { useMemo } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Stack, useLocalSearchParams } from 'expo-router';
import { PathBadge, PrimaryButton, TierChip } from '../../src/ui/components';
import { pathChip } from '../../src/features/machines/view';
import { paletteFor } from '../../src/ui/theme';
import { useThemeMode } from '../../src/ui/useThemeMode';
import { machinesStore } from '../../src/state/machinesStore';
import { useStore } from '../../src/state/useStore';
import { toModelRows, type ModelRowVM } from '../../src/features/models/view';
import type { ModelEntry } from '../../src/domain/entities';

/** §6.4 Machine detail — header chips, models, services, start chat. */
export default function MachineDetailScreen(): React.ReactElement {
  const { mode } = useThemeMode();
  const palette = paletteFor(mode);
  const params = useLocalSearchParams<{ agentId?: string }>();
  const agentId = typeof params.agentId === 'string' ? params.agentId : '';
  const { agents, conn } = useStore(machinesStore);
  const agent = agents.find((a) => a.agentId === agentId);
  const state = conn[agentId] ?? { s: 'IDLE' as const };

  // GET /mesh/v1/models arrives through the client; until the machine is
  // connected we render the stored hint list (empty on first run).
  const models: ModelRowVM[] = useMemo(() => {
    const entries: ModelEntry[] = agent ? stubModels(agent) : [];
    return toModelRows(entries);
  }, [agent]);

  if (!agent) {
    return (
      <>
        <Stack.Screen options={{ title: 'Machine' }} />
        <View style={styles.container}>
          <Text style={{ color: palette.text }}>This machine is no longer paired.</Text>
        </View>
      </>
    );
  }

  return (
    <>
      <Stack.Screen options={{ title: agent.displayName }} />
      <ScrollView contentContainerStyle={styles.container}>
        <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
          <PathBadge chip={pathChip(state.s === 'CONNECTED' ? (state.tier === 'T2' ? 'tunnel' : 'wifi') : 'offline')} palette={palette} />
          {state.tier ? <TierChip tier={state.tier} palette={palette} /> : null}
        </View>

        <Text style={{ color: palette.text, fontSize: 16, fontWeight: '500', marginTop: 16 }}>Models</Text>
        <View style={[styles.card, { backgroundColor: palette.surface, borderColor: palette.outline }]}>
          {models.length === 0 ? (
            <Text style={{ color: palette.textSecondary }}>Connect to load the model list.</Text>
          ) : (
            models.map((m) => (
              <View key={m.meshModelId} style={styles.modelRow}>
                <View style={[styles.dot, { backgroundColor: m.loaded ? palette.pathWifi : palette.outline }]} />
                <View style={{ flex: 1 }}>
                  <Text style={{ color: palette.text }}>{m.name}</Text>
                  <Text style={{ color: palette.textSecondary, fontSize: 13 }}>{m.detail}</Text>
                </View>
                {m.capability ? <TierChip tier={m.capability} palette={palette} /> : null}
              </View>
            ))
          )}
        </View>

        <Text style={{ color: palette.text, fontSize: 16, fontWeight: '500', marginTop: 16 }}>Services</Text>
        <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
          {['Chat', 'Vision', 'Voice', 'Documents', 'Agent · not set up'].map((s) => (
            <TierChip key={s} tier={s} palette={palette} />
          ))}
        </View>

        <View style={{ marginTop: 24 }}>
          <PrimaryButton label="Start chat" palette={palette} />
        </View>
        <View style={{ marginTop: 12 }}>
          <PrimaryButton label="Forget this machine" destructive palette={palette} />
        </View>
      </ScrollView>
    </>
  );
}

/** Placeholder until GET /device + /models are wired to the store (M-WP-11). */
function stubModels(agent: { displayName: string }): ModelEntry[] {
  void agent;
  return [];
}

const styles = StyleSheet.create({
  container: { padding: 16, paddingBottom: 48, gap: 8 },
  card: { borderRadius: 16, borderWidth: 1, padding: 16, marginTop: 8 },
  modelRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 8 },
  dot: { width: 8, height: 8, borderRadius: 8 },
});
