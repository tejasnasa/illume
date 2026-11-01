/**
 * The glossary screen.
 *
 * @module GlossaryScreen
 *
 * Port of ``client/src/app/repo/[id]/glossary/page.tsx`` and the search
 * wrapper it renders (``client/src/components/GlossarySearch.tsx``).
 *
 * The web page is a two-column masonry grid of entry cards with the search
 * box in the header. React Native has no masonry layout, and chasing one
 * is a dead end, so the grid becomes a single-column list: the cards are
 * narrower than a phone screen anyway, and the reader scrolls rather than
 * scans. Everything that decides *what* is on screen -- which route is
 * asked, how long the keystrokes are collected, what a term matches -- is
 * unchanged.
 *
 * The screen has three parts, stacked the way a phone reads them:
 *
 * 1. The heading and the search box, in the list's header.
 * 2. The entries (:component:`GlossaryEntry`).
 * 3. The paging controls, in the list's footer.
 */

import { useCallback } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  Text,
  View,
} from "react-native";
import { useGlobalSearchParams } from "expo-router";

import { GlossaryEntry } from "@/components/GlossaryEntry";
import { GlossarySearch } from "@/components/GlossarySearch";
import { useGlossarySearch } from "@/hooks/useGlossarySearch";
import { useRepository } from "@/hooks/useRepositories";
import { colors } from "@/theme/tokens";

/**
 * Render the glossary.
 *
 * @returns The search box, the entries and the paging controls.
 */
export default function GlossaryScreen() {
  // ``useGlobalSearchParams``, not the local variant: these screens are
  // tab children, not the ``[id]`` segment itself, and a local lookup
  // only sees the current route's own params -- which is why every
  // screen here used to receive an empty id and render nothing.
  const { id } = useGlobalSearchParams<{ id: string }>();
  const repoNumber = String(id ?? "");

  // The route carries the repository's user-scoped number; the glossary
  // routes are keyed by its UUID.
  const {
    data: repo,
    isLoading: repoLoading,
    isError: repoError,
  } = useRepository(repoNumber);
  const repoId = repo?.id;

  const {
    query,
    setQuery,
    reset,
    entries,
    total,
    page,
    pageCount,
    isSearching,
    isLoading,
    isFetching,
    error,
    retry,
    goToPage,
  } = useGlossarySearch({ repoId });

  const onPrevious = useCallback(() => goToPage(page - 1), [goToPage, page]);
  const onNext = useCallback(() => goToPage(page + 1), [goToPage, page]);

  const header = (
    <View className="px-4 pb-3 pt-4">
      <Text className="text-lg font-bold text-foreground">
        Codebase Glossary
      </Text>
      <Text className="mt-1 text-[13px] text-muted-foreground">
        Domain terms, core classes, and functions explained in plain English.
      </Text>

      <View className="mt-3">
        <GlossarySearch value={query} onChangeText={setQuery} onClear={reset} />
      </View>

      <View className="mt-2 flex-row items-center justify-between">
        <Text
          testID="glossary-count"
          className="text-[11px] text-muted-foreground"
        >
          {`Showing ${entries.length} of ${total} entries`}
        </Text>
        {isFetching && !isLoading ? (
          <ActivityIndicator size="small" color={colors.mutedForeground} />
        ) : null}
      </View>
    </View>
  );

  const footer =
    pageCount > 1 ? (
      <View className="flex-row items-center justify-between px-4 pb-6 pt-2">
        <Pressable
          testID="glossary-previous-page"
          accessibilityRole="button"
          accessibilityLabel="Previous page"
          accessibilityState={{ disabled: page <= 1 }}
          disabled={page <= 1}
          onPress={onPrevious}
          className="min-h-[44px] rounded border border-border px-4 py-2 active:bg-secondary disabled:opacity-40"
        >
          <Text className="text-sm text-foreground">Previous</Text>
        </Pressable>

        <Text
          testID="glossary-page-indicator"
          className="text-[11px] text-muted-foreground"
        >
          Page {page} of {pageCount}
        </Text>

        <Pressable
          testID="glossary-next-page"
          accessibilityRole="button"
          accessibilityLabel="Next page"
          accessibilityState={{ disabled: page >= pageCount }}
          disabled={page >= pageCount}
          onPress={onNext}
          className="min-h-[44px] rounded border border-border px-4 py-2 active:bg-secondary disabled:opacity-40"
        >
          <Text className="text-sm text-foreground">Next</Text>
        </Pressable>
      </View>
    ) : null;

  // Three different answers, and the list has to say which one it is
  // rather than showing an empty box: the request is still in flight, the
  // request failed, or the repository genuinely has no glossary yet.
  const emptyComponent =
    isLoading || repoLoading ? (
      <View
        testID="glossary-loading"
        className="items-center justify-center py-10"
      >
        <ActivityIndicator size="large" color={colors.foreground} />
      </View>
    ) : error ? (
      <View>
        <View
          testID="glossary-error"
          className="mx-4 mb-3 rounded border border-destructive/30 bg-destructive/10 p-3"
        >
          <Text className="text-xs text-destructive">{error}</Text>
        </View>
        <Pressable
          testID="glossary-retry"
          accessibilityRole="button"
          accessibilityLabel="Try loading the glossary again"
          onPress={retry}
          className="mx-4 mb-3 min-h-[44px] self-start justify-center rounded border border-border px-4 py-2 active:bg-secondary"
        >
          <Text className="text-sm font-semibold text-foreground">
            Try again
          </Text>
        </Pressable>
      </View>
    ) : (
      <View
        testID="glossary-empty"
        className="items-center justify-center py-10"
      >
        <Text className="text-center text-[13px] text-muted-foreground">
          {repoError
            ? "This repository could not be loaded."
            : isSearching
              ? "No glossary entries found matching your query."
              : "No glossary entries found."}
        </Text>
      </View>
    );

  return (
    <View className="flex-1 bg-background">
      <FlatList
        testID="glossary-list"
        data={entries}
        keyExtractor={(entry) => entry.id}
        renderItem={({ item, index }) => (
          <View className="px-4">
            <GlossaryEntry
              entry={item}
              githubUrl={repo?.github_url ?? ""}
              branch={repo?.ingested_branch ?? null}
              testID={`glossary-entry-${index}`}
            />
          </View>
        )}
        ListHeaderComponent={header}
        ListFooterComponent={footer}
        ListEmptyComponent={emptyComponent}
        className="flex-1 bg-background"
        contentContainerClassName="pb-4"
        keyboardShouldPersistTaps="handled"
      />
    </View>
  );
}
