/**
 * Root layout for the Expo router.
 *
 * Wires the providers every screen reads from:
 *
 * - :class:`QueryClientProvider` -- TanStack Query for every data fetch.
 *   The :func:`installAppStateFocusBridge` call below is the one piece of
 *   mobile glue React Query does not set up itself.
 * - :class:`AuthProvider` -- token state, cold-start validation, sign-in
 *   and sign-out. Lives in ``hooks/useAuth`` so screens can read it
 *   without pulling in the route tree.
 *
 * The :func:`createQueryClient` factory builds the client lazily so
 * default options can be tuned without re-importing the module, and so
 * tests can override :class:`QueryClient` entirely.
 *
 * NativeWind handles visual styling for the children; the Stack's
 * ``contentStyle`` background has to stay native because the Navigator
 * reads a ``ViewStyle``, not a className.
 *
 * ``global.css`` is imported here so NativeWind's Metro hook registers
 * the class registry at app start. Without this import, ``className``
 * strings never resolve to styles and the elements render with React
 * Native's defaults (dark text on iOS, light text on Android), which
 * makes dark-themed screens invisible.
 */

import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import "../../global.css";

import { installAppStateFocusBridge } from "@/api/focusManager";
import { registerQueryClient } from "@/lib/queryClientRegistry";
import { colors } from "@/theme/tokens";
import { AuthProvider } from "@/hooks/useAuth";
import {
  useNotificationNavigation,
  usePushNotifications,
} from "@/hooks/usePushNotifications";

/**
 * Default :class:`QueryClient` options.
 *
 * - ``retry: 1`` -- a single retry covers the flaky-network case (the
 *   tunnel drops once and the second attempt lands), but does not pile
 *   up on a hard 401.
 * - ``refetchOnWindowFocus`` is the web name; on mobile the equivalent
 *   is "refetch on app foreground", which is what :func:`focusManager`
 *   drives. We leave the default (``true``) and let the bridge below
 *   trigger it.
 * - ``staleTime: 30s`` -- most repository data only changes on an
 *   ingest, and the user sees the progress view while one is in
 *   flight; a 30-second stale window keeps the cache useful across
 *   navigation without forcing a refetch on every screen mount.
 */
function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        staleTime: 30_000,
      },
    },
  });
}

const queryClient = createQueryClient();
installAppStateFocusBridge();
// The auth provider clears the cache on sign-out, and it must keep working
// when it is mounted without a provider (its own specs do that).
registerQueryClient(queryClient);

/**
 * The last-resort screen.
 *
 * A render error anywhere below the root layout lands here rather than
 * showing a blank screen. The reader gets a way out -- retrying the render
 * is often enough, because the failures that reach this point are usually a
 * transient one (a chunk that failed to load, a piece of state that was
 * half-formed for one render).
 *
 * @param props - The error and the retry the router offers.
 * @returns The error screen.
 */
export function ErrorBoundary({
  error,
  retry,
}: {
  error: Error;
  retry: () => void;
}) {
  const onRetry = useCallback(() => retry(), [retry]);

  return (
    <View className="flex-1 items-center justify-center bg-background p-6">
      <Text className="mb-2 text-lg font-bold text-foreground">
        Something went wrong
      </Text>
      <Text className="mb-6 text-center text-[13px] text-muted-foreground">
        {error?.message ?? "An unexpected error stopped this screen."}
      </Text>
      <Pressable
        testID="error-boundary-retry"
        accessibilityRole="button"
        accessibilityLabel="Try again"
        onPress={onRetry}
        className="min-h-[44px] justify-center rounded bg-primary px-5 py-2.5"
      >
        <Text className="text-sm font-semibold text-primary-foreground">
          Try again
        </Text>
      </Pressable>
    </View>
  );
}

/**
 * Re-register the device's push token on every launch.
 *
 * Expo rotates tokens, and a token the backend has never seen delivers
 * nothing. This used to run only while an ingest screen was mounted, so a
 * reader whose token rotated after their first ingest stopped receiving
 * notifications without any visible failure.
 *
 * @returns Nothing; the hook works through effects.
 */
function PushRegistration(): null {
  usePushNotifications();
  return null;
}

export default function RootLayout() {
  // A tapped notification opens the repository it names.
  useNotificationNavigation();

  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <PushRegistration />
          <StatusBar style="light" />
          <Stack
            screenOptions={{
              headerShown: false,
              contentStyle: { backgroundColor: colors.background },
            }}
          />
        </AuthProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}
