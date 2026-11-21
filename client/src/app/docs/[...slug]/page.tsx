/**
 * One statically generated page per doc other than the overview (which is `/docs`).
 * The catch-all segment carries nested docs: `docs/pipeline/sync.md` is
 * `/docs/pipeline/sync`.
 *
 * `dynamicParams = false`: a slug that was not a file at build time is a 404, never
 * rendered on demand.
 * @module DocPage
 */
import { DocArticle } from "@/components/docs/DocArticle";
import { listDocSlugs, readDoc } from "@/lib/docs";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

export const dynamicParams = false;

type Params = { slug: string[] };

/**
 * One entry per doc file, read at build time.
 *
 * @returns The path segments of every doc.
 */
export function generateStaticParams(): Params[] {
  return listDocSlugs().map((slug) => ({ slug: slug.split("/") }));
}

/**
 * Title from the first `# Heading`, description from the first paragraph.
 *
 * @param params - The doc's path segments.
 * @returns The page metadata.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  const doc = readDoc((await params).slug.join("/"));
  if (!doc) return {};
  return {
    title: `${doc.title} - Illume Docs`,
    description: doc.summary || undefined,
  };
}

/**
 * Renders one doc.
 *
 * @param params - The doc's path segments.
 * @returns The doc article.
 */
export default async function DocPage({ params }: { params: Promise<Params> }) {
  const doc = readDoc((await params).slug.join("/"));
  if (!doc) notFound();
  return <DocArticle doc={doc} />;
}
