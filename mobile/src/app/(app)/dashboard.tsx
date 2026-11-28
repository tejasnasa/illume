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
 * The header carries a logout action as well. The router redirect falls
 * through to :func:`useAuth`'s sign-out; the guard rerenders and bounces to
 * ``/login`` because the token is gone.
 *
 * Styling uses NativeWind ``className``; only the safe-area inset and
 * the ``RefreshControl`` native props (``colors`` / ``tintColor`` /
 * ``progressBackgroundColor``) stay as runtime values, because they
 * cannot be expressed as static class strings.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { FlatList, Pressable, RefreshControl, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { router } from "expo-router";

import { useRepositories } from "@/hooks/useRepositories";
import { useAuth } from "@/hooks/useAuth";
import { isReadyStatus } from "@/lib/repoStatus";
import { STATUS_FILTERS, countLine, filterRepos, type StatusFilter } from "@/lib/repoFilter";
import { RepoCard } from "@/ui/RepoCard";
import { RepoCardSkeleton } from "@/ui/RepoCardSkeleton";
import { DashboardEmptyState } from "@/ui/DashboardEmptyState";
import { FloatingActionButton } from "@/ui/FloatingActionButton";
import { FreeTierBanner } from "@/ui/FreeTierBanner";
import { colors } from "@/theme/tokens";

const SKELETON_PLACEHOLDERS = 3;

/** How often the dashboard re-reads the list while an ingest is running. */
const INGEST_POLL_MS = 5_000;

export default function DashboardScreen() {
  // Polled only while something is actually being ingested: a card that
  // says "pending" has to become "ready" without the reader discovering
  // pull-to-refresh, but an idle dashboard must not poll.
  const [pollWhileIngesting, setPollWhileIngesting] = useState(false);

  const { data, isLoading, isError, error, refetch, isRefetching } =
    useRepositories({
      refetchInterval: pollWhileIngesting ? INGEST_POLL_MS : false,
    });
  const { signOut, user } = useAuth();
  const insets = useSafeAreaInsets();

  const allRepositories = useMemo(() => data ?? [], [data]);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const repositories = useMemo(
    () => filterRepos(allRepositories, query, statusFilter),
    [allRepositories, query, statusFilter],
  );

  // The interval only has to run when at least one repository is not in a
  // terminal state; once everything has settled it is switched off.
  useEffect(() => {
    const anyInFlight = allRepositories.some(
      (repo) => !isReadyStatus(repo.status) && repo.status !== "failed",
    );
    setPollWhileIngesting(anyInFlight);
  }, [allRepositories]);

  const onRepoPress = useCallback((repo: { repo_number: number }) => {
    router.push(`/(app)/repo/${repo.repo_number}`);
  }, []);

  const onAddRepository = useCallback(() => {
    router.push("/(app)/repo-picker");
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
  const showInitialSkeleton = isLoading && allRepositories.length === 0;

  return (
    <View className="flex-1">
      <FlatList
        testID="dashboard-list"
        className="flex-1"
        contentContainerStyle={{
          paddingTop: 24 + insets.top,
          // The floating action button floats over the bottom of the
          // list, so the last card needs room to scroll clear of it.
          paddingBottom: 24 + insets.bottom + 56 + 24,
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
                <Text className="font-pixel text-[13px] tracking-[1px] text-subtle-foreground">
                  <Text className="text-accent">&gt;</Text> illume ls_
                </Text>
                <Text className="mt-2 text-[30px] font-sans-medium leading-[36px] text-foreground">
                  Your <Text className="font-pixel text-accent">repositories</Text>
                </Text>
                <Text
                  testID="dashboard-count"
                  className="mt-2 font-pixel text-xs uppercase tracking-[1px] text-muted-foreground"
                >
                  {countLine(allRepositories)}
                </Text>
              </View>
              <View className="flex-row items-center">
                {/*
                  Settings is reachable from here rather than only through
                  the free-tier banner: that banner hides itself for a BYOK
                  user or once both allowances are spent, which left those
                  readers with no way to manage their key, export a
                  repository, or reach the contact form.
                */}
                <Pressable
                  onPress={() => router.push("/(app)/settings")}
                  accessibilityRole="button"
                  accessibilityLabel="Open settings"
                  testID="dashboard-settings"
                  hitSlop={8}
                  className="mr-1 rounded-sm px-2.5 py-1.5 active:bg-secondary"
                >
                  <Text className="font-pixel text-xs uppercase text-foreground">
                    Settings
                  </Text>
                </Pressable>
                <Pressable
                  onPress={handleLogout}
                  accessibilityRole="button"
                  accessibilityLabel="Log out"
                  testID="dashboard-logout"
                  hitSlop={8}
                  className="rounded-sm px-2.5 py-1.5 active:bg-secondary"
                >
                  <Text className="font-pixel text-xs uppercase text-foreground">
                    Log out
                  </Text>
                </Pressable>
              </View>
            </View>

            <FreeTierBanner user={user} />

            {allRepositories.length > 0 ? (
              <View className="mt-5 gap-3">
                <TextInput
                  testID="dashboard-search"
                  accessibilityLabel="Search repositories"
                  value={query}
                  onChangeText={setQuery}
                  placeholder="Search repositories…"
                  placeholderTextColor={colors.faintForeground}
                  autoCapitalize="none"
                  autoCorrect={false}
                  className="h-11 rounded-sm border border-border bg-card px-3 text-sm text-foreground"
                />
                <View className="flex-row flex-wrap gap-1.5">
                  {STATUS_FILTERS.map((filter) => {
                    const on = statusFilter === filter.value;
                    return (
                      <Pressable
                        key={filter.value}
                        testID={`dashboard-filter-${filter.value}`}
                        accessibilityRole="button"
                        accessibilityState={{ selected: on }}
                        onPress={() => setStatusFilter(filter.value)}
                        className={`min-h-[36px] justify-center rounded-sm border px-3 ${
                          on ? "border-accent bg-accent/10" : "border-border"
                        }`}
                      >
                        <Text
                          className={`font-pixel text-xs uppercase tracking-[1px] ${
                            on ? "text-foreground" : "text-muted-foreground"
                          }`}
                        >
                          {filter.label}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              </View>
            ) : null}
          </View>
        }
        ListEmptyComponent={
          !showInitialSkeleton ? (
            isError ? (
              <View className="min-h-[120px] items-center justify-center gap-2 rounded border border-destructive bg-destructive/5 p-6">
                <Text className="text-base font-pixel text-destructive">
                  Couldn't load repositories
                </Text>
                <Text className="text-center text-[13px] text-muted-foreground">
                  {error?.message ?? "The server could not be reached."}
                </Text>
                <Pressable
                  testID="dashboard-retry"
                  accessibilityRole="button"
                  accessibilityLabel="Try loading the repositories again"
                  onPress={handleRefresh}
                  className="mt-2 min-h-[44px] justify-center rounded border border-border px-4 py-2 active:bg-secondary"
                >
                  <Text className="text-sm font-sans-semibold text-foreground">
                    Try again
                  </Text>
                </Pressable>
              </View>
            ) : (
              allRepositories.length > 0 ? (
                <Text
                  testID="dashboard-no-match"
                  className="rounded-md border border-dashed border-input p-10 text-center font-pixel text-sm text-muted-foreground"
                >
                  No repositories match.
                </Text>
              ) : (
                <DashboardEmptyState />
              )
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

      <FloatingActionButton
        testID="dashboard-add-repository"
        accessibilityLabel="Add New Repository"
        onPress={onAddRepository}
        bottom={insets.bottom + 16}
      />
    </View>
  );
}
