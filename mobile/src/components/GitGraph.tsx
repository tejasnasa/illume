/**
 * Unified commit timeline with branch rails and ingest targeting.
 *
 * @module GitGraph
 *
 * Port of ``client/src/components/GitGraph.tsx`` to ``react-native-svg``.
 * The web version draws the rails as an absolutely-positioned SVG behind a
 * column of commit cards; the same structure works here because the rail
 * area and the card column live side by side inside one vertical
 * ``ScrollView``, so the rails scroll with the commits they belong to.
 *
 * Two things changed for the phone:
 *
 * - **Branch selection is explicit.** The web version only ever ingested
 *   the default branch, or whichever branch a pinned commit belonged to.
 *   A phone screen has room for a scrollable row of branch chips, and
 *   choosing the branch to ingest is the decision the user actually
 *   wants to make.
 * - **Touch targets.** Every commit card is a single ``Pressable`` the
 *   full height of its row, so the target is far larger than the 5-point
 *   node that marks it.
 *
 * The rail geometry itself lives in :mod:`src.lib.gitGraphLayout` so it
 * can be tested without a renderer.
 */

import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Pressable,
  ScrollView,
  Text,
  View,
} from "react-native";
import Svg, { Circle, Path } from "react-native-svg";

import { useGitGraph } from "@/hooks/useGitGraph";
import { buildGitGraphLayout } from "@/lib/gitGraphLayout";
import { timeAgo } from "@/lib/timeAgo";
import { colors } from "@/theme/tokens";
import type { GitHubMultiBranchCommit } from "@/types/github";

/** Props for the repository timeline selector. */
export interface GitGraphProps {
  /** GitHub repository owner. */
  owner: string;
  /** GitHub repository name. */
  repo: string;
  /** Called with the chosen branch and optional commit SHA. */
  onSelect: (branch: string, commitSha: string | null) => void;
  /** Disables ingest while the parent submits. */
  isSubmitting?: boolean;
}

/**
 * One commit row: the message, its branches, the author, and the short
 * SHA.
 */
function CommitCard({
  commit,
  selected,
  onPress,
}: {
  commit: GitHubMultiBranchCommit;
  selected: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      testID={`gitgraph-commit-${commit.short_sha}`}
      accessibilityRole="button"
      accessibilityLabel={`${commit.message}, ${commit.short_sha}`}
      accessibilityState={{ selected }}
      onPress={onPress}
      className={`min-h-[56px] flex-1 flex-row items-center justify-between gap-2 rounded border px-3 py-2 ${
        selected
          ? "border-primary bg-primary/10"
          : "border-border bg-secondary/10"
      }`}
    >
      <View className="min-w-0 flex-1">
        <View className="flex-row items-center gap-2">
          <Text
            className="min-w-0 flex-1 text-xs font-semibold text-foreground"
            numberOfLines={1}
          >
            {commit.message}
          </Text>
          {commit.branches.map((branch) => (
            <View
              key={branch}
              className="max-w-[110px] rounded border border-primary/30 bg-primary/15 px-1.5 py-0.5"
            >
              <Text className="text-[9px] font-bold text-primary" numberOfLines={1}>
                {branch}
              </Text>
            </View>
          ))}
        </View>

        <View className="mt-1 flex-row items-center gap-1.5">
          {commit.author_avatar ? (
            <Image
              source={{ uri: commit.author_avatar }}
              accessibilityIgnoresInvertColors
              style={{ width: 14, height: 14, borderRadius: 7 }}
            />
          ) : (
            <View className="h-3.5 w-3.5 items-center justify-center rounded-full bg-secondary">
              <Text className="text-[8px] font-bold text-muted-foreground">
                {commit.author_name.charAt(0)}
              </Text>
            </View>
          )}
          <Text
            className="max-w-[110px] text-[10px] text-muted-foreground"
            numberOfLines={1}
          >
            {commit.author_name}
          </Text>
          <Text className="text-[10px] text-muted-foreground opacity-60">•</Text>
          <Text className="text-[10px] text-muted-foreground opacity-60">
            {timeAgo(new Date(commit.authored_at))}
          </Text>
        </View>
      </View>

      <Text className="shrink-0 rounded bg-secondary px-1.5 py-0.5 font-mono text-[9px] text-muted-foreground">
        {commit.short_sha}
      </Text>
    </Pressable>
  );
}

/**
 * Renders multi-branch history and reports the ingest target.
 *
 * @param owner - GitHub repository owner.
 * @param repo - GitHub repository name.
 * @param onSelect - Called with the chosen branch and optional commit SHA.
 * @param isSubmitting - Disables ingest while the parent submits.
 * @returns Timeline panel with rail graph, commit list, and ingest footer.
 */
