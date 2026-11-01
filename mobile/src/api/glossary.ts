/**
 * Glossary browsing and search fetches.
 *
 * @module GlossaryApi
 *
 * Port of ``client/src/api/glossary.ts``. The backend exposes two routes
 * under the repository prefix:
 *
 * - ``GET /api/v1/repository/{repo_id}/glossary`` -- the whole glossary,
 *   ordered alphabetically by term, paginated.
 * - ``GET /api/v1/repository/{repo_id}/glossary/search`` -- the same list
 *   narrowed to the entries whose name *or* definition contains the term.
 *
 * The search lives on its own path rather than as a ``?q=`` parameter on the
 * browse route. The web client's ``GetGlossarySearchResults`` helper still
 * sends ``?q=`` to the browse route, which the server ignores -- it has
 * always been the hook (``client/src/hooks/useGlossarySearch.ts``) that calls
 * ``/glossary/search`` directly, and that is the route the server actually
 * serves. The mobile client calls the route the server exposes.
 *
 * The repository is addressed by its UUID, not by its user-scoped number: the
 * glossary routes are typed as a UUID, so mixing the two up returns a 404
 * that reads like "no glossary yet" rather than "wrong id".
 *
 * Both calls go through :func:`apiGet`, so the bearer token is injected and a
 * non-2xx response becomes an ``ApiError`` carrying the server's message.
 */

import type { default as Glossary } from "@/types/glossary";

import { apiGet, type ApiRequestOptions } from "@/api/client";

type TestOptions = Omit<ApiRequestOptions, "method" | "body">;

/**
 * Entries fetched per page.
 *
 * The web client browses ten at a time and searches twenty; the mobile
 * client uses one page size for both, because the two lists are the same
 * list on the phone and a reader who has seen one page size has seen them
 * all. The server caps the page size at a hundred.
 */
export const GLOSSARY_PAGE_SIZE = 20;

/**
 * One glossary term, as the server returns it.
 *
 * The payload type declares the entries inline, so the single-entry shape is
 * derived from it rather than written out twice.
 */
export type GlossaryEntryItem = Glossary["entries"][number];

/**
 * Build the path for a repository's glossary.
 *
 * @param repoId - The repository's UUID.
 * @param page - 1-indexed page number.
 * @param pageSize - Entries per page.
 * @returns The absolute API path.
 */
function glossaryPath(
  repoId: string,
  page: number,
  pageSize: number,
): string {
  const query = new URLSearchParams({
    page: page.toString(),
    page_size: pageSize.toString(),
  });

  return `/api/v1/repository/${repoId}/glossary?${query.toString()}`;
}

/**
 * Build the path for a repository's glossary search.
 *
 * @param repoId - The repository's UUID.
 * @param query - The term matched against the name and the definition.
 * @param page - 1-indexed page number.
 * @param pageSize - Entries per page.
 * @returns The absolute API path.
 */
function glossarySearchPath(
  repoId: string,
  query: string,
  page: number,
  pageSize: number,
): string {
  const params = new URLSearchParams({
    q: query,
    page: page.toString(),
    page_size: pageSize.toString(),
  });

  return `/api/v1/repository/${repoId}/glossary/search?${params.toString()}`;
}

/**
 * Browse a repository's glossary.
 *
 * @param repoId - The repository's UUID.
 * @param page - 1-indexed page number. Defaults to the first page.
 * @param pageSize - Entries per page. Defaults to twenty.
 * @param options - Test-friendly transport overrides.
 * @returns The entries on that page plus the total count.
 */
export function getGlossary(
  repoId: string,
  page: number = 1,
  pageSize: number = GLOSSARY_PAGE_SIZE,
  options: TestOptions = {},
): Promise<Glossary> {
  return apiGet<Glossary>(glossaryPath(repoId, page, pageSize), options);
}

/**
 * Search a repository's glossary.
 *
 * The server matches the term case-insensitively against the name and the
 * definition of every entry, so a term that appears only in a definition is
 * found too.
 *
 * @param repoId - The repository's UUID.
 * @param query - The term to match.
 * @param page - 1-indexed page number. Defaults to the first page.
 * @param pageSize - Entries per page. Defaults to twenty.
 * @param options - Test-friendly transport overrides.
 * @returns The matching entries plus the total count.
 */
export function searchGlossary(
  repoId: string,
  query: string,
  page: number = 1,
  pageSize: number = GLOSSARY_PAGE_SIZE,
  options: TestOptions = {},
): Promise<Glossary> {
  return apiGet<Glossary>(
    glossarySearchPath(repoId, query, page, pageSize),
    options,
  );
}
