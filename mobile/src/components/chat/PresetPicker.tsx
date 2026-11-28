/**
 * The preset picker: a button showing the current choice, and a sheet that
 * lists every preset with what it does.
 *
 * @module PresetPicker
 *
 * Port of ``client/src/components/chat/PresetPicker.tsx``. A phone has no
 * hover, so the reason a preset is unavailable is printed under its name
 * rather than shown as a tooltip. The two deep agent presets are the
 * "super agent": one agent that searches and reads the code, and one that
 * splits a broad question across parallel workers. On the free tier they,
 * and Auto, are disabled.
 */

import { useState } from "react";
import { Modal, Pressable, ScrollView, Text } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import {
  AUTO_BLURB,
  AUTO_MENU_LABEL,
  PICKER_PRESETS,
  PRESET_DEFAULTS,
  choiceLabel,
  presetAvailability,
  type Capabilities,
  type PresetChoice,
} from "@/lib/agent/presets";

/** The label and blurb a menu row shows for a choice. */
export function menuEntry(choice: PresetChoice): { label: string; blurb: string } {
  if (choice === "auto") return { label: AUTO_MENU_LABEL, blurb: AUTO_BLURB };
  const preset = PRESET_DEFAULTS[choice];
  return { label: preset.label, blurb: preset.blurb };
}

/**
 * Renders the picker.
 *
 * @param props - The current choice, whether it was customised, the account
 *   capabilities and the change handler.
 * @returns The button and its sheet.
 */
export function PresetPicker({
  value,
  custom,
  caps,
  disabled = false,
  onChange,
  onOpenAdvanced,
}: {
  value: PresetChoice;
  custom: boolean;
  caps: Capabilities;
  disabled?: boolean;
  onChange: (choice: PresetChoice) => void;
  /** Opens the advanced settings, when the screen offers them. */
  onOpenAdvanced?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const insets = useSafeAreaInsets();

  return (
    <>
      <Pressable
        testID="preset-picker"
        accessibilityRole="button"
        accessibilityLabel={`Answer mode: ${choiceLabel(value, custom)}`}
        disabled={disabled}
        onPress={() => setOpen(true)}
        className={`h-9 flex-row items-center gap-1.5 rounded-sm border border-input px-3 ${disabled ? "opacity-50" : ""}`}
      >
        <Text className="font-pixel text-[11px] uppercase tracking-[0.7px] text-zinc-300">
          {choiceLabel(value, custom)}
        </Text>
        <Text className="font-pixel text-[10px] text-muted-foreground">▾</Text>
      </Pressable>

      <Modal
        visible={open}
        transparent
        animationType="slide"
        onRequestClose={() => setOpen(false)}
      >
        <Pressable
          testID="preset-backdrop"
          className="flex-1 justify-end bg-black/60"
          onPress={() => setOpen(false)}
        >
          <Pressable
            onPress={() => {}}
            className="max-h-[80%] rounded-t-md border border-border bg-popover"
            style={{ paddingBottom: insets.bottom + 8 }}
          >
            <Text className="px-4 pb-2 pt-4 font-pixel text-xs uppercase tracking-[1.2px] text-muted-foreground">
              Answer mode
            </Text>
            <ScrollView>
              {PICKER_PRESETS.map((choice) => {
                const { available, reason } = presetAvailability(choice, caps);
                const entry = menuEntry(choice);
                const selected = choice === value;
                return (
                  <Pressable
                    key={choice}
                    testID={`preset-${choice}`}
                    accessibilityRole="button"
                    accessibilityState={{ disabled: !available, selected }}
                    disabled={!available}
                    onPress={() => {
                      onChange(choice);
                      setOpen(false);
                    }}
                    className={`min-h-[56px] justify-center px-4 py-2.5 active:bg-white/5 ${
                      selected ? "border-l-2 border-accent bg-white/5" : ""
                    } ${available ? "" : "opacity-50"}`}
                  >
                    <Text className="text-[14px] text-foreground">
                      {entry.label}
                    </Text>
                    <Text className="text-xs text-muted-foreground">
                      {entry.blurb}
                    </Text>
                    {!available && reason ? (
                      <Text
                        testID={`preset-reason-${choice}`}
                        className="mt-1 text-xs text-warning"
                      >
                        {reason}
                      </Text>
                    ) : null}
                  </Pressable>
                );
              })}
            </ScrollView>
            {onOpenAdvanced ? (
              <Pressable
                accessibilityRole="button"
                onPress={() => {
                  setOpen(false);
                  onOpenAdvanced();
                }}
                className="min-h-[48px] justify-center border-t border-border px-4"
              >
                <Text className="font-pixel text-xs uppercase text-accent">
                  Advanced settings
                </Text>
              </Pressable>
            ) : null}
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}
