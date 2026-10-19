/**
 * TanStack Query hooks for the repository list and detail payloads.
 *
 * @module useRepositories
 *
 * The hooks are the only call-site for the :mod:`src.api.repository`
 * transport: query keys live alongside the fetches and the dashboard
 * reads ``data``, ``isLoading`` and ``refetch`` from here. Having one
 * place per domain keeps Phase 5 (creation) and Phase 6 (detail view)
 * honest about cache invalidation -- a refetch after ``createRepository``
 * only needs to land in one helper.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import Repository from "@/types/repository";
import { getRepositories, getRepository } from "@/api/repository";
import { queryKeys } from "@/api/queryKeys";

/**
 * Fetch the caller's repositories.
 *
 * React Query handles loading/error/data, refetch-on-focus (wired by the
 * AppState bridge in Phase 3), and dedup across concurrent subscribers.
 * The list key (``queryKeys.repositories.list``) is stable across calls,
 * so two screens asking for the same data hit one network request.
 */
export function useRepositories(): UseQueryResult<Repository[], Error> {
  return useQuery({
    queryKey: queryKeys.repositories.list(),
    queryFn: getRepositories,
  });
}

/**
 * Fetch a single repository by its user-scoped ``repoNumber``.
 *
 * The query is disabled when ``repoNumber`` is missing or empty so the
 * screen can mount before the route param has resolved; React Query
 * treats an empty key the same as "do not run yet".
 */
export function useRepository(
  repoNumber: number | string | undefined,
): UseQueryResult<Repository, Error> {
  return useQuery({
    queryKey: queryKeys.repositories.detail(String(repoNumber ?? "")),
    queryFn: () => getRepository(repoNumber as number | string),
    enabled: repoNumber !== undefined && repoNumber !== null && String(repoNumber).length > 0,
  });
}
