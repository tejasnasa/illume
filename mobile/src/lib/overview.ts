/**
 * What the repository overview cards show, as pure functions.
 *
 * @module overview
 *
 * Port of the helpers in ``client/src/app/repo/[id]/page.tsx`` (language
 * shares, activity links, contributor initials) and of the risk spread and
 * graph sketch in ``client/src/components/OverviewGraphTiles.tsx``. Keeping
 * them out of the components means the rules are checked without rendering.
 */

import type { ActivityItem, Stats } from "@/types/guide";
import type Graph from "@/types/graph";

/** Language colours, assigned in order by share of lines. */
export const LANGUAGE_COLORS = ["#53eafd", "#f6339a", "#facc15", "#a855f7", "#22c55e"] as const;
/** The colour of the combined tail of small languages. */
export const OTHER_COLOR = "#52525b";
/** Reading-order steps shown on the overview. */
export const START_STEPS = 6;
/** Risky files shown on the overview. */
export const RISK_ROWS = 5;
/** Contributors shown on the overview. */
export const PEOPLE_ROWS = 4;
/** Tile colours for contributor initials, in order. */
export const PEOPLE_COLORS = ["#a3004c", "#0092b8", "#7e22ce", "#15803d"] as const;

/** The three risk levels and their colours. */
export const RISK_LEVELS = [
  { key: "critical", label: "Critical", color: "#ef4444" },
  { key: "caution", label: "Caution", color: "#facc15" },
  { key: "safe", label: "Safe", color: "#22c55e" },
] as const;

/** One of the risk levels. */
export type RiskKey = (typeof RISK_LEVELS)[number]["key"];

/** One segment of the language bar. */
export interface LanguageShare {
  name: string;
  loc: number;
  files: number;
  share: number;
  color: string;
}

/**
 * The share of lines per language: the top five, then everything else together.
 *
 * @param stats - The repository stats.
 * @returns The segments, largest first; empty when there are no lines.
 */
export function languageShares(stats: Pick<Stats, "language_breakdown">): LanguageShare[] {
  const rows = [...(stats.language_breakdown ?? [])]
    .filter((row) => row.loc_count > 0)
    .sort((a, b) => b.loc_count - a.loc_count);
  const total = rows.reduce((sum, row) => sum + row.loc_count, 0);
  if (total === 0) return [];
  const top: LanguageShare[] = rows.slice(0, LANGUAGE_COLORS.length).map((row, i) => ({
    name: row.language,
    loc: row.loc_count,
    files: row.file_count,
    share: row.loc_count / total,
    color: LANGUAGE_COLORS[i],
  }));
  const rest = rows.slice(LANGUAGE_COLORS.length);
  if (rest.length > 0) {
    const loc = rest.reduce((sum, row) => sum + row.loc_count, 0);
    top.push({
      name: "Other",
      loc,
      files: rest.reduce((sum, row) => sum + row.file_count, 0),
      share: loc / total,
      color: OTHER_COLOR,
    });
  }
  return top;
}

/**
 * A share as a whole percentage, with tiny shares shown as `<1%`.
 *
 * @param share - A fraction from 0 to 1.
 * @returns The label.
 */
export function percent(share: number): string {
  return share < 0.01 ? "<1%" : `${Math.round(share * 100)}%`;
}

/**
 * A count in compact form, such as `12.4K`.
 *
 * @param value - The count.
 * @returns The label.
 */
export function compactNumber(value: number): string {
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(
    Number.isFinite(value) ? value : 0,
  );
}

/**
 * Where an activity item lives on GitHub.
 *
 * @param githubUrl - The repository URL.
 * @param item - The activity item.
 * @returns The link, or null when the item has no number or hash.
 */
export function activityHref(githubUrl: string, item: ActivityItem): string | null {
  const base = githubUrl.replace(/\/+$/, "");
  if (item.kind === "pull_request" && item.number != null) return `${base}/pull/${item.number}`;
  if (item.kind === "commit" && item.hash) return `${base}/commit/${item.hash}`;
  return null;
}

/**
 * The short tag in front of an activity row.
 *
 * @param item - The activity item.
 * @returns `#123` for a pull request, the short hash for a commit.
 */
export function activityTag(item: ActivityItem): string {
  return item.kind === "pull_request" ? `#${item.number}` : (item.hash ?? "").slice(0, 7);
}

/**
 * Up to two initials for a contributor's tile.
 *
 * @param name - The contributor's name as git records it.
 * @returns The initials, upper-cased.
 */
export function initialsOf(name: string): string {
  const parts = name
    .trim()
    .split(/[\s._-]+/)
    .filter(Boolean);
  const letters = parts.length > 1 ? parts[0][0] + parts[1][0] : name.trim().slice(0, 2);
  return letters.toUpperCase();
}

