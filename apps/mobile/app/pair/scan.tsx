import React, { useState } from 'react';
import { ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { Stack, useRouter } from 'expo-router';
import { Banner, PrimaryButton } from '../../src/ui/components';
import { paletteFor } from '../../src/ui/theme';
import { useThemeMode } from '../../src/ui/useThemeMode';
import { parsePairUri } from '../../src/features/pairing/qr';
import type { ParsedPairPayload } from '../../src/features/pairing/qr';

/**
 * §6.2 step 2 — scan the QR on the PC. The camera itself is native
 * (mesh-core/host camera view lands with the Kotlin module); this screen owns
 * permission copy, manual fallback and payload validation.
 */
export default function PairScanScreen(): React.ReactElement {
  const { mode } = useThemeMode();
  const palette = paletteFor(mode);
  const router = useRouter();
  const [manual, setManual] = useState('');
  const [error, setError] = useState<string | null>(null);

  const proceed = (raw: string) => {
    const parsed = parsePairUri(raw.trim());
    if (!parsed.ok) {
      setError('That isn\u2019t a LocalMesh QR code.');
      return;
    }
    const payload: ParsedPairPayload = parsed.payload;
    // §17.8: deep link opens the flow; explicit confirmation still required.
    router.push({ pathname: '/pair/confirm', params: { payload: JSON.stringify({ ...payload, secret: undefined }) } });
  };

  return (
    <>
      <Stack.Screen options={{ title: 'Pair a machine' }} />
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={{ color: palette.text, fontSize: 22, fontWeight: '500' }}>Scan the QR code on your PC</Text>
        <Text style={{ color: palette.textSecondary, marginTop: 8 }}>
          Open LocalMesh on your PC and choose Add device. Camera permission is asked just before this screen.
        </Text>

        <View style={[styles.scanArea, { borderColor: palette.outline, backgroundColor: palette.surface }]}>
          <Text style={{ color: palette.textSecondary }}>Camera preview (native module pending)</Text>
        </View>

        {error ? <Banner tone="error" text={error} palette={palette} actionLabel="Try again" onAction={() => setError(null)} /> : null}

        <Text style={{ color: palette.text, marginTop: 24, fontSize: 16, fontWeight: '500' }}>Enter code instead</Text>
        <Text style={{ color: palette.textSecondary, marginTop: 4 }}>
          Paste the pairing link printed under the QR code.
        </Text>
        <TextInput
          value={manual}
          onChangeText={setManual}
          placeholder="localmesh://pair?v=1&aid=…"
          placeholderTextColor={palette.textSecondary}
          autoCorrect={false}
          autoCapitalize="none"
          style={[styles.input, { borderColor: palette.outline, color: palette.text, backgroundColor: palette.surfaceRaised }]}
        />
        <PrimaryButton label="Continue" palette={palette} disabled={manual.trim().length === 0} onPress={() => proceed(manual)} />
      </ScrollView>
    </>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, paddingBottom: 48, gap: 12 },
  scanArea: {
    height: 220,
    borderRadius: 16,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 8,
  },
  input: {
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 12,
    minHeight: 48,
    fontSize: 14,
  },
});
