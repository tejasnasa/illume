import Glossary from "@/types/glossary";
import { useState } from "react";
import { useForm } from "react-hook-form";

const PAGE_SIZE = 20;
type SearchForm = { query: string };

export function useGlossarySearch(repoId: string) {
  const [results, setResults] = useState<Glossary | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [lastQuery, setLastQuery] = useState("");

  const form = useForm<SearchForm>({ defaultValues: { query: "" } });

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

  const goToPage = (p: number) => fetchPage(lastQuery, p);

  const reset = () => {
    setResults(null);
    setPage(1);
    setLastQuery("");
    form.reset();
  };

  return { form, onSubmit, results, page, loading, goToPage, reset };
}
