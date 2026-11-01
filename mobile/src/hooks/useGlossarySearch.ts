/**
 * Glossary search state: the query, the debounce, and the results.
 *
 * @module UseGlossarySearch
 *
 * Port of ``client/src/hooks/useGlossarySearch.ts``, reshaped for a phone.
 *
 * The web version is a form: the reader types, presses Enter, and the
 * results replace the listing underneath. A phone has no Enter key to
 * press -- its keyboard's return key is a "search" action most readers never
 * think about -- so the search here runs as the reader types, with the
 * keystrokes collected first.
 *
 * Two things are ported rather than invented:
 *
 * - **The debounce window.** The web client collects keystrokes for 400 ms
 *   before it acts on them (``client/src/components/RepoPickerModal.tsx``),
 *   and that is the window used here. A phone keyboard fires a change event
 *   per character, so without it a six-letter term would send six requests.
 * - **The filtering.** The filter lives on the server: the backend matches
 *   the term against the name *and* the definition of every entry
 *   (``server/app/api/v1/glossary.py``). The client asks the search route
 *   for the term and shows what comes back, so both clients agree on what a
 *   term means.
 *
 * The listing itself -- the browse route, with no term -- is the same
 * screen before the reader types anything, which is how the web page opens
 * too.
 *
 * The query text is local state: it belongs to the search box, not to the
 * cache. Only the *settled* term reaches React Query, and it is part of the
 * cache key, so a term and the listing it replaced never share an entry.
 */

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  GLOSSARY_PAGE_SIZE,
  getGlossary,
  searchGlossary,
  type GlossaryEntryItem,
} from "@/api/glossary";
import { queryKeys } from "@/api/queryKeys";

/**
 * How long the search box collects keystrokes before acting on them.
 *
 * The same window the web client uses for its search boxes
 * (``client/src/components/RepoPickerModal.tsx``).
 */
export const GLOSSARY_SEARCH_DEBOUNCE_MS = 400;

/** Props identifying the repository whose glossary is searched. */
export interface UseGlossarySearchProps {
  /**
   * The repository's UUID.
   *
   * Not its user-scoped number: the glossary routes are typed as a UUID, so
   * the wrong one is a 404 that reads like "no glossary yet".
   */
  repoId: string | undefined;
  /** Whether the request may run at all. */
  enabled?: boolean;
}

/** State and actions returned by {@link useGlossarySearch}. */
export interface UseGlossarySearchResult {
  /** The text in the search box. */
  query: string;
  /** Replace the text in the search box. */
  setQuery: (value: string) => void;
  /** Clear the search and go back to the whole listing. */
  reset: () => void;
  /** The entries on the current page. */
  entries: GlossaryEntryItem[];
  /** How many entries the current term matched in total. */
  total: number;
  /** The 1-indexed page being shown. */
  page: number;
  /** How many pages the current term spans. */
  pageCount: number;
  /** Whether a term is being searched for. */
  isSearching: boolean;
  /** True while the first request is in flight and nothing is on screen yet. */
  isLoading: boolean;
  /** True while any request is in flight, including a refresh of a term. */
  isFetching: boolean;
  /** The failure message, if the request failed. */
  error: string | null;
  /**
   * Try the request again.
   *
   * A failure has to be recoverable by the reader: a dropped connection
   * on a phone is common, and making them leave the screen and come back
   * is not a reasonable answer to it.
   */
  retry: () => void;
  /** Show another page of the current listing. */
  goToPage: (page: number) => void;
}

/**
 * Search a repository's glossary.
 *
 * @param props - The repository to search and whether the request may run.
 * @returns The query, the debounced results, and the paging controls.
 */
export function useGlossarySearch({
  repoId,
  enabled = true,
}: UseGlossarySearchProps): UseGlossarySearchResult {
  // What the reader has typed. Local state: it is the search box's
  // contents, not server state, and it changes on every keystroke.
  const [query, setQuery] = useState("");
  // The term the reader has settled on. Only this reaches the network.
  const [term, setTerm] = useState("");
  const [page, setPage] = useState(1);

  // The term the last settled request was made with, kept outside the
  // state so the debounce can tell a new term from the same one typed
  // again -- "foo" and " foo " are the same search.
  const settledTerm = useRef("");

  // The debounce. Every keystroke restarts the timer, so the request goes
  // out once the reader has paused. A new term also returns to the first
  // page: page three of the old term means nothing in the new one. Both
  // updates happen in one batch, so the term and the page reach the cache
  // together and only one request is made.
  useEffect(() => {
    const handle = setTimeout(() => {
      const next = query.trim();
      if (next === settledTerm.current) return;

      settledTerm.current = next;
      setTerm(next);
      setPage(1);
    }, GLOSSARY_SEARCH_DEBOUNCE_MS);

    return () => clearTimeout(handle);
  }, [query]);

  const result = useQuery({
    queryKey: queryKeys.repositories.glossary(repoId ?? "", page, term),
    queryFn: () =>
      term.length > 0
        ? searchGlossary(repoId as string, term, page, GLOSSARY_PAGE_SIZE)
        : getGlossary(repoId as string, page, GLOSSARY_PAGE_SIZE),
    enabled: enabled && typeof repoId === "string" && repoId.length > 0,
    // The previous page stays on screen while the next one is fetched, so
    // the list does not blank out under the reader on every term change.
    placeholderData: keepPreviousData,
  });

  const total = result.data?.total ?? 0;
  const pageSize = result.data?.page_size ?? GLOSSARY_PAGE_SIZE;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  const reset = useCallback(() => {
    settledTerm.current = "";
    setQuery("");
    setTerm("");
    setPage(1);
  }, []);

  const goToPage = useCallback(
    (next: number) => {
      setPage(Math.min(Math.max(1, next), pageCount));
    },
    [pageCount],
  );

  return {
    query,
    setQuery,
    reset,
    entries: result.data?.entries ?? [],
    total,
    page,
    pageCount,
    isSearching: term.length > 0,
    // ``isPending`` is only true while there is nothing to show: once a
    // term has been fetched, the placeholder keeps the status successful
    // and only ``isFetching`` says a request is on its way.
    isLoading: result.isPending && result.isFetching,
    isFetching: result.isFetching,
    error: (result.error as Error | null)?.message ?? null,
    retry: () => {
      void result.refetch();
    },
    goToPage,
  };
}
