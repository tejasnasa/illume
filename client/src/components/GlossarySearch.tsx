/**
 * Glossary header with live search over codebase definitions.
 * @module GlossarySearch
 */
"use client";

import { useGlossarySearch } from "@/hooks/useGlossarySearch";
import Link from "next/link";
import GlossaryEntry from "./ui/GlossaryEntry";
import { PAGER_BUTTON } from "./ui/pager";

/**
 * Shows the glossary heading and swaps default content for search results.
 *
 * @param repoId - ID of the repository whose glossary to search.
 * @param repoNumber - User-scoped repository number, for chat links.
 * @param countLine - The idle summary under the heading.
 * @param children - Default glossary content shown when idle.
 * @param github_url - Repository URL for source links in entries.
 * @param commitSha Repository's ingested commit, pinned in source links.
 * @param branch Repository's ingested branch, used when the commit is missing.
 * @returns Header with search box plus results or fallback content.
 */
export default function GlossarySearch({
  repoId,
  repoNumber,
  countLine,
  children,
  github_url,
  commitSha,
  branch,
}: {
  repoId: string;
  repoNumber?: number;
  countLine?: string;
  children: React.ReactNode;
  github_url: string;
  commitSha?: string | null;
  branch?: string | null;
}) {
  const { form, onSubmit, results, page, loading, error, goToPage, reset } =
    useGlossarySearch(repoId);
  const isSearching = results !== null;
  const lastPage = results ? Math.max(1, Math.ceil(results.total / results.page_size)) : 1;

  return (
    <div className="flex w-full flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div className="flex flex-col gap-3">
          <p
            aria-hidden="true"
            className="m-0 font-pixel text-[13px] tracking-[0.12em] text-(--muted-foreground)"
          >
            &gt; illume define<span className="caret text-(--accent)">_</span>
          </p>
          <h1 className="m-0 font-pixel text-[clamp(2.4rem,5vw,4.2rem)] leading-none font-normal tracking-[-0.02em]">
            <span className="gradient-text">Codebase Glossary</span>
          </h1>
          <p className="m-0 text-base text-zinc-400">
            {countLine ?? "Domain terms, core classes, and functions explained in plain English."}
          </p>
        </div>
        <form onSubmit={onSubmit} role="search" className="relative w-full sm:w-95">
          <span
            aria-hidden="true"
            className="absolute top-1/2 left-3.5 -translate-y-1/2 font-pixel text-sm text-(--faint-foreground)"
          >
            ⌕
          </span>
          <input
            {...form.register("query")}
            type="search"
            aria-label="Search the glossary"
            placeholder="Search definitions..."
            className="w-full rounded-sm border border-(--border) bg-(--card) py-3 pr-12 pl-9.5 text-sm text-(--foreground) outline-none focus:border-(--accent)"
          />
          {isSearching && (
            <button
              type="button"
              onClick={reset}
              aria-label="Clear search"
              className="absolute top-1/2 right-3 -translate-y-1/2 rounded-sm px-1.5 py-0.5 font-pixel text-xs text-(--muted-foreground) hover:cursor-pointer hover:bg-(--secondary) hover:text-(--foreground)"
            >
              ✕
            </button>
          )}
        </form>
      </header>

      {error && (
        <div
          role="alert"
          className="rounded-sm border border-red-500/25 bg-red-500/5 px-4 py-3 text-sm text-red-300"
        >
          {error}
        </div>
      )}

      {isSearching ? (
        <div className="flex w-full flex-col gap-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span
              aria-live="polite"
              className="font-pixel text-xs tracking-[0.08em] text-(--muted-foreground) uppercase"
            >
              {loading ? (
                <span className="blink">Searching...</span>
              ) : (
                `Showing ${results.entries.length} of ${results.total} entries`
              )}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={page <= 1 || loading}
                onClick={() => goToPage(page - 1)}
                className={`${PAGER_BUTTON} disabled:cursor-default disabled:opacity-40`}
              >
                Previous
              </button>
              <button
                type="button"
                disabled={page >= lastPage || loading}
                onClick={() => goToPage(page + 1)}
                className={`${PAGER_BUTTON} disabled:cursor-default disabled:opacity-40`}
              >
                Next
              </button>
            </div>
          </div>
          {results.entries.length === 0 ? (
            <p className="m-0 rounded-md border border-dashed border-white/12 p-12 text-center font-pixel text-sm text-(--muted-foreground)">
              No terms match.{" "}
              {repoNumber !== undefined ? (
                <Link href={`/repo/${repoNumber}/chat`} className="text-(--accent) hover:underline">
                  Try the chat instead.
                </Link>
              ) : (
                "Try the chat instead."
              )}
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {results.entries.map((entry, idx) => (
                <GlossaryEntry
                  key={entry.id}
                  entry={entry}
                  start={(page - 1) * results.page_size + 1}
                  github_url={github_url}
                  repoNumber={repoNumber}
                  commitSha={commitSha}
                  branch={branch}
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
