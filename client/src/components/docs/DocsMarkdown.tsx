/**
 * Server component that turns a doc's Markdown into the page body: GFM (tables, task
 * lists), heading anchors, build-time syntax highlighting, Mermaid hand-off, and
 * link/image rewriting so relative doc links become `/docs/<slug>` routes and repo
 * files link to GitHub.
 *
 * Uses `MarkdownAsync` because the highlighter is asynchronous. Everything here runs at
 * build time; the only client JavaScript a doc page ships is the `Mermaid` component,
 * the sidebar and the outline.
 * @module DocsMarkdown
 */
import { resolveDocTarget } from "@/lib/docs";
import Link from "next/link";
import { MarkdownAsync, type Components } from "react-markdown";
import rehypeAutolinkHeadings from "rehype-autolink-headings";
import rehypePrettyCode from "rehype-pretty-code";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";
import { Mermaid } from "./Mermaid";
import { MERMAID_TAG, rehypeMermaid } from "./rehypeMermaid";

/**
 * Element overrides for one doc. Built per doc because relative links resolve from
 * the doc's own folder.
 *
 * @param slug - The doc being rendered.
 * @returns The `components` map for `react-markdown`.
 */
function componentsFor(slug: string): Components & Record<string, unknown> {
  return {
    a({ href, title, children, className, "aria-label": ariaLabel }) {
      const target = resolveDocTarget(href ?? "", slug);
      // Heading anchors carry a class and label; every branch must keep them.
      const shared = { title, className, "aria-label": ariaLabel };
      if (target.external) {
        return (
          <a
            {...shared}
            href={target.href}
            target="_blank"
            rel="noopener noreferrer"
          >
            {children}
          </a>
        );
      }
      if (target.href.startsWith("/docs")) {
        return (
          <Link {...shared} href={target.href}>
            {children}
          </Link>
        );
      }
      return (
        <a {...shared} href={target.href}>
          {children}
        </a>
      );
    },
    img({ src, alt, title }) {
      const target = resolveDocTarget(
        typeof src === "string" ? src : "",
        slug,
        "image",
      );
      return (
        // eslint-disable-next-line @next/next/no-img-element
        <img title={title} src={target.href} alt={alt ?? ""} loading="lazy" />
      );
    },
    table({ children }) {
      return (
        <div className="docs-table-scroll">
          <table>{children}</table>
        </div>
      );
    },
    [MERMAID_TAG]({ children }: { children?: React.ReactNode }) {
      return <Mermaid chart={String(children ?? "")} />;
    },
  };
}

/**
 * Renders one doc's Markdown.
 *
 * @param content - The doc source (LF line endings).
 * @param slug - The doc's slug, which relative links resolve from.
 * @returns The rendered body.
 */
export async function DocsMarkdown({
  content,
  slug,
}: {
  content: string;
  slug: string;
}) {
  return (
    <MarkdownAsync
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[
        rehypeMermaid,
        rehypeSlug,
        [
          rehypeAutolinkHeadings,
          {
            behavior: "append",
            properties: {
              className: ["docs-anchor"],
              ariaLabel: "Link to this section",
            },
            content: { type: "text", value: "#" },
          },
        ],
        [
          rehypePrettyCode,
          { theme: "github-dark-default", keepBackground: false },
        ],
      ]}
      components={componentsFor(slug)}
    >
      {content}
    </MarkdownAsync>
  );
}
