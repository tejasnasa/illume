import { FileNode, TreeNode } from "@/types/explorer";
import { FolderOpenIcon } from "@phosphor-icons/react";
import { ArrowLeftIcon, ArrowRightIcon } from "@phosphor-icons/react/dist/ssr";
import { motion } from "motion/react";
import TreeNodeRenderer from "./TreeNodeRenderer";

interface Props {
  fileTree: TreeNode;
  selectedFile: FileNode | null;
  expandedDirs: Set<string>;
  onFileClick: (e: React.MouseEvent, file: FileNode) => void;
  onToggleDir: (path: string) => void;
  pageIndex: number | null;
  totalPages: number;
  onNavigate: (index: number) => void;
}

export default function FileTreePanel({
  fileTree,
  selectedFile,
  expandedDirs,
  onFileClick,
  onToggleDir,
  pageIndex,
  totalPages,
  onNavigate,
}: Props) {
  return (
    <motion.div
      className="w-full max-w-4xl shrink-0"
      animate={{
        marginLeft: selectedFile ? "0" : "auto",
        marginRight: selectedFile ? "0" : "auto",
      }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
    >
      <div className="flex gap-3 mb-2 justify-between flex-col">
        <div className="flex justify-between items-end gap-3 mb-2 ">
          <div className="flex gap-3 items-center text-(--primary)">
            <FolderOpenIcon size={28} weight="duotone" />
            <h1 className="text-3xl font-bold text-(--foreground) tracking-tight">
              File Explorer
            </h1>
          </div>

          <div className="flex items-center gap-2">
            <div className="font-medium uppercase text-(--foreground)/90">Reading Order:</div>
            <button
              onClick={() => onNavigate((pageIndex ?? 0) - 1)}
              disabled={pageIndex === null || pageIndex === 0}
              className="p-1.5 rounded-sm border border-(--border) hover:bg-(--secondary) disabled:opacity-30 disabled:cursor-not-allowed transition-colors text-(--foreground)"
            >
              <ArrowLeftIcon size={14} />
            </button>
            <span className="text-sm text-(--muted-foreground) tabular-nums">
              {pageIndex === null ? "—" : pageIndex + 1} / {totalPages}
            </span>
            <button
              onClick={() => onNavigate((pageIndex ?? -1) + 1)}
              disabled={pageIndex !== null && pageIndex === totalPages - 1}
              className="p-1.5 rounded-sm border border-(--border) hover:bg-(--secondary) disabled:opacity-30 disabled:cursor-not-allowed transition-colors text-(--foreground)"
            >
              <ArrowRightIcon size={14} />
            </button>
          </div>
        </div>

        <p className="text-(--muted-foreground)">
          Browse the entire repository tree. Criticality guardrails are mapped
          directly to files.
        </p>
      </div>

      <div className="glass-card rounded-sm overflow-hidden border border-(--border) bg-(--card)/40 p-2">
        <div className="flex items-center justify-between px-4 py-3 bg-(--secondary)/40 rounded-xs mb-2 border border-(--border)">
          <span className="text-xs font-semibold uppercase tracking-wider text-(--muted-foreground)">
            Directory / File
          </span>
          <div className="flex items-center gap-8 text-xs font-semibold uppercase tracking-wider text-(--muted-foreground)">
            <span className="w-16 text-right">LOC</span>
            <span className="w-24 text-right">Guardrail</span>
          </div>
        </div>

        <div className="p-2 overflow-x-auto custom-scrollbar">
          <div className={selectedFile ? "" : "min-w-150"}>
            <TreeNodeRenderer
              node={fileTree}
              selectedFile={selectedFile}
              expandedDirs={expandedDirs}
              onFileClick={onFileClick}
              onToggleDir={onToggleDir}
            />
          </div>
        </div>
      </div>
    </motion.div>
  );
}
