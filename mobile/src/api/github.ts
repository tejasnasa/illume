/**
 * GitHub proxy fetches.
 *
 * @module GitHubApi
 *
 * The backend proxies every GitHub call with the caller's stored
 * ``github_access_token`` -- the mobile app never sees or sends a GitHub
 * token itself, only its own Illume bearer token. The proxy routes are:
 *
 * - ``GET /api/v1/github/repos`` -- the authenticated user's repositories.
 * - ``GET /api/v1/github/repos/{owner}/{repo}/branches`` -- branches, with
 *   the default one flagged.
 * - ``GET /api/v1/github/repos/{owner}/{repo}/commits-multibranch`` --
 *   recent commits merged across up to five branches, newest first.
 *
 * Every call goes through :func:`apiGet`, so the bearer token is injected
 * and non-2xx responses become :class:`ApiError` instances.
 */

import { apiGet, type ApiRequestOptions } from "@/api/client";
import { ApiError } from "@/lib/apiError";
import type {
  GitHubBranch,
  GitHubMultiBranchCommit,
  GitHubRepo,
} from "@/types/github";

type TestOptions = Omit<ApiRequestOptions, "method" | "body">;

/**
 * Repositories requested per page.
 *
 * The server caps ``per_page`` at 100. A large page keeps the number of
 * round trips low on a phone connection; the picker pages through the list
 * as the user scrolls.
 */
export const GITHUB_REPOS_PER_PAGE = 100;

/**
 * Shown when the backend reports that no GitHub account is linked.
 *
 * The proxy answers 403 when the user has no stored ``github_access_token``.
 * That is a different problem from an expired Illume session (401), so it
 * gets its own copy rather than the generic "not authorized" wording.
 */
export const GITHUB_NOT_LINKED_MESSAGE =
  "GitHub account not linked. Please re-authenticate.";

/**
 * Wraps a proxy call, rewriting the one status that means something
 * specific to the caller.
 *
 * The backend's 403 is always "GitHub account not linked" -- the proxy
 * checks the stored token before it talks to GitHub -- so the message can
 * be replaced with the copy the picker shows. Every other failure keeps
 * the server's own ``detail``, which is more precise than a generic
 * fallback (it distinguishes "Repository not found on GitHub" from
 * "Could not reach GitHub").
 *
 * @param promise - The in-flight proxy call.
 * @param fallback - Message used when the server sent no detail at all.
 * @returns The parsed body.
 * @throws ApiError with a rewritten message for a 403.
 */
async function withGitHubMessage<T>(
  promise: Promise<T>,
  fallback: string,
): Promise<T> {
  try {
    return await promise;
  } catch (error) {
    if (error instanceof ApiError) {
      throw new ApiError({
        kind: error.kind,
        status: error.status,
        message:
          error.status === 403
            ? GITHUB_NOT_LINKED_MESSAGE
            : hasServerDetail(error.body)
              ? error.message
              : fallback,
        body: error.body,
        cause: error.cause,
      });
    }
    throw error;
  }
}

/**
 * Whether the error body carried a reason worth showing.
 *
 * The transport already falls back to a generic per-status message when
 * the body has no ``detail``; when that happens the *proxy's* fallback
 * is the better copy, because it names the operation that failed.
 *
 * @param body - The parsed response body.
 * @returns True when the body carried a usable detail.
 */
function hasServerDetail(body: unknown): boolean {
  if (!body || typeof body !== "object") return false;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail.trim().length > 0;
  if (Array.isArray(detail)) return detail.length > 0;
  return detail !== undefined && detail !== null;
}

/**
 * List the authenticated user's GitHub repositories, newest first.
 *
 * The name filter is applied by the *client*, not the server. The proxy
 * filters a GitHub page after fetching it, so a filtered page can come
 * back short while later pages still hold matches -- a server-side filter
 * cannot say "there is nothing more". Filtering the full list locally
 * keeps every match reachable.
 *
 * @param page - 1-indexed page to fetch.
 * @param options - Test-friendly transport overrides.
 * @returns The repositories on that page.
 */
export function getMyGitHubRepos(
  page: number = 1,
  options: TestOptions = {},
): Promise<GitHubRepo[]> {
  const query = new URLSearchParams({
    page: page.toString(),
    per_page: GITHUB_REPOS_PER_PAGE.toString(),
  });

  return withGitHubMessage(
    apiGet<GitHubRepo[]>(`/api/v1/github/repos?${query.toString()}`, options),
    "Failed to fetch GitHub repositories",
  );
}

/**
 * List the branches of a GitHub repository, with the default one flagged.
 *
 * @param owner - GitHub repository owner.
 * @param repo - GitHub repository name.
 * @param options - Test-friendly transport overrides.
 * @returns The repository's branches.
 */
export function getRepoBranches(
  owner: string,
  repo: string,
  options: TestOptions = {},
): Promise<GitHubBranch[]> {
  return withGitHubMessage(
    apiGet<GitHubBranch[]>(
      `/api/v1/github/repos/${owner}/${repo}/branches`,
      options,
    ),
    "Failed to fetch branches",
  );
}

/**
 * List recent commits merged across the repository's branches, newest
 * first.
 *
 * The proxy fetches the default branch plus up to four others, dedupes
 * commits by SHA while recording every branch each one appears on, and
 * returns the 100 most recent.
 *
 * @param owner - GitHub repository owner.
 * @param repo - GitHub repository name.
 * @param options - Test-friendly transport overrides.
 * @returns The merged commit list.
 */
export function getRepoCommitsMultiBranch(
  owner: string,
  repo: string,
  options: TestOptions = {},
): Promise<GitHubMultiBranchCommit[]> {
  return withGitHubMessage(
    apiGet<GitHubMultiBranchCommit[]>(
      `/api/v1/github/repos/${owner}/${repo}/commits-multibranch`,
      options,
    ),
    "Failed to fetch multibranch commits",
  );
}
