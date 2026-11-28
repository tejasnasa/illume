import {
  PEOPLE_COLORS,
  SKETCH_H,
  SKETCH_MAX_NODES,
  SKETCH_W,
  activityHref,
  activityTag,
  compactNumber,
  initialsOf,
  languageShares,
  percent,
  riskCounts,
  riskOf,
  sketchGraph,
  stripLeadingTitle,
} from "@/lib/overview";
import type { ActivityItem } from "@/types/guide";

function item(over: Partial<ActivityItem>): ActivityItem {
  return {
    kind: "commit",
    title: "t",
    author: "a",
    at: "2026-01-01T00:00:00Z",
    number: null,
    hash: "abcdef1234",
    files_changed: 0,
    ...over,
  };
}

describe("languageShares", () => {
  it("orders by lines, folds the tail into Other and skips empty languages", () => {
    const rows = Array.from({ length: 7 }, (_, i) => ({
      language: `L${i}`,
      file_count: 1,
      loc_count: 100 - i * 10,
    }));
    rows.push({ language: "Empty", file_count: 3, loc_count: 0 });
    const shares = languageShares({ language_breakdown: rows });
    expect(shares).toHaveLength(6);
    expect(shares[0].name).toBe("L0");
    expect(shares[5].name).toBe("Other");
    expect(shares[5].files).toBe(2);
    expect(shares.reduce((sum, s) => sum + s.share, 0)).toBeCloseTo(1);
  });

  it("is empty with no lines", () => {
    expect(languageShares({ language_breakdown: [] })).toEqual([]);
  });
});

describe("number and text helpers", () => {
  it("words shares and counts", () => {
    expect(percent(0.004)).toBe("<1%");
    expect(percent(0.456)).toBe("46%");
    expect(compactNumber(48000)).toBe("48K");
    expect(compactNumber(NaN)).toBe("0");
  });

  it("takes one or two initials", () => {
    expect(initialsOf("Ada Lovelace")).toBe("AL");
    expect(initialsOf("grace.hopper")).toBe("GH");
    expect(initialsOf("linus")).toBe("LI");
    expect(PEOPLE_COLORS.length).toBeGreaterThan(0);
  });

  it("drops only the opening headings of a summary", () => {
    expect(stripLeadingTitle("# Title\n\nBody\n## Later")).toBe("Body\n## Later");
    expect(stripLeadingTitle("Body")).toBe("Body");
  });
});

describe("activity", () => {
  it("links a pull request or commit, and tags it", () => {
    const base = "https://github.com/o/r/";
    expect(activityHref(base, item({ kind: "pull_request", number: 7, hash: null }))).toBe(
      "https://github.com/o/r/pull/7",
    );
    expect(activityHref(base, item({}))).toBe("https://github.com/o/r/commit/abcdef1234");
    expect(activityHref(base, item({ hash: null }))).toBeNull();
    expect(activityTag(item({ kind: "pull_request", number: 7 }))).toBe("#7");
    expect(activityTag(item({}))).toBe("abcdef1");
  });
});

describe("risk", () => {
  it("buckets anything unknown as safe", () => {
    expect(riskOf(" Critical ")).toBe("critical");
    expect(riskOf("caution")).toBe("caution");
    expect(riskOf(null)).toBe("safe");
    expect(riskOf("weird")).toBe("safe");
    expect(
      riskCounts([{ criticality: "critical" }, { criticality: "safe" }, { criticality: null }]),
    ).toEqual({ critical: 1, caution: 0, safe: 2 });
  });
});

describe("sketchGraph", () => {
  function node(id: string, group: string, fan = 0) {
    return {
      id,
      label: id,
      path: id,
      group,
      kind: "file",
      loc: 1,
      criticality: "safe",
      criticality_score: 0,
      language: "x",
      fan_in: fan,
      fan_out: 0,
    };
  }

  it("keeps every point on the canvas and joins linked files", () => {
    const nodes = Array.from({ length: 30 }, (_, i) => node(`n${i}`, `g${i % 4}`, i));
    const { points, links } = sketchGraph({
      nodes,
      links: [
        { source: "n1", target: "n2", type: "imports", weight: 1 },
        { source: "n1", target: "missing", type: "imports", weight: 1 },
      ],
    });
    expect(points).toHaveLength(30);
    expect(links).toHaveLength(1);
    for (const p of points) {
      expect(p.x).toBeGreaterThanOrEqual(4);
      expect(p.x).toBeLessThanOrEqual(SKETCH_W - 4);
      expect(p.y).toBeGreaterThanOrEqual(4);
      expect(p.y).toBeLessThanOrEqual(SKETCH_H - 4);
    }
  });

  it("draws only the busiest files of a large graph and survives an empty one", () => {
    const nodes = Array.from({ length: SKETCH_MAX_NODES + 50 }, (_, i) => node(`n${i}`, "g", i));
    expect(sketchGraph({ nodes, links: [] }).points).toHaveLength(SKETCH_MAX_NODES);
    expect(sketchGraph({ nodes: [], links: [] })).toEqual({ points: [], links: [] });
  });
});
