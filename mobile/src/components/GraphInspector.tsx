/**
 * The inspector for a picked graph node.
 *
 * @module GraphInspector
 *
 * Port of ``client/src/components/ui/GraphCard.tsx``. On the web this is a
 * floating card in the corner of the canvas. On a phone the corner belongs
 * to the graph, and a card over the graph hides the thing the reader just
 * tapped, so the inspector is a sheet that rises from the bottom edge.
 *
 * It shows the file directory and name, its risk and language, how many
 * files import it and how many it imports, the reading-order note, and
 * lists of both neighbours that select the neighbour when tapped. The
 * actions ask the chat about the file, open it in the explorer, or open it
 * on GitHub.
 */

import { useState } from "react";
import { Linking, Pressable, ScrollView, Text, View } from "react-native";

import type { GraphLevel } from "@/api/graph";
import type { Neighbour } from "@/lib/graphSelection";
import type { GraphNodeMeta } from "@/lib/graphTypes";
import { colors } from "@/theme/tokens";

/** How many importers are listed before the rest fold behind a toggle. */
export const IMPORTERS_PREVIEW = 2;

/** How many imports are listed. */
const IMPORTS_LIMIT = 8;

/** Props for the {@link GraphInspector} component. */
export interface GraphInspectorProps {
  /** The picked node, or null when nothing is picked. */
  node: GraphNodeMeta | null;
  /** The level the graph is drawn at. */
  level: GraphLevel;
  /** The repository GitHub URL, without a trailing slash. */
  githubUrl: string;
  /** The branch the repository was ingested from. */
  branch: string | null;
  /** The commit the repository was ingested at; the GitHub link pins to it. */
  commitSha?: string | null;
  /** The reading-order note for this file, when there is one. */
  annotation?: string | null;
  /** One-based reading-order position, when the file has one. */
  tourPosition?: number | null;
  /** Nodes that depend on the picked one. */
  importers?: Neighbour[];
  /** Nodes the picked one depends on. */
  imports?: Neighbour[];
  /** Selects a neighbour. */
  onSelectNode?: (id: string) => void;
  /** Asks the chat about the file. */
  onAsk?: () => void;
  /** Opens the file in the explorer. */
  onOpenExplorer?: () => void;
  /** Called when the reader closes the sheet. */
  onClose: () => void;
}

/**
 * The colour a criticality badge is drawn in.
 *
 * @param criticality - The bucket name.
 * @returns A hex colour.
 */
function criticalityTone(criticality: string | null | undefined): string {
  if (criticality === "critical") return colors.destructive;
  if (criticality === "caution") return colors.warning;
  return colors.success;
}

/**
 * Split a path into its directory (with trailing slash) and base name.
 *
 * @param path - A repository-relative path.
 * @returns The directory prefix and the final segment.
 */
export function splitPath(path: string): { dir: string; base: string } {
  const cut = path.lastIndexOf("/");
  return cut === -1
    ? { dir: "", base: path }
    : { dir: path.slice(0, cut + 1), base: path.slice(cut + 1) };
}

/**
 * Build the GitHub link to a file.
 *
 * The ref is the commit the repository was ingested at when it is known, so
 * the link cannot drift after the branch moves; otherwise the branch, and
 * ``master`` only when the record has neither.
 *
 * @param githubUrl - The repository GitHub URL.
 * @param path - The file path in the repository.
 * @param branch - The branch the repository was ingested from.
 * @param commitSha - The ingested commit, when known.
 * @returns The absolute URL.
 */
export function buildGraphSourceUrl(
  githubUrl: string,
  path: string,
  branch: string | null,
  commitSha?: string | null,
): string {
  const base = githubUrl.replace(/\/+$/, "");
  const ref = commitSha || (branch && branch.length > 0 ? branch : "master");
  const encoded = path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
  return `${base}/blob/${ref}/${encoded}`;
}

