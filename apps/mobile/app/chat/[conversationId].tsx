import React, { useEffect } from 'react';
import { FlatList, KeyboardAvoidingView, Platform, StyleSheet, Text, View } from 'react-native';
import { Stack, useLocalSearchParams } from 'expo-router';
import { Banner, Composer, MessageBubble, PathBadge } from '../../src/ui/components';
import { paletteFor } from '../../src/ui/theme';
import { useThemeMode } from '../../src/ui/useThemeMode';
import { chatsStore, setDraft } from '../../src/state/chatsStore';
import { machinesStore } from '../../src/state/machinesStore';
import { useStore } from '../../src/state/useStore';
import { connStateToChip, tierToPath } from '../../src/features/machines/view';
import { refreshAgentData } from '../../src/features/machines/live';
import { cancelStream, sendMessage } from '../../src/features/chat/send';
import { composerVM } from '../../src/features/chat/composer';

/** §6.5 Chat — route row pinned, bubbles, composer swaps Send/Stop. */
export default function ChatScreen(): React.ReactElement {
  const { mode } = useThemeMode();
  const palette = paletteFor(mode);
  const params = useLocalSearchParams<{ conversationId?: string }>();
  const conversationId = typeof params.conversationId === 'string' ? params.conversationId : '';
  const { conversations, messages, drafts, streaming } = useStore(chatsStore);
  const { agents, conn } = useStore(machinesStore);
  const conversation = conversations.find((c) => c.id === conversationId);
  const agent = agents.find((a) => a.agentId === conversation?.agentId);
  const state = agent ? (conn[agent.agentId] ?? { s: 'IDLE' as const }) : { s: 'IDLE' as const };
  const chip = connStateToChip(state);
  const stream = streaming[conversationId];
  const thread = messages[conversationId] ?? [];
  const draft = drafts[conversationId] ?? '';
  const vm = composerVM({
    agentName: agent?.displayName ?? 'Machine',
    conn: state,
    phoneOffline: false,
    text: draft,
    streaming: !!stream,
  });

  // Direct navigation to a chat still needs the live snapshot (models, conn).
  useEffect(() => {
    if (Platform.OS === 'web') void refreshAgentData();
  }, []);

  const rows = [
    ...thread.map((m) => ({ kind: 'message' as const, id: m.id, message: m })),
    ...(stream ? [{ kind: 'stream' as const, id: `${stream.messageId}-live`, visible: stream.visible, meta: stream.meta }] : []),
  ];

  const streamHeader = stream?.meta
    ? [stream.meta.model, stream.meta.backend].filter(Boolean).join(' · ')
    : (conversation?.modelRef ?? agent?.displayName);

  return (
    <>
      <Stack.Screen options={{ headerShown: true, title: conversation?.title ?? 'Chat' }} />
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={[styles.routeRow, { borderColor: palette.outline, backgroundColor: palette.surface }]}>
          <PathBadge chip={chip} palette={palette} />
          <Text style={{ color: palette.textSecondary, fontSize: 13 }}>
            {agent?.displayName ?? ''}
            {state.tier ? ` · ${state.tier}` : ''}
          </Text>
        </View>

        {state.s === 'UNREACHABLE' || state.s === 'PIN_MISMATCH' ? (
          <Banner tone="error" text="Connection dropped. Your reply so far is saved." palette={palette} actionLabel="Retry" onAction={() => void refreshAgentData()} />
        ) : null}

        <FlatList
          style={styles.flex}
          contentContainerStyle={{ padding: 16 }}
          data={rows}
          keyExtractor={(r) => r.id}
          renderItem={({ item }) => {
            if (item.kind === 'stream') {
              return (
                <MessageBubble
                  role="assistant"
                  text={`${item.visible}▍`}
                  headerDot={palette.pathWifi}
                  headerText={streamHeader}
                  palette={palette}
                />
              );
            }
            const m = item.message;
            return (
              <MessageBubble
                role={m.role === 'system' ? 'assistant' : m.role}
                text={m.content}
                palette={palette}
                headerDot={m.role === 'assistant' ? palette.pathWifi : undefined}
                headerText={m.role === 'assistant' ? m.modelRef ?? agent?.displayName : undefined}
                statusLabel={m.status !== 'complete' ? m.status : undefined}
              />
            );
          }}
          ListEmptyComponent={
            <Text style={{ color: palette.textSecondary, textAlign: 'center', marginTop: 32 }}>
              Messages stay on this phone and the machine you pair with.
            </Text>
          }
        />

        <View style={{ padding: 12 }}>
          <Composer
            value={draft}
            onChangeText={(t) => setDraft(conversationId, t)}
            onSend={() => sendMessage(conversationId, draft)}
            onStop={() => cancelStream(conversationId)}
            streaming={!!stream}
            disabled={vm.sendDisabled}
            placeholder={vm.placeholder}
            palette={palette}
          />
          <Text style={{ color: palette.textSecondary, fontSize: 11, marginTop: 4 }}>
            {state.s === 'CONNECTED' ? `Connected via ${tierToPath(state.tier ?? 'T0')}` : chip.label}
          </Text>
        </View>
      </KeyboardAvoidingView>
    </>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  routeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderBottomWidth: 1,
  },
});
