/**
 * The detail card for the selected file.
 *
 * @module FileDetailCard
 *
 * Port of ``client/src/components/ui/FileDetailCard.tsx``.
 *
 * The web card is a slide-in panel that carries the file's metadata *and*
 * its ownership breakdown. On a phone the two belong to different places:
 * the metadata stays with the file, and the ownership moves into its own
 * panel (:component:`OwnershipPanel`) further down the screen. What is
 * left here is the identity of the file -- where it lives, what it is
 * made of, how connected it is, and how worried the guardrails are about
 * it -- plus the link out to the source.
 *
 * The source link is the one place this client deliberately diverges from
 * the web: see :func:`buildFileSourceUrl`.
 */

import { Linking, Pressable, Text, View } from "react-native";

import type { FileNode } from "@/types/explorer";
import { colors } from "@/theme/tokens";

/**
 * The branch used when the repository does not record one.
 *
 * A repository is normally ingested from its default branch, and the
 * backend stores that branch in ``ingested_branch``; the fallback only
 * applies to a repository whose branch was never recorded.
 */
export const DEFAULT_SOURCE_BRANCH = "master";

/**
 * Props for the {@link FileDetailCard} component.
 */
export interface FileDetailCardProps {
  /** The file being inspected. */
  file: FileNode;
  /** The repository's GitHub URL. The source link is built from it. */
  githubUrl: string;
  /**
   * The branch the repository was ingested from.
   *
   * The web client hard-codes ``master`` in this link
   * (``client/src/components/ui/FileDetailCard.tsx``), which makes it a
   * dead button for a repository ingested from ``main`` -- or from any
   * other branch. The mobile client uses the branch the repository was
   * actually indexed at, and only falls back to ``master`` when the
   * repository does not record one.
   */
  branch?: string | null;
  /** Called when the reader dismisses the card. */
  onClose?: () => void;
  /** Test hook. */
  testID?: string;
}

/**
 * The colours a criticality band is drawn in.
 *
 * @param criticality - The file's criticality band.
 * @returns The text, background and border colours.
 */
function criticalityTone(criticality: string): {
  color: string;
  background: string;
  border: string;
} {
  switch ((criticality ?? "").toLowerCase()) {
    case "critical":
      return {
        color: colors.destructive,
        background: `${colors.destructive}1a`,
        border: `${colors.destructive}33`,
      };
    case "caution":
      return {
        color: colors.chart2,
        background: `${colors.chart2}1a`,
        border: `${colors.chart2}33`,
      };
    default:
      return {
        color: colors.success,
        background: `${colors.success}1a`,
        border: `${colors.success}33`,
      };
  }
}

/**
 * Build the GitHub URL for a file in the ingested branch.
 *
 * The branch is the one the repository was indexed at rather than a
 * hard-coded ``master``: the web client links to ``master``
 * unconditionally, so a repository ingested from ``main`` gets a 404 the
 * moment anybody taps the link. The fallback to ``master`` only applies
 * when the repository does not record a branch at all.
 *
 * The path is escaped segment by segment, so a file whose name contains a
 * space or a ``#`` still produces a link GitHub can resolve. The branch is
 * left as it is -- GitHub's own URLs put a slashed branch name in the
 * path unescaped, and escaping the separator would break it.
 *
 * @param githubUrl - The repository's GitHub URL.
 * @param filePath - The file's repository-relative path.
 * @param branch - The branch the repository was ingested from.
 * @returns The absolute URL of the file on GitHub.
 */
export function buildFileSourceUrl(
  githubUrl: string,
  filePath: string,
  branch?: string | null,
): string {
  const base = githubUrl.replace(/\/+$/, "");
  const ref =
    branch && branch.length > 0 ? branch : DEFAULT_SOURCE_BRANCH;
  const path = filePath
    .split("/")
    .filter((segment) => segment.length > 0)
    .map(encodeURIComponent)
    .join("/");

  return `${base}/blob/${ref}/${path}`;
}

/**
 * A small labelled pill.
 */
