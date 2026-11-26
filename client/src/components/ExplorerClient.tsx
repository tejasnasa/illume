/**
 * Guided file explorer with tree navigation and ownership details.
 * @module ExplorerClient
 */
"use client";

import { GetFileDetail } from "@/api/fileDetail";
import { GetOwnership } from "@/api/ownership";
import { FileNode, TreeNode } from "@/types/explorer";
import Graph from "@/types/graph";
import Guide from "@/types/guide";
import { useCallback, useEffect, useMemo, useState } from "react";
import FileDetailCard from "./ui/FileDetailCard";
import FileTreePanel, { ReadingOrderBar } from "./ui/FileTreePanel";

/** Query parameter naming the selected file, so a selection can be linked to. */
const FILE_PARAM = "file";

/**
 * Builds a nested directory tree from a flat file list.
 *
 * @param files - Flat file nodes with slash-separated paths.
 * @returns Root tree node containing the full hierarchy.
 */
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

/**
 * Fetches something about the selected file, and follows the selection.
 *
 * Each reply is stored with the path it answers, and only a reply for the
 * current path is shown, so a slow answer for an earlier file can never
 * overwrite a later one, and switching files needs no reset.
 *
 * @param repoId - The repository the file belongs to.
 * @param path - The selected file's path, or null when nothing is selected.
 * @param load - Fetches the value for one file; a failure reads as no value.
 * @returns The value for the current path, and whether it is still on its way.
 */
function usePerFile<T>(
  repoId: string,
  path: string | null,
  load: (repoId: string, path: string) => Promise<T | null>,
): { data: T | null; loading: boolean } {
  const [reply, setReply] = useState<{ path: string; data: T | null } | null>(null);

  useEffect(() => {
    if (!path) return;
    let live = true;
    load(repoId, path)
      .catch(() => null)
      .then((data) => {
        if (live) setReply({ path, data });
      });
    return () => {
      live = false;
    };
  }, [repoId, path, load]);

  const current = path !== null && reply?.path === path;
  return { data: current ? reply.data : null, loading: path !== null && !current };
}

/**
 * Every ancestor directory of a path, nearest last.
 *
 * @param path - A repo-relative file path.
 * @returns The directory paths that must be open for the file to show.
 */
function ancestorsOf(path: string): string[] {
  const parts = path.split("/");
  return parts.slice(1).map((_, i) => parts.slice(0, i + 1).join("/"));
}

/** Reads a link endpoint as an id, whether or not a renderer has replaced it with a node. */
function endpointId(end: unknown): string {
  return typeof end === "object" && end !== null ? (end as { id: string }).id : String(end);
}

/**
 * Renders the reading-order bar, the file tree and the selected file's details.
 *
 * The selection starts from `initialPath` when it names a file, otherwise
 * from the first file on the reading order, and is mirrored into the
 * address so a file can be linked to.
 *
 * @param graphData - Graph payload whose nodes carry file metadata.
 * @param guide - Onboarding guide with reading order and annotations.
 * @param github_url - Repository URL for outbound source links.
 * @param repoId - ID used for ownership lookups.
 * @param repoNumber - User-scoped repository number, for internal links.
 * @param commitSha - Repository's ingested commit, pinned in source links.
 * @param branch - Repository's ingested branch, used when the commit is missing.
 * @param initialPath - The file named by the address, if any.
 * @returns Explorer layout with navigable tree and detail panel.
 */
