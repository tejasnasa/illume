/**
 * Server-side access to the repository's Markdown docs.
 *
 * The `docs/**\/*.md` files at the repo root are the single source of truth: this module
 * lists them, reads one, pulls out its title, summary and headings, groups the sidebar,
 * and rewrites the links inside them so they work on the site.
 *
 * Reads the filesystem, so it belongs to server components and `generateStaticParams`
 * only; never import it from a `"use client"` file. The docs are read at build time, so
 * a doc edit needs a rebuild.
 *
 * The docs must keep rendering on GitHub, so nothing here asks the files for
 * site-specific syntax. Relative `*.md` links are the GitHub-native form and are mapped
 * to `/docs/<slug>` at render time.
 * @module Docs
 */
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import GithubSlugger from "github-slugger";

/** The repository on GitHub; repo files outside `docs/` link here. */
export const GITHUB_REPO_URL = "https://github.com/tejasnasa/illume";
/** The branch repo-file links point at. */
export const GITHUB_BRANCH = "main";

/**
 * The overview, `docs/README.md`. GitHub shows it when the folder is opened, and the
 * site serves it at `/docs` rather than as one more entry in the list.
 */
export const INDEX_SLUG = "README";

/**
 * Sidebar groups, in order, matching the overview's "The documents" section. A doc
 * missing from every group is still listed, under {@link OTHER_SECTION}.
 */
export const DOC_SECTIONS = [
  {
    title: "Start here",
    slugs: [
      "architecture",
      "getting-started/local-setup",
      "getting-started/first-ingest",
      "getting-started/repository-layout",
    ],
  },
  {
    title: "The pipeline",
    slugs: [
      "pipeline/ingestion",
      "pipeline/parsing-and-dependencies",
      "pipeline/git-intelligence",
      "pipeline/generation",
      "pipeline/concurrency-and-failure",
      "pipeline/clone-cache",
      "pipeline/sync",
    ],
  },
  {
    title: "Search and chat",
    slugs: [
      "retrieval/index-and-embeddings",
      "retrieval/retrieval-arms",
      "retrieval/chat",
      "retrieval/agent",
      "retrieval/router",
    ],
  },
  {
    title: "The graph",
    slugs: ["graph/dependency-graph", "graph/rendering"],
  },
  {
    title: "Interfaces",
    slugs: [
      "api",
      "interfaces/websockets",
      "interfaces/illume-export",
      "mcp/server",
    ],
  },
  {
    title: "Clients",
    slugs: [
      "frontend/overview",
      "frontend/docs-site",
      "mobile/overview",
      "mobile/graph-renderer",
    ],
  },
  {
    title: "Security",
    slugs: ["security/auth", "security/byok-and-encryption"],
  },
  {
    title: "Evaluation",
    slugs: [
      "evals/harness",
      "evals/judging-and-statistics",
      "evals/results-full-v1",
    ],
  },
  {
    title: "Testing and operations",
    slugs: [
      "testing/overview",
      "testing/backend",
      "testing/frontend-and-e2e",
      "operations/ci-cd",
      "operations/deployment",
      "operations/runbook",
    ],
  },
  {
    title: "Reference",
    slugs: [
      "reference/cli",
      "reference/environment",
      "reference/constants",
      "reference/data-model",
    ],
  },
  {
    title: "Guides",
    slugs: [
      "guides/add-a-pipeline-stage",
      "guides/add-a-retrieval-arm",
      "guides/add-an-endpoint",
      "guides/add-an-mcp-tool",
      "guides/change-the-schema",
    ],
  },
] as const;

/** Heading for docs that no group names. */
export const OTHER_SECTION = "More";

/** What the sidebar needs to know about a doc. */
export type DocMeta = {
  /** Path under `docs/` without `.md`, e.g. `pipeline/sync`. */
  slug: string;
  title: string;
  /** First paragraph after the title, as plain text; empty when there is none. */
  summary: string;
};

/** A doc with its Markdown body and the `h2` headings for the page outline. */
export type Doc = DocMeta & {
  content: string;
  headings: DocHeading[];
};

/** A heading as the on-page outline lists it. */
export type DocHeading = { id: string; text: string };

/** One sidebar group. */
export type DocSection = {
  title: string;
  docs: Pick<DocMeta, "slug" | "title">[];
};

