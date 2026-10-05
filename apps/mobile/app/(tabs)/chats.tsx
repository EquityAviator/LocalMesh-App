import React from 'react';
import { FlatList, StyleSheet, Text, View } from 'react-native';
import { Link, Stack } from 'expo-router';
import { paletteFor } from '../../src/ui/theme';
import { useThemeMode } from '../../src/ui/useThemeMode';
import { chatsStore } from '../../src/state/chatsStore';
import { useStore } from '../../src/state/useStore';
import { machinesStore } from '../../src/state/machinesStore';

/** §6.5/§4.1 Chats tab — conversation list, newest first. */
export default function ChatsScreen(): React.ReactElement {
  const { mode } = useThemeMode();
  const palette = paletteFor(mode);
  const { conversations } = useStore(chatsStore);
  const { agents, conn } = useStore(machinesStore);
  const startDestination = Object.values(conn).some((c) => c.s === 'CONNECTED') ? 'Chats' : 'Machines';
  void startDestination; // §4.2 start-destination rule; router redirect lands in a later WP

  return (
    <>
      <Stack.Screen options={{ title: 'Chats' }} />
      <FlatList
        style={styles.list}
        contentContainerStyle={{ padding: 16 }}
        data={conversations}
        keyExtractor={(c) => c.id}
        ListEmptyComponent={
          <View style={{ alignItems: 'center', paddingVertical: 48 }}>
            <Text style={{ color: palette.text, fontSize: 16, lineHeight: 24 }}>No chats yet</Text>
            <Text style={{ color: palette.textSecondary, marginTop: 8, textAlign: 'center' }}>
              Start a chat from a machine that is online.
            </Text>
            <Link href="/(tabs)/machines" style={{ color: palette.primary, marginTop: 16, fontSize: 16 }}>
              My AI machines
            </Link>
          </View>
        }
        renderItem={({ item }) => {
          const agent = agents.find((a) => a.agentId === item.agentId);
          return (
            <Link
              href={`/chat/${item.id}`}
              style={[styles.row, { backgroundColor: palette.surface, borderColor: palette.outline }]}
            >
              <View style={{ flex: 1 }}>
                <Text style={{ color: palette.text, fontSize: 16, fontWeight: '500' }}>{item.title}</Text>
                <Text style={{ color: palette.textSecondary, marginTop: 2, fontSize: 12 }}>
                  {agent?.displayName ?? item.agentId ?? 'Portable history'}
                </Text>
              </View>
            </Link>
          );
        }}
      />
    </>
  );
}

const styles = StyleSheet.create({
  list: { flex: 1 },
  row: {
    borderRadius: 16,
    borderWidth: 1,
    padding: 16,
    marginBottom: 12,
    flexDirection: 'row',
  },
});
