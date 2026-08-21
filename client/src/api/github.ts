import {
  GitHubBranch,
  GitHubCommit,
  GitHubMultiBranchCommit,
  GitHubRepo,
} from "@/types/github";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "";

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
    if (res.status === 403) {
      throw new Error("GitHub account not linked");
    }
    throw new Error("Failed to fetch GitHub repositories");
  }

  return res.json();
}

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
