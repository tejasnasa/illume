import { FolderOpenIcon } from "@phosphor-icons/react";
import { motion } from "motion/react";
import TreeNodeRenderer from "./TreeNodeRenderer";
import { FileNode, TreeNode } from "@/types/explorer";

interface Props {
  fileTree: TreeNode;
  selectedFile: FileNode | null;
  expandedDirs: Set<string>;
  onFileClick: (e: React.MouseEvent, file: FileNode) => void;
  onToggleDir: (path: string) => void;
}

export default function FileTreePanel({
  fileTree,
  selectedFile,
  expandedDirs,
  onFileClick,
  onToggleDir,
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
      <div className="mb-10">
        <div className="flex items-center gap-3 mb-2 text-(--primary)">
          <FolderOpenIcon size={28} weight="duotone" />
          <h1 className="text-3xl font-bold text-(--foreground) tracking-tight">
            File Explorer
          </h1>
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
