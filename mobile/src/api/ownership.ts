/**
 * Code ownership fetches.
 *
 * @module OwnershipApi
 *
 * Port of ``client/src/api/ownership.ts``. Two routes are exposed:
 *
 * - ``GET /api/v1/repository/{id}/ownership`` -- the paginated ownership
 *   map, with an optional ``file_path`` filter for a single file.
 * - ``GET /api/v1/repository/{id}/ownership/silos`` -- the files flagged as
 *   knowledge silos, i.e. the ones a single person is the only person who
 *   can explain.
 *
 * The ownership map is ordered by path, so paging through it walks the
 * repository alphabetically. The explorer asks for a single file at a time
 * (page 1, one entry, filtered by path); the silos route ignores the
 * paging parameters and answers with the whole list.
 *
 * Both go through :func:`apiGet`, so the bearer token is injected and a
 * non-2xx response becomes an ``ApiError`` carrying the server's message.
 */

import { apiGet, type ApiRequestOptions } from "@/api/client";
import type { default as Ownership, Silo } from "@/types/ownership";

type TestOptions = Omit<ApiRequestOptions, "method" | "body">;

/**
 * Build the path for a repository's ownership map.
 *
 * @param repoId - The repository's UUID.
 * @param page - 1-indexed page number.
 * @param pageSize - Entries per page.
 * @param filePath - Optional exact file-path filter.
 * @returns The absolute API path.
 */
function ownershipPath(
  repoId: string,
  page: number,
  pageSize: number,
  filePath?: string,
): string {
  const query = new URLSearchParams({
    page: page.toString(),
    page_size: pageSize.toString(),
  });
  if (filePath) query.set("file_path", filePath);

  return `/api/v1/repository/${repoId}/ownership?${query.toString()}`;
}

/**
 * Build the path for a repository's knowledge silos.
 *
 * @param repoId - The repository's UUID.
 * @returns The absolute API path.
 */
function siloPath(repoId: string): string {
  return `/api/v1/repository/${repoId}/ownership/silos`;
}

/**
 * Fetch the ownership map for a repository.
 *
 * @param repoId - The repository's UUID.
 * @param page - 1-indexed page number. Defaults to the first page.
 * @param pageSize - Entries per page. Defaults to fifty.
 * @param filePath - Optional exact file-path filter; the server matches
 *   the path exactly rather than by prefix.
 * @param options - Test-friendly transport overrides.
 * @returns The ownership entries plus the total count.
 */
export function getOwnership(
  repoId: string,
  page: number = 1,
  pageSize: number = 50,
  filePath?: string,
  options: TestOptions = {},
): Promise<Ownership> {
  return apiGet<Ownership>(
    ownershipPath(repoId, page, pageSize, filePath),
    options,
  );
}

/**
 * Fetch the files flagged as knowledge silos.
 *
 * @param repoId - The repository's UUID.
 * @param options - Test-friendly transport overrides.
 * @returns The silo entries plus the total count.
 */
export function getKnowledgeSilos(
  repoId: string,
  options: TestOptions = {},
): Promise<Silo> {
  return apiGet<Silo>(siloPath(repoId), options);
}
