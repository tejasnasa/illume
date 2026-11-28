/**
 * Search and status filtering for the dashboard list.
 *
 * @module repoFilter
 *
 * Port of the filter in ``client/src/components/RepoCollection.tsx``: a
 * case-insensitive match on the repository name or its URL, and a status
 * bucket (`ready`, `ingesting`, `failed`) that mirrors the web client's
 * `statusView`.
 */

import { isFailedStatus, isReadyStatus } from "@/lib/repoStatus";

/** The buckets the status filter offers. */
export type StatusFilter = "all" | "ready" | "ingesting" | "failed";

/** The filter chips, in order. */
export const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "ready", label: "Ready" },
  { value: "ingesting", label: "Ingesting" },
  { value: "failed", label: "Failed" },
];

/** The slice of a repository the filter reads. */
export interface FilterableRepo {
  name: string;
  github_url: string;
  status: string;
}

/**
 * The bucket a repository's status falls in.
 *
 * @param status - A repository status string.
 * @returns `ready`, `failed` or `ingesting`.
 */
export function statusBucket(status: string | null | undefined): Exclude<StatusFilter, "all"> {
  if (isReadyStatus(status)) return "ready";
  if (isFailedStatus(status)) return "failed";
  return "ingesting";
}

/**
 * Narrow a list by a search string and a status bucket.
 *
 * @param repos - Every repository.
 * @param query - The search text; blank matches everything.
 * @param status - The bucket, or `all`.
 * @returns The matching repositories in their original order.
 */
export function filterRepos<T extends FilterableRepo>(
  repos: readonly T[],
  query: string,
  status: StatusFilter,
): T[] {
  const needle = query.trim().toLowerCase();
  return repos.filter((repo) => {
    if (status !== "all" && statusBucket(repo.status) !== status) return false;
    if (!needle) return true;
    return (
      repo.name.toLowerCase().includes(needle) ||
      repo.github_url.toLowerCase().includes(needle)
    );
  });
}

/**
 * The count line under the dashboard title.
 *
 * @param repos - Every repository.
 * @returns For example `3 repositories · 1 ingesting`.
 */
export function countLine(repos: readonly FilterableRepo[]): string {
  const ingesting = repos.filter((r) => statusBucket(r.status) === "ingesting").length;
  const base = `${repos.length} ${repos.length === 1 ? "repository" : "repositories"}`;
  return ingesting > 0 ? `${base} · ${ingesting} ingesting` : base;
}
