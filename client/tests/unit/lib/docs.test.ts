import { readFileSync } from "node:fs";
import path from "node:path";
import GithubSlugger from "github-slugger";
import { describe, expect, it } from "vitest";

import {
  DOC_SECTIONS,
  GITHUB_BRANCH,
  GITHUB_REPO_URL,
  INDEX_SLUG,
  OTHER_SECTION,
  extractHeadings,
  extractSummary,
  extractTitle,
  groupSlugs,
  listDocSections,
  listDocSlugs,
  readDoc,
  resolveDocTarget,
  resolveDocsDir,
  stripInlineMarkdown,
} from "@/lib/docs";

const docsDir = resolveDocsDir();
const slugs = listDocSlugs();

/** Every heading id `rehype-slug` gives a doc, in order. */
function headingIds(content: string): string[] {
  const slugger = new GithubSlugger();
  return content
    .replace(/```[\s\S]*?```/g, "")
    .split("\n")
    .map((line) => /^#{1,6}\s+(.+?)\s*#*\s*$/.exec(line)?.[1])
    .filter((text): text is string => text !== undefined)
    .map((text) => slugger.slug(stripInlineMarkdown(text)));
}

describe("the docs directory", () => {
  it("resolves to the repository docs folder, nested docs included", () => {
    expect(path.basename(docsDir)).toBe("docs");
    expect(slugs).toContain("architecture");
    expect(slugs).toContain("pipeline/sync");
  });
});

describe("every doc", () => {
  it("has a title of its own", () => {
    for (const slug of slugs) {
      const title = readDoc(slug)?.title ?? "";
      expect(title.length, slug).toBeGreaterThan(0);
      expect(title, slug).not.toBe(slug);
    }
  });

  it("is named by a sidebar group", () => {
    const named = new Set<string>(DOC_SECTIONS.flatMap((s) => s.slugs));
    const missing = slugs.filter((slug) => !named.has(slug));
    expect(missing, `add to DOC_SECTIONS: ${missing.join(", ")}`).toEqual([]);
  });

  it("only links to docs that exist, and to headings that exist", () => {
    const broken: string[] = [];
    for (const from of [INDEX_SLUG, ...slugs]) {
      const source = readFileSync(path.join(docsDir, `${from}.md`), "utf8");
      const prose = source.replace(/```[\s\S]*?```/g, "");
      for (const [, target = ""] of prose.matchAll(/\]\(([^)\s]+)\)/g)) {
        const resolved = resolveDocTarget(target, from);
        const match = /^\/docs(?:\/([^#]+))?(?:#(.*))?$/.exec(resolved.href);
        if (!match) continue;
        const [, slug = INDEX_SLUG, hash] = match;
        const doc = readDoc(slug);
        if (!doc) {
          broken.push(`${from}: ${target} (no such doc)`);
        } else if (hash && !headingIds(doc.content).includes(hash)) {
          broken.push(`${from}: ${target} (no heading #${hash})`);
        }
      }
    }
    expect(broken).toEqual([]);
  });
});

describe("the sidebar", () => {
  it("lists every doc once, in its group's order", () => {
    const sections = listDocSections();
    const listed = sections.flatMap((s) => s.docs.map((d) => d.slug));

    expect([...listed].sort()).toEqual([...slugs].sort());
    expect(sections.map((s) => s.title)).toEqual(
      DOC_SECTIONS.map((s) => s.title),
    );
  });

  it("puts docs no group names under a trailing group, alphabetically", () => {
    expect(groupSlugs(["zeta", "api", "alpha"])).toEqual([
      { title: "Interfaces", slugs: ["api"] },
      { title: OTHER_SECTION, slugs: ["alpha", "zeta"] },
    ]);
  });
});

describe("the overview", () => {
  it("exists, has a title, and is served at /docs rather than listed", () => {
    expect(readDoc(INDEX_SLUG)?.title).toBeTruthy();
    expect(slugs).not.toContain(INDEX_SLUG);
  });

  it("is what links to README.md inside docs/ point at", () => {
    expect(resolveDocTarget("README.md", "api")).toEqual({
      href: "/docs",
      external: false,
    });
    expect(
      resolveDocTarget("../README.md#glossary", "pipeline/sync").href,
    ).toBe("/docs#glossary");
  });
});

describe("readDoc", () => {
  it("reads a nested doc by its path", () => {
    expect(readDoc("pipeline/sync")?.slug).toBe("pipeline/sync");
  });

  it("returns null for unknown or path-like slugs", () => {
    expect(readDoc("nope")).toBeNull();
    expect(readDoc("../README")).toBeNull();
    expect(readDoc("pipeline/../api")).toBeNull();
    expect(readDoc("/etc/passwd")).toBeNull();
  });
});

describe("extractTitle", () => {
  it("takes the first h1 and ignores fenced comments", () => {
    expect(extractTitle("```sh\n# not a title\n```\n\n# `Real` title\n")).toBe(
      "Real title",
    );
    expect(extractTitle("## only h2")).toBeNull();
  });
});

describe("extractSummary", () => {
  it("joins the first paragraph after the title into one line", () => {
    const md =
      "# T\r\n\r\nFirst [link](x.md) line\r\nsecond `code`.\r\n\r\nNext.";
    expect(extractSummary(md)).toBe("First link line second code.");
  });

  it("is empty when the title is followed by a non-paragraph", () => {
    expect(extractSummary("# T\n\n## Sub\n\ntext")).toBe("");
    expect(extractSummary("# T\n\n- a\n- b")).toBe("");
    expect(extractSummary("no title")).toBe("");
  });
});

describe("extractHeadings", () => {
  it("lists h2s with de-duplicated slugs and skips code fences", () => {
    const md = "# T\n\n## A b\n\n```\n## no\n```\n\n### x\n\n## A b\n";
    expect(extractHeadings(md)).toEqual([
      { id: "a-b", text: "A b" },
      { id: "a-b-1", text: "A b" },
    ]);
  });
});

describe("resolveDocTarget", () => {
  it.each([
    ["api.md", "architecture", "/docs/api"],
    ["./api.md#section", "architecture", "/docs/api#section"],
    ["pipeline/sync.md", "README", "/docs/pipeline/sync"],
    ["sync.md", "pipeline/ingestion", "/docs/pipeline/sync"],
    [
      "../auth.md#password-storage",
      "pipeline/generation",
      "/docs/auth#password-storage",
    ],
  ])("maps %s in %s to %s", (input, from, href) => {
    expect(resolveDocTarget(input, from)).toEqual({ href, external: false });
  });

  it("leaves fragments and site paths alone", () => {
    expect(resolveDocTarget("#top", "api")).toEqual({
      href: "#top",
      external: false,
    });
    expect(resolveDocTarget("/login", "api")).toEqual({
      href: "/login",
      external: false,
    });
  });

  it("marks absolute URLs external without rewriting them", () => {
    expect(resolveDocTarget("https://example.com/a", "api")).toEqual({
      href: "https://example.com/a",
      external: true,
    });
    expect(resolveDocTarget("mailto:a@b.co", "api").external).toBe(true);
  });

  it("points repo files outside docs at GitHub, from either depth", () => {
    const base = `${GITHUB_REPO_URL}/blob/${GITHUB_BRANCH}`;
    expect(resolveDocTarget("../README.md", "README")).toEqual({
      href: `${base}/README.md`,
      external: true,
    });
    expect(
      resolveDocTarget("../../server/app/tasks/sync.py#L3", "pipeline/sync")
        .href,
    ).toBe(`${base}/server/app/tasks/sync.py#L3`);
  });

  it("points images at the raw file", () => {
    expect(resolveDocTarget("img/a.png", "api", "image").href).toBe(
      `${GITHUB_REPO_URL}/raw/${GITHUB_BRANCH}/docs/img/a.png`,
    );
  });

  it("leaves a target that climbs out of the repository as written", () => {
    expect(resolveDocTarget("../../x.md", "api")).toEqual({
      href: "../../x.md",
      external: false,
    });
  });
});
