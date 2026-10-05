/**
 * Minimal design-system components (UI spec §3/§5/§7). Pure react-native —
 * no external UI library. Every path is colour + icon + label (colour is
 * never the only signal, §2 "One status language").
 */

import React from 'react';
import { Pressable, StyleSheet, Text, TextInput, View, type StyleProp, type TextStyle, type ViewStyle } from 'react-native';
import type { PathKey } from '../features/machines/view';
import type { ChipView } from '../features/machines/view';
import { shape, spacing, type Palette, type as Type } from './theme';

export function pathColour(palette: Palette, path: PathKey): string {
  switch (path) {
    case 'wifi':
      return palette.pathWifi;
    case 'tunnel':
      return palette.pathTunnel;
    case 'relay':
      return palette.pathRelay;
    case 'offline':
      return palette.pathOffline;
  }
}

/** §7 Connection chip: 24 dp high, icon + 12 sp label, 15 % tint of path colour. */
export function PathBadge(props: { chip: ChipView; palette: Palette; onPress?: () => void }): React.ReactElement {
  const { chip, palette } = props;
  const colour = props.chip.attention ? palette.error : pathColour(palette, chip.path);
  const tint = `${colour}26`; // 15 % alpha
  const body = (
    <View style={[styles.chip, { backgroundColor: tint }]}>
      <StatusDot colour={colour} pulsing={chip.pulsing} />
      <Text style={[Type.labelMedium, { color: colour }]} numberOfLines={1}>
        {chip.label}
      </Text>
    </View>
  );
  if (props.onPress) {
    return (
      <Pressable onPress={props.onPress} accessibilityRole="button" accessibilityLabel={`Connection: ${chip.label}`}>
        {body}
      </Pressable>
    );
  }
  return body;
}

/** §6.5 connecting: the dot pulses softly (opacity 40–100 %) while connecting. */
export function StatusDot(props: { colour: string; pulsing?: boolean; size?: number }): React.ReactElement {
  return <View style={{ width: props.size ?? 8, height: props.size ?? 8, borderRadius: 8, backgroundColor: props.colour, opacity: props.pulsing ? 0.7 : 1 }} />;
}

export function TierChip(props: { tier: string; palette: Palette }): React.ReactElement {
  return (
    <View style={[styles.chip, { backgroundColor: props.palette.surfaceRaised }]}>
      <Text style={[Type.labelMedium, { color: props.palette.textSecondary }]}>{props.tier}</Text>
    </View>
  );
}

export function MachineCard(props: {
  name: string;
  chip: ChipView;
  hardwareLine?: string;
  modelLine?: string;
  dimmed?: boolean;
  palette: Palette;
  onPress?: () => void;
}): React.ReactElement {
  const { palette } = props;
  return (
    <Pressable
      onPress={props.onPress}
      accessibilityRole="button"
      style={[
        styles.card,
        {
          backgroundColor: palette.surface,
          borderColor: palette.outline,
          opacity: props.dimmed ? 0.78 : 1,
        },
      ]}
    >
      <Text style={[Type.titleMedium, { color: palette.text }]}>{props.name}</Text>
      <View style={{ marginTop: spacing.sm }}>
        <PathBadge chip={props.chip} palette={palette} />
      </View>
      {props.hardwareLine ? (
        <Text style={[Type.bodyMedium, { color: palette.textSecondary, marginTop: spacing.sm }]}>{props.hardwareLine}</Text>
      ) : null}
      {props.modelLine ? (
        <Text style={[Type.bodyMedium, { color: palette.textSecondary, marginTop: spacing.xs }]}>{props.modelLine}</Text>
      ) : null}
    </Pressable>
  );
}

