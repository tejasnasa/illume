import { GetGlossary } from "@/api/glossary";
import { GetRepository } from "@/api/repository";
import GlossarySearch from "@/components/GlossarySearch";
import GlossaryEntry from "@/components/ui/GlossaryEntry";
import Link from "next/link";

const PAGE_SIZE = 10;

export default async function GlossaryPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ page?: string }>;
}) {
  const { id } = await params;
  const repo = await GetRepository(Number(id));
  const { page: pageParam } = await searchParams;
  const currentPage = Math.max(1, Number(pageParam) || 1);
  const data = await GetGlossary(repo.id, currentPage, PAGE_SIZE);

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1;
  const start = (currentPage - 1) * PAGE_SIZE + 1;

  return (
    <main className="max-w-5xl mx-auto p-6 pt-12">
      <GlossarySearch github_url={repo.github_url} repoId={repo.id}>
        <div className="flex justify-between items-center mb-6">
          <span className="text-sm font-medium text-(--muted-foreground)">
            {data
              ? `Showing ${data.entries.length} of ${data.total} entries`
              : "Failed to load"}
          </span>
          <div className="flex items-center gap-2">
            {currentPage > 1 ? (
              <Link
                href={`/repo/${repo.repo_number}/glossary?page=${currentPage - 1}`}
                className="px-4 py-2 rounded-sm text-sm border border-(--border) hover:bg-(--secondary) transition-colors"
              >
                Previous
              </Link>
            ) : (
              <span className="px-4 py-2 rounded-sm text-sm border border-(--border) opacity-50 cursor-not-allowed">
                Previous
              </span>
            )}
            <span className="px-3 py-2 text-sm text-(--muted-foreground)">
              Page {currentPage} of {totalPages}
            </span>
            {currentPage < totalPages ? (
              <Link
                href={`/repo/${repo.repo_number}/glossary?page=${currentPage + 1}`}
                className="px-4 py-2 rounded-sm text-sm border border-(--border) hover:bg-(--secondary) transition-colors"
              >
                Next
              </Link>
            ) : (
              <span className="px-4 py-2 rounded-sm text-sm border border-(--border) opacity-50 cursor-not-allowed">
                Next
              </span>
            )}
          </div>
        </div>

        {!data ? (
          <div className="p-6 rounded-sm border border-(--destructive)/30 bg-(--destructive)/10 text-(--destructive)">
            Failed to load glossary data.
          </div>
        ) : data.entries.length === 0 ? (
          <div className="text-center py-24 glass-card rounded-sm text-(--muted-foreground)">
            No glossary entries found.
          </div>
        ) : (
          <div className="space-y-4">
            {data.entries.map((entry, idx) => (
              <GlossaryEntry
                key={entry.id}
                entry={entry}
                start={start}
                idx={idx}
                github_url={repo.github_url}
              />
            ))}
          </div>
        )}
      </GlossarySearch>
    </main>
  );
}
