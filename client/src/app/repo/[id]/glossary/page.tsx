import { GetGlossary } from "@/api/glossary";
import { GetRepository } from "@/api/repository";
import Link from "next/link";

export default async function GlossaryPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ page?: string }>;
}) {
  const { id } = await params;
  const { page: pageParam } = await searchParams;
  const page = Math.max(1, Number(pageParam) || 1);

  const repo = await GetRepository(Number(id));
  const glossary = await GetGlossary(repo.id, page, 10);

  const totalPages = Math.ceil(glossary.total / glossary.page_size);
  const start = (page - 1) * glossary.page_size + 1;

  return (
    <main className="p-4 h-[calc(100dvh-4rem)] flex gap-4">
      <section className="backdrop-blur-xs border rounded-sm p-4 flex flex-col bg-black/30 w-full h-full mx-auto overflow-hidden">
        <h2 className="text-2xl font-semibold mb-2">Glossary</h2>

        {glossary.entries.length === 0 ? (
          <p>No glossary entries found for this repository.</p>
        ) : (
          <>
            <ol className="space-y-2 overflow-scroll flex-1">
              {glossary.entries.map((entry, i) => (
                <li key={entry.id} className="border-b pb-2">
                  <h3 className="font-semibold">
                    <span className="text-muted-foreground mr-2">
                      {start + i}.
                    </span>
                    {entry.name}
                  </h3>
                  <p className="text-sm text-muted-foreground">
                    {entry.definition}
                  </p>
                </li>
              ))}
            </ol>

            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-2 pt-4 border-t mt-2 shrink-0">
                <Link
                  href={`?page=${page - 1}`}
                  aria-disabled={page <= 1}
                  className={page <= 1 ? "pointer-events-none opacity-40" : ""}
                >
                  ← Prev
                </Link>

                <div className="flex gap-1">
                  {Array.from({ length: totalPages }, (_, i) => i + 1).map(
                    (p) => (
                      <Link
                        key={p}
                        href={`?page=${p}`}
                        className={`px-2 py-0.5 rounded text-sm ${
                          p === page
                            ? "bg-white text-black font-semibold"
                            : "opacity-60 hover:opacity-100"
                        }`}
                      >
                        {p}
                      </Link>
                    ),
                  )}
                </div>

                <Link
                  href={`?page=${page + 1}`}
                  aria-disabled={page >= totalPages}
                  className={
                    page >= totalPages ? "pointer-events-none opacity-40" : ""
                  }
                >
                  Next →
                </Link>
              </div>
            )}
          </>
        )}
      </section>
    </main>
  );
}
