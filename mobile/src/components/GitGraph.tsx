/**
 * Unified commit timeline with branch lanes and ingest targeting.
 *
 * @module GitGraph
 *
 * Port of ``client/src/components/GitGraph.tsx`` to ``react-native-svg``.
 * The web version draws the lanes as an SVG beside a column of commit rows;
 * the same structure works here because the lane area and the rows live side
 * by side inside one vertical ``ScrollView``, so the lanes scroll with the
 * commits they belong to.
 *
 * What differs for the phone:
 *
 * - **Branch selection is explicit.** The legend in the timeline's header is
 *   a row of branch chips; tapping one chooses the branch whose tip is
 *   ingested. The web version only ever ingested the default branch, or
 *   whichever branch a pinned commit belonged to.
 * - **The box has a fixed height.** It is the same size while the history
 *   loads, once it has loaded and when it is empty, so the step does not
 *   jump around under the reader's thumb.
 * - **Two-line rows.** The web row is one line with the author on the right;
 *   a phone row puts the short SHA, the branch chips and the author on the
 *   first line and the message on the second.
 *
 * The lane geometry itself lives in :mod:`src.lib.gitGraphLayout` so it can
 * be tested without a renderer.
 */

import { useMemo, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import Svg, { Path, Rect } from "react-native-svg";

import { useGitGraph } from "@/hooks/useGitGraph";
import { PIXEL_FONT } from "@/lib/fonts";
import {
  ROW_HEIGHT,
  buildGitGraphLayout,
  getRailColor,
} from "@/lib/gitGraphLayout";
import { timeAgo } from "@/lib/timeAgo";
import { colors } from "@/theme/tokens";
import { Blink } from "@/ui/Blink";
import type { GitHubMultiBranchCommit } from "@/types/github";

/** Height of the timeline box, in points. It never changes. */
export const TIMELINE_HEIGHT = 360;

/** Side of a commit node, in points; the selected node is a little larger. */
const NODE_SIZE = 10;
const NODE_SIZE_SELECTED = 12;

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
  /** When given, a Back button in the footer returns to the repository list. */
  onBack?: () => void;
}

/** One branch in the legend, and the lane colour it is drawn in. */
interface LegendEntry {
  name: string;
  color: string;
  isDefault: boolean;
}

/**
 * One commit row: the short SHA, its branches and the author on one line,
 * the message on the next.
 *
 * @param props - The commit, its lane colour and the selection state.
 * @returns The row.
 */
function CommitRow({
  commit,
  color,
  selected,
  onPress,
}: {
  commit: GitHubMultiBranchCommit;
  color: string;
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
      style={{ height: ROW_HEIGHT }}
      className={`justify-center gap-1 pl-1 pr-3 ${
        selected ? "bg-secondary" : "active:bg-secondary"
      }`}
    >
      <View className="flex-row items-center gap-2 overflow-hidden">
        <Text
          className={`text-xs ${selected ? "text-foreground" : "text-muted-foreground"}`}
          style={{ fontFamily: PIXEL_FONT }}
        >
          {commit.short_sha}
        </Text>
        <View className="min-w-0 shrink flex-row items-center gap-1.5 overflow-hidden">
          {commit.branches.map((branch) => (
            <View
              key={branch}
              className="max-w-[120px] shrink-0 border px-1.5 py-0.5"
              style={{ borderColor: color }}
            >
              <Text
                numberOfLines={1}
                className="text-[10px]"
                style={{ fontFamily: PIXEL_FONT, color }}
              >
                {`⎇ ${branch}`}
              </Text>
            </View>
          ))}
        </View>
        <Text
          numberOfLines={1}
          className="ml-auto shrink text-[10px] text-subtle-foreground"
          style={{ fontFamily: PIXEL_FONT }}
        >
          {`${commit.author_name} · ${timeAgo(new Date(commit.authored_at))}`}
        </Text>
      </View>
      <Text numberOfLines={1} className="text-[13px] text-zinc-300">
        {commit.message}
      </Text>
    </Pressable>
  );
}

/**
 * Renders multi-branch history and reports the ingest target.
 *
 * Nothing is pinned at first, which means "the chosen branch at its tip";
 * tapping a commit pins that exact commit instead, and tapping it again
 * goes back to the tip.
 *
 * @param props - The repository, the selection callback and the footer
 *   options.
 * @returns The timeline box and the footer with the ingest action.
 */
