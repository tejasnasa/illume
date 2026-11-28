/**
 * Agent settings: the context window agent runs work within.
 *
 * @module AgentSettingsScreen
 *
 * Port of ``client/src/components/AgentSettings.tsx``. The server serves its
 * own default and bounds, so the form never carries a second copy that can
 * drift; the constants in ``lib/accountSettings`` are the fallback while the
 * request is in flight.
 */

import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { getAgentSettings, saveAgentSettings, type AgentSettings } from "@/api/account";
import { useAuth } from "@/hooks/useAuth";
import {
  CONTEXT_PRESETS,
  MAX_CONTEXT_WINDOW,
  MIN_CONTEXT_WINDOW,
  parseContextWindow,
} from "@/lib/accountSettings";
import { colors } from "@/theme/tokens";
import { Button } from "@/ui/Button";
import { Eyebrow, Panel } from "@/ui/Panel";
import { SettingsHeader } from "@/ui/SettingsHeader";

/**
 * Draw the screen.
 *
 * @returns The agent settings screen.
 */
export default function AgentSettingsScreen() {
  const { refreshUser } = useAuth();
  const [settings, setSettings] = useState<AgentSettings | null>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void getAgentSettings()
      .then((next) => {
        if (cancelled) return;
        setSettings(next);
        setValue(next.context_window == null ? "" : String(next.context_window));
      })
      .catch(() => {
        if (!cancelled) setError("Agent settings could not be loaded.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const min = settings?.context_window_min ?? MIN_CONTEXT_WINDOW;
  const max = settings?.context_window_max ?? MAX_CONTEXT_WINDOW;
  const fallback = settings?.context_window_default ?? 250_000;

  const save = useCallback(async () => {
    const parsed = parseContextWindow(value, min, max);
    if (!parsed.ok) {
      setError(parsed.message);
      return;
    }
    setPending(true);
    setError(null);
    try {
      const next = await saveAgentSettings(parsed.value);
      setSettings(next);
      setSaved(true);
      await refreshUser();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to save agent settings.");
    } finally {
      setPending(false);
    }
  }, [value, min, max, refreshUser]);

  return (
    <View className="flex-1" testID="agent-settings-screen">
      <SettingsHeader title="Agent" />
      <ScrollView contentContainerStyle={{ padding: 16, gap: 16 }} keyboardShouldPersistTaps="handled">
        {!settings && !error ? <ActivityIndicator color={colors.mutedForeground} /> : null}
        <Panel className="gap-3 p-4">
          <Eyebrow>Context window · tokens</Eyebrow>
          <TextInput
            testID="context-window-input"
            accessibilityLabel="Context window in tokens"
            value={value}
            onChangeText={(text) => {
              setValue(text);
              setSaved(false);
              setError(null);
            }}
            keyboardType="number-pad"
            placeholder={`Default · ${fallback.toLocaleString("en-US")}`}
            placeholderTextColor={colors.mutedForeground}
            className="min-h-[44px] rounded-sm border border-input bg-background px-3 text-sm text-foreground"
          />
          <View className="flex-row flex-wrap gap-2">
            {CONTEXT_PRESETS.map((preset) => (
              <Pressable
                key={preset.label}
                testID={`context-preset-${preset.label}`}
                accessibilityRole="button"
                onPress={() => {
                  setValue(String(preset.tokens));
                  setSaved(false);
                  setError(null);
                }}
                className="min-h-[36px] justify-center rounded-sm border border-input px-3"
              >
                <Text className="font-pixel text-[11px] text-zinc-300">{preset.label}</Text>
              </Pressable>
            ))}
          </View>
          <Text className="text-xs leading-[18px] text-muted-foreground">
            Set this to your model&apos;s context window or lower. When an
            investigation fills it, the agent condenses its notes and carries
            on. Leave it blank for the default.
          </Text>
          {error ? (
            <Text testID="agent-settings-error" className="text-xs text-destructive">
              {error}
            </Text>
          ) : null}
          {saved ? (
            <Text testID="agent-settings-saved" className="font-pixel text-xs uppercase text-success">
              Saved
            </Text>
          ) : null}
          <Button testID="agent-settings-save" loading={pending} onPress={() => void save()}>
            Save
          </Button>
        </Panel>
      </ScrollView>
    </View>
  );
}
