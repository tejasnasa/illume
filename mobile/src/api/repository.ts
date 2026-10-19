/**
 * Repository listing and detail fetches.
 *
 * @module RepositoryApi
 *
 * Each function is a thin wrapper over :func:`apiGet` that forwards the
 * test-friendly options (``backendUrl``, ``fetchImpl``) so unit tests
 * can drive the network without monkey-patching globals. Real callers
 * leave these unset and the production wrapper handles auth + base URL.
 */

import Repository from "@/types/repository";

import { apiGet, type ApiRequestOptions } from "@/api/client";

type TestOptions = Omit<ApiRequestOptions, "method" | "body">;

/**
 * Backend route for the user's repositories list (newest first; see
 * ``server/app/api/v1/repository.py`` for ordering).
 */
const LIST_PATH = "/api/v1/repository";

/**
 * Backend route for a single repository, keyed by the user-scoped
 * ``repo_number`` (the dashboard links use it, not the UUID).
 */
function detailPath(repoNumber: number | string): string {
  return `/api/v1/repository/${repoNumber}`;
}

/**
 * Fetch every repository belonging to the caller, newest first.
 *
 * The backend already truncates ``architecture_summary`` server-side, so
 * the response can be rendered directly without an extra clamp pass.
 */
export function getRepositories(
  options: TestOptions = {},
): Promise<Repository[]> {
  return apiGet<Repository[]>(LIST_PATH, options);
}

/**
 * Fetch one repository by its user-scoped ``repo_number``.
 */
export function getRepository(
  repoNumber: number | string,
  options: TestOptions = {},
): Promise<Repository> {
  return apiGet<Repository>(detailPath(repoNumber), options);
}
