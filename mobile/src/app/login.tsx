/**
 * Single-action login screen.
 *
 * Mirrors the web ``LoginForm`` shape -- centred title, one GitHub button,
 * no email/password option (the mobile build does not use the API's
 * register/login endpoints).
 *
 * Tapping the button hands off to :func:`openAuthSession`, which builds the
 * authorize URL with the deep link as ``state`` and lets the OS-managed
 * browser carry the rest of the OAuth dance. The deep-link URL is
 * ``illume://auth/callback`` -- the backend looks that up against its
 * ``OAUTH_REDIRECT_ALLOWLIST``.
 */

import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  SafeAreaView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import * as WebBrowser from "expo-web-browser";

import { colors } from "@/theme/tokens";
import { buildAuthorizeUrl } from "@/lib/authCallback";

const BACKEND_URL =
  process.env.EXPO_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const DEEP_LINK = "illume://auth/callback";

export default function LoginScreen() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Hand the user off to the system browser for the OAuth dance.
   *
   * ``openAuthSessionAsync`` with the deep-link as the second argument
   * tells the OS to send the final browser redirect back to the app rather
   * than back to the WebBrowser context, which would otherwise get stuck.
   */
  const onContinueWithGitHub = useCallback(async () => {
    setError(null);
    setBusy(true);
    try {
      const url = buildAuthorizeUrl(BACKEND_URL, DEEP_LINK);
      await WebBrowser.openAuthSessionAsync(url, DEEP_LINK);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to open browser");
    } finally {
      // Whether the user cancelled or completed, the auth callback screen
      // takes over the navigation; we clear ``busy`` here for safety in
      // case the in-app screen does not get a chance to mount.
      setBusy(false);
    }
  }, []);

  const disabled = busy;

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.container}>
        <View style={styles.card}>
          <Text style={styles.brand} accessibilityRole="header">
            Illume
          </Text>
          <Text style={styles.brandGlyph}>✦</Text>

          <Text style={styles.title}>Welcome to Illume</Text>
          <Text style={styles.subtitle}>Sign in to analyze your codebase</Text>

          <View style={styles.divider} />

          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Continue with GitHub"
            accessibilityState={{ disabled, busy }}
            onPress={onContinueWithGitHub}
            disabled={disabled}
            hitSlop={8}
            style={[styles.button, disabled && styles.buttonDisabled]}
          >
            {busy ? (
              <ActivityIndicator size="small" color="#000000" />
            ) : (
              <Text style={styles.buttonText}>Continue with GitHub</Text>
            )}
          </Pressable>

          {error ? (
            <Text style={styles.error} accessibilityRole="alert">
              {error}
            </Text>
          ) : null}
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.background,
  },
  container: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
    paddingVertical: 16,
  },
  card: {
    width: "100%",
    maxWidth: 380,
    paddingVertical: 32,
    paddingHorizontal: 28,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    backgroundColor: colors.card,
    alignItems: "center",
  },
  brand: {
    color: colors.foreground,
    fontSize: 16,
    fontWeight: "700",
    letterSpacing: 2,
    textTransform: "uppercase",
    textAlign: "center",
  },
  brandGlyph: {
    color: colors.chart1,
    fontSize: 44,
    lineHeight: 52,
    marginBottom: 8,
    textAlign: "center",
  },
  title: {
    color: colors.foreground,
    fontSize: 22,
    fontWeight: "700",
    textAlign: "center",
    marginTop: 8,
  },
  subtitle: {
    color: colors.mutedForeground,
    fontSize: 14,
    textAlign: "center",
    marginTop: 4,
  },
  divider: {
    width: "100%",
    height: StyleSheet.hairlineWidth,
    backgroundColor: colors.border,
    marginVertical: 20,
  },
  button: {
    width: "100%",
    backgroundColor: "#ffffff",
    paddingVertical: 14,
    paddingHorizontal: 16,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 48,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    color: "#000000",
    fontSize: 15,
    fontWeight: "600",
    includeFontPadding: false,
    textAlignVertical: "center",
  },
  error: {
    color: colors.destructive,
    fontSize: 13,
    marginTop: 12,
    textAlign: "center",
  },
});
