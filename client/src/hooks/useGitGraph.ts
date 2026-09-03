/**
 * Git branch and multi-branch commit state for the git graph view.
 * @module UseGitGraph
 */

import { getRepoBranches, getRepoCommitsMultiBranch } from "@/api/github";
import { GitHubBranch, GitHubMultiBranchCommit } from "@/types/github";
import { useEffect, useState } from "react";

/**
 * Props identifying the GitHub repository to visualize.
 */
export interface UseGitGraphProps {
  owner: string;
  repo: string;
}

/**
 * Loads branches and merged commit history for a repository.
 *
 * @param owner - GitHub repository owner.
 * @param repo - GitHub repository name.
 * @returns Branches, commits, selection state, and loading/error flags.
 */
export function useGitGraph({ owner, repo }: UseGitGraphProps) {
  const [branches, setBranches] = useState<GitHubBranch[]>([]);
  const [commits, setCommits] = useState<GitHubMultiBranchCommit[]>([]);
  const [defaultBranch, setDefaultBranch] = useState<string>("main");
  const [selectedCommit, setSelectedCommit] = useState<GitHubMultiBranchCommit | null>(null);

  const [loadingBranches, setLoadingBranches] = useState(false);
  const [loadingCommits, setLoadingCommits] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!owner || !repo) return;
    setLoadingBranches(true);
    setError(null);
    getRepoBranches(owner, repo)
      .then((data) => {
        setBranches(data);
        // Prefer the flagged default; fall back to first branch, then "main".
        const defaultB = data.find((b) => b.is_default)?.name || data[0]?.name || "main";
        setDefaultBranch(defaultB);
      })
      .catch((err) => {
        setError(err.message || "Failed to load branches");
      })
      .finally(() => {
        setLoadingBranches(false);
      });
  }, [owner, repo]);

  useEffect(() => {
    if (!owner || !repo) return;
    setLoadingCommits(true);
    setError(null);
    setCommits([]);
    setSelectedCommit(null);

    getRepoCommitsMultiBranch(owner, repo)
      .then((data) => {
        setCommits(data);
      })
      .catch((err) => {
        setError(err.message || "Failed to load git history");
      })
      .finally(() => {
        setLoadingCommits(false);
      });
  }, [owner, repo]);

  return {
    branches,
    commits,
    defaultBranch,
    selectedCommit,
    setSelectedCommit,
    loadingBranches,
    loadingCommits,
    error,
  };
}
