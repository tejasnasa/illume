/**
 * The neighbourhood of one file, laid out as a small still picture.
 *
 * @module neighbourhood
 *
 * Port of ``client/src/components/ui/NeighbourhoodGraph.tsx`` and its
 * ``neighbourhood`` builder. The web draws the file, its importers and its
 * imports as a lit 3D constellation; the phone draws the same three groups
 * flat -- importers on the left, the file in the middle, imports on the
 * right -- as pixels and lines for react-native-svg. Each side is capped so a
 * file imported by hundreds still reads as a picture.
 */

import { riskOf, RISK_LEVELS } from "@/lib/overview";
import type { FileNode } from "@/types/explorer";

/** The most neighbours drawn on each side. */
export const NEIGHBOUR_SIDE_MAX = 14;

/** The selected file's colour. */
export const SELECTED_COLOR = "#f6339a";

/** One square of the picture. */
export interface NeighbourPixel {
  id: string;
  x: number;
  y: number;
  size: number;
  color: string;
  selected: boolean;
}

/** One edge of the picture. */
export interface NeighbourLine {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

/** A laid-out neighbourhood. */
export interface NeighbourScene {
  pixels: NeighbourPixel[];
  lines: NeighbourLine[];
  /** How many neighbours were left out of each side. */
  hidden: { importers: number; imports: number };
}

/**
 * The files that import a file and the files it imports, from the file graph.
 *
 * @param nodes - Every file node.
 * @param links - The graph links, by node id.
 * @param path - The selected file's path.
 * @returns The two neighbour lists, each in link order without duplicates.
 */
export function neighboursByPath(
  nodes: readonly FileNode[],
  links: readonly { source: string; target: string }[],
  path: string,
): { importers: FileNode[]; imports: FileNode[] } {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const self = nodes.find((n) => n.path === path);
  const importers: FileNode[] = [];
  const imports: FileNode[] = [];
  if (!self) return { importers, imports };
  const seenIn = new Set<string>();
  const seenOut = new Set<string>();
  for (const { source, target } of links) {
    if (target === self.id && source !== self.id && !seenIn.has(source)) {
      const node = byId.get(source);
      if (node) {
        seenIn.add(source);
        importers.push(node);
      }
    }
    if (source === self.id && target !== self.id && !seenOut.has(target)) {
      const node = byId.get(target);
      if (node) {
        seenOut.add(target);
        imports.push(node);
      }
    }
  }
  return { importers, imports };
}

/**
 * Lays the neighbourhood out.
 *
 * @param file - The selected file.
 * @param importers - Files that import it.
 * @param imports - Files it imports.
 * @param width - Canvas width.
 * @param height - Canvas height.
 * @returns The pixels and lines to draw.
 */
export function layoutNeighbourhood(
  file: FileNode,
  importers: readonly FileNode[],
  imports: readonly FileNode[],
  width: number,
  height: number,
): NeighbourScene {
  const colorOf = (node: FileNode) =>
    RISK_LEVELS.find((r) => r.key === riskOf(node.criticality))!.color;
  const centre = { x: width / 2, y: height / 2 };
  const pixels: NeighbourPixel[] = [
    { id: file.id, x: centre.x, y: centre.y, size: 9, color: SELECTED_COLOR, selected: true },
  ];
  const lines: NeighbourLine[] = [];

  const place = (files: readonly FileNode[], side: -1 | 1) => {
    const shown = files.slice(0, NEIGHBOUR_SIDE_MAX);
    const columnX = centre.x + side * width * 0.36;
    const top = 14;
    const span = height - top * 2;
    shown.forEach((node, i) => {
      // Two staggered columns keep a long side from becoming one tall line.
      const row = Math.floor(i / 2);
      const rows = Math.ceil(shown.length / 2);
      const stagger = i % 2 === 0 ? 0 : side * width * 0.1;
      const x = columnX + stagger;
      const y = rows <= 1 ? centre.y : top + (row / (rows - 1)) * span;
      pixels.push({ id: node.id, x, y, size: 5, color: colorOf(node), selected: false });
      lines.push({ x1: x, y1: y, x2: centre.x, y2: centre.y });
    });
    return Math.max(0, files.length - shown.length);
  };

  const hiddenImporters = place(importers, -1);
  const hiddenImports = place(imports, 1);
  return { pixels, lines, hidden: { importers: hiddenImporters, imports: hiddenImports } };
}