/** A link or image target after rewriting. */
export type ResolvedTarget = {
  href: string;
  /** True when the target leaves the site (opens in a new tab). */
  external: boolean;
};

const FENCE = /^\s{0,3}(```+|~~~+)/;
const SLUG = /^[a-z0-9][a-z0-9-]*(\/[a-z0-9][a-z0-9-]*)*$/i;

/**
 * Finds the docs directory. `process.cwd()` is `client/` under `next dev`, `next build`
 * and Vitest; the repo root is tried too, for a process started there.
 *
 * @returns The absolute path of the repository's `docs` folder.
 * @throws When no candidate exists, naming every place that was tried.
 */
export function resolveDocsDir(): string {
  const candidates = [
    path.resolve(process.cwd(), "../docs"),
    path.resolve(process.cwd(), "docs"),
  ];
  const found = candidates.find(
    (dir) =>
      existsSync(dir) &&
      statSync(dir).isDirectory() &&
      existsSync(path.join(dir, `${INDEX_SLUG}.md`)),
  );
  if (!found) {
    throw new Error(
      `Docs directory not found. Looked in:\n${candidates.map((c) => `  - ${c}`).join("\n")}`,
    );
  }
  return found;
}

/** Normalises line endings so CRLF checkouts parse the same as LF ones. */
function lines(markdown: string): string[] {
  return markdown.replace(/\r\n?/g, "\n").split("\n");
}

/** Reduces inline Markdown (links, code, emphasis, images) to plain text. */
export function stripInlineMarkdown(text: string): string {
  return text
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/(\*\*|__)(.+?)\1/g, "$2")
    .replace(/(\*|_)(.+?)\1/g, "$2")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Reads the first `# Heading` outside code fences.
 *
 * @param markdown - A doc's source.
 * @returns The heading as plain text, or `null` when there is none.
 */
export function extractTitle(markdown: string): string | null {
  let inFence = false;
  for (const line of lines(markdown)) {
    if (FENCE.test(line)) inFence = !inFence;
    if (inFence) continue;
    const match = /^#\s+(.+?)\s*#*\s*$/.exec(line);
    if (match) return stripInlineMarkdown(match[1] ?? "");
  }
  return null;
}

/**
 * Reads the first paragraph after the title. Headings, lists, tables, quotes, fences
 * and HTML are not paragraphs, so a doc that opens with one of them has no summary.
 *
 * @param markdown - A doc's source.
 * @returns The paragraph as one line of plain text; `""` when there is none.
 */
export function extractSummary(markdown: string): string {
  const all = lines(markdown);
  let i = all.findIndex((line) => /^#\s+\S/.test(line));
  if (i === -1) return "";
  i += 1;
  while (i < all.length && (all[i] ?? "").trim() === "") i += 1;
  const first = all[i] ?? "";
  if (/^(#|>|[-*+]\s|\d+[.)]\s|\||<|\s{0,3}(```|~~~))/.test(first)) return "";
  const paragraph: string[] = [];
  for (; i < all.length; i += 1) {
    const line = all[i] ?? "";
    if (line.trim() === "") break;
    paragraph.push(line);
  }
  return stripInlineMarkdown(paragraph.join(" "));
}

/**
 * Lists the `h2` headings with the ids `rehype-slug` gives them: both use
 * `github-slugger` over every heading in document order, so duplicates get the same
 * `-1`, `-2` suffixes.
 *
 * @param markdown - A doc's source.
 * @returns The `h2` headings in order.
 */
export function extractHeadings(markdown: string): DocHeading[] {
  const slugger = new GithubSlugger();
  const headings: DocHeading[] = [];
  let inFence = false;
  for (const line of lines(markdown)) {
    if (FENCE.test(line)) inFence = !inFence;
    if (inFence) continue;
    const match = /^(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line);
    if (!match) continue;
    const text = stripInlineMarkdown(match[2] ?? "");
    const id = slugger.slug(text);
    if (match[1]?.length === 2) headings.push({ id, text });
  }
  return headings;
}

/** Every `.md` file under `dir`, as slugs relative to `root`. */
function walk(dir: string, root: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return walk(full, root);
    if (!entry.name.endsWith(".md")) return [];
    return [path.relative(root, full).slice(0, -3).split(path.sep).join("/")];
  });
}

/** Slugs of every doc except the overview, sorted alphabetically. */
export function listDocSlugs(): string[] {
  const root = resolveDocsDir();
  return walk(root, root)
    .filter((slug) => slug !== INDEX_SLUG && SLUG.test(slug))
    .sort((a, b) => a.localeCompare(b));
}

/**
 * Reads one doc.
 *
 * @param slug - Path under `docs/` without `.md`.
 * @returns The doc, or `null` when no such file exists (a slug is never joined into a
 *          path unless it is made of plain name segments).
 */
export function readDoc(slug: string): Doc | null {
  if (!SLUG.test(slug)) return null;
  const file = path.join(resolveDocsDir(), `${slug}.md`);
  if (!existsSync(file)) return null;
  const content = readFileSync(file, "utf8").replace(/\r\n?/g, "\n");
  return {
    slug,
    title: extractTitle(content) ?? slug,
    summary: extractSummary(content),
    content,
    headings: extractHeadings(content),
  };
}

/**
 * Groups slugs into the sidebar: {@link DOC_SECTIONS} in order, keeping only docs that
 * exist, then any doc no group names, alphabetically, so a new doc never disappears.
 *
 * @param slugs - Every doc slug except the overview.
 * @returns Non-empty groups of slugs, in sidebar order.
 */
export function groupSlugs(
  slugs: readonly string[],
): { title: string; slugs: string[] }[] {
  const present = new Set(slugs);
  const named = new Set<string>(DOC_SECTIONS.flatMap((s) => s.slugs));
  const groups: { title: string; slugs: string[] }[] = DOC_SECTIONS.map(
    (section) => ({
      title: section.title,
      slugs: section.slugs.filter((slug) => present.has(slug)),
    }),
  );
  const rest = [...slugs].filter((slug) => !named.has(slug)).sort();
  groups.push({ title: OTHER_SECTION, slugs: rest });
  return groups.filter((group) => group.slugs.length > 0);
}

/** The sidebar, with each doc's title read from its file. */
export function listDocSections(): DocSection[] {
  return groupSlugs(listDocSlugs()).map((group) => ({
    title: group.title,
    docs: group.slugs.map((slug) => ({
      slug,
      title: readDoc(slug)?.title ?? slug,
    })),
  }));
}

/**
 * Maps a link or image target found in a doc to where it lives on the site.
 *
 * Relative targets are resolved from the doc's own folder, as GitHub resolves them:
 * another doc becomes `/docs/<slug>` (hash kept), the overview becomes `/docs`, any
 * other repo file becomes a GitHub URL, and absolute URLs and fragments are left alone.
 *
 * @param target - The raw `href` or `src`.
 * @param fromSlug - The slug of the doc the target appears in.
 * @param kind - `"link"` points at GitHub's file view, `"image"` at the raw file.
 * @returns The rewritten target and whether it leaves the site.
 */
export function resolveDocTarget(
  target: string,
  fromSlug: string,
  kind: "link" | "image" = "link",
): ResolvedTarget {
  if (!target || target.startsWith("#") || target.startsWith("/")) {
    return { href: target, external: false };
  }
  if (/^[a-z][a-z0-9+.-]*:/i.test(target) || target.startsWith("//")) {
    return { href: target, external: true };
  }

  const splitAt = target.search(/[?#]/);
  const pathPart = splitAt === -1 ? target : target.slice(0, splitAt);
  const suffix = splitAt === -1 ? "" : target.slice(splitAt);
  const fromDir = path.posix.dirname(`docs/${fromSlug}.md`);
  const repoPath = path.posix.normalize(path.posix.join(fromDir, pathPart));

  if (repoPath.startsWith("..")) return { href: target, external: false };

  const doc = /^docs\/(.+)\.md$/.exec(repoPath);
  if (doc && kind === "link") {
    const slug = doc[1];
    const href = slug === INDEX_SLUG ? "/docs" : `/docs/${slug}`;
    return { href: `${href}${suffix}`, external: false };
  }

  const view = kind === "image" ? "raw" : "blob";
  return {
    href: `${GITHUB_REPO_URL}/${view}/${GITHUB_BRANCH}/${repoPath}${suffix}`,
    external: true,
  };
}