export default function ExplorerClient({
  graphData,
  guide,
  github_url,
  repoId,
  repoNumber,
  commitSha,
  branch,
  initialPath = null,
}: {
  graphData: Graph;
  guide: Guide | null;
  github_url: string;
  repoId: string;
  repoNumber: number;
  commitSha?: string | null;
  branch?: string | null;
  initialPath?: string | null;
}) {
  const files = graphData.nodes as FileNode[];

  /** Fast lookup of file nodes by path and by id. */
  const { byPath, byId } = useMemo(() => {
    const byPath = new Map<string, FileNode>();
    const byId = new Map<string, FileNode>();
    for (const f of files) {
      byPath.set(f.path, f);
      byId.set(f.id, f);
    }
    return { byPath, byId };
  }, [files]);

  /** Importers and imports per file id, from the file-level edges. */
  const neighbours = useMemo(() => {
    const importers = new Map<string, FileNode[]>();
    const imports = new Map<string, FileNode[]>();
    for (const link of graphData.links) {
      const from = byId.get(endpointId(link.source));
      const to = byId.get(endpointId(link.target));
      if (!from || !to || from.id === to.id) continue;
      imports.set(from.id, [...(imports.get(from.id) ?? []), to]);
      importers.set(to.id, [...(importers.get(to.id) ?? []), from]);
    }
    return { importers, imports };
  }, [graphData.links, byId]);

  /** Guide reading order resolved to file nodes, in position order. */
  const orderedFiles = useMemo(
    () =>
      [...(guide?.reading_order ?? [])]
        .sort((a, b) => a.position - b.position)
        .map((entry) => byPath.get(entry.file_path))
        .filter((f): f is FileNode => Boolean(f)),
    [guide, byPath],
  );

  /** Annotation text keyed by file path. */
  const annotationMap = useMemo(
    () =>
      new Map((guide?.reading_order ?? []).map((entry) => [entry.file_path, entry.annotation])),
    [guide],
  );

  /** Nested tree derived from the flat graph node list. */
  const fileTree = useMemo(() => buildTree(files), [files]);

  const firstFile = (initialPath && byPath.get(initialPath)) || orderedFiles[0] || null;
  const [selectedFile, setSelectedFile] = useState<FileNode | null>(firstFile);

  /** Top-level directories, plus the way to the first selection, start open. */
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(() => {
    const set = new Set<string>();
    Object.values(fileTree.children).forEach((child) => {
      if (child.type === "directory") set.add(child.path);
    });
    if (firstFile) ancestorsOf(firstFile.path).forEach((d) => set.add(d));
    return set;
  });

  const selectedPath = selectedFile?.path ?? null;
  const ownership = usePerFile(
    repoId,
    selectedPath,
    useCallback(
      async (id: string, path: string) => (await GetOwnership(id, 1, 1, path)).files?.[0] ?? null,
      [],
    ),
  );
  const detail = usePerFile(repoId, selectedPath, GetFileDetail);

  // The address names the selected file, without adding history entries.
  useEffect(() => {
    const url = new URL(window.location.href);
    if (selectedFile) url.searchParams.set(FILE_PARAM, selectedFile.path);
    else url.searchParams.delete(FILE_PARAM);
    window.history.replaceState(window.history.state, "", url);
  }, [selectedFile]);

  /**
   * Selects a file and opens the directories above it.
   *
   * @param file - The file to show.
   */
  const select = useCallback((file: FileNode) => {
    setSelectedFile(file);
    setExpandedDirs((prev) => {
      const next = new Set(prev);
      ancestorsOf(file.path).forEach((d) => next.add(d));
      return next;
    });
  }, []);

  /**
   * Toggles a directory's expanded state in the tree.
   *
   * @param path - Directory path to expand or collapse.
   */
  const toggleDir = (path: string) => {
    setExpandedDirs((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  /**
   * Selects the clicked file.
   *
   * @param e - Click event whose default navigation is suppressed.
   * @param file - File node that was clicked.
   */
  const handleFileClick = (e: React.MouseEvent, file: FileNode) => {
    e.preventDefault();
    select(file);
  };

  const pageIndex = selectedFile
    ? orderedFiles.findIndex((f) => f.path === selectedFile.path)
    : -1;

  /**
   * Selects the reading-order entry at an index, clamped to the order.
   *
   * @param index - Position in the ordered reading list.
   */
  const navigateToPage = (index: number) => {
    const file = orderedFiles[Math.max(0, Math.min(orderedFiles.length - 1, index))];
    if (file) select(file);
  };

  return (
    <div className="flex w-full flex-col gap-5">
      <h1 className="sr-only">File Explorer</h1>
      <ReadingOrderBar
        pageIndex={pageIndex === -1 ? null : pageIndex}
        totalPages={orderedFiles.length}
        onNavigate={navigateToPage}
      />

      <div className="grid grid-cols-1 items-start gap-5 md:grid-cols-[300px_minmax(0,1fr)]">
        <FileTreePanel
          fileTree={fileTree}
          fileCount={files.length}
          selectedFile={selectedFile}
          expandedDirs={expandedDirs}
          onFileClick={handleFileClick}
          onToggleDir={toggleDir}
        />

        {selectedFile ? (
          <FileDetailCard
            key={selectedFile.path}
            file={selectedFile}
            annotation={annotationMap.get(selectedFile.path) ?? null}
            readingPosition={pageIndex === -1 ? null : pageIndex + 1}
            ownershipData={ownership.data}
            isLoading={ownership.loading}
            detail={detail.data}
            isLoadingDetail={detail.loading}
            githubUrl={github_url}
            repoNumber={repoNumber}
            commitSha={commitSha}
            branch={branch}
            importers={neighbours.importers.get(selectedFile.id) ?? []}
            imports={neighbours.imports.get(selectedFile.id) ?? []}
            onSelectPath={(path) => {
              const file = byPath.get(path);
              if (file) select(file);
            }}
          />
        ) : (
          <p className="m-0 rounded-md border border-dashed border-white/12 p-12 text-center font-pixel text-sm text-(--muted-foreground)">
            Pick a file from the tree to see who knows it and what it touches.
          </p>
        )}
      </div>
    </div>
  );
}
