/**
 * BYOK AI credentials editor -- provider, model, and plaintext key.
 *
 * @module AiSettings
 *
 * Port of ``client/src/components/AiSettings.tsx``. The web version renders
 * the provider as a dropdown menu; on a phone a dropdown is a list of radio
 * rows inside a modal, which is the idiom that behaves the same on both
 * platforms and does not need the click-outside handling a DOM menu needs.
 *
 * The key is write-only. It is sent to the backend and wiped from the form
 * as soon as the save lands; the server never sends it back, only whether
 * one is stored.
 */

import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  Text,
  TextInput,
  View,
} from "react-native";

import {
  AI_PROVIDER_PRESETS,
  useAiCredentialsForm,
  type AiProviderPreset,
} from "@/hooks/useAiCredentialsForm";
import type { SettingsRequestOptions } from "@/api/settings";
import { timeAgo } from "@/lib/timeAgo";
import { colors } from "@/theme/tokens";

/**
 * Props for the AiSettings component.
 */
export interface AiSettingsProps {
  /** The provider key already saved on the account, if any. */
  initialProviderKey?: string | null;
  /** The model id already saved on the account, if any. */
  initialModel?: string | null;
  /** Whether a key is already saved on the account. */
  hasKey?: boolean;
  /** When the saved key was last validated, if known. */
  validatedAt?: string | null;
  /** Called after a credential was saved successfully. */
  onSaved?: () => void;
  /** Called after the credential was removed successfully. */
  onRemoved?: () => void;
  /** Transport overrides, so a test can inject a backend and a fetch. */
  options?: SettingsRequestOptions;
}

/**
 * Render the BYOK form: provider, key, model, and the save/remove actions.
 *
 * @param props - The saved credential's shape and the transport overrides.
 * @returns The rendered BYOK form.
 */
export function AiSettings({
  initialProviderKey,
  initialModel,
  hasKey = false,
  validatedAt,
  onSaved,
  onRemoved,
  options,
}: AiSettingsProps) {
  const {
    provider,
    setProvider,
    apiKey,
    setApiKey,
    model,
    setModel,
    errors,
    rootError,
    isSubmitting,
    isRemoving,
    hasKey: keyStored,
    onSubmit,
    handleRemove,
  } = useAiCredentialsForm({
    presets: AI_PROVIDER_PRESETS,
    initialProviderKey,
    initialModel,
    hasKey,
    options,
    onSaved,
    onRemoved,
  });

  const [pickerOpen, setPickerOpen] = useState(false);

  const activePreset = useMemo(
    () => AI_PROVIDER_PRESETS.find((preset) => preset.key === provider),
    [provider],
  );

  /**
   * The hint shown in the empty model field.
   *
   * With a provider picked it is that provider's default model; without one
   * the field says to choose a provider first.
   */
  const modelPlaceholder = useMemo(() => {
    if (model.trim()) return "";
    return activePreset?.defaultModel ?? "Choose a provider first";
  }, [activePreset, model]);

  return (
    <View
      testID="ai-settings"
      className="rounded border border-primary/20 bg-card p-4"
    >
      <View className="mb-3 flex-row items-center justify-between">
        <Text className="text-[11px] font-semibold uppercase tracking-wider text-primary">
          AI Provider
        </Text>
        {keyStored ? (
          <Text
            testID="ai-settings-connected"
            className="text-xs font-medium text-chart-1"
          >
            Connected
          </Text>
        ) : null}
      </View>

      <Text className="mb-4 text-[13px] text-muted-foreground">
        Power the glossary, reading order, architecture brief, and chat answers
        with your own provider. Embeddings stay on the server to keep the search
        index consistent.
      </Text>

      <Text className="mb-1 text-[13px] font-medium text-foreground">
        Provider
      </Text>
      <Pressable
        testID="ai-settings-provider"
        accessibilityRole="button"
        accessibilityLabel="Choose an AI provider"
        accessibilityState={{ expanded: pickerOpen }}
        onPress={() => setPickerOpen(true)}
        className="min-h-[44px] flex-row items-center justify-between rounded border border-border bg-secondary/20 px-3 active:bg-secondary"
      >
        <Text className="text-sm text-foreground">
          {activePreset?.label ?? "Select a provider"}
        </Text>
        <Text className="text-xs text-muted-foreground">▾</Text>
      </Pressable>
      {errors.provider ? (
        <Text
          testID="ai-settings-provider-error"
          className="mt-1 text-xs text-destructive"
        >
          {errors.provider}
        </Text>
      ) : null}

      <Text className="mb-1 mt-4 text-[13px] font-medium text-foreground">
        API Key
      </Text>
      <TextInput
        testID="ai-settings-api-key"
        accessibilityLabel="API key"
        value={apiKey}
        onChangeText={setApiKey}
        secureTextEntry
        autoCapitalize="none"
        autoCorrect={false}
        placeholder={
          keyStored
            ? "Enter a new key to replace the saved one"
            : "Paste your provider key"
        }
        placeholderTextColor={colors.mutedForeground}
        className="min-h-[44px] rounded border border-border bg-secondary/20 px-3 py-2 text-sm text-foreground"
      />
      {errors.apiKey ? (
        <Text
          testID="ai-settings-api-key-error"
          className="mt-1 text-xs text-destructive"
        >
          {errors.apiKey}
        </Text>
      ) : null}

      <Text className="mb-1 mt-4 text-[13px] font-medium text-foreground">
        Model
      </Text>
      <TextInput
        testID="ai-settings-model"
        accessibilityLabel="Model"
        value={model}
        onChangeText={setModel}
        autoCapitalize="none"
        autoCorrect={false}
        placeholder={modelPlaceholder}
        placeholderTextColor={colors.mutedForeground}
        className="min-h-[44px] rounded border border-border bg-secondary/20 px-3 py-2 text-sm text-foreground"
      />
      {errors.model ? (
        <Text
          testID="ai-settings-model-error"
          className="mt-1 text-xs text-destructive"
        >
          {errors.model}
        </Text>
      ) : null}

      {rootError ? (
        <View
          testID="ai-settings-error"
          className="mx-0 mb-3 mt-4 rounded border border-destructive/30 bg-destructive/10 p-3"
        >
          <Text className="text-xs text-destructive">{rootError}</Text>
        </View>
      ) : null}

      {validatedAt ? (
        <Text className="mb-3 mt-3 text-[11px] text-muted-foreground">
          Last validated {timeAgo(validatedAt)}
        </Text>
      ) : null}

      <View className="mt-2 flex-row items-center justify-end gap-2">
        {keyStored ? (
          <Pressable
            testID="ai-settings-remove"
            accessibilityRole="button"
            accessibilityLabel="Remove key"
            accessibilityState={{ disabled: isSubmitting || isRemoving }}
            disabled={isSubmitting || isRemoving}
            onPress={() => {
              void handleRemove();
            }}
            className="min-h-[44px] items-center justify-center rounded border border-destructive px-3 active:bg-secondary"
          >
            {isRemoving ? (
              <ActivityIndicator size="small" color={colors.destructive} />
            ) : (
              <Text className="text-[13px] font-semibold text-destructive">
                Remove key
              </Text>
            )}
          </Pressable>
        ) : null}

        <Pressable
          testID="ai-settings-save"
          accessibilityRole="button"
          accessibilityLabel={keyStored ? "Replace key" : "Save key"}
          accessibilityState={{ disabled: isSubmitting || isRemoving }}
          disabled={isSubmitting || isRemoving}
          onPress={() => {
            void onSubmit();
          }}
          className="min-h-[44px] items-center justify-center rounded bg-primary px-4 active:opacity-80"
        >
          {isSubmitting ? (
            <ActivityIndicator size="small" color={colors.primaryForeground} />
          ) : (
            <Text className="text-[13px] font-semibold text-primary-foreground">
              {keyStored ? "Replace key" : "Save key"}
            </Text>
          )}
        </Pressable>
      </View>

      <ProviderPicker
        open={pickerOpen}
        selectedKey={provider}
        presets={AI_PROVIDER_PRESETS}
        onClose={() => setPickerOpen(false)}
        onSelect={(key) => {
          setProvider(key);
          setPickerOpen(false);
        }}
      />
    </View>
  );
}

