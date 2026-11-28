/**
 * A bottom sheet with the settings behind a preset.
 *
 * @module AdvancedSheet
 *
 * Port of ``client/src/components/chat/AdvancedDrawer.tsx``. Without an API
 * key of the account's own the server only lets a run get cheaper, so the
 * agent presets are shown disabled rather than offered and refused.
 */

import { Modal, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import {
  ALL_CHANNELS,
  PRESET_DEFAULTS,
  defaultSettings,
  presetAvailability,
  type Capabilities,
  type ChannelId,
  type DrawerSettings,
  type PresetId,
  type RerankId,
  type TransformId,
} from "@/lib/agent/presets";

const RERANKERS: { value: RerankId; label: string }[] = [
  { value: "none", label: "None" },
  { value: "cohere", label: "Cohere" },
  { value: "llm", label: "Language model" },
  { value: "jev", label: "Jev" },
];

const TRANSFORMS: { value: TransformId; label: string }[] = [
  { value: "identity", label: "As typed" },
  { value: "multi_query", label: "Multi-query" },
  { value: "hyde", label: "HyDE" },
];

const PRESET_ORDER: PresetId[] = [
  "classic",
  "hybrid",
  "hybrid_rerank",
  "structural",
  "deep_agent",
  "deep_agent_workers",
];

/** A row of mutually exclusive chips. */
function Chips<T extends string>({
  options,
  value,
  onChange,
  testPrefix,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (next: T) => void;
  testPrefix: string;
}) {
  return (
    <View className="flex-row flex-wrap gap-2">
      {options.map((option) => (
        <Pressable
          key={option.value}
          testID={`${testPrefix}-${option.value}`}
          accessibilityRole="button"
          accessibilityState={{ selected: option.value === value }}
          onPress={() => onChange(option.value)}
          className={`min-h-[36px] justify-center rounded-sm border px-3 ${
            option.value === value
              ? "border-accent bg-accent/10"
              : "border-input"
          }`}
        >
          <Text className="font-pixel text-[11px] uppercase text-zinc-300">
            {option.label}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

/** A number with minus and plus buttons. */
function Stepper({
  label,
  value,
  min,
  max,
  onChange,
  testPrefix,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (next: number) => void;
  testPrefix: string;
}) {
  return (
    <View className="flex-row items-center justify-between">
      <Text className="text-sm text-foreground">{label}</Text>
      <View className="flex-row items-center gap-3">
        <Pressable
          testID={`${testPrefix}-down`}
          accessibilityLabel={`Fewer ${label}`}
          onPress={() => onChange(Math.max(min, value - 1))}
          className="h-9 w-9 items-center justify-center rounded-sm border border-input"
        >
          <Text className="font-pixel text-foreground">-</Text>
        </Pressable>
        <Text className="w-8 text-center font-pixel text-foreground">{value}</Text>
        <Pressable
          testID={`${testPrefix}-up`}
          accessibilityLabel={`More ${label}`}
          onPress={() => onChange(Math.min(max, value + 1))}
          className="h-9 w-9 items-center justify-center rounded-sm border border-input"
        >
          <Text className="font-pixel text-foreground">+</Text>
        </Pressable>
      </View>
    </View>
  );
}

/**
 * The advanced settings sheet.
 *
 * @param props - Visibility, the preset being tuned, its values and the handlers.
 * @returns The sheet.
 */
export function AdvancedSheet({
  open,
  preset,
  settings,
  caps,
  onClose,
  onPreset,
  onChange,
}: {
  open: boolean;
  preset: PresetId;
  settings: DrawerSettings;
  caps: Capabilities;
  onClose: () => void;
  onPreset: (preset: PresetId) => void;
  onChange: (settings: DrawerSettings) => void;
}) {
  const insets = useSafeAreaInsets();
  const defaults = PRESET_DEFAULTS[preset];

  const toggleChannel = (channel: ChannelId) => {
    const has = settings.channels.includes(channel);
    // At least one search channel must stay on.
    if (has && settings.channels.length === 1) return;
    onChange({
      ...settings,
      channels: has
        ? settings.channels.filter((c) => c !== channel)
        : [...settings.channels, channel],
    });
  };

  return (
    <Modal visible={open} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable className="flex-1 justify-end bg-black/60" onPress={onClose}>
        <Pressable
          onPress={() => {}}
          className="max-h-[88%] rounded-t-md border border-border bg-popover"
          style={{ paddingBottom: insets.bottom + 8 }}
        >
          <View className="flex-row items-center justify-between px-4 pb-2 pt-4">
            <Text className="font-pixel text-xs uppercase tracking-[1.2px] text-muted-foreground">
              Advanced settings
            </Text>
            <Pressable
              testID="advanced-close"
              accessibilityLabel="Close advanced settings"
              onPress={onClose}
              className="px-2 py-1"
            >
              <Text className="font-pixel text-muted-foreground">✕</Text>
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={{ padding: 16, gap: 20 }}>
            <View className="gap-2">
              <Text className="text-xs text-muted-foreground">Preset</Text>
              <View className="flex-row flex-wrap gap-2">
                {PRESET_ORDER.map((id) => {
                  const { available } = presetAvailability(id, caps);
                  return (
                    <Pressable
                      key={id}
                      testID={`advanced-preset-${id}`}
                      accessibilityState={{ disabled: !available, selected: id === preset }}
                      disabled={!available}
                      onPress={() => onPreset(id)}
                      className={`min-h-[36px] justify-center rounded-sm border px-3 ${
                        id === preset ? "border-accent bg-accent/10" : "border-input"
                      } ${available ? "" : "opacity-40"}`}
                    >
                      <Text className="font-pixel text-[11px] uppercase text-zinc-300">
                        {PRESET_DEFAULTS[id].label}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
            </View>

            <View className="gap-2">
              <Text className="text-xs text-muted-foreground">Search channels</Text>
              <View className="flex-row flex-wrap gap-2">
                {ALL_CHANNELS.map((channel) => {
                  const on = settings.channels.includes(channel);
                  return (
                    <Pressable
                      key={channel}
                      testID={`channel-${channel}`}
                      accessibilityState={{ selected: on }}
                      onPress={() => toggleChannel(channel)}
                      className={`min-h-[36px] justify-center rounded-sm border px-3 ${
                        on ? "border-accent bg-accent/10" : "border-input"
                      }`}
                    >
                      <Text className="font-pixel text-[11px] uppercase text-zinc-300">
                        {channel}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
            </View>

            <View className="gap-2">
              <Text className="text-xs text-muted-foreground">Reranker</Text>
              <Chips
                testPrefix="rerank"
                options={RERANKERS}
                value={settings.rerank}
                onChange={(rerank) => onChange({ ...settings, rerank })}
              />
            </View>

            <View className="gap-2">
              <Text className="text-xs text-muted-foreground">Query rewrite</Text>
              <Chips
                testPrefix="transform"
                options={TRANSFORMS}
                value={settings.transform}
                onChange={(transform) => onChange({ ...settings, transform })}
              />
            </View>

            {defaults.agent ? (
              <Stepper
                testPrefix="iterations"
                label="Max steps"
                value={settings.maxIterations}
                min={1}
                max={40}
                onChange={(maxIterations) => onChange({ ...settings, maxIterations })}
              />
            ) : null}
            {defaults.workers ? (
              <Stepper
                testPrefix="workers"
                label="Max workers"
                value={settings.maxWorkers}
                min={1}
                max={8}
                onChange={(maxWorkers) => onChange({ ...settings, maxWorkers })}
              />
            ) : null}

            <Pressable
              testID="advanced-reset"
              accessibilityRole="button"
              onPress={() => onChange(defaultSettings(preset))}
              className="min-h-[44px] items-center justify-center rounded-sm border border-input"
            >
              <Text className="font-pixel text-xs uppercase text-zinc-300">
                Reset to preset
              </Text>
            </Pressable>
          </ScrollView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
