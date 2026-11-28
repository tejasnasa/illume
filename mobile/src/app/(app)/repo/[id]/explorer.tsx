/**
 * The repository explorer screen.
 *
 * @module ExplorerScreen
 *
 * Port of ``client/src/app/repo/[id]/explorer/page.tsx`` and the client it
 * renders (``client/src/components/ExplorerClient.tsx``).
 *
 * The screen has three parts, stacked the way a phone reads them:
 *
 * 1. The file tree (:component:`FileTreePanel`), which is the screen's
 *    reason to exist.
 * 2. The detail card of the selected file (:component:`FileDetailCard`).
 * 3. The ownership panel of that file (:component:`OwnershipPanel`).
 *
 * The tree and the detail panel are one scrolling list rather than two
 * views: the detail card and the ownership panel are the list's footer, so
 * a file can be tapped and its details read without the tree scrolling out
 * from under the reader.
 *
 * A ``file`` route parameter opens that file's details, which is how the
 * overview and the graph inspector link here. The details add the file's
 * reading-order note, its symbols and recent commits, a still picture of its
 * neighbourhood and its importers and imports; tapping a neighbour moves the
 * selection to it. The reading-order pager the web client carries is not
 * here; the overview's "Start here" card opens the same files.
 */

import { useEffect, useMemo, useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";
import { router, useGlobalSearchParams, type Href } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { getFileDetail } from "@/api/explorer";
import { getGraph } from "@/api/graph";
import { getOwnership } from "@/api/ownership";
import { queryKeys } from "@/api/queryKeys";
import { FileDetailCard } from "@/components/FileDetailCard";
import { FileTreePanel } from "@/components/FileTreePanel";
import {
  NeighbourListCard,
  NeighbourhoodCard,
  RecentChangesCard,
  SymbolsCard,
} from "@/components/explorer/FileExtras";
import { OwnershipPanel } from "@/components/OwnershipPanel";
import { useRepositoryGuide } from "@/hooks/useRepoGuide";
import { useRepository } from "@/hooks/useRepositories";
import {
  ancestorPaths,
  buildFileTree,
  defaultExpandedPaths,
  toggleExpandedPath,
} from "@/lib/fileTree";
import { neighboursByPath } from "@/lib/neighbourhood";
import type { FileNode } from "@/types/explorer";

/**
 * Render the explorer.
 *
 * @returns The tree, and the detail and ownership panels for the file the
 *   reader has selected.
 */
export default function ExplorerScreen() {
  // ``useGlobalSearchParams``, not the local variant: these screens are
  // tab children, not the ``[id]`` segment itself, and a local lookup
  // only sees the current route's own params -- which is why every
  // screen here used to receive an empty id and render nothing.
  const { id, file: fileParam } = useGlobalSearchParams<{ id: string; file?: string }>();
  const repoNumber = String(id ?? "");
  const insets = useSafeAreaInsets();

  // The route carries the repository's user-scoped number; the graph and
  // ownership routes are keyed by its UUID.
  const {
    data: repo,
    isLoading: repoLoading,
    isError: repoError,
  } = useRepository(repoNumber);
  const repoId = repo?.id;

  // The file graph is the tree's source and also where each file's
  // neighbours come from. Sharing the graph screen's query key means the
  // payload is fetched once however the reader moves between the tabs.
  const treeQuery = useQuery({
    queryKey: queryKeys.repositories.graph(repoId ?? "", "file"),
    queryFn: () => getGraph(repoId as string, "file"),
    enabled: typeof repoId === "string" && repoId.length > 0,
  });
  const files = treeQuery.data?.nodes;
  const links = treeQuery.data?.links;
  const { data: guide } = useRepositoryGuide(repoId, repo?.status === "ready");

  const [selectedFile, setSelectedFile] = useState<FileNode | null>(null);
  // ``null`` means "not decided yet": the tree opens with its top level
  // expanded, and the first tap on a directory takes over from there.
  const [expandedDirs, setExpandedDirs] = useState<Set<string> | null>(null);

  const tree = useMemo(() => buildFileTree(files ?? []), [files]);
  const defaultExpanded = useMemo(() => defaultExpandedPaths(tree), [tree]);
  const openDirs = expandedDirs ?? defaultExpanded;

  // A link from the overview or the graph names the file to open.
  useEffect(() => {
    if (!fileParam || !files) return;
    const match = files.find((f) => f.path === fileParam);
    if (match) {
      setSelectedFile(match);
      setExpandedDirs((previous) => {
        const next = new Set(previous ?? defaultExpandedPaths(buildFileTree(files)));
        for (const ancestor of ancestorPaths(match.path)) next.add(ancestor);
        return next;
      });
    }
  }, [fileParam, files]);

  const neighbours = useMemo(
    () =>
      selectedFile && files && links
        ? neighboursByPath(files, links, selectedFile.path)
        : { importers: [], imports: [] },
    [selectedFile, files, links],
  );

  const detailQuery = useQuery({
    queryKey: queryKeys.repositories.fileDetail(repoId ?? "", selectedFile?.path ?? ""),
    queryFn: () => getFileDetail(repoId as string, selectedFile?.path as string),
    enabled: typeof repoId === "string" && repoId.length > 0 && selectedFile !== null,
  });

  const guideStep = useMemo(
    () => guide?.reading_order?.find((step) => step.file_path === selectedFile?.path) ?? null,
    [guide, selectedFile],
  );

  const ownershipQuery = useQuery({
    queryKey: [
      ...queryKeys.repositories.ownership(repoId ?? ""),
      selectedFile?.path ?? "",
    ],
    queryFn: () => getOwnership(repoId as string, 1, 1, selectedFile?.path),
    enabled:
      typeof repoId === "string" && repoId.length > 0 && selectedFile !== null,
  });

  const treeError = repoError
    ? "This repository could not be loaded."
    : treeQuery.error
      ? treeQuery.error.message
      : null;

  const treeLoading = !treeError && (repoLoading || treeQuery.isPending);

  /**
   * Open or close a directory.
   *
   * @param path - The directory's path.
   */
  const handleToggleDir = (path: string) => {
    setExpandedDirs((previous) =>
      toggleExpandedPath(previous ?? defaultExpanded, path),
    );
  };

  /**
   * Select a file and open the directories that contain it.
   *
   * @param file - The file whose row was tapped.
   */
  const selectByPath = (path: string) => {
    const match = files?.find((f) => f.path === path);
    if (match) handleFilePress(match);
  };

  const handleFilePress = (file: FileNode) => {
    setSelectedFile(file);
    setExpandedDirs((previous) => {
      const next = new Set(previous ?? defaultExpanded);
      for (const ancestor of ancestorPaths(file.path)) next.add(ancestor);
      return next;
    });
  };

  const header = (
    <View className="px-4 pb-2 pt-4">
      <Text className="text-lg font-pixel text-foreground">File Explorer</Text>
      <Text className="mt-1 text-[13px] text-muted-foreground">
        Browse the entire repository tree. Criticality guardrails are mapped
        directly to files.
      </Text>
    </View>
  );

  const closeDetails = () => setSelectedFile(null);

  return (
    <View className="flex-1 bg-background">
      <FileTreePanel
        fileTree={tree}
        selectedFile={selectedFile}
        expandedDirs={openDirs}
        onFilePress={handleFilePress}
        onToggleDir={handleToggleDir}
        isLoading={treeLoading}
        error={treeError}
        header={header}
      />

      {/*
        The details open over the tree rather than below it. As a footer
        they pushed the tree up or off the screen the moment a file was
        tapped, and the reader lost the row they had just selected; as a
        sheet the tree stays where it was.
      */}
      <Modal
        visible={selectedFile !== null}
        transparent
        animationType="slide"
        onRequestClose={closeDetails}
      >
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Close the file details"
          onPress={closeDetails}
          className="flex-1 justify-end bg-black/60"
        >
          <Pressable
            accessibilityRole="none"
            onPress={() => {}}
            className="max-h-[80%] rounded-t-md border-t border-border bg-background p-4"
            style={{ paddingBottom: insets.bottom + 16 }}
          >
            {selectedFile ? (
              <ScrollView
                testID="explorer-details"
                keyboardShouldPersistTaps="handled"
              >
                <FileDetailCard
                  file={selectedFile}
                  githubUrl={repo?.github_url ?? ""}
                  branch={repo?.ingested_branch ?? null}
                  annotation={guideStep?.annotation ?? null}
                  readingPosition={guideStep?.position ?? null}
                  onAsk={() =>
                    router.push(
                      `/(app)/repo/${repoNumber}/chat?q=${encodeURIComponent(
                        `What does ${selectedFile.path} do, and what depends on it?`,
                      )}` as Href,
                    )
                  }
                  onOpenGraph={() => router.push(`/(app)/repo/${repoNumber}/graph` as Href)}
                  onClose={closeDetails}
                />
                <NeighbourhoodCard
                  file={selectedFile}
                  importers={neighbours.importers}
                  imports={neighbours.imports}
                />
                <SymbolsCard
                  detail={detailQuery.data ?? null}
                  loading={detailQuery.isLoading}
                  githubUrl={repo?.github_url ?? ""}
                  gitRef={repo?.ingested_commit_sha ?? repo?.ingested_branch ?? "master"}
                  path={selectedFile.path}
                />
                <RecentChangesCard
                  detail={detailQuery.data ?? null}
                  loading={detailQuery.isLoading}
                  githubUrl={repo?.github_url ?? ""}
                />
                <NeighbourListCard
                  title="Imported by"
                  testID="file-importers"
                  files={neighbours.importers}
                  empty="Nothing imports this file"
                  onSelectPath={selectByPath}
                />
                <NeighbourListCard
                  title="Imports"
                  testID="file-imports"
                  files={neighbours.imports}
                  empty="No internal imports"
                  onSelectPath={selectByPath}
                />
                <OwnershipPanel
                  ownership={ownershipQuery.data?.files?.[0] ?? null}
                  isLoading={ownershipQuery.isLoading}
                  error={ownershipQuery.error?.message ?? null}
                  onRetry={() => void ownershipQuery.refetch()}
                />
              </ScrollView>
            ) : null}
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}
