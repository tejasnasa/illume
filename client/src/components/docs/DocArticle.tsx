/**
 * One rendered doc: the article itself and, on wide screens, the "On this page"
 * outline of its `h2` headings with the section being read highlighted. Shared by the
 * overview at `/docs` and every `/docs/<slug>` page.
 * @module DocArticle
 */
import type { Doc } from "@/lib/docs";
import { DocsMarkdown } from "./DocsMarkdown";
import { DocsOutline } from "./DocsOutline";

/**
 * Renders a doc.
 *
 * @param doc - The doc, as `readDoc` returns it.
 * @returns The article and its outline.
 */
export function DocArticle({ doc }: { doc: Doc }) {
  return (
    <div className="flex gap-10">
      <article className="docs-prose min-w-0 max-w-3xl flex-1">
        <DocsMarkdown content={doc.content} slug={doc.slug} />
      </article>
      {doc.headings.length > 0 && (
        <aside className="sticky top-24 hidden h-fit w-52 shrink-0 xl:block">
          <p className="mb-2 text-xs uppercase tracking-wider text-(--muted-foreground)">
            On this page
          </p>
          <DocsOutline headings={doc.headings} />
        </aside>
      )}
    </div>
  );
}
