"use client";

import { GetOwnership } from "@/api/ownership";
import { FileNode, TreeNode } from "@/types/explorer";
import Graph from "@/types/graph";
import { AnimatePresence } from "motion/react";
import { useMemo, useState } from "react";
import FileDetailCard from "./ui/FileDetailCard";
import FileTreePanel from "./ui/FileTreePanel";

const buildTree = (files: FileNode[]): TreeNode => {
  const root: TreeNode = {
    name: "root",
    path: "",
    type: "directory",
    children: {},
  };

  files.forEach((file) => {
    const parts = file.path.replace(/^[/\\]+/, "").split(/[/\\]/);
    let current = root;

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isFile = i === parts.length - 1;

      if (!current.children[part]) {
        current.children[part] = {
          name: part,
          path: parts.slice(0, i + 1).join("/"),
          type: isFile ? "file" : "directory",
          children: {},
        };
      }
      current = current.children[part];
      if (isFile) current.file = file;
    }
  });

  return root;
};

export default function ExplorerClient({
  graphData,
  github_url,
  repoId,
}: {
  graphData: Graph;
  github_url: string;
  repoId: string;
}) {
  const [selectedFile, setSelectedFile] = useState<FileNode | null>(null);
  const [ownershipData, setOwnershipData] = useState<any>(null);
  const [isLoadingOwnership, setIsLoadingOwnership] = useState(false);

  const fileTree = useMemo(
    () => buildTree(graphData.nodes as any as FileNode[]),
    [graphData],
  );

  const defaultExpanded = useMemo(() => {
    const set = new Set<string>();
    Object.values(fileTree.children).forEach((child) => {
      if (child.type === "directory") set.add(child.path);
    });
    return set;
  }, [fileTree]);

  const [expandedDirs, setExpandedDirs] =
    useState<Set<string>>(defaultExpanded);

  const toggleDir = (path: string) => {
    setExpandedDirs((prev) => {
      const next = new Set(prev);
      next.has(path) ? next.delete(path) : next.add(path);
      return next;
    });
  };

  const fetchOwnership = async (path: string) => {
    setIsLoadingOwnership(true);
    try {
      const data = await GetOwnership(repoId, 1, 1, path);
      setOwnershipData(data.files?.[0] ?? null);
    } catch {
      setOwnershipData(null);
    } finally {
      setIsLoadingOwnership(false);
    }
  };

  const handleFileClick = (e: React.MouseEvent, file: FileNode) => {
    e.preventDefault();
    if (selectedFile?.path === file.path) {
      setSelectedFile(null);
      setOwnershipData(null);
    } else {
      setSelectedFile(file);
      fetchOwnership(file.path);
    }
  };

  const handleClose = () => {
    setSelectedFile(null);
    setOwnershipData(null);
  };

  return (
    <div className="w-full">
      <div className="w-full flex gap-6 items-start">
        <FileTreePanel
          fileTree={fileTree}
          selectedFile={selectedFile}
          expandedDirs={expandedDirs}
          onFileClick={handleFileClick}
          onToggleDir={toggleDir}
        />

        <AnimatePresence mode="wait">
          {selectedFile && (
            <FileDetailCard
              key="detail-card"
              file={selectedFile}
              ownershipData={ownershipData}
              isLoading={isLoadingOwnership}
              githubUrl={github_url}
              onClose={handleClose}
            />
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
