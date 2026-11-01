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
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { router } from "expo-router";
import * as WebBrowser from "expo-web-browser";

import { resolveBackendUrl } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";
import { buildAuthorizeUrl, parseAuthCallback } from "@/lib/authCallback";

const DEEP_LINK = "illume://auth/callback";

export default function LoginScreen() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { signIn } = useAuth();
  const insets = useSafeAreaInsets();

  /**
   * Hand the user off to the system browser for the OAuth dance.
   *
   * ``openAuthSessionAsync`` with the deep-link as the second argument
   * tells the OS to send the final browser redirect back to the app rather
   * than back to the WebBrowser context, which would otherwise get stuck.
   *
   * The returned URL is handled here as well as by the deep-link route,
   * because the two platforms differ: Android delivers the redirect as a
   * ``Linking`` event (which mounts ``/auth/callback``), while iOS uses
   * ``ASWebAuthenticationSession``, which hands the URL back to this
   * promise and emits no event at all. Relying on the deep link alone makes
   * sign-in impossible on iOS -- the browser closes and the login screen
   * sits there.
   */
  const onContinueWithGitHub = useCallback(async () => {
    setError(null);
    setBusy(true);
    try {
      const url = buildAuthorizeUrl(resolveBackendUrl(), DEEP_LINK);
      const result = await WebBrowser.openAuthSessionAsync(url, DEEP_LINK);

      if (result.type !== "success" || !result.url) return;

      const payload = parseAuthCallback(result.url);
      if (!payload.token) {
        setError(
          payload.error ?? "GitHub did not return a sign-in token. Try again.",
        );
        return;
      }

      const accepted = await signIn(payload.token);
      if (accepted) {
        router.replace("/(app)/dashboard");
      } else {
        setError("That sign-in could not be verified. Please try again.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to open browser");
    } finally {
      // Whether the user cancelled or completed, the auth callback screen
      // takes over the navigation; we clear ``busy`` here for safety in
      // case the in-app screen does not get a chance to mount.
      setBusy(false);
    }
  }, [signIn]);

  const disabled = busy;

  return (
    // A plain ``View`` padded by the inset: the safe-area component is a
    // native view that ``className`` does not reach, so its ``flex-1`` was
    // ignored and the centred card below collapsed to no height.
    <View
      className="flex-1 bg-background"
      style={{ paddingTop: insets.top, paddingBottom: insets.bottom }}
    >
      {/*
        The introduction is reachable again from here: once it has been
        seen, the flag stops the cold start from showing it, so a reader who
        signs out and wants to read it once more has no other way back in.
      */}
      <View className="flex-row justify-end px-4 pt-2">
        <Pressable
          testID="login-help"
          accessibilityRole="button"
          accessibilityLabel="Show the introduction"
          onPress={() => router.push("/onboarding")}
          hitSlop={8}
          className="min-h-[44px] min-w-[44px] items-center justify-center rounded-full border border-border active:bg-secondary"
        >
          <Text className="text-base font-semibold text-muted-foreground">
            ?
          </Text>
        </Pressable>
      </View>

      <View className="flex-1 items-center justify-center px-6 py-4">
        <View className="w-full max-w-[380px] items-center rounded-xl border border-border bg-card px-7 py-8">
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
    </View>
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
