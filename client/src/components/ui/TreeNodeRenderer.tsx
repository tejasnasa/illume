/**
 * Recursive renderer for file-explorer tree nodes.
 * @module TreeNodeRenderer
 */
import { FileNode, TreeNode } from "@/types/explorer";

/** Risk dot colour per criticality; anything else is safe. */
export const RISK_DOT: Record<string, string> = {
  critical: "#ef4444",
  caution: "#facc15",
};

const SAFE_DOT = "#22c55e";

/**
 * Props for the TreeNodeRenderer component.
 */
interface Props {
  node: TreeNode;
  level?: number;
  selectedFile: FileNode | null;
  expandedDirs: Set<string>;
  onFileClick: (e: React.MouseEvent, file: FileNode) => void;
  onToggleDir: (path: string) => void;
}

/**
 * Renders a file row or an expandable directory with sorted children.
 * @param node The tree node to render.
 * @param level Indentation depth.
 * @param selectedFile Currently selected file used to highlight the active row.
 * @param expandedDirs Set of expanded directory paths.
 * @param onFileClick Handler invoked when a file row is clicked.
 * @param onToggleDir Handler invoked when a directory is expanded or collapsed.
 * @returns The rendered tree node element.
 */
export default function TreeNodeRenderer({
  node,
  level = 0,
  selectedFile,
  expandedDirs,
  onFileClick,
  onToggleDir,
}: Props) {
  const isExpanded = expandedDirs.has(node.path);
  const indent = { paddingLeft: `${level * 14 + 8}px` };

  if (node.type === "file" && node.file) {
    const file = node.file;
    const selected = selectedFile?.path === node.path;
    const risk = (file.criticality ?? "").toLowerCase();
    return (
      <button
        type="button"
        aria-current={selected ? "true" : undefined}
        title={`${file.path} · ${file.loc || 0} LOC · ${risk || "safe"}`}
        className={`flex w-full items-center gap-2 rounded-[3px] py-1.5 pr-2 text-left font-pixel text-[13px] hover:cursor-pointer ${
          selected
            ? "bg-(--accent)/10 text-(--foreground) shadow-[inset_2px_0_0_var(--accent)]"
            : "text-zinc-300 hover:bg-(--secondary)"
        }`}
        style={indent}
        onClick={(e) => onFileClick(e, file)}
      >
        <span aria-hidden="true" className="w-3 shrink-0 text-(--faint-foreground)">
          ·
        </span>
        <span className="min-w-0 grow truncate">{node.name}</span>
        {/* The dot is colour alone, so the risk is also spoken. */}
        {RISK_DOT[risk] && <span className="sr-only">{risk}</span>}
        <span
          aria-hidden="true"
          className="h-1.5 w-1.5 shrink-0"
          style={{ background: RISK_DOT[risk] ?? SAFE_DOT }}
        />
      </button>
    );
  }

  // Directories first, then files, each sorted alphabetically.
  const sortedChildren = Object.values(node.children).sort((a, b) => {
    if (a.type !== b.type) return a.type === "directory" ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  return (
    <div>
      {node.name !== "root" && (
        <button
          type="button"
          aria-expanded={isExpanded}
          onClick={() => onToggleDir(node.path)}
          className="flex w-full items-center gap-2 rounded-[3px] py-1.5 pr-2 text-left font-pixel text-[13px] text-(--foreground) hover:cursor-pointer hover:bg-(--secondary)"
          style={indent}
        >
          <span aria-hidden="true" className="w-3 shrink-0 text-(--chart-1)">
            {isExpanded ? "▾" : "▸"}
          </span>
          <span className="min-w-0 grow truncate">{node.name}</span>
        </button>
      )}

      {(isExpanded || node.name === "root") &&
        sortedChildren.map((child) => (
          <TreeNodeRenderer
            key={child.path}
            node={child}
            level={node.name === "root" ? level : level + 1}
            selectedFile={selectedFile}
            expandedDirs={expandedDirs}
            onFileClick={onFileClick}
            onToggleDir={onToggleDir}
          />
        ))}
    </div>
  );
}
