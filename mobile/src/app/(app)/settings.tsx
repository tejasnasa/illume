/**
 * Settings hub -- the grouped list every configurable thing hangs off.
 *
 * @module SettingsScreen
 *
 * The web client spreads its settings across a page, a repository panel and
 * a footer. A phone has one narrow column, so the settings tree becomes a
 * list of rows that push to sub-screens:
 *
 * - **AI** -- the BYOK credentials editor.
 * - **Support** -- the contact form, and the links out.
 * - **Account** -- signing out.
 *
 * Everything repository-scoped -- auto-update, export, re-ingest, delete --
 * lives on that repository's own settings screen, reached from the gear in
 * its header. This list deliberately holds only things that belong to the
 * account.
 */

import { useCallback, useMemo, useState } from "react";
import { Linking, Modal, Pressable, ScrollView, Text, View } from "react-native";
import { router } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Constants from "expo-constants";

import { useAuth } from "@/hooks/useAuth";
import { AI_PROVIDER_PRESETS } from "@/hooks/useAiCredentialsForm";

/**
 * The external links the About sheet offers.
 *
 * The same set the web client's footer carries.
 */
const EXTERNAL_LINKS = [
  { href: "https://github.com/tejasnasa", label: "GitHub" },
  { href: "https://www.linkedin.com/in/tejasnasa/", label: "LinkedIn" },
  { href: "https://x.com/tejasnasa/", label: "X" },
];

/**
 * Props for a settings row.
 */
interface SettingsRowProps {
  /** The row's title. */
  title: string;
  /** The secondary line under the title. */
  subtitle?: string;
  /** The value shown on the trailing edge. */
  value?: string;
  /** The row's test id. */
  testID: string;
  /** Called when the row is pressed. */
  onPress: () => void;
}

/**
 * One row of the settings list.
 *
 * @param props - The row's content and its press handler.
 * @returns The rendered row.
 */
function SettingsRow({
  title,
  subtitle,
  value,
  testID,
  onPress,
}: SettingsRowProps) {
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={title}
      onPress={onPress}
      className="min-h-[44px] flex-row items-center justify-between border-b border-border/60 px-4 py-3 active:bg-secondary"
    >
      <View className="min-w-0 flex-1 pr-3">
        <Text className="text-sm font-medium text-foreground">{title}</Text>
        {subtitle ? (
          <Text className="mt-0.5 text-xs text-muted-foreground">
            {subtitle}
          </Text>
        ) : null}
      </View>
      {value ? (
        <Text className="mr-2 text-xs text-muted-foreground">{value}</Text>
      ) : null}
      <Text className="text-sm text-muted-foreground">›</Text>
    </Pressable>
  );
}

/**
 * Draw the settings list.
 *
 * @returns The rendered screen.
 */
