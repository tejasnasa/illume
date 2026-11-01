/**
 * Turning the flat file list into a browsable tree.
 *
 * @module FileTree
 *
 * The backend hands the explorer a flat list of files -- one entry per
 * indexed file, each carrying its path. The web client turns that list into
 * a nested tree and renders it recursively
 * (``client/src/components/ui/TreeNodeRenderer.tsx``); a recursive render
 * tree gets expensive once a repository has a few thousand files, because
 * every re-render walks the whole tree.
 *
 * So the tree is built once, as data, and then *flattened* into a list of
 * rows that a ``FlatList`` can render. Each row carries the depth it sits
 * at, so the indentation is a padding value rather than a level of nested
 * views.
 *
 * Expansion is a single ``Set`` of directory paths rather than per-node
 * state: a node is expanded when its path is in the set. That keeps the
 * state one value the screen owns, and it makes "expand every ancestor of
 * this file" a one-line set operation.
 *
 * Nothing in this module touches React or React Native, so it can be unit
 * tested in the node environment.
 */

import type { FileNode, TreeNode } from "@/types/explorer";

/**
 * One rendered row of the flattened tree.
 */
export interface TreeRow {
  /** The node the row draws. */
  node: TreeNode;
  /**
   * How deep the node sits. The root's own children are at depth 0 and
   * every level below that adds one.
   */
  depth: number;
  /** Whether the node has children of its own. */
  hasChildren: boolean;
  /** Whether the node is currently expanded. */
  expanded: boolean;
}

/**
 * The synthetic node the whole tree hangs off.
 *
 * The root is never rendered -- it only exists to give the top level a
 * parent, exactly as it does in the web client's tree builder.
 */
const ROOT_NAME = "root";

/**
 * Build the nested tree from a flat list of files.
 *
 * The list comes from the file-level graph payload, so a file's path is
 * the only thing that has to be split: every segment becomes a directory
 * except the last one, which carries the file payload.
 *
 * A path that is both a file and a directory prefix ("a/b" and "a/b/c")
 * is pathological but not impossible. The subtree wins there: a node with
 * children has to be expandable, or the files underneath it would be
 * unreachable.
 *
 * @param files - The flat file list, one entry per indexed file.
 * @returns The root node holding the whole hierarchy.
 */
export function buildFileTree(files: FileNode[]): TreeNode {
  const root: TreeNode = {
    name: ROOT_NAME,
    path: "",
    type: "directory",
    children: {},
  };

  for (const file of files) {
    const parts = file.path
      .replace(/^[/\\]+/, "")
      .split(/[/\\]/)
      .filter((part) => part.length > 0);

    if (parts.length === 0) continue;

    let current = root;

    for (let index = 0; index < parts.length; index += 1) {
      const part = parts[index];
      const isFile = index === parts.length - 1;
      const path = parts.slice(0, index + 1).join("/");

      let child = current.children[part];
      if (!child) {
        child = {
          name: part,
          path,
          type: isFile ? "file" : "directory",
          children: {},
        };
        current.children[part] = child;
      } else if (!isFile && child.type === "file") {
        // The path is also a directory prefix, so it has to be expandable --
        // and the file payload it arrived with has to go, or the directory
        // would keep a file record that no row can ever select.
        child.type = "directory";
        delete child.file;
      }

      current = child;
      // A node that already has children is a directory; a file entry for
      // the same path loses to the subtree, by the rule documented above.
      if (isFile && current.type === "file") current.file = file;
    }
  }

  return root;
}

/**
 * Order a directory's children for display.
 *
 * Directories come first, then files, each group sorted by name. The web
 * client sorts the same way in its tree renderer, so both clients walk a
 * repository in the same order.
 *
 * @param children - The children of one directory.
 * @returns A new array in display order.
 */
export function sortTreeChildren(children: TreeNode[]): TreeNode[] {
  return [...children].sort((left, right) => {
    const leftIsDirectory = Object.keys(left.children).length > 0;
    const rightIsDirectory = Object.keys(right.children).length > 0;
    if (leftIsDirectory !== rightIsDirectory) return leftIsDirectory ? -1 : 1;
    return left.name.localeCompare(right.name);
  });
}

/**
 * Flatten a tree into the rows a list can render.
 *
 * A directory contributes its children only when it is expanded; a file
 * always contributes itself. The root is a container and is never a row.
 *
 * @param root - The root of the tree.
 * @param expanded - Paths of the expanded directories.
 * @returns The rows, in the order they should be drawn.
 */
export function flattenTree(root: TreeNode, expanded: Set<string>): TreeRow[] {
  const rows: TreeRow[] = [];

  const walk = (node: TreeNode, depth: number): void => {
    for (const child of sortTreeChildren(Object.values(node.children))) {
      const hasChildren = Object.keys(child.children).length > 0;
      const isExpanded = hasChildren && expanded.has(child.path);

      rows.push({ node: child, depth, hasChildren, expanded: isExpanded });

      if (isExpanded) walk(child, depth + 1);
    }
  };

  walk(root, 0);
  return rows;
}

/**
 * The directories that are open when the tree first appears.
 *
 * The web client opens the top level for orientation; everything deeper is
 * left closed so a large repository does not open into a wall of rows.
 *
 * @param root - The root of the tree.
 * @returns The paths of the top-level directories.
 */
export function defaultExpandedPaths(root: TreeNode): Set<string> {
  const paths = new Set<string>();

  for (const child of Object.values(root.children)) {
    if (Object.keys(child.children).length > 0) paths.add(child.path);
  }

  return paths;
}

/**
 * Toggle a directory's expanded state.
 *
 * The set is copied rather than mutated: the caller owns it, and React
 * needs a new identity to see the change.
 *
 * @param expanded - The currently expanded directory paths.
 * @param path - The directory to expand or collapse.
 * @returns A new set with the path toggled.
 */
export function toggleExpandedPath(
  expanded: Set<string>,
  path: string,
): Set<string> {
  const next = new Set(expanded);
  if (next.has(path)) {
    next.delete(path);
  } else {
    next.add(path);
  }
  return next;
}

/**
 * The directories that contain a file, outermost first.
 *
 * @param filePath - The file's repository-relative path.
 * @returns The paths of the file's ancestor directories.
 */
export function ancestorPaths(filePath: string): string[] {
  const parts = filePath.split("/").filter((part) => part.length > 0);
  const paths: string[] = [];

  for (let index = 1; index < parts.length; index += 1) {
    paths.push(parts.slice(0, index).join("/"));
  }

  return paths;
}

/**
 * Add every directory that contains a file to the expanded set.
 *
 * Selecting a file deep in the tree should not leave it hidden behind a
 * collapsed directory, so the file's ancestors are opened on the way in.
 *
 * @param expanded - The currently expanded directory paths.
 * @param filePath - The file's repository-relative path.
 * @returns A new set with the file's ancestors expanded.
 */
export function expandAncestors(
  expanded: Set<string>,
  filePath: string,
): Set<string> {
  const next = new Set(expanded);
  for (const ancestor of ancestorPaths(filePath)) {
    next.add(ancestor);
  }
  return next;
}