/** §7 Banner: one at a time, persistent until resolved, at most one action. */
export function Banner(props: {
  tone: 'info' | 'warning' | 'error';
  text: string;
  actionLabel?: string;
  onAction?: () => void;
  palette: Palette;
}): React.ReactElement | null {
  const { palette } = props;
  const colour = props.tone === 'error' ? palette.error : props.tone === 'warning' ? palette.pathRelay : palette.primary;
  if (!props.text) return null;
  return (
    <View style={[styles.banner, { borderColor: colour, backgroundColor: palette.surface }]}>
      <Text style={[Type.bodyMedium, { color: palette.text, flex: 1 }]}>{props.text}</Text>
      {props.actionLabel && props.onAction ? (
        <Pressable onPress={props.onAction} accessibilityRole="button" hitSlop={8}>
          <Text style={[Type.labelLarge, { color: colour }]}>{props.actionLabel}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export function PrimaryButton(props: {
  label: string;
  onPress?: () => void;
  disabled?: boolean;
  destructive?: boolean;
  palette: Palette;
}): React.ReactElement {
  const bg = props.disabled ? props.palette.surfaceRaised : props.destructive ? props.palette.error : props.palette.primary;
  const fg = props.disabled ? props.palette.textSecondary : '#FFFFFF';
  return (
    <Pressable
      onPress={props.disabled ? undefined : props.onPress}
      accessibilityRole="button"
      accessibilityState={{ disabled: !!props.disabled }}
      style={[styles.button, { backgroundColor: bg }]}
    >
      <Text style={[Type.labelLarge, { color: fg }]}>{props.label}</Text>
    </Pressable>
  );
}

/** Your message: Primary container, 82 % max width, 18/4 dp corners (§7). */
export function MessageBubble(props: {
  role: 'user' | 'assistant' | 'system';
  text: string;
  statusLabel?: string;
  palette: Palette;
  headerDot?: string;
  headerText?: string;
}): React.ReactElement {
  const { palette } = props;
  if (props.role === 'user') {
    return (
      <View style={[styles.userBubble, { backgroundColor: palette.primaryContainer }]}>
        <Text style={[Type.bodyLarge, { color: palette.text }]}>{props.text}</Text>
        {props.statusLabel ? <Text style={[Type.labelMedium, { color: palette.textSecondary, marginTop: spacing.xs }]}>{props.statusLabel}</Text> : null}
      </View>
    );
  }
  return (
    <View style={styles.assistantBlock}>
      {props.headerText ? (
        <View style={styles.assistantHeader}>
          {props.headerDot ? <StatusDot colour={props.headerDot} size={6} /> : null}
          <Text style={[Type.labelMedium, { color: palette.textSecondary }]}>{props.headerText}</Text>
        </View>
      ) : null}
      <Text style={[Type.bodyLarge, { color: palette.text }]}>{props.text}</Text>
      {props.statusLabel ? <Text style={[Type.labelMedium, { color: palette.textSecondary, marginTop: spacing.xs }]}>{props.statusLabel}</Text> : null}
    </View>
  );
}

/** §7 Composer: 52 dp min, 28 dp radius, trailing mic/send/stop button. */
export function Composer(props: {
  value: string;
  onChangeText: (t: string) => void;
  onSend: () => void;
  onStop?: () => void;
  streaming?: boolean;
  disabled?: boolean;
  placeholder: string;
  palette: Palette;
}): React.ReactElement {
  const canSend = !props.disabled && (props.value.trim().length > 0 || !!props.streaming);
  return (
    <View style={[styles.composer, { backgroundColor: props.palette.surfaceRaised }]}>
      <TextInput
        style={[Type.bodyLarge, { color: props.palette.text, flex: 1 }]}
        value={props.value}
        editable={!props.disabled}
        onChangeText={props.onChangeText}
        placeholder={props.placeholder}
        placeholderTextColor={props.palette.textSecondary}
        multiline
      />
      <Pressable
        accessibilityRole="button"
        onPress={props.streaming ? props.onStop : canSend ? props.onSend : undefined}
        disabled={!props.streaming && !canSend}
        style={[styles.sendButton, { backgroundColor: props.streaming ? props.palette.error : canSend ? props.palette.primary : props.palette.outline }]}
      >
        <Text style={[Type.labelLarge, { color: '#FFFFFF' }]}>{props.streaming ? 'Stop' : 'Send'}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  chip: {
    height: shape.chipHeight,
    borderRadius: shape.chipRadius,
    paddingHorizontal: spacing.sm,
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: spacing.xs,
  },
  card: {
    borderRadius: shape.cardRadius,
    borderWidth: 1,
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: shape.cardRadius,
    borderWidth: 1,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    gap: spacing.md,
  },
  button: {
    height: shape.buttonHeight,
    borderRadius: shape.buttonHeight / 2,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.xl,
  },
  userBubble: {
    maxWidth: '82%',
    alignSelf: 'flex-end',
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    borderBottomLeftRadius: 18,
    borderBottomRightRadius: 4,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    marginVertical: spacing.xs,
  },
  assistantBlock: {
    marginVertical: spacing.xs,
    paddingVertical: spacing.xs,
  },
  assistantHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginBottom: spacing.xs,
  },
  composer: {
    minHeight: shape.composerMinHeight,
    borderRadius: shape.composerRadius,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    gap: spacing.sm,
  },
  sendButton: {
    height: 40,
    borderRadius: 20,
    paddingHorizontal: spacing.lg,
    alignItems: 'center',
    justifyContent: 'center',
  },
});

export const S: { row: StyleProp<ViewStyle>; caption: StyleProp<TextStyle> } = {
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  caption: { ...Type.bodyMedium, color: undefined },
};
