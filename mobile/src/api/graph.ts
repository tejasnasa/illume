/**
 * The dependency graph payload.
 *
 * @module graphApi
 *
 * One route serves both levels of granularity; the level is a query
 * parameter rather than a second path, so the mobile client mirrors the
 * web client's single call.
 *
 * The endpoint has no node cap and nothing is cached, so a large repository
 * is a large payload over a phone connection. The screen reports progress
 * while the layout settles rather than pretending the wait is short.
 */

import { apiGet, type ApiRequestOptions } from "@/api/client";
import type Graph from "@/types/graph";

/** The level of granularity the graph is drawn at. */
export type GraphLevel = "file" | "symbol";

type TestOptions = Omit<ApiRequestOptions, "method" | "body">;

/**
 * Fetch the dependency graph of a repository.
 *
 * @param repoId - The repository's UUID. The route is typed as a UUID, so
 *   the user-scoped number is a 404 here.
 * @param level - File level or symbol level.
 * @param options - Test seam for the base URL and the fetch implementation.
 * @returns The graph payload.
 */
export function getGraph(
  repoId: string,
  level: GraphLevel,
  options: TestOptions = {},
): Promise<Graph> {
  return apiGet<Graph>(
    `/api/v1/repository/${repoId}/graph?level=${level}`,
    options,
  );
}
