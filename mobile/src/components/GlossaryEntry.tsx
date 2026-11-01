/**
 * One glossary entry: its term, its definition and where it came from.
 *
 * @module GlossaryEntry
 *
 * Port of ``client/src/components/ui/GlossaryEntry.tsx``.
 *
 * The web entry is a numbered card in a two-column masonry grid. A phone
 * has one column, so the card becomes a row in a list.
 *
 * **The definition is shown in full.** An earlier version folded it and
 * offered a "show more" control; the fold hid the part most worth reading
 * and added a tap to every entry, so the whole definition renders instead.
 *
 * **The source link names the branch.** The link is built from the branch
 * the repository was actually indexed at, read from the repository record
 * the screen already holds. ``master`` is only the fallback for a
 * repository that records no branch at all -- a repository ingested from
 * ``main`` must not link to a branch that does not exist.
 */


import { Linking, Pressable, Text, View } from "react-native";

import type { GlossaryEntryItem } from "@/api/glossary";

/**
 * The branch used when the repository does not record one.
 *
 * A repository is normally ingested from its default branch, and the
 * backend stores that branch in ``ingested_branch``; the fallback only
 * applies to a repository whose branch was never recorded.
 */
export const DEFAULT_SOURCE_BRANCH = "master";

/**
 * How much {@link previewDefinition} keeps before eliding.
 *
 * Kept as a exported helper because other surfaces (the inspector's short
 * summaries) still fold long text; the entry itself no longer does.
 */
export const DEFINITION_PREVIEW_LENGTH = 180;

/**
 * Build the GitHub URL for the file an entry was defined in.
 *
 * The branch is the one the repository was indexed at rather than a
 * hard-coded ``master``: a repository ingested from ``main`` must not link
 * to a branch that does not exist, or the reader gets a 404 the moment they
 * tap the link. The fallback to ``master`` only applies when the repository
 * does not record a branch at all.
 *
 * The path is escaped segment by segment, so a file whose name contains a
 * space or a ``#`` still produces a link GitHub can resolve. The branch is
 * left as it is -- GitHub's own URLs put a slashed branch name in the
 * path unescaped, and escaping the separator would break it. The line
 * anchor is only added when the entry carries a line number, which the
 * web client appends unconditionally and so produces ``#Lnull`` for an
 * entry with no position.
 *
 * @param githubUrl - The repository's GitHub URL.
 * @param filePath - The file the entry was defined in.
 * @param branch - The branch the repository was ingested from.
 * @param lineNumber - The line the definition starts on, if it is known.
 * @returns The absolute URL of the file on GitHub.
 */
export function buildGlossarySourceUrl(
  githubUrl: string,
  filePath: string,
  branch?: string | null,
  lineNumber?: number | null,
): string {
  const base = githubUrl.replace(/\/+$/, "");
  const ref = branch && branch.length > 0 ? branch : DEFAULT_SOURCE_BRANCH;
  const path = filePath
    .split("/")
    .filter((segment) => segment.length > 0)
    .map(encodeURIComponent)
    .join("/");
  const anchor = typeof lineNumber === "number" ? `#L${lineNumber}` : "";

  return `${base}/blob/${ref}/${path}${anchor}`;
}

/**
 * Fold a definition down to its opening lines.
 *
 * The cut is made at a word boundary so the preview does not end
 * mid-word, and an ellipsis says there is more.
 *
 * @param definition - The full definition.
 * @param limit - How many characters to keep.
 * @returns The preview, or the definition itself when it is short enough.
 */
export function previewDefinition(
  definition: string,
  limit: number = DEFINITION_PREVIEW_LENGTH,
): string {
  if (definition.length <= limit) return definition;

  const cut = definition.slice(0, limit);
  const lastSpace = cut.lastIndexOf(" ");
  const head = lastSpace > limit * 0.5 ? cut.slice(0, lastSpace) : cut;

  return `${head.trimEnd()}…`;
}

/** Props for the {@link GlossaryEntry} component. */
export interface GlossaryEntryProps {
  /** The entry to draw. */
  entry: GlossaryEntryItem;
  /** The repository's GitHub URL; the source link is built from it. */
  githubUrl: string;
  /**
   * The branch the repository was ingested from.
   *
   * Read from the repository's own record, so a repository ingested from
   * ``main`` links to ``main``. ``master`` is only the fallback for a
   * repository that records no branch at all.
   */
  branch?: string | null;
  /** Test hook. */
  testID?: string;
}

/**
 * Draw one glossary entry.
 *
 * @param props - The entry, the repository's URL and branch.
 * @returns The rendered entry.
 */
export function GlossaryEntry({
  entry,
  githubUrl,
  branch,
  testID = "glossary-entry",
}: GlossaryEntryProps) {
  const definition = entry.definition;

  // An entry whose defining symbol could not be resolved carries no file
  // path, and so has no source link to offer.
  const filePath = entry.file_path;
  const fileName = filePath ? (filePath.split("/").pop() ?? filePath) : "";
  const sourceUrl = filePath
    ? buildGlossarySourceUrl(githubUrl, filePath, branch, entry.line_number)
    : null;

  return (
    <View
      testID={testID}
      className="mb-3 rounded border border-border bg-card p-4"
    >
      <View className="mb-2 flex-row items-start justify-between gap-3">
        <Text
          testID={`${testID}-term`}
          className="flex-1 text-base font-bold text-foreground"
        >
          {entry.name}
        </Text>

        {sourceUrl ? (
          <Pressable
            testID={`${testID}-link`}
            accessibilityRole="link"
            accessibilityLabel={`View ${fileName} on GitHub`}
            onPress={() => void Linking.openURL(sourceUrl)}
            hitSlop={8}
            className="max-w-[45%] rounded border border-border bg-secondary/20 px-2 py-1 active:bg-secondary"
          >
            <Text
              numberOfLines={1}
              className="font-mono text-[11px] text-chart-2"
            >
              ◈ {fileName}
            </Text>
          </Pressable>
        ) : null}
      </View>

      <Text
        testID={`${testID}-definition`}
        className="text-[13px] leading-[19px] text-muted-foreground"
      >
        {definition}
      </Text>

      {entry.line_number ? (
        <Text
          testID={`${testID}-line`}
          className="mt-2 font-mono text-[10px] text-muted-foreground opacity-70"
        >
          Line: {entry.line_number}
        </Text>
      ) : null}
    </View>
  );
}

export default GlossaryEntry;
