/**
 * GitHub proxy fetches using the linked OAuth token (client-side).
 * @module GitHubApi
 */

import {
  GitHubBranch,
  GitHubCommit,
  GitHubMultiBranchCommit,
  GitHubRepo,
} from "@/types/github";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "";

/**
 * Lists the authenticated user's GitHub repositories, newest first.
 *
 * @param page - 1-indexed page number.
 * @param search - Case-insensitive name substring filter.
 * @param signal - Optional abort signal to cancel in-flight requests.
 * @returns Filtered repository items for the requested page.
 * @throws Error if GitHub is not linked or the fetch fails.
 */
export async function getMyGitHubRepos(
  page: number = 1,
  search: string = "",
  signal?: AbortSignal,
): Promise<GitHubRepo[]> {
  const query = new URLSearchParams({
    page: page.toString(),
    q: search,
  });
  const res = await fetch(
    `${BACKEND_URL}/api/v1/github/repos?${query}&sort=updated&direction=desc`,
    {
      headers: {
        "Content-Type": "application/json",
      },
      credentials: "include",
      signal,
    },
  );

  if (!res.ok) {
    // 403 specifically means the OAuth account isn't linked yet.
    if (res.status === 403) {
      throw new Error("GitHub account not linked");
    }
    throw new Error("Failed to fetch GitHub repositories");
  }

  return res.json();
}

/**
 * Lists branches for a GitHub repository with the default flagged.
 *
 * @param owner - GitHub repository owner.
 * @param repo - GitHub repository name.
 * @returns Branch items marking which one is the default.
 * @throws Error if the fetch fails.
 */
export async function getRepoBranches(
  owner: string,
  repo: string,
): Promise<GitHubBranch[]> {
  const res = await fetch(
    `${BACKEND_URL}/api/v1/github/repos/${owner}/${repo}/branches`,
    {
      credentials: "include",
    },
  );

  if (!res.ok) {
    throw new Error("Failed to fetch branches");
  }

  return res.json();
}

/**
 * Lists commits for a branch or ref with pagination.
 *
 * @param owner - GitHub repository owner.
 * @param repo - GitHub repository name.
 * @param sha - Optional branch or commit ref to list from.
 * @param page - 1-indexed page number.
 * @returns Commit items with first-line messages.
 * @throws Error if the fetch fails.
 */
export async function getRepoCommits(
  owner: string,
  repo: string,
  sha?: string,
  page: number = 1,
): Promise<GitHubCommit[]> {
  const query = new URLSearchParams({
    sha: sha || "",
    page: page.toString(),
  });
  const res = await fetch(
    `${BACKEND_URL}/api/v1/github/repos/${owner}/${repo}/commits?${query}`,
    {
      credentials: "include",
    },
  );

  if (!res.ok) {
    throw new Error("Failed to fetch commits");
  }

  return res.json();
}

/**
 * Lists recent commits merged across branches, newest first.
 *
 * @param owner - GitHub repository owner.
 * @param repo - GitHub repository name.
 * @returns Up to 100 merged commits with branch attribution.
 * @throws Error if the fetch fails.
 */
export async function getRepoCommitsMultiBranch(
  owner: string,
  repo: string,
): Promise<GitHubMultiBranchCommit[]> {
  const res = await fetch(
    `${BACKEND_URL}/api/v1/github/repos/${owner}/${repo}/commits-multibranch`,
    {
      credentials: "include",
    },
  );

  if (!res.ok) {
    throw new Error("Failed to fetch multibranch commits");
  }

  return res.json();
}
