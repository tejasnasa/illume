/**
 * One rendered doc: the article itself and, on wide screens, the "On this page"
 * outline of its `h2` headings with the section being read highlighted. Shared by the
 * overview at `/docs` and every `/docs/<slug>` page.
 * @module DocArticle
 */
import Link from "next/link";
import {
  GITHUB_BRANCH,
  GITHUB_REPO_URL,
  INDEX_SLUG,
  listDocSections,
  placeDoc,
  readingMinutes,
  type Doc,
} from "@/lib/docs";
import { DocsMarkdown } from "./DocsMarkdown";
import { DocsOutline } from "./DocsOutline";

/**
 * Renders a doc, with its place in the docs, its reading time and a pager to
 * the docs either side of it.
 *
 * @param doc - The doc, as `readDoc` returns it.
 * @returns The article and its outline.
 */
export function DocArticle({ doc }: { doc: Doc }) {
  const source = `${GITHUB_REPO_URL}/blob/${GITHUB_BRANCH}/docs/${doc.slug}.md`;
  const place = placeDoc(doc.slug, listDocSections());
  const hrefOf = (slug: string) => (slug === INDEX_SLUG ? "/docs" : `/docs/${slug}`);

  return (
    <div className="grid grid-cols-1 items-start gap-12 xl:grid-cols-[minmax(0,1fr)_200px]">
      <div className="min-w-0 max-w-190 pt-10 pb-18">
        <div className="mb-6 flex flex-wrap items-center gap-x-4 gap-y-2 font-pixel text-[11px] tracking-[0.1em] text-zinc-500 uppercase">
          <span>
            Docs / <span className="text-(--accent)">{place.section ?? "Overview"}</span>
          </span>
          <span>{readingMinutes(doc.content)} min read</span>
          <a
            href={source}
            target="_blank"
            rel="noopener noreferrer"
            className="text-zinc-400 transition-colors hover:text-(--accent)"
          >
            Edit on GitHub <span aria-hidden="true">↗</span>
          </a>
        </div>
        <article className="docs-prose">
          <DocsMarkdown content={doc.content} slug={doc.slug} />
        </article>
        {(place.prev || place.next) && (
          <nav aria-label="Pager" className="mt-14 grid grid-cols-2 gap-3 border-t border-white/8 pt-6">
            {place.prev ? (
              <Link
                href={hrefOf(place.prev.slug)}
                className="ghost flex flex-col gap-1.5 rounded-sm border border-white/10 px-4 py-3.5"
              >
                <span className="font-pixel text-[11px] tracking-[0.1em] text-zinc-500 uppercase">
                  <span aria-hidden="true">← </span>Previous
                </span>
                <span className="text-[15px] text-(--foreground)">{place.prev.title}</span>
              </Link>
            ) : (
              <span />
            )}
            {place.next && (
              <Link
                href={hrefOf(place.next.slug)}
                className="ghost flex flex-col items-end gap-1.5 rounded-sm border border-white/10 px-4 py-3.5 text-right"
              >
                <span className="font-pixel text-[11px] tracking-[0.1em] text-zinc-500 uppercase">
                  Next<span aria-hidden="true"> →</span>
                </span>
                <span className="text-[15px] text-(--foreground)">{place.next.title}</span>
              </Link>
            )}
          </nav>
        )}
      </div>
      {doc.headings.length > 0 && (
        <aside className="custom-scrollbar sticky top-16 hidden h-[calc(100dvh-4rem)] overflow-y-auto overscroll-contain py-10 xl:block">
          <p className="m-0 mb-2.5 font-pixel text-[11px] tracking-[0.12em] text-zinc-500 uppercase">
            On this page
          </p>
          <DocsOutline headings={doc.headings} />
        </aside>
      )}
    </div>
  );
}