/** A tappable neighbour row. */
function NeighbourRow({
  prefix,
  item,
  onPress,
}: {
  prefix: string;
  item: Neighbour;
  onPress?: (id: string) => void;
}) {
  return (
    <Pressable
      testID={`graph-neighbour-${item.id}`}
      accessibilityRole="button"
      onPress={() => onPress?.(item.id)}
      className="min-h-[36px] justify-center rounded-sm px-2 active:bg-secondary"
    >
      <Text numberOfLines={1} className="font-pixel text-xs text-zinc-300">
        {prefix} {item.text}
      </Text>
    </Pressable>
  );
}

/**
 * Render the inspector.
 *
 * @param props - The picked node and the repository it belongs to.
 * @returns The sheet, or nothing when no node is picked.
 */
export function GraphInspector({
  node,
  level,
  githubUrl,
  branch,
  commitSha,
  annotation,
  tourPosition,
  importers = [],
  imports = [],
  onSelectNode,
  onAsk,
  onOpenExplorer,
  onClose,
}: GraphInspectorProps) {
  const [showAll, setShowAll] = useState(false);
  if (!node) return null;

  const isFile = level === "file";
  const href = buildGraphSourceUrl(githubUrl, node.path, branch, commitSha);
  const { dir, base } = splitPath(node.path);
  const tone = criticalityTone(node.criticality);
  const hidden = Math.max(0, importers.length - IMPORTERS_PREVIEW);
  const visibleImporters = showAll
    ? importers
    : importers.slice(0, IMPORTERS_PREVIEW);

  return (
    <View testID="graph-inspector" style={styles.root}>
      <View style={styles.grabber} />

      <View className="flex-row items-start justify-between px-4 pb-2">
        <View className="min-w-0 flex-1 pr-3">
          {isFile && dir ? (
            <Text
              numberOfLines={1}
              className="font-pixel text-[11px] tracking-[1px] text-subtle-foreground"
            >
              {dir}
            </Text>
          ) : null}
          <Text
            testID="graph-inspector-label"
            className="font-pixel text-[20px] leading-[24px] text-foreground"
          >
            {isFile ? base : node.label}
          </Text>
        </View>
        <Pressable
          testID="graph-inspector-close"
          accessibilityRole="button"
          accessibilityLabel="Close"
          onPress={onClose}
          hitSlop={8}
          className="rounded-sm border border-border px-2 py-1 active:border-accent"
        >
          <Text className="font-pixel text-base text-muted-foreground">✕</Text>
        </Pressable>
      </View>

      <View className="flex-row flex-wrap items-center gap-1.5 px-4 pb-3">
        <View
          className="rounded-sm border px-2 py-1"
          style={{ borderColor: `${tone}80` }}
        >
          <Text
            className="font-pixel text-[11px] uppercase tracking-[1px]"
            style={{ color: tone }}
          >
            {node.criticality || "safe"}
          </Text>
        </View>
        {node.language ? (
          <View className="rounded-sm border border-border px-2 py-1">
            <Text className="font-pixel text-[11px] uppercase tracking-[1px] text-muted-foreground">
              {node.language}
            </Text>
          </View>
        ) : null}
        {isFile && node.loc != null ? (
          <View className="rounded-sm border border-border px-2 py-1">
            <Text className="font-pixel text-[11px] uppercase tracking-[1px] text-muted-foreground">
              {node.loc} lines
            </Text>
          </View>
        ) : null}
        {tourPosition != null ? (
          <View className="rounded-sm border border-accent/50 px-2 py-1">
            <Text className="font-pixel text-[11px] uppercase tracking-[1px] text-accent">
              Read #{tourPosition}
            </Text>
          </View>
        ) : null}
      </View>

      <ScrollView
        contentContainerStyle={{
          paddingHorizontal: 16,
          paddingBottom: 16,
          gap: 14,
        }}
        style={{ maxHeight: 340 }}
      >
        <Text className="font-pixel text-xs text-muted-foreground">
          {node.path}
        </Text>

        <View className="flex-row gap-2">
          <View className="flex-1 rounded-sm border border-border p-2.5">
            <Text
              testID="graph-inspector-importers"
              className="font-pixel text-2xl text-foreground"
            >
              {importers.length}
            </Text>
            <Text className="font-pixel text-[10px] uppercase tracking-[1px] text-subtle-foreground">
              Imported by
            </Text>
          </View>
          <View className="flex-1 rounded-sm border border-border p-2.5">
            <Text
              testID="graph-inspector-imports"
              className="font-pixel text-2xl text-foreground"
            >
              {imports.length}
            </Text>
            <Text className="font-pixel text-[10px] uppercase tracking-[1px] text-subtle-foreground">
              Imports
            </Text>
          </View>
        </View>

        {annotation ? (
          <Text className="border-l-2 border-accent bg-accent/5 px-3 py-2.5 text-[13px] leading-[19px] text-zinc-300">
            {annotation}
          </Text>
        ) : null}

        {importers.length > 0 ? (
          <View>
            <Text className="px-2 font-pixel text-[11px] uppercase text-faint-foreground">
              Imported by
            </Text>
            {visibleImporters.map((item) => (
              <NeighbourRow
                key={item.id}
                prefix="←"
                item={item}
                onPress={onSelectNode}
              />
            ))}
            {hidden > 0 ? (
              <Pressable
                testID="graph-importers-toggle"
                accessibilityRole="button"
                onPress={() => setShowAll((v) => !v)}
                className="min-h-[36px] justify-center px-2"
              >
                <Text className="font-pixel text-[11px] uppercase text-subtle-foreground">
                  {showAll ? "Show fewer" : `Show ${hidden} more`}
                </Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}

        {imports.length > 0 ? (
          <View>
            <Text className="px-2 font-pixel text-[11px] uppercase text-faint-foreground">
              Imports
            </Text>
            {imports.slice(0, IMPORTS_LIMIT).map((item) => (
              <NeighbourRow
                key={item.id}
                prefix="→"
                item={item}
                onPress={onSelectNode}
              />
            ))}
            {imports.length > IMPORTS_LIMIT ? (
              <Text className="px-2 pt-1 font-pixel text-[11px] uppercase text-faint-foreground">
                and {imports.length - IMPORTS_LIMIT} more
              </Text>
            ) : null}
          </View>
        ) : null}

        {isFile && onAsk ? (
          <Pressable
            testID="graph-inspector-ask"
            accessibilityRole="button"
            onPress={onAsk}
            className="min-h-[44px] items-center justify-center rounded-sm bg-primary px-4"
          >
            <Text className="font-pixel text-[13px] text-primary-foreground">
              Ask about this file
            </Text>
          </Pressable>
        ) : null}
        <View className="flex-row gap-2">
          {isFile && onOpenExplorer ? (
            <Pressable
              testID="graph-inspector-explorer"
              accessibilityRole="button"
              onPress={onOpenExplorer}
              className="min-h-[44px] flex-1 items-center justify-center rounded-sm border border-input"
            >
              <Text className="font-pixel text-xs uppercase text-zinc-300">
                Explorer
              </Text>
            </Pressable>
          ) : null}
          <Pressable
            testID="graph-inspector-github"
            accessibilityRole="link"
            accessibilityLabel={`Open ${node.label} on GitHub`}
            onPress={() => void Linking.openURL(href)}
            className="min-h-[44px] flex-1 items-center justify-center rounded-sm border border-input"
          >
            <Text className="font-pixel text-xs uppercase text-zinc-300">
              GitHub
            </Text>
          </Pressable>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = {
  root: {
    position: "absolute" as const,
    left: 0,
    right: 0,
    bottom: 0,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    borderTopLeftRadius: 6,
    borderTopRightRadius: 6,
    backgroundColor: colors.card,
    paddingTop: 6,
  },
  grabber: {
    alignSelf: "center" as const,
    width: 36,
    height: 4,
    marginBottom: 6,
    backgroundColor: colors.borderStrong,
  },
};

export default GraphInspector;