export function GitGraph({
  owner,
  repo,
  onSelect,
  isSubmitting = false,
}: GitGraphProps) {
  const {
    branches,
    commits,
    defaultBranch,
    selectedCommit,
    setSelectedCommit,
    loadingBranches,
    loadingCommits,
    error,
  } = useGitGraph({ owner, repo });

  // The branch the user has chosen to ingest. A pinned commit overrides
  // it, because ingesting a commit means ingesting that commit's branch.
  const [chosenBranch, setChosenBranch] = useState<string | null>(null);
  const effectiveBranch =
    selectedCommit?.branches[0] ?? chosenBranch ?? defaultBranch;

  const layout = useMemo(
    () =>
      buildGitGraphLayout(
        commits.map((commit) => ({ sha: commit.sha, parents: commit.parents })),
      ),
    [commits],
  );

  /**
   * Toggles selection of a commit row.
   *
   * @param commit - Commit that was tapped.
   */
  const handleCommitPress = (commit: GitHubMultiBranchCommit) => {
    setSelectedCommit(
      selectedCommit?.sha === commit.sha ? null : commit,
    );
  };

  /** Reports the selected target to the parent. */
  const handleIngest = () => {
    onSelect(effectiveBranch, selectedCommit?.sha ?? null);
  };

  const selectedTarget = selectedCommit
    ? `commit ${selectedCommit.short_sha}`
    : `branch ${effectiveBranch}`;

  return (
    <View className="flex-1 overflow-hidden rounded border border-border bg-background">
      <View className="flex-row items-center justify-between border-b border-border bg-secondary/10 px-4 py-3">
        <Text className="text-sm font-semibold text-foreground">
          Unified Repository Timeline
        </Text>
        {loadingBranches || loadingCommits ? (
          <ActivityIndicator size="small" color={colors.primary} />
        ) : null}
      </View>

      {error ? (
        <View className="m-3 rounded border border-destructive/30 bg-destructive/10 p-3">
          <Text className="text-xs text-destructive">{error}</Text>
        </View>
      ) : null}

      {branches.length > 0 ? (
        <View className="border-b border-border bg-secondary/5 px-3 py-2">
          <Text className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            Branch to ingest
          </Text>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ gap: 6 }}
          >
            {branches.map((branch) => {
              const isActive = effectiveBranch === branch.name;
              return (
                <Pressable
                  key={branch.name}
                  testID={`gitgraph-branch-${branch.name}`}
                  accessibilityRole="button"
                  accessibilityState={{ selected: isActive }}
                  onPress={() => {
                    setSelectedCommit(null);
                    setChosenBranch(branch.name);
                  }}
                  className={`min-h-[36px] justify-center rounded-full border px-3 py-1.5 ${
                    isActive
                      ? "border-primary bg-primary/20"
                      : "border-border bg-secondary/20"
                  }`}
                >
                  <Text
                    className={`text-[11px] font-semibold ${
                      isActive ? "text-primary" : "text-muted-foreground"
                    }`}
                  >
                    {branch.name}
                    {branch.is_default ? " (default)" : ""}
                  </Text>
                </Pressable>
              );
            })}
          </ScrollView>
        </View>
      ) : null}

      <ScrollView
        testID="gitgraph-scroll"
        className="flex-1"
        contentContainerStyle={{ padding: 8 }}
      >
        {commits.length > 0 ? (
          <View className="flex-row" style={{ minHeight: layout.height }}>
            <Svg
              width={layout.width}
              height={layout.height}
              style={{ position: "absolute", left: 0, top: 0 }}
            >
              {layout.links.map((link, index) => (
                <Path
                  key={`link-${index}`}
                  d={link.path}
                  fill="none"
                  stroke={link.stroke}
                  strokeWidth={2}
                  opacity={0.6}
                />
              ))}
              {layout.nodes.map((node) => {
                const isSelected = selectedCommit?.sha === node.sha;
                return (
                  <Circle
                    key={`node-${node.sha}`}
                    cx={node.x}
                    cy={node.y}
                    r={isSelected ? 7.5 : 5}
                    fill={isSelected ? colors.primary : colors.background}
                    stroke={isSelected ? "#ffffff" : undefined}
                    strokeWidth={isSelected ? 2.5 : 2}
                  />
                );
              })}
            </Svg>

            <View
              className="flex-1"
              style={{ paddingLeft: layout.width + 4, paddingTop: 0 }}
            >
              {commits.map((commit) => (
                <View
                  key={commit.sha}
                  className="justify-center py-1"
                  style={{ minHeight: 64 }}
                >
                  <CommitCard
                    commit={commit}
                    selected={selectedCommit?.sha === commit.sha}
                    onPress={() => handleCommitPress(commit)}
                  />
                </View>
              ))}
            </View>
          </View>
        ) : !loadingCommits ? (
          <View className="items-center justify-center py-12">
            <Text className="text-sm italic text-muted-foreground">
              No commits found.
            </Text>
          </View>
        ) : null}
      </ScrollView>

      <View className="border-t border-border bg-secondary/10 px-4 py-3">
        <Text className="mb-2 text-[11px] text-muted-foreground">
          <Text>Target Selection: </Text>
          <Text className="font-mono font-bold text-primary">
            {selectedCommit
              ? `commit ${selectedCommit.short_sha} (${selectedCommit.branches[0]})`
              : `branch ${effectiveBranch} (default)`}
          </Text>
        </Text>

        <Pressable
          testID="gitgraph-ingest"
          accessibilityRole="button"
          accessibilityLabel={`Ingest ${selectedTarget}`}
          accessibilityState={{ disabled: isSubmitting || commits.length === 0 }}
          onPress={handleIngest}
          disabled={isSubmitting || commits.length === 0}
          className={`min-h-[44px] w-full flex-row items-center justify-center gap-2 rounded bg-primary px-5 py-2.5 ${
            isSubmitting || commits.length === 0 ? "opacity-50" : ""
          }`}
        >
          {isSubmitting ? (
            <ActivityIndicator size="small" color={colors.primaryForeground} />
          ) : null}
          <Text className="text-xs font-semibold text-primary-foreground">
            {isSubmitting ? "Ingesting..." : `Ingest ${selectedTarget}`}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

export default GitGraph;
