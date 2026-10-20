/**
 * The authenticated user's GitHub repository list.
 *
 * @module useGitHubRepos
 *
 * Fetches the user's repositories through the backend's GitHub proxy and
 * exposes them for the picker list.
 *
 * **Filtering is client-side on purpose.** The proxy accepts a name filter
 * but applies it *after* it has fetched a page from GitHub, so a filtered
 * page can come back short while later pages still hold matches -- the
 * picker would then stop paging and never show them. Fetching whole pages
 * and filtering here keeps every match reachable, and the search box
 * filters instantly instead of waiting on a round trip.
 */

import { useInfiniteQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";

import { GITHUB_REPOS_PER_PAGE, getMyGitHubRepos } from "@/api/github";
import { queryKeys } from "@/api/queryKeys";
import type { GitHubRepo } from "@/types/github";

/**
 * Filter repositories by a case-insensitive substring of their name.
 *
 * Matches the proxy's own filter semantics (a substring of ``name``,
 * case-insensitive) so the mobile list and the backend agree on what a
 * query means.
 *
 * @param repos - Repositories to filter.
 * @param query - The search term. An empty term matches everything.
 * @returns The repositories whose name contains the term.
 */
export function filterReposByName(
  repos: readonly GitHubRepo[],
  query: string,
): GitHubRepo[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return repos as GitHubRepo[];
  return repos.filter((repo) => repo.name.toLowerCase().includes(needle));
}

/** State and actions returned by :func:`useGitHubRepos`. */
export interface UseGitHubReposResult {
  /** The repositories matching the current search term. */
  repos: GitHubRepo[];
  /** Every repository fetched so far, unfiltered. */
  allRepos: GitHubRepo[];
  /** True while the first page is in flight. */
  isLoading: boolean;
  /** True while any page is in flight (including background pages). */
  isFetching: boolean;
  /** True when the last request failed. */
  isError: boolean;
  /** The failure from the last request, if any. */
  error: Error | null;
  /** True when more pages are available on the server. */
  hasMore: boolean;
  /** Load the next page of repositories. */
  fetchMore: () => void;
  /** Set the search term. */
  setSearch: (value: string) => void;
  /** The current search term. */
  search: string;
}

/**
 * Load the authenticated user's GitHub repositories, page by page.
 *
 * @returns The filtered list plus paging and search state.
 */
export function useGitHubRepos(): UseGitHubReposResult {
  const [search, setSearch] = useState("");

  const query = useInfiniteQuery({
    queryKey: queryKeys.github.myRepos(),
    queryFn: ({ pageParam }) => getMyGitHubRepos(pageParam),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _allPages, lastPageParam) =>
      // A short page means GitHub has no more repositories. The proxy
      // returns whole pages, so this is an exact end-of-list signal.
      lastPage.length < GITHUB_REPOS_PER_PAGE ? undefined : lastPageParam + 1,
  });

  const allRepos = useMemo(
    () => (query.data?.pages ?? []).flat(),
    [query.data],
  );
  const repos = useMemo(
    () => filterReposByName(allRepos, search),
    [allRepos, search],
  );

  const hasMore = query.hasNextPage === true;
  const fetchNextPage = query.fetchNextPage;

  const fetchMore = useCallback(() => {
    if (query.hasNextPage && !query.isFetching) {
      void fetchNextPage();
    }
  }, [query.hasNextPage, query.isFetching, fetchNextPage]);

  // A search that matches nothing in the pages loaded so far would leave
  // the list empty and the user with nothing to scroll -- and therefore
  // no trigger to load the next page. Keep pulling while the filtered
  // result is empty and more pages remain.
  useEffect(() => {
    if (search.trim() && repos.length === 0 && hasMore && !query.isFetching) {
      void fetchNextPage();
    }
  }, [search, repos.length, hasMore, query.isFetching, fetchNextPage]);

  const isError = query.isError;
  const error = (query.error as Error | null) ?? null;

  return {
    repos,
    allRepos,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    isError,
    error,
    hasMore,
    fetchMore,
    setSearch: useCallback((value: string) => setSearch(value), []),
    search,
  };
}
