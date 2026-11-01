/**
 * The inspector for a picked graph node.
 *
 * @module GraphInspector
 *
 * On the web this is a floating card in the corner of the canvas. On a
 * phone the corner belongs to the graph, and a card over the graph hides
 * the thing the reader just tapped, so the inspector is a sheet that
 * rises from the bottom edge.
 *
 * It shows the same fields the web card does, and the same GitHub link.
 */

import { Linking, Pressable, ScrollView, Text, View } from "react-native";

import type { GraphLevel } from "@/api/graph";
import type { GraphNodeMeta } from "@/lib/graphTypes";
import { colors } from "@/theme/tokens";

/** Props for the {@link GraphInspector} component. */
export interface GraphInspectorProps {
  /** The picked node, or null when nothing is picked. */
  node: GraphNodeMeta | null;
  /** The level the graph is drawn at. */
  level: GraphLevel;
  /** The repository's GitHub URL, without a trailing slash. */
  githubUrl: string;
  /** The branch the repository was ingested from. */
  branch: string | null;
  /** The reading-order note for this file, when there is one. */
  annotation?: string | null;
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
  if (criticality === "critical") return "#ef4444";
  if (criticality === "caution") return "#facc15";
  return "#22c55e";
}

/**
 * Build the GitHub link to a file.
 *
 * The branch is the one the repository was ingested from. It falls back to
 * ``master`` only when the record has no branch, which is the one case
 * where there is nothing better to guess.
 *
 * @param githubUrl - The repository's GitHub URL.
 * @param path - The file's path in the repository.
 * @param branch - The branch the repository was ingested from.
 * @returns The absolute URL.
 */
export function buildGraphSourceUrl(
  githubUrl: string,
  path: string,
  branch: string | null,
): string {
  const base = githubUrl.replace(/\/+$/, "");
  const ref = branch && branch.length > 0 ? branch : "master";
  const encoded = path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
  return `${base}/blob/${ref}/${encoded}`;
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
  annotation,
  onClose,
}: GraphInspectorProps) {
  if (!node) return null;

  const href = buildGraphSourceUrl(githubUrl, node.path, branch);

  return (
    <View testID="graph-inspector" style={styles.root}>
      <View style={styles.grabber} />

      <View className="flex-row items-start justify-between px-4 pb-2">
        <Text
          testID="graph-inspector-label"
          className="flex-1 pr-3 text-base font-bold text-foreground"
          numberOfLines={2}
        >
          {node.label}
        </Text>
        <Pressable
          testID="graph-inspector-close"
          accessibilityRole="button"
          accessibilityLabel="Close the inspector"
          onPress={onClose}
          hitSlop={10}
          className="rounded px-2 py-1 active:bg-secondary"
        >
          <Text className="text-base text-muted-foreground">✕</Text>
        </Pressable>
      </View>

      <View className="flex-row flex-wrap items-center gap-2 px-4 pb-3">
        <View className="rounded border border-border bg-secondary/40 px-2 py-0.5">
          <Text className="text-[10px] font-bold uppercase tracking-widest text-foreground">
            {node.kind || level}
          </Text>
        </View>
        {node.criticality ? (
          <View
            className="rounded border px-2 py-0.5"
            style={{
              borderColor: `${criticalityTone(node.criticality)}33`,
              backgroundColor: `${criticalityTone(node.criticality)}1a`,
            }}
          >
            <Text
              className="text-[10px] font-bold uppercase tracking-wider"
              style={{ color: criticalityTone(node.criticality) }}
            >
              {node.criticality}
            </Text>
          </View>
        ) : null}
      </View>

      <ScrollView
        className="max-h-[46vh]"
        contentContainerClassName="px-4 pb-4"
      >
        <Text className="mb-1 text-xs text-muted-foreground">Full path</Text>
        <View className="mb-3 rounded border border-border bg-secondary/30 p-2">
          <Text className="font-mono text-xs text-muted-foreground">
            {node.path}
          </Text>
        </View>

        {node.group ? (
          <View className="mb-3">
            <Text className="mb-1 text-xs text-muted-foreground">
              Directory group
            </Text>
            <Text className="text-sm text-foreground">{node.group}</Text>
          </View>
        ) : null}

        <View className="mb-3 flex-row flex-wrap gap-2">
          <View className="min-w-[80px] flex-1 rounded border border-border bg-secondary/30 p-2">
            <Text className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Lines of code
            </Text>
            <Text className="font-mono text-base font-semibold text-foreground">
              {node.loc || 0}
            </Text>
          </View>

          {/* The symbol level carries no language, fan-in or fan-out, so
              these are only drawn at the file level. */}
          {level === "file" ? (
            <>
              <View className="min-w-[80px] flex-1 rounded border border-border bg-secondary/30 p-2">
                <Text className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Fan in
                </Text>
                <Text className="font-mono text-base font-semibold text-foreground">
                  {node.fan_in ?? 0}
                </Text>
              </View>
              <View className="min-w-[80px] flex-1 rounded border border-border bg-secondary/30 p-2">
                <Text className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Fan out
                </Text>
                <Text className="font-mono text-base font-semibold text-foreground">
                  {node.fan_out ?? 0}
                </Text>
              </View>
            </>
          ) : null}

          {level === "file" && node.language ? (
            <View className="min-w-[80px] flex-1 rounded border border-border bg-secondary/30 p-2">
              <Text className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Language
              </Text>
              <Text
                className="font-mono text-sm font-semibold text-foreground"
                numberOfLines={1}
              >
                {node.language}
              </Text>
            </View>
          ) : null}

          {/* The server sends complexity on symbol nodes only. */}
          {level === "symbol" && typeof node.complexity === "number" ? (
            <View className="min-w-[80px] flex-1 rounded border border-border bg-secondary/30 p-2">
              <Text className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Complexity
              </Text>
              <Text className="font-mono text-base font-semibold text-foreground">
                {node.complexity}
              </Text>
            </View>
          ) : null}
        </View>

        {annotation && level === "file" ? (
          <View className="mb-3 border-t border-border pt-3">
            <Text className="text-sm text-muted-foreground">
              Note: {annotation}
            </Text>
          </View>
        ) : null}

        <Pressable
          testID="graph-inspector-github"
          accessibilityRole="link"
          accessibilityLabel={`Open ${node.label} on GitHub`}
          onPress={() => void Linking.openURL(href)}
          className="min-h-[44px] items-center justify-center rounded bg-foreground px-4 py-2.5"
        >
          <Text className="text-xs font-bold uppercase text-background">
            View on GitHub
          </Text>
        </Pressable>
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
    borderTopLeftRadius: 12,
    borderTopRightRadius: 12,
    backgroundColor: colors.card,
    paddingTop: 6,
  },
  grabber: {
    alignSelf: "center" as const,
    width: 36,
    height: 4,
    borderRadius: 2,
    marginBottom: 6,
    backgroundColor: colors.border,
  },
};

export default GraphInspector;
