/**
 * Glossary search state with paginated fetching.
 * @module UseGlossarySearch
 */

import Glossary from "@/types/glossary";
import { useState } from "react";
import { useForm } from "react-hook-form";

const PAGE_SIZE = 20;

/**
 * Search form fields.
 */
type SearchForm = { query: string };

/**
 * Manages glossary search, pagination, and reset for a repository.
 *
 * @param repoId - ID of the repository whose glossary to search.
 * @returns Form helpers, results, paging controls, and loading flag.
 */
export function useGlossarySearch(repoId: string) {
  const [results, setResults] = useState<Glossary | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [lastQuery, setLastQuery] = useState("");

  const form = useForm<SearchForm>({ defaultValues: { query: "" } });

  /**
   * Fetches one results page for a query.
   *
   * @param query - Search term matched against name and definition.
   * @param p - 1-indexed page number.
   */
  async function fetchPage(query: string, p: number) {
    setLoading(true);
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${repoId}/glossary/search?q=${encodeURIComponent(query)}&page=${p}&page_size=${PAGE_SIZE}`,
        { credentials: "include", cache: "no-store" },
      );
      if (!res.ok) throw new Error("Failed to fetch glossary");
      const data: Glossary = await res.json();
      setResults(data);
      setPage(p);
    } finally {
      setLoading(false);
    }
  }

  const onSubmit = form.handleSubmit(async ({ query }) => {
    setLastQuery(query);
    await fetchPage(query, 1);
  });

  /**
   * Navigates to another page of the last submitted query.
   *
   * @param p - 1-indexed page number to load.
   */
  const goToPage = (p: number) => fetchPage(lastQuery, p);

  /**
   * Clears results and restores the pristine form state.
   */
  const reset = () => {
    setResults(null);
    setPage(1);
    setLastQuery("");
    form.reset();
  };

  return { form, onSubmit, results, page, loading, goToPage, reset };
}
