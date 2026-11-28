/**
 * TanStack Query hook for the onboarding guide.
 *
 * @module useRepoGuide
 *
 * The guide is keyed by the repository's UUID and only exists once the
 * pipeline has finished, so the hook takes an ``enabled`` flag the caller
 * sets from ``status === 'ready'``. Querying it earlier would spend a
 * request on a 404 that is guaranteed to fail.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import type { default as Guide, ActivityItem, Stats } from "@/types/guide";
import { getGuide, getRecentActivity, getStats } from "@/api/guide";
import { queryKeys } from "@/api/queryKeys";

/**
 * Whether a query has enough to run against.
 *
 * @param repoId - The repository UUID, if it is known yet.
 * @param enabled - Whether the caller wants the data at all.
 * @returns ``true`` when the query should fire.
 */
function canFetch(
  repoId: string | undefined,
  enabled: boolean,
): repoId is string {
  return enabled && typeof repoId === "string" && repoId.length > 0;
}

/**
 * Fetch the onboarding guide for a repository.
 *
 * @param repoId - The repository UUID.
 * @param enabled - Whether the guide is available yet.
 * @returns The guide query.
 */
export function useRepositoryGuide(
  repoId: string | undefined,
  enabled = true,
): UseQueryResult<Guide, Error> {
  return useQuery({
    queryKey: queryKeys.repositories.guide(repoId ?? ""),
    queryFn: () => getGuide(repoId as string),
    enabled: canFetch(repoId, enabled),
  });
}

/**
 * Fetch the aggregated stats for a repository.
 *
 * @param repoId - The repository UUID.
 * @param enabled - Whether the repository is ready.
 * @returns The stats query.
 */
export function useRepositoryStats(
  repoId: string | undefined,
  enabled = true,
): UseQueryResult<Stats, Error> {
  return useQuery({
    queryKey: queryKeys.repositories.stats(repoId ?? ""),
    queryFn: () => getStats(repoId as string),
    enabled: canFetch(repoId, enabled),
  });
}

/**
 * Fetch the latest pull requests and commits.
 *
 * @param repoId - The repository UUID.
 * @param enabled - Whether the repository is ready.
 * @returns The activity query.
 */
export function useRepositoryActivity(
  repoId: string | undefined,
  enabled = true,
): UseQueryResult<ActivityItem[], Error> {
  return useQuery({
    queryKey: queryKeys.repositories.activity(repoId ?? ""),
    queryFn: () => getRecentActivity(repoId as string),
    enabled: canFetch(repoId, enabled),
  });
}