function Badge({
  label,
  testID,
  tone,
}: {
  /** The text inside the pill. */
  label: string;
  /** Test hook. */
  testID?: string;
  /** The colours to draw the pill in. */
  tone?: { color: string; background: string; border: string };
}) {
  return (
    <View
      testID={testID}
      className="rounded border px-2 py-0.5"
      style={{
        borderColor: tone?.border ?? colors.border,
        backgroundColor: tone?.background ?? colors.secondary,
      }}
    >
      <Text
        className="text-[10px] font-bold uppercase tracking-wider"
        style={{ color: tone?.color ?? colors.mutedForeground }}
      >
        {label}
      </Text>
    </View>
  );
}

/**
 * A labelled number.
 */
function Stat({
  label,
  value,
  testID,
}: {
  /** The name of the number. */
  label: string;
  /** The number itself. */
  value: number | string;
  /** Test hook. */
  testID?: string;
}) {
  return (
    <View className="mr-4 flex-1">
      <Text className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </Text>
      <Text testID={testID} className="text-lg font-bold text-foreground">
        {value}
      </Text>
    </View>
  );
}

/**
 * Draw the detail card for a file.
 *
 * @param props - The file, the repository's URL and branch, and the handler.
 * @returns The rendered card.
 */
export function FileDetailCard({
  file,
  githubUrl,
  branch,
  onClose,
  testID = "file-detail",
}: FileDetailCardProps) {
  const sourceUrl = buildFileSourceUrl(githubUrl, file.path, branch);
  const tone = criticalityTone(file.criticality);

  return (
    <View
      testID={testID}
      className="mb-3 rounded border border-border bg-card p-4"
    >
      <View className="mb-3 flex-row items-start justify-between">
        <View className="mr-2 flex-1 flex-row items-center">
          <Text className="mr-2 text-lg text-primary">▤</Text>
          <Text
            testID="file-detail-label"
            className="flex-1 text-base font-bold text-foreground"
            numberOfLines={2}
          >
            {file.label}
          </Text>
        </View>
        {onClose ? (
          <Pressable
            testID="file-detail-close"
            accessibilityRole="button"
            accessibilityLabel="Close file details"
            onPress={onClose}
            hitSlop={8}
            className="rounded p-2 active:bg-secondary"
          >
            <Text className="text-base text-muted-foreground">✕</Text>
          </Pressable>
        ) : null}
      </View>

      <View className="mb-3 flex-row flex-wrap" testID="file-detail-badges">
        <View className="mr-1.5 mb-1.5">
          <Badge
            label={file.language || "unknown"}
            testID="file-detail-language"
          />
        </View>
        <View className="mr-1.5 mb-1.5">
          <Badge label={file.kind || "file"} testID="file-detail-kind" />
        </View>
        <View className="mb-1.5">
          <Badge
            label={file.criticality || "unknown"}
            testID="file-detail-criticality"
            tone={tone}
          />
        </View>
      </View>

      <Text
        testID="file-detail-path"
        className="mb-3 rounded border border-border bg-secondary/40 p-2 font-mono text-[11px] text-muted-foreground"
      >
        {file.path}
      </Text>

      <View className="mb-3 flex-row">
        <Stat label="LOC" value={file.loc ?? 0} testID="file-detail-loc" />
        <Stat
          label="Fan in"
          value={file.fan_in ?? 0}
          testID="file-detail-fan-in"
        />
        <Stat
          label="Fan out"
          value={file.fan_out ?? 0}
          testID="file-detail-fan-out"
        />
      </View>

      <Pressable
        testID="file-detail-github-link"
        accessibilityRole="link"
        accessibilityLabel={`View ${file.path} on GitHub`}
        onPress={() => void Linking.openURL(sourceUrl)}
        className="min-h-[44px] flex-row items-center rounded border border-border px-3 active:bg-secondary"
      >
        <Text className="mr-2 text-sm text-foreground">◈</Text>
        <Text className="text-[13px] font-medium text-primary">
          View on GitHub
        </Text>
        <Text
          testID="file-detail-branch"
          className="ml-auto font-mono text-[10px] text-muted-foreground"
        >
          {branch && branch.length > 0 ? branch : DEFAULT_SOURCE_BRANCH}
        </Text>
      </Pressable>
    </View>
  );
}

export default FileDetailCard;
