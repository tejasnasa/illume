/**
 * Dashboard screen -- list of the caller's ingested repositories.
 *
 * @module DashboardScreen
 *
 * The screen owns one ``FlatList`` of :component:`RepoCard` rows plus
 * three peripheral surfaces:
 *
 * - A :component:`DashboardEmptyState` when the backend reports zero
 *   repositories.
 * - Three :component:`RepoCardSkeleton` placeholders during the initial
 *   load so the screen has a stable height before real data arrives.
 * - A pull-to-refresh :component:`RefreshControl` so the user can force a
 *   refetch without leaving the screen.
 *
 * The header carries a logout action so Phase 4 has an entry point
 * before Settings (Phase 12) is wired up properly. The router redirect
 * falls through to :func:`useAuth`'s sign-out; the guard rerenders and
 * bounces to ``/login`` because the token is gone.
 *
 * Styling uses NativeWind ``className``; only the safe-area inset and
 * the ``RefreshControl`` native props (``colors`` / ``tintColor`` /
 * ``progressBackgroundColor``) stay as runtime values, because they
 * cannot be expressed as static class strings.
 */

import { useCallback, useMemo } from "react";
import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { router } from "expo-router";

import { useRepositories } from "@/hooks/useRepositories";
import { useAuth } from "@/hooks/useAuth";
import { RepoCard } from "@/ui/RepoCard";
import { RepoCardSkeleton } from "@/ui/RepoCardSkeleton";
import { DashboardEmptyState } from "@/ui/DashboardEmptyState";
import { colors } from "@/theme/tokens";

const SKELETON_PLACEHOLDERS = 3;

export default function DashboardScreen() {
  const { data, isLoading, isError, error, refetch, isRefetching } =
    useRepositories();
  const { signOut } = useAuth();
  const insets = useSafeAreaInsets();

  const repositories = useMemo(() => data ?? [], [data]);

  const onRepoPress = useCallback((repo: { repo_number: number }) => {
    router.push(`/(app)/repo/${repo.repo_number}`);
  }, []);

  const handleLogout = useCallback(async () => {
    await signOut();
    // The ``(app)`` guard rerenders on token change and pushes /login.
  }, [signOut]);

  const handleRefresh = useCallback(() => {
    void refetch();
  }, [refetch]);

  // ``isLoading`` is the first fetch; subsequent lists are background
  // refetches and should not blank the screen.
  const showInitialSkeleton = isLoading && repositories.length === 0;

  return (
    <FlatList
      testID="dashboard-list"
      className="flex-1 bg-background"
      contentContainerStyle={{
        paddingTop: 24 + insets.top,
        paddingBottom: 48,
        flexGrow: 1,
      }}
      contentContainerClassName="px-4"
      data={
        showInitialSkeleton
          ? Array.from({ length: SKELETON_PLACEHOLDERS })
          : repositories
      }
      // Stable keys: skeletons get deterministic indices, real rows key by id.
      // Never use the array index alone. ``item`` can be ``undefined`` while
      // FlatList probes the data shape, so guard against that.
      keyExtractor={(item, index) =>
        item !== null &&
        item !== undefined &&
        typeof item === "object" &&
        "id" in item &&
        typeof item.id === "string"
          ? item.id
          : `skeleton-${index}`
      }
      renderItem={({ item, index }) =>
        showInitialSkeleton ? (
          <RepoCardSkeleton testID={`dashboard-skeleton-${index}`} />
        ) : (
          <RepoCard repo={item as never} onPress={onRepoPress as never} />
        )
      }
      ListHeaderComponent={
        <View className="mb-4">
          <View className="flex-row items-start justify-between gap-3">
            <View className="min-w-0 flex-1">
              <Text className="text-[32px] font-extrabold tracking-tight text-foreground">
                Dashboard
              </Text>
              <Text className="mt-2 text-base text-muted-foreground">
                Manage and explore your indexed codebases.
              </Text>
            </View>
            <Pressable
              onPress={handleLogout}
              accessibilityRole="button"
              accessibilityLabel="Log out"
              testID="dashboard-logout"
              hitSlop={8}
              className="rounded px-2.5 py-1.5 active:bg-secondary"
            >
              <Text className="text-sm font-semibold text-foreground">
                Log out
              </Text>
            </Pressable>
          </View>
          <Text className="mt-6 text-[11px] font-bold uppercase tracking-[2px] text-muted-foreground opacity-60">
            Your Indexed Libraries
          </Text>
        </View>
      }
      ListEmptyComponent={
        !showInitialSkeleton ? (
          isError ? (
            <View className="min-h-[120px] items-center justify-center gap-2 rounded border border-destructive bg-destructive/5 p-6">
              <Text className="text-base font-bold text-destructive">
                Couldn't load repositories
              </Text>
              <Text className="text-center text-[13px] text-muted-foreground">
                {error?.message ?? "Pull down to try again."}
              </Text>
            </View>
          ) : (
            <DashboardEmptyState />
          )
        ) : null
      }
      refreshControl={
        <RefreshControl
          refreshing={isRefetching}
          onRefresh={handleRefresh}
          tintColor={colors.foreground}
          colors={[colors.primary]}
          progressBackgroundColor={colors.card}
        />
      }
    />
  );
}
