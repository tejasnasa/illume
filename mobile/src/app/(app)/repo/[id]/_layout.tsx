/**
 * The shell every repository screen lives in.
 *
 * @module RepoLayout
 *
 * Port of the web app's repository layout
 * (``client/src/app/repo/[id]/layout.tsx``) and its navbar
 * (``client/src/components/RepoNavbar.tsx``). The web navbar is a row of
 * section links across the top of the page; on a phone that row becomes a
 * tab bar pinned to the top, with the repository's identity above it.
 *
 * The layout is the right place for the pieces that have to outlive any
 * one screen:
 *
 * - The identity header, so the repository's name and status are visible
 *   from every tab.
 * - The :component:`RepoStatusPoller`, so a background sync repaints the
 *   page even while the reader is on another tab.
 *
 * The tab bar is a custom one (:component:`RepoTabBar`) rather than the
 * navigator's built-in bar: the built-in bar is a bottom bar that wants an
 * icon above every label, and the web navbar is the opposite -- a row of
 * text links. The labels are the web client's, unchanged: Home, Glossary,
 * Explorer, Graph.
 */

import { useCallback, useEffect } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import { router, useLocalSearchParams, usePathname } from "expo-router";
import { Tabs } from "expo-router/js-tabs";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { RepoStatusPoller } from "@/components/RepoStatusPoller";
import { useRepository } from "@/hooks/useRepositories";
import { isReadyStatus } from "@/lib/repoStatus";
import { RepoStatusBadge } from "@/ui/RepoStatusBadge";
import { RepoTabBar } from "@/ui/RepoTabBar";
import { colors } from "@/theme/tokens";

/**
 * The section tabs, in the order the web navbar lists them.
 *
 * A tab that is not available yet -- because the repository has not been
 * indexed -- is left out of the bar rather than shown disabled. On the web
 * the links stay visible and greyed out; on a phone three permanently dead
 * tabs crowd out the one that works, and the data behind them does not
 * exist yet anyway.
 */
const SECTION_TABS = [
  { name: "glossary", title: "Glossary" },
  { name: "explorer", title: "Explorer" },
  { name: "graph", title: "Graph" },
] as const;

/**
 * Render the repository shell.
 *
 * @returns The shell, or a redirect when the requested tab does not exist
 *   for a repository that has not been indexed.
 */
export default function RepoLayout() {
  const { id } = useLocalSearchParams<{ id: string }>();
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
        <Text className="mb-2 text-lg font-bold text-foreground">
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
          className="rounded border border-border px-4 py-2"
        >
          <Text className="text-sm font-semibold text-foreground">
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
    <View className="flex-1 bg-background" style={{ paddingTop: insets.top }}>
      <View className="flex-row items-center border-b border-border px-3 py-2">
        <Pressable
          testID="repo-back"
          accessibilityRole="button"
          accessibilityLabel="Back to dashboard"
          onPress={goBack}
          hitSlop={8}
          className="mr-2 rounded px-2 py-1 active:bg-secondary"
        >
          <Text className="text-lg text-foreground">←</Text>
        </Pressable>

        <Text
          testID="repo-name"
          className="flex-1 text-base font-medium text-foreground"
          numberOfLines={1}
        >
          {repo.name}
        </Text>

        <RepoStatusBadge
          status={repo.status}
          syncStatus={repo.sync_status}
          testID="repo-header-status"
        />
      </View>

      <RepoStatusPoller
        repoNumber={repoNumber}
        status={repo.status}
        syncStatus={repo.sync_status}
      />

      <Tabs
        tabBar={(props) => <RepoTabBar {...props} sectionsAvailable={ready} />}
        screenOptions={{
          headerShown: false,
          // The bar is custom, but the position still decides whether it
          // is laid out above the scenes or below them.
          tabBarPosition: "top",
          sceneStyle: { backgroundColor: colors.background },
        }}
      >
        <Tabs.Screen name="index" options={{ title: "Home" }} />

        {SECTION_TABS.map((tab) => (
          <Tabs.Screen
            key={tab.name}
            name={tab.name}
            options={{ title: tab.title }}
          />
        ))}
      </Tabs>
    </View>
  );
}
