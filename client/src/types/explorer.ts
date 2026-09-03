/**
 * File explorer shapes for the tree and graph views.
 * @module ExplorerTypes
 */

/**
 * Flat file entry with metrics used for coloring and grouping nodes.
 */
export interface FileNode {
  id: string;
  label: string;
  path: string;
  group: string;
  kind: string;
  loc: number;
  criticality: string;
  language: string;
  fan_in: number;
  fan_out: number;
}

/**
 * Nested directory tree node; leaves carry the file payload.
 */
export interface TreeNode {
  name: string;
  path: string;
  type: "file" | "directory";
  children: Record<string, TreeNode>;
  file?: FileNode;
}
