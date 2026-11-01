/**
 * The repository file tree.
 *
 * @module FileTreePanel
 *
 * Port of ``client/src/components/ui/FileTreePanel.tsx`` and its
 * recursive renderer (``client/src/components/ui/TreeNodeRenderer.tsx``).
 *
 * The web version draws the tree with a recursive component: every
 * directory renders its children by rendering another tree node. That is
 * fine on a desktop page and slow on a phone -- a repository with a few
 * thousand files makes every re-render walk the whole hierarchy.
 *
 * So the tree is flattened first (:func:`flattenTree`) and the rows are
 * drawn by a ``FlatList``. A row knows its own depth, so nesting is a
 * padding value rather than a level of views, and the list recycles rows
 * the way it does everywhere else in the app.
 *
 * Expansion is a ``Set`` of directory paths owned by the screen, not by
 * the rows: a row is expanded when its path is in the set. That keeps the
 * state one value the screen can hand to the detail panel, and it means a
 * tap on a directory is a single set operation rather than a walk up the
 * tree looking for the node that owns the state.
 */

import { useMemo, type ReactElement } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  Text,
  View,
} from "react-native";

import type { FileNode, TreeNode } from "@/types/explorer";
import { flattenTree, type TreeRow } from "@/lib/fileTree";
import { colors } from "@/theme/tokens";

/** How far one level of the tree is indented, in points. */
const INDENT_PER_LEVEL = 16;

/** The padding every row starts with, before its depth is added. */
const BASE_PADDING = 8;

/**
 * Props for the {@link FileTreePanel} component.
 */
export interface FileTreePanelProps {
  /** The root of the tree to draw. */
  fileTree: TreeNode;
  /** The file whose row is highlighted, if one is selected. */
  selectedFile: FileNode | null;
  /** The paths of the directories that are open. */
  expandedDirs: Set<string>;
  /** Called with the file whose row was tapped. */
  onFilePress: (file: FileNode) => void;
  /** Called with the path of the directory whose row was tapped. */
  onToggleDir: (path: string) => void;
  /** Whether the tree is still being fetched. */
  isLoading?: boolean;
  /** The failure message, when the tree could not be fetched. */
  error?: string | null;
  /** Drawn above the rows. */
  header?: ReactElement | null;
  /** Drawn below the rows. */
  footer?: ReactElement | null;
  /** Test hook. */
  testID?: string;
}

/**
 * Turn a path into a token that can sit inside a ``testID``.
 *
 * ``testID``s are kebab-case, and a repository path is neither kebab-case
 * nor safe to paste into one, so the separators become dashes.
 *
 * @param path - The directory or file path.
 * @returns The kebab-case token.
 */
export function pathToken(path: string): string {
  const token = path
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+/, "")
    .replace(/-+$/, "");
  return token.length > 0 ? token : "root";
}

/**
 * One row of the tree.
 *
 * A directory draws a chevron and toggles when tapped; a file draws its
 * line count and criticality band and selects when tapped.
 */
