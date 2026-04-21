"use client";

import { useGlossarySearch } from "@/hooks/useGlossarySearch";
import Button from "./ui/Button";
import Input from "./ui/Input";

const PAGE_SIZE = 20;

export default function GlossarySearch({
  repoId,
  children,
}: {
  repoId: string;
  children: React.ReactNode;
}) {
  const { form, onSubmit, results, page, loading, goToPage, reset } =
    useGlossarySearch(repoId);
  const isSearching = results !== null;
  const totalPages = results ? Math.ceil(results.total / results.page_size) : 0;
  const start = (page - 1) * (results?.page_size ?? PAGE_SIZE) + 1;

  return (
    <>
      <form onSubmit={onSubmit} className="flex gap-2 mb-4 shrink-0">
        <Input
          {...form.register("query")}
          placeholder="Search glossary..."
          className="flex-1 "
        />
        <Button
          type="submit"
          loading={loading}
          className="px-4 py-1.5 text-sm border rounded-sm disabled:opacity-50 transition-colors"
        >
          {loading ? "Search" : "Search"}
        </Button>
        {isSearching && (
          <Button type="button" onClick={reset}>
            Clear
          </Button>
        )}
      </form>

      {!isSearching ? (
        children
      ) : results.entries.length === 0 ? (
        <p className="text-sm text-(--muted-foreground)">No results found.</p>
      ) : (
        <>
          <p className="text-xs text-(--muted-foreground) mb-2 shrink-0">
            {results.total} result{results.total !== 1 ? "s" : ""}
          </p>
          <ol className="space-y-2 overflow-scroll flex-1">
            {results.entries.map((entry, i) => (
              <li key={entry.id} className="border-b pb-2">
                <h3 className="font-semibold text-sm">
                  <span className="text-muted-foreground mr-2">
                    {start + i}.
                  </span>
                  {entry.name} ({entry.file_path})
                </h3>
                <p className="text-sm text-muted-foreground">
                  {entry.definition}
                </p>
              </li>
            ))}
          </ol>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 pt-4 border-t mt-2 shrink-0">
              <Button
                onClick={() => goToPage(page - 1)}
                disabled={page <= 1 || loading}
                className="disabled:opacity-40"
              >
                ← Prev
              </Button>
              <div className="flex gap-1">
                {Array.from({ length: totalPages }, (_, i) => i + 1).map(
                  (p) => (
                    <Button
                      key={p}
                      onClick={() => goToPage(p)}
                      disabled={loading}
                      className={` ${
                        p === page ? "font-semibold" : "hover:opacity-100"
                      }`}
                    >
                      {p}
                    </Button>
                  ),
                )}
              </div>
              <Button
                onClick={() => goToPage(page + 1)}
                disabled={page >= totalPages || loading}
                className="disabled:opacity-40"
              >
                Next →
              </Button>
            </div>
          )}
        </>
      )}
    </>
  );
}
