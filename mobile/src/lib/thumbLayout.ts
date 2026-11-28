/**
 * A still pixel picture of a repository graph, for the dashboard cards.
 *
 * @module thumbLayout
 *
 * A condensed take on the web client's pixel constellation
 * (``client/src/lib/pixelGraph.ts``): one hub per directory laid out on a
 * ring, the files of a directory scattered around their hub, and the real
 * import edges drawn between them. It is computed once and drawn as a few
 * hundred SVG rectangles and lines, so a dashboard full of cards costs
 * nothing per frame. Everything is seeded so a repository always gets the
 * same picture.
 */

import { mulberry } from "@/lib/starfield";

/** The tints directories take in turn, as hex. */
export const THUMB_TINTS = [
  "#00b8db",
  "#f6339a",
  "#53eafd",
  "#0092b8",
  "#ec4899",
] as const;

/** The most files a thumbnail draws. */
export const THUMB_MAX_FILES = 140;

/** One square of the picture. */
export interface ThumbPixel {
  x: number;
  y: number;
  size: number;
  color: string;
  /** True for a directory hub. */
  hub: boolean;
}

/** One edge of the picture. */
export interface ThumbLine {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

/** A laid-out picture. */
export interface ThumbScene {
  pixels: ThumbPixel[];
  lines: ThumbLine[];
}

/** The slice of a graph payload the layout reads. */
export interface ThumbSource {
  nodes: { id: string; group?: string | null; path?: string | null }[];
  links: { source: string; target: string }[];
}

/**
 * Hash a string to a 32-bit seed.
 *
 * @param text - Any string.
 * @returns A seed for {@link mulberry}.
 */
export function hashSeed(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h | 0;
}

/**
 * Lay a graph out inside a box.
 *
 * @param source - The nodes and links; anything malformed is ignored.
 * @param width - Box width.
 * @param height - Box height.
 * @param seed - Text the scatter is seeded from, such as the repository id.
 * @param cell - Side of one pixel.
 * @returns The squares and lines to draw; empty for an empty graph.
 */
export function layoutThumb(
  source: ThumbSource | null | undefined,
  width: number,
  height: number,
  seed: string,
  cell = 3,
): ThumbScene {
  const nodes = Array.isArray(source?.nodes) ? source.nodes.slice(0, THUMB_MAX_FILES) : [];
  const links = Array.isArray(source?.links) ? source.links : [];
  if (nodes.length === 0 || !(width > 0) || !(height > 0)) {
    return { pixels: [], lines: [] };
  }

  const rnd = mulberry(hashSeed(seed));
  const groups = new Map<string, string[]>();
  for (const node of nodes) {
    const key = node.group || node.path?.split("/")[0] || "root";
    const members = groups.get(key) ?? [];
    members.push(node.id);
    groups.set(key, members);
  }

  const cx = width / 2;
  const cy = height / 2;
  const ringX = width * 0.3;
  const ringY = height * 0.3;
  const pixels: ThumbPixel[] = [];
  const at = new Map<string, { x: number; y: number }>();
  const snap = (v: number) => Math.round(v / cell) * cell;

  pixels.push({ x: snap(cx), y: snap(cy), size: cell * 2, color: "#0078ff", hub: true });

  let index = 0;
  for (const [, members] of groups) {
    const angle = (index / groups.size) * Math.PI * 2 + rnd() * 0.4;
    const hx = cx + Math.cos(angle) * ringX;
    const hy = cy + Math.sin(angle) * ringY;
    const tint = THUMB_TINTS[index % THUMB_TINTS.length];
    pixels.push({ x: snap(hx), y: snap(hy), size: cell * 2, color: tint, hub: true });
    for (const id of members) {
      const a = rnd() * Math.PI * 2;
      const r = (0.25 + rnd() * 0.75) * Math.min(width, height) * 0.2;
      const x = Math.min(width - cell, Math.max(0, hx + Math.cos(a) * r * 1.4));
      const y = Math.min(height - cell, Math.max(0, hy + Math.sin(a) * r));
      at.set(id, { x: snap(x), y: snap(y) });
      pixels.push({ x: snap(x), y: snap(y), size: cell, color: tint, hub: false });
    }
    index += 1;
  }

  const lines: ThumbLine[] = [];
  for (const link of links) {
    const a = at.get(link.source);
    const b = at.get(link.target);
    if (!a || !b) continue;
    lines.push({ x1: a.x, y1: a.y, x2: b.x, y2: b.y });
    if (lines.length >= 220) break;
  }
  return { pixels, lines };
}