/**
 * Buckets a stored criticality into one of the three risk levels.
 *
 * @param value - The node's criticality column.
 * @returns `critical` or `caution`; anything else is `safe`.
 */
export function riskOf(value: string | null | undefined): RiskKey {
  const v = (value ?? "").toLowerCase().trim();
  return v === "critical" || v === "caution" ? v : "safe";
}

/**
 * How many files fall in each risk level.
 *
 * @param nodes - The graph nodes.
 * @returns The count per level.
 */
export function riskCounts(
  nodes: readonly { criticality: string | null | undefined }[],
): Record<RiskKey, number> {
  const counts: Record<RiskKey, number> = { critical: 0, caution: 0, safe: 0 };
  for (const node of nodes) counts[riskOf(node.criticality)]++;
  return counts;
}

/** The sketch canvas. */
export const SKETCH_W = 360;
export const SKETCH_H = 210;
/** The most files the sketch draws. */
export const SKETCH_MAX_NODES = 240;
const GOLDEN = Math.PI * (3 - Math.sqrt(5));

/** One square of the sketch. */
export interface SketchPoint {
  /** The file's path, so a caller can style a point by file. */
  path: string;
  x: number;
  y: number;
  color: string;
  size: number;
}

/**
 * Lays the graph out flat: the busiest files, clustered by directory.
 *
 * Each directory gets a centre on an ellipse, larger directories first, and
 * its files spiral out from that centre. It is a quick sketch of the real
 * graph's shape, not a force layout.
 *
 * @param graph - The file graph.
 * @param keep - Paths that stay on the canvas even when they are not among
 *   the busiest files, such as the files a run touched.
 * @returns Positioned points and the links between them.
 */
export function sketchGraph(
  graph: Pick<Graph, "nodes" | "links">,
  keep?: ReadonlySet<string>,
): {
  points: SketchPoint[];
  links: [SketchPoint, SketchPoint][];
} {
  const ranked = [...graph.nodes].sort(
    (a, b) => b.fan_in + b.fan_out - (a.fan_in + a.fan_out),
  );
  const nodes = ranked.slice(0, SKETCH_MAX_NODES);
  if (keep && keep.size > 0) {
    const shown = new Set(nodes.map((n) => n.id));
    for (const node of ranked.slice(SKETCH_MAX_NODES)) {
      if (keep.has(node.path) && !shown.has(node.id)) nodes.push(node);
    }
  }

  const groups = new Map<string, typeof nodes>();
  for (const n of nodes) {
    const list = groups.get(n.group) ?? [];
    list.push(n);
    groups.set(n.group, list);
  }
  const ordered = [...groups.values()].sort((a, b) => b.length - a.length);

  const placed = new Map<string, SketchPoint>();
  ordered.forEach((members, gi) => {
    const angle = (gi / ordered.length) * Math.PI * 2 - Math.PI / 2;
    const ring = ordered.length === 1 ? 0 : gi === 0 ? 0.15 : 0.62;
    const cx = SKETCH_W / 2 + Math.cos(angle) * ring * (SKETCH_W / 2 - 30);
    const cy = SKETCH_H / 2 + Math.sin(angle) * ring * (SKETCH_H / 2 - 22);
    members.forEach((n, i) => {
      const r = 3.2 * Math.sqrt(i);
      const a = i * GOLDEN;
      placed.set(n.id, {
        path: n.path,
        x: Math.max(4, Math.min(SKETCH_W - 4, cx + Math.cos(a) * r * 1.4)),
        y: Math.max(4, Math.min(SKETCH_H - 4, cy + Math.sin(a) * r)),
        color: RISK_LEVELS.find((k) => k.key === riskOf(n.criticality))!.color,
        size: n.fan_in > 8 ? 4 : 3,
      });
    });
  });

  const links: [SketchPoint, SketchPoint][] = [];
  for (const l of graph.links) {
    const a = placed.get(l.source);
    const b = placed.get(l.target);
    if (a && b) links.push([a, b]);
  }
  return { points: [...placed.values()], links };
}

const LEADING_HEADINGS = /^(?:[ \t]*(?:#{1,6}[ \t].*|#{1,6})[ \t]*(?:\r?\n|$)|[ \t]*\r?\n)+/;

/**
 * Drops headings and blank lines at the very start of a generated summary.
 *
 * Generated summaries often open with a title that only repeats the card's
 * own heading. Headings later in the text are left alone.
 *
 * @param text - Markdown text.
 * @returns The text without its opening headings.
 */
export function stripLeadingTitle(text: string): string {
  return text.replace(LEADING_HEADINGS, "").trim();
}
