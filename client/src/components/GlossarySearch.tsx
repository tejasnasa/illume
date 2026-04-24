"use client";

import { useGlossarySearch } from "@/hooks/useGlossarySearch";
import {
  BookOpenTextIcon,
  MagnifyingGlassIcon,
  XIcon,
} from "@phosphor-icons/react/dist/ssr";
import GlossaryEntry from "./ui/GlossaryEntry";

export default function GlossarySearch({
  repoId,
  children,
  github_url,
}: {
  repoId: string;
  children: React.ReactNode;
  github_url: string;
}) {
  const { form, onSubmit, results, page, loading, goToPage, reset } =
    useGlossarySearch(repoId);
  const isSearching = results !== null;

  return (
    <div className="w-full">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-10">
        <div className="flex-1">
          <div>
            <div className="flex items-center gap-3 mb-2 text-(--primary)">
              <BookOpenTextIcon size={28} weight="duotone" />
              <h1 className="text-3xl font-bold text-(--foreground) tracking-tight">
                Codebase Glossary
              </h1>
            </div>
            <p className="text-(--muted-foreground)">
              Domain terms, core classes, and functions explained in plain
              English.
            </p>
          </div>
        </div>
        <form onSubmit={onSubmit} className="relative w-full md:w-80 group">
          <MagnifyingGlassIcon
            size={18}
            className="absolute left-4 top-1/2 -translate-y-1/2 text-(--muted-foreground) group-focus-within:text-(--primary) transition-colors"
          />
          <input
            {...form.register("query")}
            placeholder="Search definitions..."
            className="w-full bg-(--secondary)/30 border border-(--border) rounded-sm pl-11 pr-12 py-2.5 text-sm outline-none focus:border-(--primary)/50 focus:ring-2 focus:ring-(--primary)/20 transition-all text-(--foreground)"
          />
          {isSearching && (
            <button
              type="button"
              onClick={reset}
              className="absolute right-3 top-1/2 -translate-y-1/2 p-1.5 rounded-full text-(--muted-foreground) hover:text-(--foreground) hover:bg-(--secondary) transition-colors"
            >
              <XIcon size={14} weight="bold" />
            </button>
          )}
        </form>
      </div>

      {isSearching ? (
        <div className="w-full">
          <div className="flex justify-between items-center mb-6">
            <span className="text-sm font-medium text-(--muted-foreground)">
              {loading ? (
                <span className="flex items-center gap-2">
                  <div className="w-3.5 h-3.5 rounded-full border-2 border-(--primary) border-t-transparent animate-spin" />
                  Searching...
                </span>
              ) : (
                `Showing ${results.entries.length} of ${results.total} entries`
              )}
            </span>
            <div className="flex gap-2">
              <button
                disabled={page <= 1 || loading}
                onClick={() => goToPage(page - 1)}
                className="px-4 py-2 rounded-lg text-sm border border-(--border) hover:bg-(--secondary) disabled:opacity-50 transition-colors"
              >
                Previous
              </button>
              <button
                disabled={
                  page >= Math.ceil(results.total / results.page_size) ||
                  loading
                }
                onClick={() => goToPage(page + 1)}
                className="px-4 py-2 rounded-lg text-sm border border-(--border) hover:bg-(--secondary) disabled:opacity-50 transition-colors"
              >
                Next
              </button>
            </div>
          </div>
          {results.entries.length === 0 ? (
            <div className="text-center py-24 glass-card rounded-2xl text-(--muted-foreground)">
              No glossary entries found matching your query.
            </div>
          ) : (
            <div className="space-y-4">
              {results.entries.map((entry, idx) => (
                <GlossaryEntry
                  key={entry.id}
                  entry={entry}
                  start={(page - 1) * results.page_size + 1}
                  github_url={github_url}
                  idx={idx}
                />
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="w-full">{children}</div>
      )}
    </div>
  );
}
