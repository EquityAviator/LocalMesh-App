import React, { useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Stack } from 'expo-router';
import { PrimaryButton } from '../../src/ui/components';
import { paletteFor } from '../../src/ui/theme';
import { useThemeMode } from '../../src/ui/useThemeMode';
import { buildDoctorReport, runDoctor, type DoctorCheck } from '../../src/features/diagnostics/doctor';
import { SystemClock } from '../../src/domain/connection/clock';
import { machinesStore } from '../../src/state/machinesStore';
import { useStore } from '../../src/state/useStore';

/**
 * §18.4 Diagnostics screen — runs the ordered ladder and offers the shareable
 * report (no Content, no secrets).
 */
export default function DoctorScreen(): React.ReactElement {
  const { mode } = useThemeMode();
  const palette = paletteFor(mode);
  const { agents, conn } = useStore(machinesStore);
  const [checks, setChecks] = useState<DoctorCheck[] | null>(null);
  const [running, setRunning] = useState(false);
  const agent = agents[0];

  const run = async () => {
    setRunning(true);
    try {
      const clock = new SystemClock();
      // The probes below are wired to mesh-core in WP-11; until the native
      // build lands they report structurally honest "not available" results.
      const results = await runDoctor({
        clock,
        getNetwork: async () => ({ transport: 'none', vpnActive: false, metered: false }),
        getPermission: async () => 'unknown',
        isTailscaleInstalled: async () => false,
        discoverySawAgent: () => false,
        candidates: agent?.endpoints ?? [],
        probeCandidate: async () => ({ dns: false, tcp: false, tlsPin: false, info: false, agentIdOk: false }),
        authCheck: async () => ({ ok: false }),
        healthCheck: async () => ({ ok: false }),
        backendStatus: async () => ({ ok: false, summary: 'not available yet' }),
      });
      setChecks(results);
    } finally {
      setRunning(false);
    }
  };

  const report = checks
    ? buildDoctorReport(checks, {
        agentName: agent?.displayName ?? 'no machine paired',
        pin: agent?.spkiPin,
        at: Date.now(),
        generatedBy: 'LocalMesh App 1.0.0-rc.1',
      })
    : null;

  return (
    <>
      <Stack.Screen options={{ title: 'Diagnostics' }} />
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={{ color: palette.textSecondary }}>
          Checks: network type/VPN → permission → tunnel app → discovery → candidates → auth → health → backends.
        </Text>
        <PrimaryButton label={running ? 'Running…' : 'Run checks'} disabled={running} palette={palette} onPress={() => void run()} />
        {checks?.map((c, i) => (
          <View key={`${c.id}-${i}`} style={[styles.row, { backgroundColor: palette.surface, borderColor: palette.outline }]}>
            <Text style={{ color: c.ok ? palette.pathWifi : palette.error }}>{c.ok ? '✓' : '✗'}</Text>
            <View style={{ flex: 1 }}>
              <Text style={{ color: palette.text }}>{c.id}</Text>
              {c.detail ? <Text style={{ color: palette.textSecondary, fontSize: 13 }}>{c.detail}</Text> : null}
            </View>
            {c.ci ? <Text style={{ color: palette.pathRelay, fontSize: 12 }}>{c.ci}</Text> : null}
          </View>
        ))}
        {report ? (
          <View style={[styles.report, { backgroundColor: palette.surfaceRaised }]}>
            <Text style={{ color: palette.text, fontFamily: undefined }}>{report}</Text>
          </View>
        ) : null}
      </ScrollView>
    </>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, paddingBottom: 48, gap: 12 },
  row: { flexDirection: 'row', gap: 8, borderRadius: 12, borderWidth: 1, padding: 12, alignItems: 'center' },
  report: { borderRadius: 12, padding: 12 },
});
