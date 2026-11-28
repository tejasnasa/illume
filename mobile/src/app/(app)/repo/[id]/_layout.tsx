/**
 * The shell every repository screen lives in.
 *
 * @module RepoLayout
 *
 * Port of the web app's repository layout
 * (``client/src/app/repo/[id]/layout.tsx``). A slim top bar carries the
 * repository's identity and a way back and to its settings; a bottom dock
 * (:component:`RepoDock`) switches between the sections and opens the chat.
 *
 * The layout is the right place for the pieces that have to outlive any
 * one screen:
 *
 * - The top bar, so the repository's name and status are visible from every
 *   section.
 * - The :component:`RepoStatusPoller`, so a background sync repaints the
 *   page even while the reader is on another section.
 */

import { useCallback, useEffect } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import { router, useGlobalSearchParams, usePathname } from "expo-router";
import { Tabs, type BottomTabBarProps } from "expo-router/js-tabs";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { RepoStatusPoller } from "@/components/RepoStatusPoller";
import { useRepository } from "@/hooks/useRepositories";
import { isReadyStatus } from "@/lib/repoStatus";
import { RepoDock } from "@/ui/RepoDock";
import { RepoTopBar } from "@/ui/RepoTopBar";
import { colors } from "@/theme/tokens";

/**
 * The sections that need an indexed repository.
 *
 * A section that is not available yet -- because the repository has not
 * been indexed -- is left out of the dock rather than shown disabled, and a
 * deep link into one is sent back to the overview.
 */
const SECTION_TABS = [
  { name: "glossary", title: "Terms" },
  { name: "explorer", title: "Files" },
  { name: "graph", title: "Graph" },
  { name: "chat", title: "Ask" },
] as const;

/**
 * The routes that are reachable but never listed in the dock.
 *
 * ``href: null`` is what marks a screen as hidden: the navigator drops
 * the item from its own bar. This shell draws a custom dock instead
 * (:component:`RepoDock`), and a custom dock has to honour the same rule
 * itself -- otherwise the settings screen turns into another slot.
 */
const HIDDEN_ROUTES = new Set(["settings"]);

/**
 * Drop the hidden routes from the state the custom dock draws.
 *
 * The focused index is carried over rather than recomputed: a hidden route
 * that is focused leaves the index pointing past the end of the shortened
 * list, which is exactly what keeps every slot unhighlighted while the
 * settings screen is open.
 *
 * @param state - The navigator's state.
 * @returns The state without the hidden routes.
 */
function withoutHiddenRoutes(
  state: BottomTabBarProps["state"],
): BottomTabBarProps["state"] {
  const routes = state.routes.filter((route) => !HIDDEN_ROUTES.has(route.name));
  if (routes.length === state.routes.length) return state;

  const focusedKey = state.routes[state.index]?.key;
  const focusedIndex = routes.findIndex((route) => route.key === focusedKey);

  return {
    ...state,
    routes,
    index: focusedIndex >= 0 ? focusedIndex : state.index,
  };
}

/**
 * Render the repository shell.
 *
 * @returns The shell, or a redirect when the requested tab does not exist
 *   for a repository that has not been indexed.
 */
export default function RepoLayout() {
  const { id } = useGlobalSearchParams<{ id: string }>();
  const repoNumber = String(id ?? "");
  const pathname = usePathname();
  const insets = useSafeAreaInsets();

  const { data: repo, isLoading, isError } = useRepository(repoNumber);

  const ready = isReadyStatus(repo?.status);

  // The overview is ``/repo/<number>``; every section adds a suffix. The
  // route group is not part of the path, so the suffixes are matched
  // against the end of it rather than by counting segments.
  const onSectionTab = SECTION_TABS.some((tab) =>
    pathname.endsWith(`/${tab.name}`),
  );

  const goBack = useCallback(() => {
    // ``dismissTo`` pops back to the dashboard when it is on the stack and
    // replaces the current screen with it when it is not, so a deep link
    // into a repository still has somewhere to go back to.
    router.dismissTo("/(app)/dashboard");
  }, []);

  // A section tab was deep-linked into on a repository that has not been
  // indexed; the data behind it does not exist, so the overview is the
  // only honest place to land.
  //
  // ``navigate`` rather than ``replace``: the sections are tabs, and
  // replacing one tab with another leaves the navigator with two routes
  // named the same. Navigating switches to the overview tab instead.
  //
  // The redirect waits for the repository to load -- until it does, every
  // status reads as "not ready", and a redirect fired then would eject
  // the reader from a perfectly good section.
  const repoLoaded = !isLoading && !isError && !!repo;
  const shouldRedirect = repoLoaded && !ready && onSectionTab;

  useEffect(() => {
    if (!shouldRedirect) return;
    router.navigate(`/(app)/repo/${repoNumber}`);
  }, [shouldRedirect, repoNumber]);

  if (isError) {
    return (
      <View className="flex-1 items-center justify-center bg-background p-6">
        <Text className="mb-2 text-lg font-pixel text-foreground">
          Repository not found
        </Text>
        <Text className="mb-6 text-center text-[13px] text-muted-foreground">
          It may have been deleted, or it belongs to another account.
        </Text>
        <Pressable
          testID="repo-not-found-back"
          accessibilityRole="button"
          accessibilityLabel="Back to dashboard"
          onPress={goBack}
          className="min-h-[44px] justify-center rounded border border-border px-4 py-2"
        >
          <Text className="text-sm font-sans-semibold text-foreground">
            Back to dashboard
          </Text>
        </Pressable>
      </View>
    );
  }

  if (isLoading || !repo) {
    return (
      <View
        className="flex-1 items-center justify-center bg-background"
        style={{ paddingTop: insets.top }}
      >
        <ActivityIndicator size="large" color={colors.foreground} />
      </View>
    );
  }

  return (
    <View className="flex-1" style={{ paddingTop: insets.top }}>
      <RepoTopBar
        repo={repo}
        onBack={goBack}
        onSettings={() => router.push(`/(app)/repo/${repoNumber}/settings`)}
      />

      <RepoStatusPoller
        repoNumber={repoNumber}
        status={repo.status}
        syncStatus={repo.sync_status}
      />

      <Tabs
        tabBar={(props) => (
          <RepoDock
            {...props}
            state={withoutHiddenRoutes(props.state)}
            sectionsAvailable={ready}
          />
        )}
        screenOptions={{
          headerShown: false,
          // The dock is custom, but the position still decides whether it
          // is laid out above the scenes or below them.
          tabBarPosition: "bottom",
          sceneStyle: { backgroundColor: "transparent" },
        }}
      >
        <Tabs.Screen name="index" options={{ title: "Overview" }} />

        {SECTION_TABS.map((tab) => (
          <Tabs.Screen
            key={tab.name}
            name={tab.name}
            options={{ title: tab.title }}
          />
        ))}

        {/* Settings has a URL of its own but no slot in the dock. */}
        <Tabs.Screen name="settings" options={{ href: null }} />
      </Tabs>
    </View>
  );
}
