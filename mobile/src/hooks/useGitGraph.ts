/**
 * Branches and merged commit history for the git timeline.
 *
 * @module UseGitGraph
 *
 * Port of ``client/src/hooks/useGitGraph.ts``. The web version hand-rolled
 * two ``useEffect`` fetches; here the same two payloads come from React
 * Query, so navigating away and back does not re-request them and a
 * rotation does not blank the timeline.
 *
 * The selection state (which commit is pinned for ingest) stays local to
 * the hook -- it is UI state, not server state, and must not be cached.
 */

import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { getRepoBranches, getRepoCommitsMultiBranch } from "@/api/github";
import { queryKeys } from "@/api/queryKeys";
import type { GitHubBranch, GitHubMultiBranchCommit } from "@/types/github";

/** Props identifying the GitHub repository to visualize. */
export interface UseGitGraphProps {
  /** GitHub repository owner. */
  owner: string;
  /** GitHub repository name. */
  repo: string;
}

/** State and actions returned by :func:`useGitGraph`. */
export interface UseGitGraphResult {
  /** The repository's branches. */
  branches: GitHubBranch[];
  /** Recent commits merged across branches, newest first. */
  commits: GitHubMultiBranchCommit[];
  /** The branch the repository's default points at. */
  defaultBranch: string;
  /** The commit pinned for ingest, if any. */
  selectedCommit: GitHubMultiBranchCommit | null;
  /** Pin (or unpin) a commit. */
  setSelectedCommit: (commit: GitHubMultiBranchCommit | null) => void;
  /** True while the branch list is loading. */
  loadingBranches: boolean;
  /** True while the commit list is loading. */
  loadingCommits: boolean;
  /** The failure from either request, if any. */
  error: string | null;
}

/**
 * Load branches and merged commit history for a repository.
 *
 * @param owner - GitHub repository owner.
 * @param repo - GitHub repository name.
 * @returns Branches, commits, selection state, and loading/error flags.
 */
export function useGitGraph({ owner, repo }: UseGitGraphProps): UseGitGraphResult {
  const enabled = Boolean(owner && repo);

  const branchesQuery = useQuery({
    queryKey: queryKeys.github.branches(owner, repo),
    queryFn: () => getRepoBranches(owner, repo),
    enabled,
  });

  const commitsQuery = useQuery({
    queryKey: queryKeys.github.multiBranchCommits(owner, repo),
    queryFn: () => getRepoCommitsMultiBranch(owner, repo),
    enabled,
  });

  const [selectedCommit, setSelectedCommit] =
    useState<GitHubMultiBranchCommit | null>(null);

  // The pinned commit belongs to the repository that was open when it was
  // picked. Switching repositories must not carry it over.
  useEffect(() => {
    setSelectedCommit(null);
  }, [owner, repo]);

  const branches = branchesQuery.data ?? [];

  // Prefer the flagged default; fall back to the first branch, then "main".
  const defaultBranch =
    branches.find((branch) => branch.is_default)?.name ??
    branches[0]?.name ??
    "main";

  const error =
    (branchesQuery.error as Error | null)?.message ??
    (commitsQuery.error as Error | null)?.message ??
    null;

  return {
    branches,
    commits: commitsQuery.data ?? [],
    defaultBranch,
    selectedCommit,
    setSelectedCommit: useCallback(
      (commit: GitHubMultiBranchCommit | null) => setSelectedCommit(commit),
      [],
    ),
    loadingBranches: branchesQuery.isLoading,
    loadingCommits: commitsQuery.isLoading,
    error,
  };
}
