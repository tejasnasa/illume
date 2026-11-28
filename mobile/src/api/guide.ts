/**
 * Onboarding guide fetch.
 *
 * @module GuideApi
 *
 * Port of ``client/src/api/guide.ts``. The endpoint is keyed by the
 * repository's UUID rather than its user-scoped ``repo_number`` -- the
 * detail endpoint is the odd one out, and mixing the two up returns a 404
 * that reads like "no guide yet" rather than "wrong id".
 *
 * The guide carries the reading order, the critical files and the
 * architecture brief. It only exists once a repository has been indexed,
 * so the caller gates it on ``status === 'ready'``.
 */

import type { default as Guide, ActivityItem, Stats } from "@/types/guide";

import { apiGet, type ApiRequestOptions } from "@/api/client";

type TestOptions = Omit<ApiRequestOptions, "method" | "body">;

/**
 * Build the guide path for a repository.
 *
 * @param repoId - The repository's UUID.
 * @returns The absolute API path.
 */
function guidePath(repoId: string): string {
  return `/api/v1/repository/${repoId}/guide`;
}

/**
 * Fetch the parsed onboarding guide for a repository.
 *
 * @param repoId - The repository's UUID.
 * @param options - Test-friendly transport overrides.
 * @returns The reading order, critical files and architecture brief.
 */
export function getGuide(
  repoId: string,
  options: TestOptions = {},
): Promise<Guide> {
  return apiGet<Guide>(guidePath(repoId), options);
}

/**
 * Fetch the aggregated stats for a repository.
 *
 * @param repoId - The repository's UUID.
 * @param options - Test-friendly transport overrides.
 * @returns Totals, the language breakdown and the top contributors.
 */
export function getStats(
  repoId: string,
  options: TestOptions = {},
): Promise<Stats> {
  return apiGet<Stats>(`/api/v1/repository/${repoId}/stats`, options);
}

/**
 * Fetch the latest merged pull requests and commits.
 *
 * @param repoId - The repository's UUID.
 * @param limit - The most items to return.
 * @param options - Test-friendly transport overrides.
 * @returns Activity items, newest first.
 */
export async function getRecentActivity(
  repoId: string,
  limit = 6,
  options: TestOptions = {},
): Promise<ActivityItem[]> {
  const body = await apiGet<{ items: ActivityItem[] }>(
    `/api/v1/repository/${repoId}/activity?limit=${limit}`,
    options,
  );
  return body.items ?? [];
}
