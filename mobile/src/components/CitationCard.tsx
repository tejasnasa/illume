/**
 * Expandable citation card for a single RAG source.
 *
 * @module CitationCard
 *
 * Port of ``client/src/components/ui/CitationCard.tsx``.
 *
 * The web card is a two-column grid entry with an icon, a headline, a
 * sub-label, a link out to GitHub and a disclosure that reveals the chunk
 * of text the citation was built from. On a phone the cards are one per
 * row, so the chunk has room to breathe.
 *
 * The link out to GitHub follows the same commit-pinned rule as the web
 * client: see :func:`resolveGithubHref`.
 */

import { useState } from "react";
import { Linking, Pressable, Text, View } from "react-native";

import type { ChatSource } from "@/types/chat";
import { colors } from "@/theme/tokens";

/**
 * The branch used when the repository does not record one.
 *
 * A repository is normally ingested from its default branch, and the
 * backend stores that branch in ``ingested_branch``; the fallback only
 * applies to a repository whose branch was never recorded.
 */
export const DEFAULT_SOURCE_BRANCH = "master";

/** The source kinds the card knows how to dress. */
export type CitationSourceType =
  | "symbol"
  | "commit"
  | "pull_request"
  | "file"
  | "document";

/**
 * How a source kind is drawn.
 */
interface TypeConfig {
  /** The glyph shown in the badge. */
  glyph: string;
  /** The colour of the glyph. */
  color: string;
  /** The name shown to the reader. */
  label: string;
}

/**
 * The badge and the name of every source kind.
 *
 * The web card uses a yellow, a purple and two pinks; the mobile palette
 * has no yellow and no purple, so the kinds are spread across the chart
 * ramp and the two accent colours instead.
 */
const TYPE_CONFIG: Record<CitationSourceType, TypeConfig> = {
  symbol: { glyph: "ƒ", color: colors.chart1, label: "Symbol" },
  commit: { glyph: "●", color: colors.chart2, label: "Commit" },
  pull_request: { glyph: "⇄", color: colors.chart4, label: "Pull Request" },
  file: { glyph: "▤", color: colors.destructive, label: "File" },
  document: { glyph: "≡", color: colors.success, label: "File" },
};

/**
 * Normalise a raw source type to one the card knows.
 *
 * @param src - The citation source to classify.
 * @returns The matching source type, or ``document`` for an unknown one.
 */
function resolveType(src: ChatSource): CitationSourceType {
  return ["symbol", "commit", "pull_request", "file"].includes(
    src.source_type as CitationSourceType,
  )
    ? (src.source_type as CitationSourceType)
    : "document";
}

/**
 * The headline of a citation.
 *
 * @param type - The normalised source type.
 * @param src - The citation source.
 * @returns The label shown on the card.
 */
function resolvePrimaryLabel(
  type: CitationSourceType,
  src: ChatSource,
): string {
  switch (type) {
    case "symbol":
      return src.symbol_name && src.symbol_name !== "<anonymous>"
        ? src.symbol_name
        : "";
    case "commit":
      return src.commit_hash
        ? src.commit_hash.slice(0, 7)
        : (src.author_name ?? "");
    case "pull_request":
      return `PR #${src.pr_number}`;
    case "file":
      return src.file_path ? src.file_path.split("/").pop() ?? "File" : "File";
    case "document":
      return src.file_path
        ? src.file_path.split("/").pop() ?? "Source"
        : "Source";
  }
}

/**
 * The sub-label of a citation.
 *
 * @param type - The normalised source type.
 * @param src - The citation source.
 * @returns The label shown under the headline.
 */
function resolveSubLabel(
  type: CitationSourceType,
  src: ChatSource,
): string {
  switch (type) {
    case "symbol":
      return src.file_path ?? "";
    case "commit":
      return src.author_name ? `by ${src.author_name}` : "";
    case "pull_request":
      return src.pr_title ?? "";
    case "file":
      return src.file_path ?? "";
    case "document":
      return src.file_path ?? "";
  }
}

/**
 * Build the GitHub link for a citation, when one applies.
 *
 * The link pins to the commit the repository was ingested at, because that
 * is the snapshot the answer was grounded in -- a branch link drifts as the
 * branch moves. The branch is the fallback for a repository ingested before
 * the commit watermark was recorded, and ``master`` is the last resort for a
 * row that records neither.
 *
 * The line anchor is only added for a symbol whose range is known; the
 * web client appends it unconditionally, which produces a
 * ``#Lnull-Lnull`` fragment for a source that carries no line numbers.
 *
 * @param src - The citation source.
 * @param url - The repository's GitHub URL.
 * @param branch - The branch the repository was ingested from.
 * @param commitSha - The commit the repository was ingested at.
 * @returns The GitHub URL, or ``null`` when the kind has no link target.
 */
