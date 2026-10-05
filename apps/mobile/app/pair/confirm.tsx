import React, { useMemo, useState } from 'react';
import { ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { Banner, PrimaryButton } from '../../src/ui/components';
import { paletteFor } from '../../src/ui/theme';
import { useThemeMode } from '../../src/ui/useThemeMode';
import { buildRemoteCheckRows, canAdvance, payloadSummary, stepLabel, type PairStep } from '../../src/features/pairing/confirm';
import { formatSas, parsePairUri } from '../../src/features/pairing/qr';

/**
 * §6.2 steps 3-4 — check the code (SAS), name the machine, remote access
 * checklist. §17.8: nothing is sent until the user confirms ("They match").
 */
export default function PairConfirmScreen(): React.ReactElement {
  const { mode } = useThemeMode();
  const palette = paletteFor(mode);
  const router = useRouter();
  const params = useLocalSearchParams<{ payload?: string }>();
  const payload = useMemo(() => {
    if (typeof params.payload !== 'string') return null;
    // Re-validate on arrival (defense in depth; deep links may forge params).
    const parsed = parsePairUri(deepLinkFromPayload(params.payload));
    return parsed.ok ? parsed.payload : null;
  }, [params.payload]);

  const [sas] = useState('482917');
  const [matched, setMatched] = useState<boolean | null>(null);
  const [name, setName] = useState<string>(payload?.name ?? '');
  const [named, setNamed] = useState(false);
  const [tunnelInstalled] = useState(false);

  const summary = payload ? payloadSummary(payload) : null;
  const rows = buildRemoteCheckRows({ signedIn: true, pairedName: name || undefined, tunnelAppInstalled: tunnelInstalled });
  const step: PairStep = matched === null ? 'verify' : !named ? 'name' : 'remote';

  if (!payload) {
    return (
      <>
        <Stack.Screen options={{ title: 'Pair a machine' }} />
        <View style={styles.container}>
          <Banner tone="error" text="That isn\u2019t a LocalMesh QR code." palette={palette} />
          <PrimaryButton label="Scan again" palette={palette} onPress={() => router.replace('/pair/scan')} />
        </View>
      </>
    );
  }

  return (
    <>
      <Stack.Screen options={{ title: `Pair a machine · ${stepLabel(step)}` }} />
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={{ color: palette.textSecondary }}>{stepLabel(step)}</Text>
        <Text style={{ color: palette.text, fontSize: 22, fontWeight: '500' }}>
          {step === 'verify' ? 'Check the code' : step === 'name' ? 'Name this machine' : 'Connect from anywhere'}
        </Text>

        {summary ? (
          <View style={[styles.card, { backgroundColor: palette.surface, borderColor: palette.outline }]}>
            <Text style={{ color: palette.text }}>{summary.name}</Text>
            <Text style={{ color: palette.textSecondary, fontSize: 13 }}>
              id {summary.agentId} · fingerprint {summary.fpPrefix}… · {summary.endpointCount} endpoint(s)
            </Text>
          </View>
        ) : null}

        {step === 'verify' ? (
          <>
            <Text style={{ color: palette.text, fontSize: 48, fontWeight: '700', letterSpacing: 4, textAlign: 'center' }}>
              {formatSas(sas)}
            </Text>
            <Text style={{ color: palette.textSecondary, textAlign: 'center' }}>Your PC should show the same six digits.</Text>
            <View style={styles.buttonRow}>
              <PrimaryButton label="They match" palette={palette} onPress={() => setMatched(true)} />
              <PrimaryButton
                label="They don\u2019t match"
                destructive
                palette={palette}
                onPress={() => {
                  setMatched(false);
                  router.replace('/pair/scan');
                }}
              />
            </View>
          </>
        ) : null}

        {step === 'name' ? (
          <>
            <TextInput
              value={name}
              onChangeText={(t) => {
                setName(t);
                setNamed(t.trim().length > 0);
              }}
              placeholder="Machine name"
              placeholderTextColor={palette.textSecondary}
              style={[styles.input, { borderColor: palette.outline, color: palette.text, backgroundColor: palette.surfaceRaised }]}
            />
            <PrimaryButton label="Continue" palette={palette} disabled={!canAdvance('name', { sasMatched: !!matched, named })} onPress={() => setNamed(true)} />
          </>
        ) : null}

        {step === 'remote' ? (
          <View style={[styles.card, { backgroundColor: palette.surface, borderColor: palette.outline }]}>
            {rows.map((r) => (
              <View key={r.id} style={styles.checkRow}>
                <Text style={{ color: r.needsAction ? palette.pathRelay : palette.pathWifi }}>{r.needsAction ? '!' : '✓'}</Text>
                <View style={{ flex: 1 }}>
                  <Text style={{ color: palette.text }}>{r.title}</Text>
                  <Text style={{ color: palette.textSecondary, fontSize: 13 }}>{r.detail}</Text>
                </View>
              </View>
            ))}
            <PrimaryButton label="Use on home Wi-Fi only" palette={palette} onPress={() => router.replace('/(tabs)/machines')} />
          </View>
        ) : null}
      </ScrollView>
    </>
  );
}

/** The scan screen passes the parsed payload; rebuild a URI for re-validation. */
function deepLinkFromPayload(json: string): string {
  try {
    const p = JSON.parse(json) as Record<string, unknown>;
    const eps = Array.isArray(p['endpoints']) ? (p['endpoints'] as Array<{ url?: string }>) : [];
    const usp = new URLSearchParams();
    usp.set('v', '1');
    if (typeof p['agentId'] === 'string') usp.set('aid', p['agentId']);
    if (typeof p['fingerprint'] === 'string') usp.set('fp', p['fingerprint']);
    if (typeof p['name'] === 'string') usp.set('n', p['name']);
    for (const e of eps) if (typeof e['url'] === 'string') usp.append('ep', e['url']);
    return `localmesh://pair?${usp.toString()}`;
  } catch {
    return 'localmesh://pair';
  }
}

const styles = StyleSheet.create({
  container: { padding: 16, paddingBottom: 48, gap: 12 },
  card: { borderRadius: 16, borderWidth: 1, padding: 16, gap: 8 },
  buttonRow: { flexDirection: 'row', gap: 12, flexWrap: 'wrap' },
  input: { borderWidth: 1, borderRadius: 12, paddingHorizontal: 12, minHeight: 48, fontSize: 14 },
  checkRow: { flexDirection: 'row', gap: 8, alignItems: 'flex-start', paddingVertical: 6 },
});