function TreeRowItem({
  row,
  selectedFile,
  onFilePress,
  onToggleDir,
}: {
  /** The flattened row to draw. */
  row: TreeRow;
  /** The file whose row is highlighted, if one is selected. */
  selectedFile: FileNode | null;
  /** Called with the file whose row was tapped. */
  onFilePress: (file: FileNode) => void;
  /** Called with the path of the directory whose row was tapped. */
  onToggleDir: (path: string) => void;
}) {
  const { node, depth, hasChildren, expanded } = row;
  const file = node.file;
  const isSelected = !!file && selectedFile?.path === file.path;
  const paddingLeft = BASE_PADDING + depth * INDENT_PER_LEVEL;

  if (hasChildren) {
    return (
      <Pressable
        testID={`file-tree-dir-${pathToken(node.path)}`}
        accessibilityRole="button"
        accessibilityLabel={`${node.name} folder, ${expanded ? "expanded" : "collapsed"}`}
        accessibilityState={{ expanded }}
        onPress={() => onToggleDir(node.path)}
        className="min-h-[48px] flex-row items-center border-b border-border/60 bg-card px-2 pr-3 active:bg-secondary"
        style={{ paddingLeft }}
      >
        <Text
          testID={`file-tree-chevron-${pathToken(node.path)}`}
          className="mr-2 w-5 text-center text-[17px] leading-[20px] text-muted-foreground"
        >
          {expanded ? "▾" : "▸"}
        </Text>
        <Text
          className="flex-1 font-mono text-[13px] text-foreground"
          numberOfLines={1}
        >
          {node.name}
        </Text>
      </Pressable>
    );
  }

  if (!file) {
    // A leaf with no payload cannot happen for a tree built by
    // ``buildFileTree``; it is drawn as a plain name rather than crashing
    // the list.
    return (
      <View
        className="min-h-[48px] flex-row items-center border-b border-border/60 bg-card px-2 pr-3"
        style={{ paddingLeft }}
      >
        <Text className="mr-2 w-5 text-center text-[15px] text-muted-foreground">·</Text>
        <Text
          className="flex-1 font-mono text-[13px] text-muted-foreground"
          numberOfLines={1}
        >
          {node.name}
        </Text>
      </View>
    );
  }

  return (
    <Pressable
      testID={`file-tree-file-${pathToken(file.path)}`}
      accessibilityRole="button"
      accessibilityLabel={`${node.name}, ${file.language || "unknown language"}, ${file.loc || 0} lines`}
      accessibilityState={{ selected: isSelected }}
      onPress={() => onFilePress(file)}
      className={`min-h-[48px] flex-row items-center border-b border-border/60 px-2 pr-3 active:bg-secondary ${
        isSelected ? "bg-primary/10" : "bg-card"
      }`}
      style={{ paddingLeft }}
    >
      <Text className="mr-2 w-5 text-center text-[15px] text-muted-foreground">·</Text>
      <Text
        className={`flex-1 font-mono text-[13px] ${
          isSelected ? "text-primary" : "text-muted-foreground"
        }`}
        numberOfLines={1}
      >
        {node.name}
      </Text>
      <Text className="ml-2 w-12 text-right font-mono text-[11px] text-muted-foreground">
        {file.loc || 0}
      </Text>
      <Text
        testID={`file-tree-criticality-${pathToken(file.path)}`}
        className="ml-2 w-16 text-right text-[10px] font-bold uppercase text-muted-foreground"
        numberOfLines={1}
      >
        {file.criticality}
      </Text>
    </Pressable>
  );
}

/**
 * Draw the repository tree.
 *
 * @param props - The tree, the selection, the expanded set and the handlers.
 * @returns The rendered tree.
 */
export function FileTreePanel({
  fileTree,
  selectedFile,
  expandedDirs,
  onFilePress,
  onToggleDir,
  isLoading = false,
  error = null,
  header,
  footer,
  testID = "file-tree",
}: FileTreePanelProps) {
  // The rows are memoised: a new array on every render would give the
  // list a new ``data`` prop every time, and the list reacts to that by
  // recomputing its cells -- work the reader would pay for on every
  // unrelated state change.
  const rows = useMemo(
    () => flattenTree(fileTree, expandedDirs),
    [fileTree, expandedDirs],
  );

  // Loading, failure and "nothing indexed yet" are three different
  // answers, and the list has to say which one it is rather than showing
  // an empty box.
  const emptyComponent = isLoading ? (
    <View
      testID="file-tree-loading"
      className="items-center justify-center py-10"
    >
      <ActivityIndicator size="large" color={colors.foreground} />
    </View>
  ) : error ? (
    <View
      testID="file-tree-error"
      className="mx-4 mb-3 rounded border border-destructive/30 bg-destructive/10 p-3"
    >
      <Text className="text-xs text-destructive">{error}</Text>
    </View>
  ) : (
    <View
      testID="file-tree-empty"
      className="items-center justify-center py-10"
    >
      <Text className="text-[13px] text-muted-foreground">
        This repository has no files to browse.
      </Text>
    </View>
  );

  return (
    <FlatList
      testID={testID}
      data={rows}
      keyExtractor={(row) => row.node.path}
      renderItem={({ item }) => (
        <TreeRowItem
          row={item}
          selectedFile={selectedFile}
          onFilePress={onFilePress}
          onToggleDir={onToggleDir}
        />
      )}
      ListHeaderComponent={header}
      ListFooterComponent={footer}
      ListEmptyComponent={emptyComponent}
      className="flex-1 bg-background"
      contentContainerClassName="pb-6"
      keyboardShouldPersistTaps="handled"
    />
  );
}

export default FileTreePanel;
