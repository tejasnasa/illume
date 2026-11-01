/**
 * The ownership panel for the selected file.
 *
 * @module OwnershipPanel
 *
 * The ownership half of the web client's detail card
 * (``client/src/components/ui/FileDetailCard.tsx``), split out into its
 * own panel so a phone can show the file's identity and its ownership
 * without one crowding out the other.
 *
 * It answers four questions about the file:
 *
 * - Who owns it? The primary owner is the contributor with the largest
 *   share of the history.
 * - Who else touched it? Every contributor, with their share.
 * - How fragile is it? The bus factor is the number of people the file's
 *   knowledge actually lives in.
 * - Is it a silo? A file only one person understands is flagged, because
 *   that is where an onboarding reader gets stuck.
 */

import { ActivityIndicator, Pressable, Text, View } from "react-native";

import type { default as Ownership } from "@/types/ownership";
import { colors } from "@/theme/tokens";

/**
 * One file's ownership entry, taken from the ownership map payload.
 */
export type FileOwnership = Ownership["files"][number];

/**
 * Props for the {@link OwnershipPanel} component.
 */
export interface OwnershipPanelProps {
  /** The ownership entry for the selected file, if the server has one. */
  ownership: FileOwnership | null;
  /** Whether the ownership request is still in flight. */
  isLoading?: boolean;
  /** The failure message, when the request failed. */
  error?: string | null;
  /** Called when the reader asks for the ownership of another file. */
  onRetry?: () => void;
  /** Test hook. */
  testID?: string;
}

/**
 * A contributor's share of a file's history, as a percentage.
 *
 * The server sends the share as a float and may send nothing at all for
 * a contributor whose history was not counted, so the value is clamped
 * into a range a bar can be drawn with.
 *
 * @param percentage - The share the server reported.
 * @returns The share, between 0 and 100.
 */
function shareOf(percentage: number | null | undefined): number {
  if (typeof percentage !== "number" || !Number.isFinite(percentage)) return 0;
  return Math.min(100, Math.max(0, percentage));
}

/**
 * Draw the ownership panel.
 *
 * @param props - The ownership entry and the state of its request.
 * @returns The rendered panel.
 */