export default function SettingsScreen() {
  const insets = useSafeAreaInsets();
  const { signOut, user } = useAuth();
  const [aboutOpen, setAboutOpen] = useState(false);

  const providerLabel = useMemo(() => {
    const key = user?.ai_provider;
    if (!key) return undefined;
    // The preset table carries the label the provider is written with, so
    // "openai" reads as "OpenAI" rather than "Openai".
    return (
      AI_PROVIDER_PRESETS.find((preset) => preset.key === key)?.label ?? key
    );
  }, [user?.ai_provider]);

  const goBack = useCallback(() => {
    router.back();
  }, []);

  const handleSignOut = useCallback(async () => {
    await signOut();
    // The guard in ``(app)/_layout.tsx`` rerenders on the token change and
    // redirects to /login; the explicit replace makes the destination
    // immediate rather than dependent on that rerender.
    router.replace("/login");
  }, [signOut]);

  /**
   * Open a link outside the app.
   *
   * @param href - The URL to open.
   */
  const openLink = useCallback((href: string) => {
    void Linking.openURL(href).catch(() => {
      // No handler for the URL, or the platform refused it. There is
      // nothing useful to say about it, so it is swallowed.
    });
  }, []);

  return (
    <View className="flex-1 bg-background" style={{ paddingTop: insets.top }}>
      <View className="flex-row items-center border-b border-border px-3 py-2">
        <Pressable
          testID="settings-back"
          accessibilityRole="button"
          accessibilityLabel="Back"
          onPress={goBack}
          hitSlop={8}
          className="mr-2 rounded px-2 py-1 active:bg-secondary"
        >
          <Text className="text-lg text-foreground">←</Text>
        </Pressable>
        <Text className="flex-1 text-base font-medium text-foreground">
          Settings
        </Text>
      </View>

      <ScrollView
        testID="settings-list"
        contentContainerStyle={{ paddingBottom: insets.bottom + 32 }}
      >
        <Text className="px-4 pb-2 pt-5 text-[11px] font-bold uppercase tracking-[2px] text-muted-foreground opacity-60">
          AI
        </Text>
        <View className="rounded border border-border bg-card">
          <SettingsRow
            testID="settings-row-ai"
            title="AI credentials"
            subtitle="Use your own provider for the glossary and chat"
            value={providerLabel ?? "Not set"}
            onPress={() => router.push("/(app)/settings/ai")}
          />
        </View>

        <Text className="px-4 pb-2 pt-5 text-[11px] font-bold uppercase tracking-[2px] text-muted-foreground opacity-60">
          Support
        </Text>
        <View className="rounded border border-border bg-card">
          <SettingsRow
            testID="settings-row-contact"
            title="Contact"
            subtitle="Report a bug or send a question"
            onPress={() => router.push("/(app)/settings/contact")}
          />
          <SettingsRow
            testID="settings-row-about"
            title="About Illume"
            subtitle="Version and links"
            onPress={() => setAboutOpen(true)}
          />
        </View>

        <Text className="px-4 pb-2 pt-5 text-[11px] font-bold uppercase tracking-[2px] text-muted-foreground opacity-60">
          Account
        </Text>
        <View className="rounded border border-border bg-card">
          <Pressable
            testID="settings-row-logout"
            accessibilityRole="button"
            accessibilityLabel="Log out"
            onPress={() => {
              void handleSignOut();
            }}
            className="min-h-[44px] items-center justify-center border-b border-border/60 px-4 py-3 active:bg-secondary"
          >
            <Text className="text-sm font-semibold text-destructive">
              Log out
            </Text>
          </Pressable>
        </View>
      </ScrollView>

      <Modal
        visible={aboutOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setAboutOpen(false)}
      >
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Close about sheet"
          onPress={() => setAboutOpen(false)}
          className="flex-1 items-center justify-center bg-black/60 px-6"
        >
          <Pressable
            accessibilityRole="none"
            onPress={() => {}}
            className="w-full rounded-2xl border border-border bg-card p-5"
          >
            <Text className="text-lg font-bold text-foreground">Illume</Text>
            <Text className="mt-1 text-xs text-muted-foreground">
              Version {Constants.expoConfig?.version ?? "1.0.0"} · Built by
              Tejas Nasa
            </Text>

            <Text className="mb-2 mt-5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Links
            </Text>
            {EXTERNAL_LINKS.map((link) => (
              <Pressable
                key={link.href}
                testID={`settings-about-link-${link.label.toLowerCase()}`}
                accessibilityRole="link"
                accessibilityLabel={link.label}
                onPress={() => openLink(link.href)}
                className="min-h-[44px] flex-row items-center justify-between border-b border-border/60 active:bg-secondary"
              >
                <Text className="text-sm text-foreground">{link.label}</Text>
                <Text className="text-sm text-muted-foreground">›</Text>
              </Pressable>
            ))}

            <Pressable
              testID="settings-about-close"
              accessibilityRole="button"
              accessibilityLabel="Close about sheet"
              onPress={() => setAboutOpen(false)}
              className="mt-4 min-h-[44px] items-center justify-center rounded border border-border active:bg-secondary"
            >
              <Text className="text-[13px] font-medium text-foreground">
                Close
              </Text>
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}
