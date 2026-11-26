/**
 * Paginated glossary route for domain terms and symbols.
 * @module GlossaryPage
 */
import { GetGlossary } from "@/api/glossary";
import { GetRepository } from "@/api/repository";
import GlossarySearch from "@/components/GlossarySearch";
import GlossaryEntry from "@/components/ui/GlossaryEntry";
import GlossaryLetters, { parseInitial } from "@/components/ui/GlossaryLetters";
import { PAGER_BUTTON, PAGER_DISABLED } from "@/components/ui/pager";
import Link from "next/link";

const PAGE_SIZE = 10;

/**
 * Server-rendered glossary page with page-based navigation.
 *
 * @param params - Route params promise resolving to the repository number.
 * @param searchParams - Query params promise carrying the page number and letter.
 * @returns Glossary search wrapper with entries and pagination controls.
 */
export default async function GlossaryPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ page?: string; letter?: string }>;
}) {
  const { id } = await params;
  const repo = await GetRepository(Number(id));
  const { page: pageParam, letter: letterParam } = await searchParams;
  const letter = parseInitial(letterParam);
  // Clamp to page 1 so malformed query values can't produce empty offsets.
  const currentPage = Math.max(1, Number(pageParam) || 1);
  const data = await GetGlossary(repo.id, currentPage, PAGE_SIZE, letter ?? undefined);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const start = (currentPage - 1) * PAGE_SIZE + 1;
  const glossaryHref = (page: number, initial: string | null) =>
    `/repo/${repo.repo_number}/glossary?page=${page}${initial ? `&letter=${encodeURIComponent(initial)}` : ""}`;
  const pageHref = (page: number) => glossaryHref(page, letter);
  const countLine = data
    ? `${data.total.toLocaleString()} ${data.total === 1 ? "term" : "terms"} from the code, explained in plain English.`
    : undefined;

  return (
    <div className="mx-auto w-full max-w-7xl px-4 pt-11 pb-16 sm:px-6">
      <GlossarySearch
        github_url={repo.github_url}
        repoId={repo.id}
        repoNumber={repo.repo_number}
        countLine={countLine}
        commitSha={repo.ingested_commit_sha}
        branch={repo.ingested_branch}
      >
        <div className="flex flex-col gap-5">
          {data && (
            <GlossaryLetters
              active={letter}
              present={data.letters ?? []}
              hrefFor={(initial) => glossaryHref(1, initial)}
            />
          )}
          <nav
            aria-label="Glossary pages"
            className="flex flex-wrap items-center justify-between gap-3"
          >
            <span className="font-pixel text-xs tracking-[0.08em] text-(--muted-foreground) uppercase">
              {data
                ? `Showing ${data.entries.length} of ${data.total} entries`
                : "Failed to load"}
            </span>
            <div className="flex items-center gap-2">
              {currentPage > 1 ? (
                <Link href={pageHref(currentPage - 1)} className={PAGER_BUTTON}>
                  Previous
                </Link>
              ) : (
                <span aria-disabled="true" className={PAGER_DISABLED}>
                  Previous
                </span>
              )}
              <span className="px-2 font-pixel text-xs text-(--muted-foreground)">
                Page {currentPage} of {totalPages}
              </span>
              {currentPage < totalPages ? (
                <Link href={pageHref(currentPage + 1)} className={PAGER_BUTTON}>
                  Next
                </Link>
              ) : (
                <span aria-disabled="true" className={PAGER_DISABLED}>
                  Next
                </span>
              )}
            </div>
          </nav>

          {!data ? (
            <div
              role="alert"
              className="rounded-sm border border-red-500/25 bg-red-500/5 p-5 text-sm text-red-300"
            >
              Failed to load glossary data.
            </div>
          ) : data.entries.length === 0 ? (
            <p className="m-0 rounded-md border border-dashed border-white/12 p-12 text-center font-pixel text-sm text-(--muted-foreground)">
              {letter ? (
                <>
                  No terms start with {letter === "#" ? "anything but a letter" : letter}.{" "}
                  <Link href={glossaryHref(1, null)} className="text-(--accent) hover:underline">
                    Show all
                  </Link>
                </>
              ) : (
                "No glossary entries found."
              )}
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {data.entries.map((entry, idx) => (
                <GlossaryEntry
                  key={entry.id}
                  entry={entry}
                  start={start}
                  idx={idx}
                  github_url={repo.github_url}
                  repoNumber={repo.repo_number}
                  commitSha={repo.ingested_commit_sha}
                  branch={repo.ingested_branch}
                />
              ))}
            </div>
          )}
        </div>
      </GlossarySearch>
    </div>
  );
}
