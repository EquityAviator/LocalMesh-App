import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Stack, useRouter, useLocalSearchParams } from 'expo-router';
import { PathBadge, PrimaryButton, TierChip } from '../../src/ui/components';
import { pathChip } from '../../src/features/machines/view';
import { firstChatModelId, refreshAgentData } from '../../src/features/machines/live';
import { applyModelOpResponse, modelOpNotice, toModelRows, type ModelOpState, type ModelRowVM } from '../../src/features/models/view';
import { paletteFor, type Palette } from '../../src/ui/theme';
import { useThemeMode } from '../../src/ui/useThemeMode';
import { agentDataStore, patchAgentModel } from '../../src/state/agentDataStore';
import { machinesStore } from '../../src/state/machinesStore';
import { useStore } from '../../src/state/useStore';
import { createConversation } from '../../src/state/chatsStore';
import { getMeshApiClient } from '../../src/data/mesh/client';

/** §6.4 Machine detail — header chips, models, services, start chat. */
export default function MachineDetailScreen(): React.ReactElement {
  const { mode } = useThemeMode();
  const palette = paletteFor(mode);
  const router = useRouter();
  const params = useLocalSearchParams<{ agentId?: string }>();
  const agentId = typeof params.agentId === 'string' ? params.agentId : '';
  const { agents, conn } = useStore(machinesStore);
  const agentData = useStore(agentDataStore);
  const agent = agents.find((a) => a.agentId === agentId);
  const state = conn[agentId] ?? { s: 'IDLE' as const };
  const live = agent ? agentData[agent.agentId] : undefined;
  const isWeb = Platform.OS === 'web';

  useEffect(() => {
    if (isWeb) void refreshAgentData();
  }, [isWeb]);

  const [opStates, setOpStates] = useState<Record<string, ModelOpState>>({});
  const [notice, setNotice] = useState<string | null>(null);

  // Live GET /mesh/v1/models arrives through the client (§11.3); until data
  // lands we render the stored hint list (empty on first run).
  const models: ModelRowVM[] = useMemo(() => toModelRows(live?.models ?? []), [live]);

  const toggleModel = useCallback(
    async (row: ModelRowVM) => {
      if (!agent) return;
      const target: ModelOpState = row.loaded ? 'unloading' : 'loading';
      setOpStates((prev) => ({ ...prev, [row.meshModelId]: target }));
      setNotice(modelOpNotice(row.name, target));
      const client = getMeshApiClient();
      try {
        const body = row.loaded ? await client.unloadModel(row.meshModelId) : await client.loadModel(row.meshModelId);
        const next = applyModelOpResponse(target, { state: body.state });
        // Optimistic flip (202 loading/unloaded, §13.2); the next refresh
        // reconciles with the registry's real state.
        patchAgentModel(agent.agentId, row.meshModelId, { loaded: !row.loaded });
        setOpStates((prev) => ({ ...prev, [row.meshModelId]: next }));
        setNotice(modelOpNotice(row.name, next));
      } catch {
        setOpStates((prev) => ({ ...prev, [row.meshModelId]: 'error' }));
        patchAgentModel(agent.agentId, row.meshModelId, { loaded: row.loaded });
        setNotice(modelOpNotice(row.name, 'error'));
      }
    },
    [agent],
  );

  const startChat = useCallback(() => {
    if (!agent) return;
    const conv = createConversation({
      agentId: agent.agentId,
      title: agent.displayName,
      modelRef: firstChatModelId(agent.agentId) ?? undefined,
    });
    router.push(`/chat/${conv.id}`);
  }, [agent, router]);

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
                <ModelOpButton row={m} state={opStates[m.meshModelId] ?? 'idle'} palette={palette} onPress={() => void toggleModel(m)} />
              </View>
            ))
          )}
        </View>
        {notice ? <Text style={{ color: palette.textSecondary, fontSize: 13 }}>{notice}</Text> : null}

        <Text style={{ color: palette.text, fontSize: 16, fontWeight: '500', marginTop: 16 }}>Backends</Text>
        <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
          {(live?.backends ?? []).map((b) => (
            <TierChip key={b.id} tier={`${b.id} · ${b.status}`} palette={palette} />
          ))}
          {live?.status ? <TierChip tier={`agent · ${live.status}`} palette={palette} /> : null}
          {live && live.backends.length === 0 && !live.status ? (
            <Text style={{ color: palette.textSecondary }}>Health unavailable.</Text>
          ) : null}
        </View>

        <Text style={{ color: palette.text, fontSize: 16, fontWeight: '500', marginTop: 16 }}>Services</Text>
        <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
          {['Chat', 'Vision', 'Voice', 'Documents', 'Agent · not set up'].map((s) => (
            <TierChip key={s} tier={s} palette={palette} />
          ))}
        </View>

        <View style={{ marginTop: 24 }}>
          <PrimaryButton label="Start chat" palette={palette} onPress={startChat} />
        </View>
        <View style={{ marginTop: 12 }}>
          <PrimaryButton label="Forget this machine" destructive palette={palette} />
        </View>
      </ScrollView>
    </>
  );
}

/** Load/unload toggle per model row (§13.2 API-MODEL-02/03, FR-MOD-04). */
function ModelOpButton(props: { row: ModelRowVM; state: ModelOpState; palette: Palette; onPress: () => void }): React.ReactElement {
  const busy = props.state === 'loading' || props.state === 'unloading';
  const label = busy
    ? props.state === 'loading'
      ? 'Loading…'
      : 'Unloading…'
    : props.state === 'error'
      ? 'Retry'
      : props.row.loaded
        ? 'Unload'
        : 'Load';
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: busy }}
      onPress={busy ? undefined : props.onPress}
      style={[styles.opButton, { backgroundColor: props.palette.surfaceRaised, opacity: busy ? 0.5 : 1 }]}
    >
      <Text style={{ color: props.palette.text, fontSize: 13 }}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, paddingBottom: 48, gap: 8 },
  card: { borderRadius: 16, borderWidth: 1, padding: 16, marginTop: 8 },
  modelRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 8 },
  dot: { width: 8, height: 8, borderRadius: 8 },
  opButton: { borderRadius: 12, paddingHorizontal: 12, paddingVertical: 6 },
});
