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
  Text,
  View,
} from "react-native";
import * as WebBrowser from "expo-web-browser";

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
    <SafeAreaView className="flex-1 bg-background">
      <View className="flex-1 items-center justify-center px-6 py-4">
        <View className="w-full max-w-[380px] items-center rounded-xl border border-border bg-card px-7 py-8">
          <Text
            accessibilityRole="header"
            className="text-center text-base font-bold uppercase tracking-[2px] text-foreground"
          >
            Illume
          </Text>
          <Text className="mb-2 text-center text-[44px] leading-[52px] text-chart-1">
            ✦
          </Text>

          <Text className="mt-2 text-center text-[22px] font-bold text-foreground">
            Welcome to Illume
          </Text>
          <Text className="mt-1 text-center text-sm text-muted-foreground">
            Sign in to analyze your codebase
          </Text>

          <View className="my-5 h-px w-full bg-border" />

          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Continue with GitHub"
            accessibilityState={{ disabled, busy }}
            onPress={onContinueWithGitHub}
            disabled={disabled}
            hitSlop={8}
            className={`min-h-[48px] w-full items-center justify-center rounded-lg bg-white px-4 py-3.5 ${
              disabled ? "opacity-60" : ""
            }`}
          >
            {busy ? (
              <ActivityIndicator size="small" color="#000000" />
            ) : (
              <Text
                className="text-[15px] font-semibold text-black"
                style={buttonTextStyle}
              >
                Continue with GitHub
              </Text>
            )}
          </Pressable>

          {error ? (
            <Text
              accessibilityRole="alert"
              className="mt-3 text-center text-[13px] text-destructive"
            >
              {error}
            </Text>
          ) : null}
        </View>
      </View>
    </SafeAreaView>
  );
}

// ``includeFontPadding`` / ``textAlignVertical`` are Android-only native
// props that NativeWind does not surface; the GitHub button text is
// vertically centered through them so the line height matches the
// button's min-height.
const buttonTextStyle = {
  includeFontPadding: false,
  textAlignVertical: "center" as const,
};
