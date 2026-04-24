import { FileNode, TreeNode } from "@/types/explorer";
import {
  FileTextIcon,
  FolderIcon,
  FolderOpenIcon,
} from "@phosphor-icons/react/dist/ssr";

interface Props {
  node: TreeNode;
  level?: number;
  selectedFile: FileNode | null;
  expandedDirs: Set<string>;
  onFileClick: (e: React.MouseEvent, file: FileNode) => void;
  onToggleDir: (path: string) => void;
}

export default function TreeNodeRenderer({
  node,
  level = 0,
  selectedFile,
  expandedDirs,
  onFileClick,
  onToggleDir,
}: Props) {
  const isExpanded = expandedDirs.has(node.path);

  if (node.type === "file" && node.file) {
    const file = node.file;
    return (
      <button
        key={node.path}
        className={`w-full flex items-center justify-between py-1.5 transition-colors group relative rounded-sm px-2 text-left ${
          selectedFile?.path === node.path
            ? "bg-(--primary)/10 text-(--primary)"
            : "text-(--muted-foreground) hover:bg-(--secondary)/50 hover:text-(--foreground) hover:cursor-pointer"
        }`}
        style={{ paddingLeft: `${level * 20 + 8}px` }}
        onClick={(e) => onFileClick(e, file)}
      >
        <div
          className="absolute top-1/2 w-3 h-px bg-(--border)/30"
          style={{ left: `${level * 20 - 10}px` }}
        />
        <div className="flex items-center gap-2 overflow-hidden">
          <FileTextIcon size={16} className="shrink-0 transition-colors" />
          <span className="font-mono text-sm truncate">{node.name}</span>
        </div>
        <div className="flex items-center gap-8 shrink-0">
          <span className="font-mono text-xs text-(--muted-foreground) w-16 text-right">
            {file.loc || 0}
          </span>
          <div className="w-24 flex justify-end">
            <span
              className={`text-[10px] font-bold tracking-widest uppercase px-2 py-0.5 border ${
                file.criticality === "critical"
                  ? "bg-red-500/10 text-red-500 border-red-500/20"
                  : file.criticality === "caution"
                    ? "bg-yellow-400/10 text-yellow-500 border-yellow-400/20"
                    : "bg-green-500/10 text-green-500 border-green-500/20"
              }`}
            >
              {file.criticality}
            </span>
          </div>
        </div>
      </button>
    );
  }

  const sortedChildren = Object.values(node.children).sort((a, b) => {
    if (a.type !== b.type) return a.type === "directory" ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  return (
    <div key={node.path}>
      {node.name !== "root" && (
        <button
          onClick={() => onToggleDir(node.path)}
          className="w-full flex items-center justify-between py-1.5 hover:bg-(--secondary)/50 transition-colors group text-left rounded-sm px-2"
          style={{ paddingLeft: `${level * 20 + 8}px` }}
        >
          <div className="flex items-center gap-2">
            {isExpanded ? (
              <FolderOpenIcon
                size={16}
                className="text-(--chart-4) shrink-0"
                weight="fill"
              />
            ) : (
              <FolderIcon
                size={16}
                className="text-(--muted-foreground) group-hover:text-(--chart-4) shrink-0 transition-colors"
                weight="fill"
              />
            )}
            <span className="font-mono text-sm text-(--foreground) truncate">
              {node.name}
            </span>
          </div>
        </button>
      )}

      {(isExpanded || node.name === "root") && sortedChildren.length > 0 && (
        <div className="relative">
          {node.name !== "root" && (
            <div
              className="absolute top-0 bottom-0 w-px bg-(--border)/30"
              style={{ left: `${level * 20 + 15}px` }}
            />
          )}
          {sortedChildren.map((child) => (
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
      )}
    </div>
  );
}
