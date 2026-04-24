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

export interface TreeNode {
  name: string;
  path: string;
  type: "file" | "directory";
  children: Record<string, TreeNode>;
  file?: FileNode;
}
