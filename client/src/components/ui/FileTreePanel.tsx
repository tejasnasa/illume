/**
 * The explorer's reading-order bar and its sticky file tree.
 * @module FileTreePanel
 */
import { FileNode, TreeNode } from "@/types/explorer";
import TreeNodeRenderer from "./TreeNodeRenderer";

/** Reading-order segments drawn at most; long orders are bucketed into these. */
const MAX_SEGMENTS = 40;

/**
 * Props for the reading-order bar.
 */
interface ReadingOrderProps {
  pageIndex: number | null;
  totalPages: number;
  onNavigate: (index: number) => void;
}

/**
 * Steps through the guide's reading order, with a segmented progress rail.
 *
 * @param pageIndex Current reading-order position, or null when the selected
 *   file is not on the order.
 * @param totalPages Number of files on the order.
 * @param onNavigate Called with the target index.
 * @returns The bar, or null when the guide has no order.
 */
export function ReadingOrderBar({ pageIndex, totalPages, onNavigate }: ReadingOrderProps) {
  if (totalPages === 0) return null;
  const segments = Math.min(totalPages, MAX_SEGMENTS);
  const perSegment = totalPages / segments;
  const arrow =
    "ghost rounded-sm border border-(--input) px-2.5 py-1.5 font-pixel text-xs text-zinc-300 hover:cursor-pointer disabled:cursor-not-allowed disabled:opacity-30";

  return (
    <div className="panel flex flex-wrap items-center gap-3.5 px-3.5 py-3">
      <span className="font-pixel text-xs tracking-[0.12em] text-(--muted-foreground) uppercase">
        Reading order
      </span>
      <button
        type="button"
        aria-label="Previous file in reading order"
        onClick={() => onNavigate((pageIndex ?? 0) - 1)}
        disabled={pageIndex === null || pageIndex === 0}
        className={arrow}
      >
        ◀
      </button>
      <span className="font-pixel text-sm tabular-nums">
        <span className="text-(--accent)">{pageIndex === null ? "—" : pageIndex + 1}</span>{" "}
        <span className="text-(--faint-foreground)">/ {totalPages}</span>
      </span>
      <button
        type="button"
        aria-label="Next file in reading order"
        onClick={() => onNavigate((pageIndex ?? -1) + 1)}
        disabled={pageIndex !== null && pageIndex === totalPages - 1}
        className={arrow}
      >
        ▶
      </button>
      <span className="flex h-1.5 min-w-30 grow gap-0.5">
        {Array.from({ length: segments }, (_, s) => {
          const start = Math.floor(s * perSegment);
          const end = Math.floor((s + 1) * perSegment) - 1;
          const here = pageIndex !== null && pageIndex >= start && pageIndex <= end;
          const read = pageIndex !== null && pageIndex > end;
          return (
            <button
              key={s}
              type="button"
              tabIndex={-1}
              aria-hidden="true"
              onClick={() => onNavigate(start)}
              className={`h-1.5 flex-1 hover:cursor-pointer ${here ? "bg-(--accent)" : read ? "bg-(--chart-3)" : "bg-(--muted) hover:bg-(--border-strong)"}`}
            />
          );
        })}
      </span>
    </div>
  );
}

/**
 * Props for the FileTreePanel component.
 */
interface Props {
  fileTree: TreeNode;
  fileCount: number;
  selectedFile: FileNode | null;
  expandedDirs: Set<string>;
  onFileClick: (e: React.MouseEvent, file: FileNode) => void;
  onToggleDir: (path: string) => void;
}

/**
 * Renders the repository tree in a sticky, independently scrolling panel.
 * @param fileTree Root tree node to render.
 * @param fileCount Number of files in the tree.
 * @param selectedFile Currently selected file.
 * @param expandedDirs Set of expanded directory paths.
 * @param onFileClick Handler invoked when a file row is clicked.
 * @param onToggleDir Handler invoked when a directory is expanded or collapsed.
 * @returns The rendered file tree panel element.
 */
export default function FileTreePanel({
  fileTree,
  fileCount,
  selectedFile,
  expandedDirs,
  onFileClick,
  onToggleDir,
}: Props) {
  return (
    <nav
      aria-label="Files"
      className="panel flex flex-col gap-0.5 overflow-y-auto p-3 [scrollbar-width:thin] md:sticky md:top-21 md:max-h-[calc(100dvh-110px)]"
    >
      <p className="m-0 flex justify-between px-2 pt-1 pb-2.5 font-pixel text-xs tracking-[0.12em] text-(--muted-foreground) uppercase">
        <span>Files</span>
        <span className="text-(--faint-foreground)">{fileCount.toLocaleString()}</span>
      </p>
      <TreeNodeRenderer
        node={fileTree}
        selectedFile={selectedFile}
        expandedDirs={expandedDirs}
        onFileClick={onFileClick}
        onToggleDir={onToggleDir}
      />
    </nav>
  );
}
