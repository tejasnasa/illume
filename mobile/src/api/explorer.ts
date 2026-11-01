/**
 * The file tree behind the explorer.
 *
 * @module ExplorerApi
 *
 * The web explorer has no file-tree endpoint of its own: it reads the
 * file-level dependency graph and rebuilds the tree from the flat node
 * list client-side (``client/src/app/repo/[id]/explorer/page.tsx`` calls
 * ``getRepoGraph(repo.id, "file")``). This module mirrors that exactly --
 * the same path, the same ``level=file`` query -- and hands back the nodes
 * as the flat file list the tree builder expects.
 *
 * The file-level nodes carry everything the explorer shows: the path, the
 * language, the line count, the fan-in/fan-out counts and the criticality
 * band. The tree hierarchy itself is derived from the paths, so nothing
 * else has to be fetched.
 */

import { apiGet, type ApiRequestOptions } from "@/api/client";
import type { default as Graph } from "@/types/graph";
import type { FileNode } from "@/types/explorer";

type TestOptions = Omit<ApiRequestOptions, "method" | "body">;

/**
 * Build the path for a repository's file-level graph.
 *
 * @param repoId - The repository's UUID.
 * @returns The absolute API path.
 */
function fileTreePath(repoId: string): string {
  return `/api/v1/repository/${repoId}/graph?level=file`;
}

/**
 * Fetch the flat file list behind the repository tree.
 *
 * The endpoint answers 409 while the repository is still being indexed and
 * 404 when it is not the caller's, both of which surface as an
 * ``ApiError`` with the server's own message.
 *
 * @param repoId - The repository's UUID.
 * @param options - Test-friendly transport overrides.
 * @returns One entry per indexed file.
 */
export function getFileTree(
  repoId: string,
  options: TestOptions = {},
): Promise<FileNode[]> {
  return apiGet<Graph>(fileTreePath(repoId), options).then(
    (graph) => graph.nodes,
  );
}
