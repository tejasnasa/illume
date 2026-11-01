/**
 * AI credentials screen.
 *
 * @module AiCredentialsScreen
 *
 * Port of the web client's settings page
 * (``client/src/app/settings/page.tsx``), which renders the
 * :component:`AiSettings` card. On a phone the card is its own screen so
 * the form is not buried under a list of unrelated settings.
 *
 * The screen reads the saved credential from
 * ``GET /api/v1/auth/me/ai-credentials``, which answers with the provider,
 * the model and whether a key is stored -- never the key itself. The form
 * is not rendered until that read lands, so the provider and model fields
 * are seeded once and never rewritten under the reader's hands.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  Text,
  View,
} from "react-native";
import { router } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { AiSettings } from "@/components/AiSettings";
import { getAiCredentials, type AiCredentials } from "@/api/settings";
import { useAuth } from "@/hooks/useAuth";
import { colors } from "@/theme/tokens";

/**
 * Draw the AI credentials screen.
 *
 * @returns The rendered screen.
 */
export default function AiCredentialsScreen() {
  const insets = useSafeAreaInsets();
  const { refreshUser } = useAuth();

  const [credentials, setCredentials] = useState<AiCredentials | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  /**
   * Read the saved credential.
   *
   * The request is re-issued after a save or a removal, so the screen
   * always shows what the server holds.
   */
  const load = useCallback(async () => {
    try {
      const next = await getAiCredentials();
      setCredentials(next);
      setLoadError(null);
    } catch (cause) {
      setLoadError(
        cause instanceof Error && cause.message
          ? cause.message
          : "Failed to load AI credentials",
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /**
   * Re-read the credential and the profile after a change.
   */
  const handleChanged = useCallback(() => {
    void load();
    // The profile carries the ``has_ai_key`` flag the rest of the app
    // reads -- the free-tier banner and the chat quota both look at it.
    void refreshUser();
  }, [load, refreshUser]);

  return (
    <View className="flex-1 bg-background" style={{ paddingTop: insets.top }}>
      <View className="flex-row items-center border-b border-border px-3 py-2">
        <Pressable
          testID="settings-ai-back"
          accessibilityRole="button"
          accessibilityLabel="Back to settings"
          onPress={() => router.back()}
          hitSlop={8}
          className="mr-2 rounded px-2 py-1 active:bg-secondary"
        >
          <Text className="text-lg text-foreground">←</Text>
        </Pressable>
        <Text className="flex-1 text-base font-medium text-foreground">
          AI credentials
        </Text>
      </View>

      <ScrollView
        testID="settings-ai-scroll"
        automaticallyAdjustKeyboardInsets
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{
          padding: 16,
          paddingBottom: insets.bottom + 32,
        }}
      >
        {loadError ? (
          <View className="mx-0 mb-3 rounded border border-destructive/30 bg-destructive/10 p-3">
            <Text className="text-xs text-destructive">{loadError}</Text>
          </View>
        ) : null}

        {credentials ? (
          <AiSettings
            initialProviderKey={credentials.provider}
            initialModel={credentials.model}
            hasKey={credentials.has_key}
            validatedAt={credentials.validated_at}
            onSaved={handleChanged}
            onRemoved={handleChanged}
          />
        ) : loadError ? null : (
          <View className="items-center justify-center py-10">
            <ActivityIndicator size="large" color={colors.foreground} />
          </View>
        )}
      </ScrollView>
    </View>
  );
}
