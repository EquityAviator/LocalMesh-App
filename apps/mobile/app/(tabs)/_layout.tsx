import React from 'react';
import { Tabs } from 'expo-router';
import { Text } from 'react-native';
import { paletteFor } from '../../src/ui/theme';
import { useThemeMode } from '../../src/ui/useThemeMode';

/** §4.2: three items in phase 1 (Chats, Machines, Settings). */
export default function TabsLayout(): React.ReactElement {
  const { mode } = useThemeMode();
  const palette = paletteFor(mode);
  const icon = (label: string, colour: string) => <Text style={{ fontSize: 18, color: colour }}>{label}</Text>;
  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: palette.primary,
        tabBarInactiveTintColor: palette.textSecondary,
        tabBarStyle: { backgroundColor: palette.surface },
        sceneStyle: { backgroundColor: palette.background },
      }}
    >
      <Tabs.Screen name="chats" options={{ title: 'Chats', tabBarIcon: ({ color }) => icon('💬', color) }} />
      <Tabs.Screen name="machines" options={{ title: 'Machines', tabBarIcon: ({ color }) => icon('🖥', color) }} />
      <Tabs.Screen name="settings" options={{ title: 'Settings', tabBarIcon: ({ color }) => icon('⚙️', color) }} />
    </Tabs>
  );
}
