/**
 * `/docs`: the overview, rendered from `docs/README.md`, the same file GitHub shows
 * when the folder is opened. Statically generated.
 * @module DocsIndexPage
 */
import { DocArticle } from "@/components/docs/DocArticle";
import { INDEX_SLUG, readDoc } from "@/lib/docs";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

/**
 * Title and description from the overview's heading and first paragraph.
 *
 * @returns The page metadata.
 */
export function generateMetadata(): Metadata {
  const doc = readDoc(INDEX_SLUG);
  return {
    title: `${doc?.title ?? "Documentation"} - Illume`,
    description:
      doc?.summary ||
      "How Illume is built: architecture, the analysis pipeline, retrieval, the API, data model, testing and deployment.",
  };
}

/**
 * Renders the overview.
 *
 * @returns The overview article.
 */
export default function DocsIndexPage() {
  const doc = readDoc(INDEX_SLUG);
  if (!doc) notFound();
  return <DocArticle doc={doc} />;
}
