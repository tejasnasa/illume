/**
 * The authenticated user's GitHub repository list.
 *
 * @module useGitHubRepos
 *
 * Fetches the user's repositories through the backend's GitHub proxy and
 * exposes them for the picker list.
 *
 * **Search is server-side.** The proxy scans the user's whole list for a
 * name match and paginates the matches, so a typed term reaches
 * repositories well beyond the pages already loaded. The term is debounced
 * so a request is not sent per keystroke, and it is part of the query key,
 * so each term keeps its own cached pages.
 */

import { useInfiniteQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";

import { GITHUB_REPOS_PER_PAGE, getMyGitHubRepos } from "@/api/github";
import { queryKeys } from "@/api/queryKeys";
import type { GitHubRepo } from "@/types/github";

/** How long the search box rests before the term is sent to the server. */
export const SEARCH_DEBOUNCE_MS = 400;

/** State and actions returned by :func:`useGitHubRepos`. */
export interface UseGitHubReposResult {
  /** The repositories matching the settled search term. */
  repos: GitHubRepo[];
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
  const [settled, setSettled] = useState("");

  useEffect(() => {
    const handle = setTimeout(() => setSettled(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [search]);

  const query = useInfiniteQuery({
    queryKey: queryKeys.github.myRepos(settled),
    queryFn: ({ pageParam }) => getMyGitHubRepos(pageParam, settled),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _allPages, lastPageParam) =>
      // A short page means GitHub has no more repositories. The proxy
      // returns whole pages, so this is an exact end-of-list signal.
      lastPage.length < GITHUB_REPOS_PER_PAGE ? undefined : lastPageParam + 1,
  });

  const repos = useMemo(
    () => (query.data?.pages ?? []).flat(),
    [query.data],
  );

  const hasMore = query.hasNextPage === true;
  const fetchNextPage = query.fetchNextPage;

  const fetchMore = useCallback(() => {
    if (query.hasNextPage && !query.isFetching) {
      void fetchNextPage();
    }
  }, [query.hasNextPage, query.isFetching, fetchNextPage]);

  const isError = query.isError;
  const error = (query.error as Error | null) ?? null;

  return {
    repos,
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
