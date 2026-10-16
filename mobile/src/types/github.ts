/**
 * GitHub proxy response shapes (repos, branches, commits).
 * @module GitHubTypes
 */

/**
 * Repository entry from the authenticated user's GitHub account.
 */
export interface GitHubRepo {
  full_name: string;
  name: string;
  private: boolean;
  default_branch: string;
  description: string | null;
  language: string | null;
  updated_at: string;
  html_url: string;
  stargazers_count: number;
}

/**
 * Branch with head SHA and default-branch marker.
 */
export interface GitHubBranch {
  name: string;
  sha: string;
  is_default: boolean;
}

/**
 * Single commit with first-line message and author details.
 */
export interface GitHubCommit {
  sha: string;
  short_sha: string;
  message: string;
  author_name: string;
  author_avatar: string | null;
  authored_at: string;
}

/**
 * Commit merged across branches with parent SHAs and branch names.
 */
export interface GitHubMultiBranchCommit extends GitHubCommit {
  parents: string[];
  branches: string[];
}