export function GitGraph({
  owner,
  repo,
  onSelect,
  isSubmitting = false,
  onBack,
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

  // The branch the reader has chosen to ingest. A pinned commit overrides
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

  // Each branch the timeline shows, coloured by the lane its tip sits on;
  // branches the commit window does not reach follow, in a muted colour.
  const legend = useMemo<LegendEntry[]>(() => {
    const entries: LegendEntry[] = [];
    const seen = new Set<string>();
    const isDefault = (name: string) =>
      branches.some((branch) => branch.name === name && branch.is_default);
    commits.forEach((commit, row) => {
      for (const name of commit.branches) {
        if (seen.has(name)) continue;
        seen.add(name);
        entries.push({
          name,
          color: getRailColor(layout.tracks[row]),
          isDefault: isDefault(name),
        });
      }
    });
    for (const branch of branches) {
      if (seen.has(branch.name)) continue;
      entries.push({
        name: branch.name,
        color: colors.subtleForeground,
        isDefault: branch.is_default,
      });
    }
    return entries;
  }, [branches, commits, layout.tracks]);

  /**
   * Toggles the pin on a commit row.
   *
   * @param commit - Commit that was tapped.
   */
  const handleCommitPress = (commit: GitHubMultiBranchCommit) => {
    setSelectedCommit(selectedCommit?.sha === commit.sha ? null : commit);
  };

  /** Reports the selected target to the parent. */
  const handleIngest = () => {
    onSelect(effectiveBranch, selectedCommit?.sha ?? null);
  };

  const onBranch = selectedCommit?.branches[0];
  const targetLabel = selectedCommit
    ? `Ingest commit ${selectedCommit.short_sha}${onBranch ? ` on ${onBranch}` : ""} →`
    : `Ingest branch ${effectiveBranch} @ tip →`;

  const loading = loadingCommits || loadingBranches;
  const disabled = isSubmitting || commits.length === 0;

  return (
    <View>
      <View
        testID="gitgraph-box"
        className="overflow-hidden rounded-sm border border-border bg-background"
        style={{ height: TIMELINE_HEIGHT }}
      >
        <View className="gap-2 border-b border-border px-3.5 py-2.5">
          <Text
            className="text-[11px] uppercase tracking-[1.4px] text-muted-foreground"
            style={{ fontFamily: PIXEL_FONT }}
          >
            All branches · one timeline
          </Text>
          {legend.length > 0 ? (
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              accessibilityLabel="Branches"
              contentContainerStyle={{ gap: 6 }}
            >
              {legend.map(({ name, color, isDefault }) => {
                const active = effectiveBranch === name && !selectedCommit;
                return (
                  <Pressable
                    key={name}
                    testID={`gitgraph-branch-${name}`}
                    accessibilityRole="button"
                    accessibilityLabel={`Ingest branch ${name}`}
                    accessibilityState={{ selected: active }}
                    onPress={() => {
                      setSelectedCommit(null);
                      setChosenBranch(name);
                    }}
                    className="min-h-[32px] flex-row items-center gap-1.5 border px-2"
                    style={{
                      borderColor: active ? color : "transparent",
                      backgroundColor: active ? colors.secondary : undefined,
                    }}
                  >
                    <View
                      style={{ width: 8, height: 8, backgroundColor: color }}
                    />
                    <Text
                      className={`text-[11px] ${
                        active ? "text-foreground" : "text-muted-foreground"
                      }`}
                      style={{ fontFamily: PIXEL_FONT }}
                    >
                      {name}
                      {isDefault ? " (default)" : ""}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          ) : null}
        </View>

        {commits.length > 0 ? (
          <ScrollView
            testID="gitgraph-scroll"
            nestedScrollEnabled
            className="flex-1"
          >
            <View className="flex-row" style={{ minHeight: layout.height }}>
              <Svg
                width={layout.width}
                height={layout.height}
                style={{ flexShrink: 0 }}
              >
                {layout.links.map((link, index) => (
                  <Path
                    key={`link-${index}`}
                    d={link.path}
                    fill="none"
                    stroke={link.stroke}
                    strokeWidth={2}
                  />
                ))}
                {layout.nodes.map((node) => {
                  const on = selectedCommit?.sha === node.sha;
                  const size = on ? NODE_SIZE_SELECTED : NODE_SIZE;
                  const lane = getRailColor(node.column);
                  return (
                    <Rect
                      key={`node-${node.sha}`}
                      x={node.x - size / 2}
                      y={node.y - size / 2}
                      width={size}
                      height={size}
                      fill={on ? colors.foreground : lane}
                      stroke={lane}
                      strokeWidth={2}
                    />
                  );
                })}
              </Svg>

              <View className="min-w-0 flex-1">
                {commits.map((commit, row) => (
                  <CommitRow
                    key={commit.sha}
                    commit={commit}
                    color={getRailColor(layout.tracks[row])}
                    selected={selectedCommit?.sha === commit.sha}
                    onPress={() => handleCommitPress(commit)}
                  />
                ))}
              </View>
            </View>
          </ScrollView>
        ) : (
          <View className="flex-1 items-center justify-center px-4">
            {error ? (
              <Text
                accessibilityRole="alert"
                className="text-center text-xs text-red-300"
              >
                {error}
              </Text>
            ) : loading ? (
              <Blink testID="gitgraph-loading">
                <Text
                  className="text-center text-xs uppercase tracking-[1.4px] text-muted-foreground"
                  style={{ fontFamily: PIXEL_FONT }}
                >
                  Loading history
                </Text>
              </Blink>
            ) : (
              <Text
                className="text-center text-xs uppercase text-faint-foreground"
                style={{ fontFamily: PIXEL_FONT }}
              >
                No commits found
              </Text>
            )}
          </View>
        )}
      </View>

      <View className="flex-row items-center justify-between gap-3 pt-4">
        {onBack ? (
          <Pressable
            testID="gitgraph-back"
            accessibilityRole="button"
            accessibilityLabel="Back to repository list"
            onPress={onBack}
            className="min-h-[44px] justify-center rounded-sm border border-input px-3.5 active:bg-secondary"
          >
            <Text
              className="text-xs uppercase text-zinc-300"
              style={{ fontFamily: PIXEL_FONT }}
            >
              ← Back
            </Text>
          </Pressable>
        ) : null}

        <Pressable
          testID="gitgraph-ingest"
          accessibilityRole="button"
          accessibilityLabel={targetLabel.replace(" →", "")}
          accessibilityState={{ disabled, busy: isSubmitting }}
          onPress={handleIngest}
          disabled={disabled}
          className={`min-h-[44px] shrink flex-row items-center justify-center rounded-sm bg-primary px-4 active:opacity-80 ${
            onBack ? "" : "flex-1"
          } ${disabled ? "opacity-50" : ""}`}
        >
          <Text
            numberOfLines={1}
            className="text-[13px] text-primary-foreground"
            style={{ fontFamily: PIXEL_FONT }}
          >
            {isSubmitting ? "Ingesting..." : targetLabel}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

export default GitGraph;