/**
 * Props for the provider picker modal.
 */
interface ProviderPickerProps {
  /** Whether the modal is on screen. */
  open: boolean;
  /** The provider key currently chosen. */
  selectedKey: string;
  /** The presets to list. */
  presets: AiProviderPreset[];
  /** Called when the modal is dismissed. */
  onClose: () => void;
  /** Called with the chosen provider key. */
  onSelect: (key: string) => void;
}

/**
 * The provider chooser.
 *
 * A list of radio rows rather than a dropdown: a menu that opens over the
 * content is awkward to dismiss with a thumb, and the list of providers is
 * short enough that a sheet of rows is the faster path.
 *
 * @param props - The modal's state and its two callbacks.
 * @returns The rendered modal.
 */
function ProviderPicker({
  open,
  selectedKey,
  presets,
  onClose,
  onSelect,
}: ProviderPickerProps) {
  return (
    <Modal
      visible={open}
      transparent
      animationType="fade"
      onRequestClose={onClose}
    >
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Close provider picker"
        onPress={onClose}
        className="flex-1 justify-end bg-black/60"
      >
        <Pressable
          accessibilityRole="none"
          onPress={() => {}}
          className="rounded-t-2xl border-t border-border bg-card p-4"
        >
          <Text className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            AI Provider
          </Text>

          {presets.map((preset) => {
            const selected = preset.key === selectedKey;
            return (
              <Pressable
                key={preset.key}
                testID={`ai-settings-provider-option-${preset.key}`}
                accessibilityRole="radio"
                accessibilityLabel={preset.label}
                accessibilityState={{ selected }}
                onPress={() => onSelect(preset.key)}
                className="min-h-[44px] flex-row items-center justify-between border-b border-border/60 active:bg-secondary"
              >
                <View className="flex-1 pr-3">
                  <Text className="text-sm font-medium text-foreground">
                    {preset.label}
                  </Text>
                  <Text className="mt-0.5 text-[11px] text-muted-foreground">
                    {preset.defaultModel}
                  </Text>
                </View>
                <Text
                  className={`text-sm ${
                    selected ? "text-primary" : "text-muted-foreground"
                  }`}
                >
                  {selected ? "●" : "○"}
                </Text>
              </Pressable>
            );
          })}

          <Pressable
            testID="ai-settings-provider-close"
            accessibilityRole="button"
            accessibilityLabel="Close provider picker"
            onPress={onClose}
            className="mt-3 min-h-[44px] items-center justify-center rounded border border-border active:bg-secondary"
          >
            <Text className="text-[13px] font-medium text-foreground">
              Cancel
            </Text>
          </Pressable>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

export default AiSettings;
