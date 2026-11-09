import { describe, expect, it } from "vitest";

import {
  answerKeys,
  decorateAnswer,
  findCitation,
  keysFromHref,
  partitionSources,
  shortKeyLabel,
  stripMarks,
  trimPartialMarkup,
} from "@/lib/agent/answer";

describe("decorateAnswer", () => {
  it("turns a citation key into a chip link", () => {
    const out = decorateAnswer("Hashes with bcrypt [F:app/security.py:4-8].");
    expect(out).toContain("[security.py:4-8](#illume-cite=");
    expect(out).not.toContain("[F:app");
  });

  it("splits several keys in one bracket", () => {
    expect(answerKeys("See [F:a.py:1-2; C:abcd1234, PR:7].")).toEqual([
      "F:a.py:1-2",
      "C:abcd1234",
      "PR:7",
    ]);
  });

  it("keeps brackets and parentheses inside paths", () => {
    expect(answerKeys("Route [F:app/repo/[id]/page.tsx:1-5].")).toEqual([
      "F:app/repo/[id]/page.tsx:1-5",
    ]);
    expect(answerKeys("Group [F:app/(auth)/x.ts].")).toEqual([
      "F:app/(auth)/x.ts",
    ]);
    const href = decorateAnswer("[F:app/(auth)/x.ts]").match(
      /#illume-cite=[^)\s]+/,
    )![0];
    expect(keysFromHref(href)).toEqual(["F:app/(auth)/x.ts"]);
  });

  it("removes every verification mark", () => {
    const out = decorateAnswer(
      "A is true. [[verify:supported]] B maybe. [[verify:partially_supported]]",
    );
    expect(out).toBe("A is true.  B maybe. ");
  });

  it("shows a source once per paragraph", () => {
    const out = decorateAnswer(
      "One [F:a.py:1-2]. Two [F:a.py:1-2]. Three [F:a.py:1-2; F:b.py].\n\nNext [F:a.py:1-2].",
    );
    expect([...out.matchAll(/#illume-cite=/g)]).toHaveLength(3);
    expect(out).toContain("Next [a.py:1-2](");
    expect(out).toContain("One [a.py:1-2](");
    expect(out).toContain("Two.");
    expect(out).toContain("Three [b.py](");
  });

  it("leaves code spans and fences untouched", () => {
    const text = "Use `[F:a.py]` and\n```\n[F:b.py] [[verify:unsupported]]\n```";
    expect(decorateAnswer(text)).toBe(text);
  });

  it("does not touch ordinary markdown links or brackets", () => {
    const text = "See [docs](https://example.com) and [note].";
    expect(decorateAnswer(text)).toBe(text);
  });
});

describe("stripMarks", () => {
  it("removes every mark", () => {
    expect(
      stripMarks("A. [[verify:supported]] B. [[verify:unsupported]]"),
    ).toBe("A.  B. ");
  });
});

describe("shortKeyLabel", () => {
  it.each([
    ["F:server/app/main.py:3-9", "main.py:3-9"],
    ["F:server/app/main.py", "main.py"],
    ["C:a1b2c3d4e5", "commit a1b2c3d"],
    ["PR:142", "PR #142"],
    ["D:README#install", "install"],
  ])("%s -> %s", (key, label) => {
    expect(shortKeyLabel(key)).toBe(label);
  });
});

describe("findCitation", () => {
  const citations = [
    { key: "F:a.py:1-5", source_type: "symbol", file_path: "a.py" },
    { source_type: "commit", commit_hash: "abcdef1234567" },
  ];

  it("matches an exact key", () => {
    expect(findCitation("F:a.py:1-5", citations)).toBe(citations[0]);
  });

  it("falls back to the same file with a different range", () => {
    expect(findCitation("F:a.py:9-10", citations)).toBe(citations[0]);
  });

  it("matches a commit by short hash", () => {
    expect(findCitation("C:abcdef12", citations)).toBe(citations[1]);
  });

  it("returns null for an unknown key", () => {
    expect(findCitation("F:zzz.py", citations)).toBeNull();
  });
});

describe("partitionSources", () => {
  const a = { key: "F:a.py:1-2", source_type: "symbol", file_path: "a.py" };
  const b = { key: "F:b.py:1-2", source_type: "symbol", file_path: "b.py" };

  it("separates cited sources from retrieved ones", () => {
    const parts = partitionSources("Uses [F:a.py:1-2].", [a, b], ["F:c.py:1-2"]);
    expect(parts.cited).toEqual([a]);
    expect(parts.retrieved).toEqual([b]);
    expect(parts.retrievedKeys).toEqual(["F:c.py:1-2"]);
  });

  it("treats every source as cited when the answer carries no keys", () => {
    const parts = partitionSources("An older stored answer.", [a, b], []);
    expect(parts.cited).toEqual([a, b]);
    expect(parts.retrieved).toEqual([]);
  });
});

describe("trimPartialMarkup", () => {
  it.each([
    ["Entry is in [F:app/ma", "Entry is in "],
    ["Entry is in [", "Entry is in "],
    ["See [PR:4", "See "],
    ["Done. [[veri", "Done. "],
    ["Done. [[verify:supp", "Done. "],
  ])("holds back %j", (input, expected) => {
    expect(trimPartialMarkup(input)).toBe(expected);
  });

  it.each([
    "Entry is in [F:app/main.py:1-3].",
    "An array [1, 2",
    "A link [the docs",
    "No brackets at all",
  ])("leaves %j alone", (input) => {
    expect(trimPartialMarkup(input)).toBe(input);
  });
});
