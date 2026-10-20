/**
 * Repository overview card with status, summary, and detected stack.
 *
 * @module RepoCard
 *
 * Port of ``client/src/components/ui/RepoCard.tsx``. The web version
 * relied on CSS features that have no React Native equivalent
 * (``glass-card``'s backdrop-filter, ``line-clamp-4``), so the visual
 * structure carries over but the surface and truncation are simple
 * RN primitives. The summary string stays as the server returns it --
 * the backend already truncates ``architecture_summary`` so the card
 * renders the same text regardless of viewport size.
 *
 * Styling uses NativeWind ``className``. The status pill swaps colour
 * through Tailwind's ``bg-*-500/10`` opacity syntax; the activity
 * spinner and conditional summary placeholder keep their inline native
 * ``style`` because they need dynamic values that are awkward to
 * express as class strings.
 */

import { useMemo } from "react";
import { Pressable, Text, View, ActivityIndicator } from "react-native";
import type Repository from "@/types/repository";
import { timeAgo } from "@/lib/timeAgo";
import { colors } from "@/theme/tokens";

export interface RepoCardProps {
  /** The repository record rendered by this card. */
  repo: Repository;
  /** Stable per-row press handler; the dashboard owns navigation. */
  onPress?: (repo: Repository) => void;
}

/**
 * Renders a tap-target summarising one repository's ingestion state.
 *
 * The whole surface is one ``Pressable``; the parent decides what
 * ``onPress`` does (the dashboard navigates to the repo shell). The
 * web card's open-in-browser GitHub icon is dropped here -- deep-linking
 * to a URL on RN hands control to the system browser which is rarely
 * what the user wants from a tile that already leads to a richer
 * in-app view.
 */
export function RepoCard({ repo, onPress }: RepoCardProps) {
  const isReady = repo.status === "ready";
  const isFailed = repo.status === "failed";
  const isPending = !isReady && !isFailed;

  // Tailwind opacity-suffixed backgrounds are only supported against
  // built-in palette names (e.g. ``green-500``), not the custom
  // ``success`` token. The ready / failed / pending pills use the
  // built-in ``green-500``, ``red-500``, and ``yellow-500`` swatches at
  // 10% opacity so the colour reads the same on every card.
  const pillClass = isReady
    ? "bg-green-500/10"
    : isFailed
      ? "bg-red-500/10"
      : "bg-yellow-500/10";
  const pillLabelClass = isReady
    ? "text-green-500"
    : isFailed
      ? "text-red-500"
      : "text-yellow-500";

  const chips = useMemo<string[]>(
    () => [
      ...((repo.detected_stack?.languages ?? []) as string[]),
      ...((repo.detected_stack?.frameworks ?? []) as string[]),
    ],
    [repo.detected_stack],
  );

  const shortSha = repo.ingested_commit_sha
    ? repo.ingested_commit_sha.substring(0, 7)
    : null;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Open ${repo.name}`}
      onPress={onPress ? () => onPress(repo) : undefined}
      className="mb-3 rounded border border-border p-4 active:border-primary"
    >
      <View className="mb-3 flex-row items-start">
        <View className="flex-1 min-w-0">
          <Text
            className="pr-3 text-lg font-bold text-foreground"
            numberOfLines={1}
          >
            {repo.name}
          </Text>

          <View className="mt-1.5 flex-row flex-wrap items-center gap-2">
            <View
              className={`flex-row items-center rounded-full px-2 py-0.5 ${pillClass}`}
            >
              {isReady ? (
                <Text
                  className={`mr-1 text-[10px] font-bold ${pillLabelClass}`}
                >
                  ✓
                </Text>
              ) : null}
              {isFailed ? (
                <Text
                  className={`mr-1 text-[10px] font-bold ${pillLabelClass}`}
                >
                  !
                </Text>
              ) : null}
              {isPending ? (
                <ActivityIndicator
                  size="small"
                  color={colors.foreground}
                  style={styles.spinner}
                />
              ) : null}
              <Text
                className={`text-[10px] font-bold uppercase tracking-widest ${pillLabelClass}`}
              >
                {repo.status}
              </Text>
            </View>
            <Text className="text-[10px] text-muted-foreground">
              {timeAgo(repo.updated_at)}
            </Text>
          </View>

          {repo.ingested_branch ? (
            <View className="mt-2 max-w-[220px] flex-row items-center self-start rounded border border-border bg-secondary/20 px-1.5 py-0.5">
              <Text className="mr-1 text-[11px]">🔀</Text>
              <Text
                className="flex-shrink text-[11px] font-mono text-muted-foreground"
                numberOfLines={1}
              >
                {repo.ingested_branch}
              </Text>
              {shortSha ? (
                <>
                  <Text className="mx-1 text-[11px] text-muted-foreground opacity-40">
                    @
                  </Text>
                  <Text className="text-[11px] font-mono text-primary">
                    {shortSha}
                  </Text>
                </>
              ) : null}
            </View>
          ) : null}
        </View>
      </View>

      {repo.architecture_summary ? (
        <Text
          className="mb-3 text-[13px] leading-[18px] text-muted-foreground"
          numberOfLines={4}
        >
          {repo.architecture_summary}
        </Text>
      ) : (
        <View className="mb-3 min-h-[60px] items-center justify-center rounded-lg border border-dashed border-border bg-white/[0.02]">
          <Text className="text-xs italic text-muted-foreground">
            Waiting for AI analysis...
          </Text>
        </View>
      )}

      <View className="flex-row flex-wrap gap-1">
        {chips.length > 0 ? (
          chips.map((item, i) => (
            <View
              key={`${item}-${i}`}
              className="rounded border border-border bg-muted px-1.5 py-0.5"
            >
              <Text className="font-mono text-xs text-foreground">{item}</Text>
            </View>
          ))
        ) : (
          <Text className="text-[10px] italic text-muted-foreground opacity-60">
            Detecting...
          </Text>
        )}
      </View>
    </Pressable>
  );
}

// NativeWind has no spinner scale; the ``ActivityIndicator`` keeps an
// inline transform so the pill stays a tight horizontal row.
const styles = {
  spinner: { marginRight: 4, transform: [{ scale: 0.6 }] },
} as const;
