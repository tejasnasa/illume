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
 * The reading-order pager the web client carries is not here. It needs the
 * onboarding guide, which is a separate request the web page makes on the
 * server; the mobile reader reaches the same files through the tree.
 */

import { useMemo, useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";
import { useGlobalSearchParams } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { getFileTree } from "@/api/explorer";
import { getOwnership } from "@/api/ownership";
import { queryKeys } from "@/api/queryKeys";
import { FileDetailCard } from "@/components/FileDetailCard";
import { FileTreePanel } from "@/components/FileTreePanel";
import { OwnershipPanel } from "@/components/OwnershipPanel";
import { useRepository } from "@/hooks/useRepositories";
import {
  ancestorPaths,
  buildFileTree,
  defaultExpandedPaths,
  toggleExpandedPath,
} from "@/lib/fileTree";
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
  const { id } = useGlobalSearchParams<{ id: string }>();
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

  const treeQuery = useQuery({
    queryKey: queryKeys.repositories.explorer(repoId ?? ""),
    queryFn: () => getFileTree(repoId as string),
    enabled: typeof repoId === "string" && repoId.length > 0,
  });

  const [selectedFile, setSelectedFile] = useState<FileNode | null>(null);
  // ``null`` means "not decided yet": the tree opens with its top level
  // expanded, and the first tap on a directory takes over from there.
  const [expandedDirs, setExpandedDirs] = useState<Set<string> | null>(null);

  const tree = useMemo(
    () => buildFileTree(treeQuery.data ?? []),
    [treeQuery.data],
  );
  const defaultExpanded = useMemo(() => defaultExpandedPaths(tree), [tree]);
  const openDirs = expandedDirs ?? defaultExpanded;

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
      <Text className="text-lg font-bold text-foreground">File Explorer</Text>
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
            className="max-h-[80%] rounded-t-2xl border-t border-border bg-background p-4"
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
                  onClose={closeDetails}
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