export function resolveGithubHref(
  src: ChatSource,
  url: string,
  branch?: string | null,
  commitSha?: string | null,
): string | null {
  const ref =
    commitSha && commitSha.length > 0
      ? commitSha
      : branch && branch.length > 0
        ? branch
        : DEFAULT_SOURCE_BRANCH;
  const base = url.replace(/\/+$/, "");

  if (src.source_type === "symbol") {
    const anchor =
      typeof src.start_line === "number" && typeof src.end_line === "number"
        ? `#L${src.start_line}-L${src.end_line}`
        : "";
    return `${base}/blob/${ref}/${src.file_path ?? ""}${anchor}`;
  }
  if (src.source_type === "file") {
    return `${base}/blob/${ref}/${src.file_path ?? ""}`;
  }
  if (src.source_type === "commit") {
    return `${base}/commit/${src.commit_hash ?? ""}`;
  }
  if (src.source_type === "pull_request") {
    return `${base}/pull/${src.pr_number ?? ""}`;
  }
  return null;
}

/** Props for the {@link CitationCard} component. */
export interface CitationCardProps {
  /** The citation source to display. */
  src: ChatSource;
  /** The repository's GitHub URL; the source link is built from it. */
  url: string;
  /**
   * The commit the repository was ingested at.
   *
   * Preferred over ``branch`` so the link cannot drift after the branch
   * moves. Falls back to the branch, then ``master``, when absent.
   */
  commitSha?: string | null;
  /** The branch the repository was ingested from; the fallback ref. */
  branch?: string | null;
  /** Test hook. */
  testID?: string;
}

/**
 * Draw one citation.
 *
 * @param props - The source, the repository's URL, commit and branch.
 * @returns The rendered card.
 */
export function CitationCard({
  src,
  url,
  commitSha,
  branch,
  testID = "citation-card",
}: CitationCardProps) {
  const [expanded, setExpanded] = useState(false);

  const type = resolveType(src);
  const config = TYPE_CONFIG[type];
  const primary = resolvePrimaryLabel(type, src);
  const sub = resolveSubLabel(type, src);
  const href = resolveGithubHref(src, url, branch, commitSha);

  const toggle = () => setExpanded((value) => !value);

  return (
    <View
      testID={testID}
      className="mb-2 overflow-hidden rounded border border-border bg-secondary/20"
    >
      <View className="flex-row items-center">
        <Pressable
          testID={`${testID}-toggle`}
          accessibilityRole="button"
          accessibilityLabel={`${config.label} citation${primary ? `: ${primary}` : ""}`}
          accessibilityState={{ expanded }}
          onPress={toggle}
          className="min-h-[44px] flex-1 flex-row items-center px-2 py-1.5 active:bg-secondary"
        >
          <View
            className="mr-2 h-6 w-6 items-center justify-center rounded"
            style={{ backgroundColor: `${config.color}1a` }}
          >
            <Text className="text-[11px] font-bold" style={{ color: config.color }}>
              {config.glyph}
            </Text>
          </View>

          <View className="flex-1">
            <Text
              testID={`${testID}-title`}
              className="text-xs font-bold text-foreground"
              numberOfLines={1}
            >
              {primary}
            </Text>
            {sub ? (
              <Text
                testID={`${testID}-subtitle`}
                className="mt-0.5 text-[10px] text-muted-foreground"
                numberOfLines={1}
              >
                {sub}
              </Text>
            ) : null}
          </View>
        </Pressable>

        {href ? (
          <Pressable
            testID={`${testID}-github`}
            accessibilityRole="link"
            accessibilityLabel={`View ${primary || config.label} on GitHub`}
            onPress={() => void Linking.openURL(href)}
            hitSlop={8}
            className="rounded p-2 active:bg-secondary"
          >
            <Text className="text-sm text-muted-foreground">◈</Text>
          </Pressable>
        ) : null}

        <Pressable
          testID={`${testID}-caret`}
          accessibilityRole="button"
          accessibilityLabel={expanded ? "Hide source text" : "Show source text"}
          accessibilityState={{ expanded }}
          onPress={toggle}
          hitSlop={8}
          className="rounded p-2 active:bg-secondary"
        >
          <Text className="text-xs text-muted-foreground">
            {expanded ? "⌃" : "⌄"}
          </Text>
        </Pressable>
      </View>

      {expanded && src.chunk_text ? (
        <View className="border-t border-border p-2">
          <Text
            testID={`${testID}-chunk`}
            className="rounded border border-border bg-secondary/40 p-2 font-mono text-[10px] leading-[14px] text-muted-foreground"
          >
            {src.chunk_text}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

export default CitationCard;
