import React, { useCallback, useMemo } from 'react';
import { FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { Link, Stack } from 'expo-router';
import { MachineCard } from '../../src/ui/components';
import { paletteFor } from '../../src/ui/theme';
import { useThemeMode } from '../../src/ui/useThemeMode';
import { buildMachineCard, sortCards, type MachineCardVM } from '../../src/features/machines/view';
import { machinesStore } from '../../src/state/machinesStore';
import { useStore } from '../../src/state/useStore';
import type { PairedAgent } from '../../src/domain/entities';

/** §6.3 Machines — "My AI machines": cards with the connection chip. */
export default function MachinesScreen(): React.ReactElement {
  const { mode } = useThemeMode();
  const palette = paletteFor(mode);
  const { agents, conn, discovery } = useStore(machinesStore);

  const refresh = useCallback(() => {
    // Pull to refresh re-runs discovery (§6.3); the native events update the store.
    void agents.length;
    void discovery.length;
  }, [agents.length, discovery.length]);

  const cards: MachineCardVM[] = useMemo(() => {
    const built = agents.map((a: PairedAgent) =>
      buildMachineCard({
        agent: a,
        conn: conn[a.agentId] ?? { s: 'IDLE' },
        now: Date.now(),
      }),
    );
    return sortCards(built, {});
  }, [agents, conn]);

  const onlineCount = cards.filter((c) => !c.dimmed).length;

  return (
    <>
      <Stack.Screen options={{ title: 'My AI machines' }} />
      <FlatList
        style={styles.list}
        contentContainerStyle={{ padding: 16 }}
        data={cards}
        keyExtractor={(c) => c.agentId}
        ListHeaderComponent={
          <Text style={[{ color: palette.textSecondary, marginBottom: 12, ...{ fontSize: 14, lineHeight: 20 } }]}>
            {agents.length === 0 ? 'No machines yet' : `${onlineCount} of ${cards.length} online`}
          </Text>
        }
        ListEmptyComponent={
          <View style={{ alignItems: 'center', paddingVertical: 48 }}>
            <Text style={{ color: palette.text, fontSize: 16, lineHeight: 24 }}>No machines yet</Text>
            <Text style={{ color: palette.textSecondary, marginTop: 8, textAlign: 'center' }}>
              Add the PC that runs your models to chat with them from this phone.
            </Text>
            <Link href="/pair/scan" style={{ color: palette.primary, marginTop: 16, fontSize: 16 }}>
              Add your first machine
            </Link>
          </View>
        }
        renderItem={({ item }) => (
          <Link href={`/machine/${item.agentId}`} asChild>
            <MachineCard name={item.name} chip={item.chip} hardwareLine={item.hardwareLine} modelLine={item.modelLine} dimmed={item.dimmed} palette={palette} />
          </Link>
        )}
        ListFooterComponent={
          <Link href="/pair/scan" style={{ color: palette.primary, paddingVertical: 16, fontSize: 16 }}>
            Add machine
          </Link>
        }
        refreshControl={<RefreshControl refreshing={false} onRefresh={refresh} tintColor={palette.textSecondary} />}
      />
    </>
  );
}

const styles = StyleSheet.create({
  list: { flex: 1 },
});
