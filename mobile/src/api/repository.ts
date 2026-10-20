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

import { apiGet, apiPost, type ApiRequestOptions } from "@/api/client";

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

/**
 * Body accepted by the create endpoint.
 *
 * ``github_url`` is the only required field. ``branch`` and ``commit_sha``
 * narrow the ingest to a specific snapshot; omitting both ingests the
 * repository's default branch tip.
 */
export interface CreateRepositoryRequest {
  /** The GitHub URL of the repository to ingest. */
  github_url: string;
  /** Branch to ingest. ``null`` means "whatever the default branch is". */
  branch?: string | null;
  /** Commit SHA to pin the ingest to. ``null`` means "the branch tip". */
  commit_sha?: string | null;
}

/**
 * Response returned by the create endpoint.
 *
 * Note the naming asymmetry with the ``Repository`` record: the create
 * response uses ``repo_num``, while the repository payload itself uses
 * ``repo_number``. Both are the user-scoped integer.
 */
export interface CreateRepositoryResponse {
  /** UUID of the newly created repository. */
  repo_id: string;
  /** User-scoped integer the repository's routes are keyed on. */
  repo_num: number;
}

/**
 * Create a repository record and queue background ingestion.
 *
 * The endpoint answers 202 immediately -- ingestion runs in a background
 * worker, so a successful response means "queued", not "analysed".
 *
 * @param payload - The repository to create and the version to ingest.
 * @param options - Test-friendly transport overrides.
 * @returns The new repository's identifiers.
 */
export function createRepository(
  payload: CreateRepositoryRequest,
  options: TestOptions = {},
): Promise<CreateRepositoryResponse> {
  return apiPost<CreateRepositoryResponse>(LIST_PATH, payload, options);
}
