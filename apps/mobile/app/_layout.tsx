import React from 'react';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useThemeMode } from '../src/ui/useThemeMode';
import { paletteFor } from '../src/ui/theme';

/** Root stack: tabs + pushed screens (§11.1 app/ layout; UI spec §4). */
export default function RootLayout(): React.ReactElement {
  const { mode } = useThemeMode();
  const palette = paletteFor(mode);
  return (
    <>
      <StatusBar style={mode === 'dark' ? 'light' : 'dark'} />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: palette.surface },
          headerTintColor: palette.text,
          contentStyle: { backgroundColor: palette.background },
        }}
      >
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="pair/scan" options={{ title: 'Pair a machine' }} />
        <Stack.Screen name="pair/confirm" options={{ title: 'Pair a machine' }} />
        <Stack.Screen name="machine/[agentId]" options={{ title: 'Machine' }} />
        <Stack.Screen name="chat/[conversationId]" options={{ headerShown: false }} />
        <Stack.Screen name="doctor" options={{ title: 'Diagnostics' }} />
      </Stack>
    </>
  );
}
