"use client";

import { GetOwnership } from "@/api/ownership";
import { FileNode, TreeNode } from "@/types/explorer";
import Graph from "@/types/graph";
import Guide from "@/types/guide";
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
  guide,
  github_url,
  repoId,
}: {
  graphData: Graph;
  guide: Guide;
  github_url: string;
  repoId: string;
}) {
  const [selectedFile, setSelectedFile] = useState<FileNode | null>(null);
  const [ownershipData, setOwnershipData] = useState<any>(null);
  const [isLoadingOwnership, setIsLoadingOwnership] = useState(false);
  const [pageIndex, setPageIndex] = useState<number | null>(null);

  const fileNodeMap = useMemo(() => {
    const map = new Map<string, FileNode>();
    (graphData.nodes as any as FileNode[]).forEach((f) => map.set(f.path, f));
    return map;
  }, [graphData]);

  const orderedFiles = useMemo(
    () =>
      guide.reading_order
        .sort((a, b) => a.position - b.position)
        .map((entry) => fileNodeMap.get(entry.file_path))
        .filter(Boolean) as FileNode[],
    [guide, fileNodeMap],
  );

  const navigateToPage = (index: number) => {
    const file = orderedFiles[index];
    if (!file) return;
    setPageIndex(index);
    setSelectedFile(file);
    fetchOwnership(file.path);

    const parts = file.path.split("/");
    setExpandedDirs((prev) => {
      const next = new Set(prev);
      for (let i = 1; i < parts.length; i++) {
        next.add(parts.slice(0, i).join("/"));
      }
      return next;
    });
  };

  const annotationMap = Object.fromEntries(
    guide.reading_order.map((entry) => [entry.file_path, entry.annotation]),
  );

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
      setPageIndex(null);
    } else {
      setSelectedFile(file);
      fetchOwnership(file.path);
      const idx = orderedFiles.findIndex((f) => f.path === file.path);
      setPageIndex(idx === -1 ? null : idx);
    }
  };

  const handleClose = () => {
    setSelectedFile(null);
    setOwnershipData(null);
    setPageIndex(null);
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
          pageIndex={pageIndex}
          totalPages={orderedFiles.length}
          onNavigate={navigateToPage}
        />

        <AnimatePresence mode="wait">
          {selectedFile && (
            <FileDetailCard
              key="detail-card"
              file={selectedFile}
              annotation={annotationMap[selectedFile.path] ?? null}
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