export function OwnershipPanel({
  ownership,
  isLoading = false,
  error = null,
  onRetry,
  testID = "ownership-panel",
}: OwnershipPanelProps) {
  if (isLoading) {
    return (
      <View
        testID="ownership-loading"
        className="mb-3 rounded border border-border bg-card p-4"
      >
        <Text className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Ownership
        </Text>
        <View className="items-center justify-center py-6">
          <ActivityIndicator size="large" color={colors.foreground} />
        </View>
      </View>
    );
  }

  if (error) {
    return (
      <View testID={testID} className="mb-3">
        <View
          testID="ownership-error"
          className="mx-4 mb-3 rounded border border-destructive/30 bg-destructive/10 p-3"
        >
          <Text className="text-xs text-destructive">{error}</Text>
        </View>
        {onRetry ? (
          // The success and empty states both offer a reload; the failure
          // case needs one most, because nothing else refetches a file the
          // reader has already selected.
          <Pressable
            testID="ownership-retry"
            accessibilityRole="button"
            accessibilityLabel="Try loading the ownership data again"
            onPress={onRetry}
            className="mx-4 min-h-[44px] items-center justify-center rounded border border-border px-4 py-2 active:bg-secondary"
          >
            <Text className="text-[13px] font-semibold text-foreground">
              Try again
            </Text>
          </Pressable>
        ) : null}
      </View>
    );
  }

  if (!ownership) {
    return (
      <View
        testID={testID}
        className="mb-3 rounded border border-border bg-card p-4"
      >
        <Text className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Ownership
        </Text>
        <View testID="ownership-empty" className="items-center justify-center py-6">
          <Text className="text-[13px] font-medium text-foreground">
            No ownership data
          </Text>
          <Text className="mt-1 text-center text-xs text-muted-foreground">
            This file might not have enough history or is untracked.
          </Text>
        </View>
      </View>
    );
  }

  const contributors = ownership.contributors ?? [];
  const silo = ownership.is_knowledge_silo;

  return (
    <View
      testID={testID}
      className="mb-3 rounded border border-border bg-card p-4"
    >
      <View className="mb-3 flex-row items-center justify-between">
        <Text className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Ownership
        </Text>
        {silo ? (
          <View
            testID="ownership-silo-badge"
            className="rounded border border-chart-2/30 bg-chart-2/10 px-2 py-0.5"
          >
            <Text className="text-[10px] font-bold uppercase tracking-wider text-chart-2">
              Knowledge Silo
            </Text>
          </View>
        ) : null}
      </View>

      <View className="mb-3 flex-row items-center rounded border border-primary/20 bg-primary/5 p-3">
        <Text className="mr-3 text-xl text-chart-2">♛</Text>
        <View className="flex-1">
          <Text
            testID="ownership-primary-owner"
            className="font-semibold text-foreground"
            numberOfLines={1}
          >
            {ownership.primary_owner || "Unknown"}
          </Text>
          <Text className="text-[10px] text-muted-foreground">
            Highest contribution share
          </Text>
        </View>
      </View>

      <View className="mb-3 flex-row">
        <View className="mr-3 flex-1 rounded border border-border bg-secondary/40 p-3">
          <Text className="text-[10px] font-semibold uppercase text-muted-foreground">
            Bus Factor
          </Text>
          <View className="flex-row items-end">
            <Text
              testID="ownership-bus-factor"
              className="text-xl font-bold text-foreground"
            >
              {ownership.bus_factor}
            </Text>
            <Text className="mb-0.5 ml-1 text-[10px] font-medium text-muted-foreground">
              {ownership.bus_factor === 1 ? "engineer" : "engineers"}
            </Text>
          </View>
        </View>
        <View className="flex-1 rounded border border-border bg-secondary/40 p-3">
          <Text className="text-[10px] font-semibold uppercase text-muted-foreground">
            Contributors
          </Text>
          <View className="flex-row items-end">
            <Text
              testID="ownership-contributor-count"
              className="text-xl font-bold text-foreground"
            >
              {contributors.length}
            </Text>
            <Text className="mb-0.5 ml-1 text-[10px] font-medium text-muted-foreground">
              total
            </Text>
          </View>
        </View>
      </View>

      {contributors.length > 0 ? (
        <View testID="ownership-contributors">
          <View className="mb-2 flex-row items-center justify-between">
            <Text className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Knowledge Distribution
            </Text>
            <Text className="text-[10px] text-muted-foreground">
              {contributors.length} authors
            </Text>
          </View>

          {contributors.map((contributor, index) => {
            const share = shareOf(contributor.percentage);
            return (
              <View
                key={`${contributor.name}-${index}`}
                testID={`ownership-contributor-${index}`}
                className="mb-2"
              >
                <View className="mb-1 flex-row items-center justify-between">
                  <Text
                    className="mr-2 flex-1 text-xs font-medium text-foreground"
                    numberOfLines={1}
                  >
                    {contributor.name}
                  </Text>
                  <Text
                    testID={`ownership-contributor-percentage-${index}`}
                    className="font-mono text-xs font-bold text-primary"
                  >
                    {share > 0 ? `${share.toFixed(1)}%` : "N/A"}
                  </Text>
                </View>
                <View className="h-1 w-full overflow-hidden rounded-full bg-secondary">
                  <View
                    className="h-full rounded-full bg-primary"
                    style={{ width: `${share}%` }}
                  />
                </View>
              </View>
            );
          })}
        </View>
      ) : null}

      {onRetry ? (
        <Pressable
          testID="ownership-retry"
          accessibilityRole="button"
          accessibilityLabel="Reload ownership"
          onPress={onRetry}
          className="mt-1 min-h-[44px] items-center justify-center rounded border border-border active:bg-secondary"
        >
          <Text className="text-[13px] font-medium text-foreground">
            Reload ownership
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export default OwnershipPanel;
