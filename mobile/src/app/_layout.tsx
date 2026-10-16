/**
 * Root layout for the Expo router.
 *
 * Wires the providers every screen reads from:
 *
 * - :class:`QueryClientProvider` -- TanStack Query for every data fetch
 *   after Phase 3. The :func:`installAppStateFocusBridge` call below is
 *   the one piece of mobile glue React Query does not set up itself.
 * - :class:`AuthProvider` -- token state, cold-start validation, sign-in
 *   and sign-out. Lives in ``hooks/useAuth`` so screens can read it
 *   without pulling in the route tree.
 *
 * The :func:`createQueryClient` factory builds the client lazily so
 * default options can be tuned without re-importing the module, and so
 * tests can override :class:`QueryClient` entirely.
 */

import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { installAppStateFocusBridge } from "@/api/focusManager";
import { colors } from "@/theme/tokens";
import { AuthProvider } from "@/hooks/useAuth";

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

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
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
